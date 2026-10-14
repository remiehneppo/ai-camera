"""Evidence orchestration; recorder owns files, outbox owns durable state."""
from contextlib import contextmanager
import fcntl
import json
import logging
from pathlib import Path
import sqlite3
import subprocess

from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder

logger = logging.getLogger(__name__)


class EvidenceLifecycle:
    def __init__(self, outbox, recorder, transport=None):
        self.outbox = outbox if isinstance(outbox, EventOutbox) else EventOutbox(outbox)
        self.recorder = recorder if isinstance(recorder, FileRecorder) else FileRecorder(recorder)
        self.transport = transport

    @contextmanager
    def _worker(self):
        # One coordinator per recorder store, including threads and other processes.
        with (self.recorder.root / ".evidence-worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def persist(self, event):
        with self._worker():
            self.outbox.enqueue(event)
            ids = {r["request_id"] for r in event["payload"].get("evidence_requests", [])}
            for request in self.outbox.evidence_requests():
                if request["request_id"] in ids and request["state"] in {"requested", "collecting", "pending", "in_progress"}:
                    try:
                        self._pin(request)
                    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                        self.outbox.update_evidence(request["request_id"], error=exc)
        return event

    def _pin(self, request):
        owner = f'{request["device_id"]}/{request["event_id"]}/{request["revision"]}'
        pin = self.recorder.pin(request["request_id"], request["session_id"],
                                request["requested_start"], request["requested_end"], owner)
        self.outbox.update_evidence(request["request_id"], state="collecting", receipt=pin)
        return pin

    def reconcile(self, *, finish_sessions=()):
        with self._worker():
            return self._reconcile(finish_sessions=finish_sessions)

    def _reconcile(self, *, finish_sessions=()):
        cleaned = self.recorder.cleanup_evidence_temps()
        ended = self.outbox.ended_sessions(finish_sessions)
        completed = failed = 0
        for request in self.outbox.evidence_requests():
            request_id = request["request_id"]
            status = None
            try:
                status = self.recorder.pin_status(request_id)
                if status and status.get("transfer_state") == "acknowledged":
                    self.outbox.update_evidence(request_id, state="acknowledged", receipt=status)
                    continue
                if request["state"] == "acknowledged":
                    continue
                if status and status.get("manifest"):
                    if status.get("availability") in {"missing", "quarantined"}:
                        raise ValueError("finalized clip missing or corrupt")
                    state = self._state(status)
                    if request["state"] != state:
                        self.outbox.update_evidence(request_id, state=state, receipt=status)
                        completed += state in {"fulfilled", "partial"}
                    continue
                if request["state"] == "failed":
                    continue
                self._pin(request)
                status = self.recorder.pin_status(request_id)
                if status["state"] == "collecting" and request["session_id"] not in ended:
                    continue
                receipt = self.recorder.finalize_pin(request_id,
                    allow_partial=request["session_id"] in ended,
                    request_metadata={key: request[key] for key in (
                        "evidence_anchor_kind", "evidence_anchor_time", "mapping_uncertainty",
                        "policy_version", "supersedes_request_id")})
                self.outbox.update_evidence(request_id, state=self._state(receipt), receipt=receipt)
                completed += 1
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, sqlite3.Error) as exc:
                # Retry transient failures without inventing a terminal build result.
                terminal = bool(status and status.get("manifest")) or isinstance(exc, ValueError)
                self.outbox.update_evidence(request_id, state="failed" if terminal else None, error=exc)
                failed += 1
        return {"cleaned_files": cleaned, "recovered_fulfilled": completed, "failed_requests": failed}

    @staticmethod
    def _state(receipt):
        if receipt.get("build_state") == "failed":
            return "failed"
        return "fulfilled" if receipt.get("completeness") == "complete" else "partial"

    def upload_single_request(self, request_id):
        with self._worker():
            return self._upload(request_id)

    def _upload(self, request_id):
        from apps.edge.uploader import _calculate_file_sha256
        if self.transport is None:
            return None
        pin_status = self.recorder.pin_status(request_id)
        if pin_status and pin_status.get("transfer_state") == "acknowledged":
            self.outbox.update_evidence(request_id, state="acknowledged", receipt=pin_status)
            return pin_status["transfer_receipt"]
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
            self.outbox.update_evidence(request_id, error="missing artifact metadata in receipt")
            return None

        artifact_path = Path(artifact["path"])
        if not artifact_path.is_file():
            logger.warning("evidence clip file missing on disk: %s", artifact_path)
            self.outbox.update_evidence(request_id, state="failed", error=f"clip file missing: {artifact_path}")
            return None

        # Verify size and SHA-256 before upload
        actual_size = artifact_path.stat().st_size
        if actual_size != artifact["size_bytes"]:
            logger.warning("evidence clip size mismatch for %s: %d != %d", request_id, actual_size, artifact["size_bytes"])
            self.outbox.update_evidence(request_id, error=f"size mismatch: {actual_size} != {artifact['size_bytes']}")
            return None

        actual_sha256 = _calculate_file_sha256(artifact_path)
        if actual_sha256 != artifact["sha256"]:
            logger.warning("evidence clip sha256 mismatch for %s", request_id)
            self.outbox.update_evidence(request_id, error="sha256 integrity mismatch")
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

        endpoint = f"{self.transport.server_url}/v1/evidence/{device_id}/{event_id}/{request_id}"
        headers = {
            "Authorization": f"Bearer {self.transport.device_token}",
            "X-Evidence-Sha256": artifact["sha256"],
            "X-Evidence-Metadata": json.dumps(metadata, separators=(",", ":")),
            "Content-Type": artifact.get("content_type", "video/x-matroska"),
            "Content-Length": str(artifact["size_bytes"]),
        }

        try:
            server_receipt = self.transport.transfer(endpoint, artifact, headers)
            self.recorder.acknowledge_transfer(request_id, server_receipt)
            self.outbox.update_evidence(request_id, state="acknowledged", receipt={
                **receipt, "transfer_state": "acknowledged", "transfer_receipt": server_receipt})
            return server_receipt
        except (OSError, ValueError) as exc:
            self.outbox.update_evidence(request_id, error=exc)
            return None

    def upload_pending(self, batch_size=10, *, reconcile=False):
        with self._worker():
            if reconcile:
                self._reconcile()
            requests = [r for r in self.outbox.evidence_requests() if r["state"] in {"fulfilled", "partial"}]
            return sum(self._upload(r["request_id"]) is not None for r in requests[:batch_size])
