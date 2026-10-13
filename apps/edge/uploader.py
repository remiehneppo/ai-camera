"""Edge evidence uploader client and outbox reconciliation."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import ssl
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder

logger = logging.getLogger(__name__)


def _validate_server_url(server_url: str) -> str:
    parsed = urlparse(server_url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("server_url must use HTTPS; loopback HTTP is allowed for testing")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("server_url must be an origin without credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("server_url must not contain a path component")
    return server_url.rstrip("/")


def _validate_receipt(server_receipt: Any, artifact: dict[str, Any], request_id: str) -> dict[str, Any]:
    if not isinstance(server_receipt, dict):
        raise ValueError("server evidence receipt must be an object")
    expected = {
        "request_id": request_id,
        "sha256": artifact["sha256"],
        "size_bytes": artifact["size_bytes"],
    }
    for key, value in expected.items():
        if server_receipt.get(key) != value:
            raise ValueError(f"receipt field {key}={server_receipt.get(key)!r} does not match expected {value!r}")
    location = server_receipt.get("location")
    if not isinstance(location, str) or not location:
        raise ValueError("receipt location must be a non-empty string")
    return server_receipt


def _calculate_file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _set_outbox_request_state(
    outbox_path: str | Path,
    request_id: str,
    state: str,
    *,
    receipt: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    receipt_json = json.dumps(receipt, separators=(",", ":")) if receipt else None
    with sqlite3.connect(str(outbox_path), timeout=5) as db:
        db.execute("PRAGMA busy_timeout=5000")
        if state == "failed":
            db.execute(
                "UPDATE evidence_requests SET state=?, last_error=? WHERE request_id=?",
                (state, error[:512] if error else "unknown error", request_id),
            )
        elif receipt_json is not None:
            db.execute(
                "UPDATE evidence_requests SET state=?, receipt_json=?, last_error=? WHERE request_id=?",
                (state, receipt_json, error[:512] if error else None, request_id),
            )
        else:
            db.execute(
                "UPDATE evidence_requests SET state=?, last_error=? WHERE request_id=?",
                (state, error[:512] if error else None, request_id),
            )


def reconcile_and_cleanup(
    outbox: EventOutbox | str | Path,
    recorder: FileRecorder | str | Path,
) -> dict[str, Any]:
    outbox_inst = outbox if isinstance(outbox, EventOutbox) else EventOutbox(outbox)
    recorder_inst = recorder if isinstance(recorder, FileRecorder) else FileRecorder(recorder)

    cleaned_files: list[str] = []
    # 1. Clean orphaned temporary files (*.tmp*, *.concat) in recorder output / clip directories
    if recorder_inst.root.exists():
        for path in list(recorder_inst.root.rglob("*")):
            if path.is_file() and (".tmp" in path.name or path.suffix == ".tmp" or path.suffix == ".concat"):
                try:
                    path.unlink(missing_ok=True)
                    cleaned_files.append(str(path))
                except OSError:
                    pass

    # 2. For evidence requests in outbox
    requests = outbox_inst.evidence_requests()
    recovered_fulfilled = 0
    failed_requests = 0

    for req in requests:
        state = req.get("state")
        request_id = req["request_id"]
        session_id = req.get("session_id")
        try:
            requested_start = float(req.get("requested_start", 0.0))
            requested_end = float(req.get("requested_end", 0.0))
        except (ValueError, TypeError):
            requested_start = 0.0
            requested_end = 0.0

        if state not in {"pending", "in_progress", "requested", "collecting"}:
            # For fulfilled/partial, ensure clip on disk is intact
            if state in {"fulfilled", "partial"}:
                receipt = req.get("receipt") or {}
                artifact = receipt.get("artifact")
                if artifact and isinstance(artifact, dict) and artifact.get("path"):
                    cpath = Path(artifact["path"])
                    if not cpath.is_file():
                        # Clip missing, check if ring segments expired
                        available_segs = recorder_inst.segments(session_id) if session_id else []
                        if not available_segs or min(s.start_seconds for s in available_segs) > requested_end:
                            _set_outbox_request_state(
                                outbox_inst.path,
                                request_id,
                                "failed",
                                error="ring segments expired: clip file missing and ring pruned",
                            )
                            failed_requests += 1
                    else:
                        c_size = cpath.stat().st_size
                        c_hash = _calculate_file_sha256(cpath)
                        if (artifact.get("size_bytes") is not None and c_size != artifact["size_bytes"]) or \
                           (artifact.get("sha256") and c_hash != artifact["sha256"]):
                            _set_outbox_request_state(
                                outbox_inst.path,
                                request_id,
                                "failed",
                                error="clip corrupted: sha256 or size mismatch",
                            )
                            failed_requests += 1
            continue

        # Look for existing clip file and manifest
        manifest_dir = recorder_inst.root / "manifests"
        name = hashlib.sha256(request_id.encode()).hexdigest()
        manifest_path = manifest_dir / f"{name}.json"
        default_clip_path = manifest_dir / f"{name}.mkv"

        receipt = req.get("receipt") or {}
        artifact = receipt.get("artifact")

        clip_file: Path | None = None
        if artifact and isinstance(artifact, dict) and artifact.get("path"):
            clip_file = Path(artifact["path"])
        elif default_clip_path.is_file():
            clip_file = default_clip_path
        elif (manifest_dir / f"{request_id}.mkv").is_file():
            clip_file = manifest_dir / f"{request_id}.mkv"
        elif manifest_path.is_file():
            try:
                m_data = json.loads(manifest_path.read_text())
                if m_data.get("artifact") and isinstance(m_data["artifact"], dict):
                    artifact = m_data["artifact"]
                    clip_file = Path(artifact["path"])
                    receipt = m_data
            except Exception:
                pass

        # Also check pin_status if artifact not found yet
        if not artifact:
            pin_status = recorder_inst.pin_status(request_id)
            if pin_status and pin_status.get("artifact"):
                artifact = pin_status["artifact"]
                receipt = {**receipt, **pin_status}
                if not clip_file and artifact.get("path"):
                    clip_file = Path(artifact["path"])

        if clip_file is not None and clip_file.is_file():
            # Clip exists on disk! Check integrity
            actual_size = clip_file.stat().st_size
            actual_sha256 = _calculate_file_sha256(clip_file)

            expected_size = artifact.get("size_bytes") if artifact else None
            expected_sha256 = artifact.get("sha256") if artifact else None

            if expected_size is not None and actual_size != expected_size:
                _set_outbox_request_state(
                    outbox_inst.path,
                    request_id,
                    "failed",
                    error=f"clip corrupted: size mismatch {actual_size} != {expected_size}",
                )
                failed_requests += 1
                continue
            if expected_sha256 is not None and actual_sha256 != expected_sha256:
                _set_outbox_request_state(
                    outbox_inst.path,
                    request_id,
                    "failed",
                    error="clip corrupted: sha256 integrity mismatch",
                )
                failed_requests += 1
                continue

            # Valid clip! Transition to fulfilled
            if not receipt or not receipt.get("artifact"):
                receipt = {
                    **receipt,
                    "request_id": request_id,
                    "session_id": session_id,
                    "artifact": {
                        "path": str(clip_file),
                        "size_bytes": actual_size,
                        "sha256": actual_sha256,
                        "content_type": "video/x-matroska",
                        "codec": "h264",
                    },
                    "completeness": receipt.get("completeness", "complete"),
                }
            _set_outbox_request_state(outbox_inst.path, request_id, "fulfilled", receipt=receipt)
            recovered_fulfilled += 1
            continue

        # Clip file does not exist on disk. Check if recorder can still fulfill the requested range
        if not session_id:
            _set_outbox_request_state(
                outbox_inst.path, request_id, "failed", error="ring segments expired: missing session_id"
            )
            failed_requests += 1
            continue

        available_segs = recorder_inst.segments(session_id)
        if not available_segs:
            _set_outbox_request_state(
                outbox_inst.path, request_id, "failed", error="ring segments expired: no segments in ring"
            )
            failed_requests += 1
            continue

        earliest_start = min(s.start_seconds for s in available_segs)
        latest_end = max(s.end_seconds for s in available_segs)
        matching_segs = [s for s in available_segs if s.end_seconds >= requested_start and s.start_seconds <= requested_end]

        if not matching_segs or earliest_start > requested_end:
            _set_outbox_request_state(
                outbox_inst.path, request_id, "failed", error="ring segments expired: range pruned from ring"
            )
            failed_requests += 1
            continue

        # Range can still be fulfilled
        owner = f"{req.get('device_id')}/{req.get('event_id')}/{req.get('revision')}"
        try:
            pin_stat = recorder_inst.pin_status(request_id)
            if not pin_stat:
                recorder_inst.pin(request_id, session_id, requested_start, requested_end, owner)
                pin_stat = recorder_inst.pin_status(request_id)

            if pin_stat and pin_stat.get("artifact"):
                _set_outbox_request_state(outbox_inst.path, request_id, "fulfilled", receipt=pin_stat)
                recovered_fulfilled += 1
            elif latest_end >= requested_end:
                fin_receipt = recorder_inst.finalize_pin(request_id, allow_partial=True)
                if fin_receipt.get("artifact"):
                    _set_outbox_request_state(outbox_inst.path, request_id, "fulfilled", receipt=fin_receipt)
                    recovered_fulfilled += 1
                else:
                    _set_outbox_request_state(
                        outbox_inst.path, request_id, "failed", error="ring segments expired: finalize produced no artifact"
                    )
                    failed_requests += 1
        except Exception as exc:
            _set_outbox_request_state(outbox_inst.path, request_id, "failed", error=f"ring segments expired: {exc}")
            failed_requests += 1

    return {
        "cleaned_files": cleaned_files,
        "recovered_fulfilled": recovered_fulfilled,
        "failed_requests": failed_requests,
    }


class EdgeUploader:
    """Client for uploading finalized edge evidence clips to the server."""

    def __init__(
        self,
        outbox: EventOutbox | str | Path,
        recorder: FileRecorder | str | Path,
        server_url: str,
        device_token: str,
        *,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ) -> None:
        self.outbox = outbox if isinstance(outbox, EventOutbox) else EventOutbox(outbox)
        self.recorder = recorder if isinstance(recorder, FileRecorder) else FileRecorder(recorder)
        self.server_url = _validate_server_url(server_url)
        if not device_token or not isinstance(device_token, str):
            raise ValueError("device_token must be a non-empty string")
        self.device_token = device_token
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._ssl_context = ssl.create_default_context()

    def _update_outbox_state(
        self,
        request_id: str,
        state: str,
        *,
        receipt: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        receipt_json = json.dumps(receipt, separators=(",", ":")) if receipt else None
        with sqlite3.connect(self.outbox.path, timeout=5) as db:
            db.execute("PRAGMA busy_timeout=5000")
            if state == "acknowledged":
                db.execute(
                    "UPDATE evidence_requests SET state=?, receipt_json=COALESCE(?, receipt_json), last_error=NULL WHERE request_id=?",
                    (state, receipt_json, request_id),
                )
            elif state == "failed":
                db.execute(
                    "UPDATE evidence_requests SET state=?, last_error=? WHERE request_id=?",
                    (state, error[:512] if error else "unknown error", request_id),
                )
            else:
                db.execute(
                    "UPDATE evidence_requests SET state=?, last_error=? WHERE request_id=?",
                    (state, error[:512] if error else None, request_id),
                )

    def _record_outbox_error(self, request_id: str, error: str) -> None:
        with sqlite3.connect(self.outbox.path, timeout=5) as db:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute(
                "UPDATE evidence_requests SET last_error=? WHERE request_id=?",
                (error[:512], request_id),
            )

    def upload_single_request(self, request_id: str) -> dict[str, Any] | None:
        """Upload a single evidence request by id. Returns the server receipt on success."""
        pin_status = self.recorder.pin_status(request_id)
        if pin_status and pin_status.get("transfer_state") == "acknowledged":
            transfer_receipt = pin_status.get("transfer_receipt")
            self._update_outbox_state(request_id, "acknowledged", receipt=pin_status)
            return transfer_receipt

        all_requests = {req["request_id"]: req for req in self.outbox.evidence_requests()}
        req_entry = all_requests.get(request_id)
        if not req_entry:
            logger.warning("evidence request %s not found in outbox", request_id)
            return None

        device_id = req_entry.get("device_id")
        event_id = req_entry.get("event_id")
        receipt = req_entry.get("receipt") or {}
        if pin_status:
            receipt = {**receipt, **pin_status}

        artifact = receipt.get("artifact")
        if not artifact or not isinstance(artifact, dict):
            self._record_outbox_error(request_id, "missing artifact metadata in receipt")
            return None

        artifact_path = Path(artifact["path"])
        if not artifact_path.is_file():
            logger.warning("evidence clip file missing on disk: %s", artifact_path)
            self._update_outbox_state(request_id, "failed", error=f"clip file missing: {artifact_path}")
            return None

        # Verify size and SHA-256 before upload
        actual_size = artifact_path.stat().st_size
        if actual_size != artifact["size_bytes"]:
            logger.warning("evidence clip size mismatch for %s: %d != %d", request_id, actual_size, artifact["size_bytes"])
            self._record_outbox_error(request_id, f"size mismatch: {actual_size} != {artifact['size_bytes']}")
            return None

        actual_sha256 = _calculate_file_sha256(artifact_path)
        if actual_sha256 != artifact["sha256"]:
            logger.warning("evidence clip sha256 mismatch for %s", request_id)
            self._record_outbox_error(request_id, "sha256 integrity mismatch")
            return None

        # Prepare headers & metadata
        metadata = {
            "request_id": request_id,
            "session_id": receipt.get("session_id"),
            "owner": receipt.get("owner"),
            "requested_start": receipt.get("requested_start"),
            "requested_end": receipt.get("requested_end"),
            "actual_start": receipt.get("actual_start"),
            "actual_end": receipt.get("actual_end"),
            "actual_range": [receipt.get("actual_start"), receipt.get("actual_end")],
            "actual_ranges": receipt.get("actual_ranges", []),
            "completeness": receipt.get("completeness"),
            "reason": receipt.get("reason"),
            "codec": artifact.get("codec"),
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
        }
        for k in (
            "evidence_anchor_kind",
            "evidence_anchor_time",
            "mapping_uncertainty",
            "policy_version",
            "supersedes_request_id",
        ):
            if receipt.get(k) is not None:
                metadata[k] = receipt[k]

        endpoint = f"{self.server_url}/v1/evidence/{device_id}/{event_id}/{request_id}"
        headers = {
            "Authorization": f"Bearer {self.device_token}",
            "X-Evidence-Sha256": artifact["sha256"],
            "X-Evidence-Metadata": json.dumps(metadata, separators=(",", ":")),
            "Content-Type": artifact.get("content_type", "video/x-matroska"),
            "Content-Length": str(artifact["size_bytes"]),
        }

        # Upload with retry logic
        last_error_str = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0 and self.backoff_base > 0:
                delay = self.backoff_base * (2 ** (attempt - 1))
                time.sleep(delay)

            try:
                with artifact_path.open("rb") as stream:
                    request = Request(endpoint, data=stream, headers=headers, method="PUT")
                    with urlopen(request, timeout=self.timeout_seconds, context=self._ssl_context) as response:
                        response_body = response.read()
                        raw_receipt = json.loads(response_body.decode("utf-8"))
                        server_receipt = _validate_receipt(raw_receipt, artifact, request_id)

                # Server accepted the upload
                self.recorder.acknowledge_transfer(request_id, server_receipt)
                updated_receipt = {
                    **receipt,
                    "transfer_state": "acknowledged",
                    "transfer_receipt": server_receipt,
                }
                self._update_outbox_state(request_id, "acknowledged", receipt=updated_receipt)
                return server_receipt

            except HTTPError as exc:
                last_error_str = f"HTTP {exc.code}: {exc.reason}"
                logger.warning("evidence upload HTTPError %s on attempt %d: %s", request_id, attempt, last_error_str)
                # Retry on 503 Service Unavailable or 429 Too Many Requests or 5xx
                if exc.code in {503, 429, 502, 504} and attempt < self.max_retries:
                    continue
                # Non-retryable error or retries exhausted
                self._record_outbox_error(request_id, last_error_str)
                return None

            except (URLError, TimeoutError, OSError) as exc:
                last_error_str = f"{type(exc).__name__}: {exc}"
                logger.warning("evidence upload network error %s on attempt %d: %s", request_id, attempt, last_error_str)
                if attempt < self.max_retries:
                    continue
                self._record_outbox_error(request_id, last_error_str)
                return None

            except ValueError as exc:
                # Receipt verification failed
                last_error_str = f"receipt validation error: {exc}"
                logger.warning("evidence receipt verification failed for %s: %s", request_id, last_error_str)
                self._record_outbox_error(request_id, last_error_str)
                return None

        if last_error_str:
            self._record_outbox_error(request_id, last_error_str)
        return None

    def reconcile_and_cleanup(self) -> dict[str, Any]:
        return reconcile_and_cleanup(self.outbox, self.recorder)

    def upload_pending(self, batch_size: int = 10, reconcile: bool = False) -> int:
        """Scan outbox for pending evidence requests in fulfilled or partial state and upload them."""
        if reconcile:
            self.reconcile_and_cleanup()

        pending_candidates = [
            req for req in self.outbox.evidence_requests()
            if req.get("state") in {"fulfilled", "partial"}
        ]

        uploaded_count = 0
        for req in pending_candidates[:batch_size]:
            request_id = req["request_id"]
            receipt = self.upload_single_request(request_id)
            if receipt is not None:
                uploaded_count += 1

        return uploaded_count
