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

    def upload_pending(self, batch_size: int = 10) -> int:
        """Scan outbox for pending evidence requests in fulfilled or partial state and upload them."""
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
