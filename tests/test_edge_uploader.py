from __future__ import annotations

import hashlib
import http.server
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from typing import Any
import unittest
from urllib.error import HTTPError, URLError

from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder
from apps.edge.uploader import EdgeUploader
from domain.evidence_contract import make_evidence_request
from tests.test_event_delivery import event_fixture


class MockEvidenceServer(http.server.BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.server_state = kwargs.pop("server_state", None)
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        pass  # Suppress console logging in tests

    def do_PUT(self):
        state = self.server.state  # type: ignore[attr-defined]
        path = self.path
        headers = dict(self.headers)
        length = int(headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        record = {
            "path": path,
            "headers": headers,
            "body": body,
            "method": "PUT",
        }
        state["requests"].append(record)

        # Check programmed response handlers
        if state.get("fail_503_count", 0) > 0:
            state["fail_503_count"] -= 1
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "service temporarily unavailable"}')
            return

        if state.get("fail_413"):
            self.send_response(413)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "payload too large"}')
            return

        if state.get("fail_400"):
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "bad request"}')
            return

        if state.get("bad_receipt"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"request_id": "wrong", "sha256": "wrong", "size_bytes": 0, "location": ""}')
            return

        # Default 200 success
        # Extract device_id, event_id, request_id from path /v1/evidence/{device_id}/{event_id}/{request_id}
        parts = path.strip("/").split("/")
        device_id = parts[2] if len(parts) > 2 else "unknown"
        event_id = parts[3] if len(parts) > 3 else "unknown"
        request_id = parts[4] if len(parts) > 4 else "unknown"

        digest = hashlib.sha256(body).hexdigest()
        receipt = {
            "request_id": request_id,
            "sha256": digest,
            "size_bytes": len(body),
            "location": f"/v1/evidence/{device_id}/{event_id}/{request_id}/media",
            "status": "committed",
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(receipt).encode("utf-8"))


class EdgeUploaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.outbox_path = self.root / "events.sqlite3"
        self.outbox = EventOutbox(self.outbox_path)
        self.recorder_dir = self.root / "recorder"
        self.recorder = FileRecorder(self.recorder_dir, probe_timeout_seconds=5)

        # Setup mock HTTP server
        self.server_requests: list[dict[str, Any]] = []
        self.server_state: dict[str, Any] = {
            "requests": self.server_requests,
            "fail_503_count": 0,
            "fail_400": False,
            "bad_receipt": False,
        }
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockEvidenceServer)
        self.httpd.state = self.server_state  # type: ignore[attr-defined]
        self.port = self.httpd.server_port
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()

        self.server_url = f"http://127.0.0.1:{self.port}"
        self.device_token = "secret-device-token-123"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server_thread.join(timeout=2)
        self.tempdir.cleanup()

    def _create_evidence(
        self,
        request_id: str = "req-1",
        state: str = "fulfilled",
        clip_bytes: bytes = b"RIFF-fake-mkv-clip-bytes-payload-123",
        completeness: str = "complete",
        event_id: str | None = None,
    ) -> dict[str, Any]:
        import uuid
        event = event_fixture()
        if event_id:
            event["event_id"] = event_id
            event["message_id"] = f"msg-{event_id}"
        else:
            eid = str(uuid.uuid4())
            event["event_id"] = eid
            event["message_id"] = f"msg-{eid}"
        stream_session_id = str(event["stream_session_id"])
        req = make_evidence_request(request_id, stream_session_id, "synthetic", 10)
        payload = event["payload"]
        if isinstance(payload, dict):
            payload["evidence_requests"] = [req]
        self.outbox.enqueue(event)

        clip_dir = self.recorder_dir / "manifests"
        clip_dir.mkdir(parents=True, exist_ok=True)
        clip_path = clip_dir / f"{request_id}.mkv"
        clip_path.write_bytes(clip_bytes)
        digest = hashlib.sha256(clip_bytes).hexdigest()

        artifact = {
            "path": str(clip_path),
            "size_bytes": len(clip_bytes),
            "sha256": digest,
            "content_type": "video/x-matroska",
            "codec": "h264",
        }
        receipt = {
            "request_id": request_id,
            "session_id": event["stream_session_id"],
            "owner": f"{event['device_id']}/{event['event_id']}/{event['revision']}",
            "requested_start": 0,
            "requested_end": 30,
            "actual_start": 0.0,
            "actual_end": 30.0,
            "actual_ranges": [[0.0, 30.0]],
            "gaps": [],
            "completeness": completeness,
            "reason": None if completeness == "complete" else "missing_preroll",
            "build_state": "finalized",
            "state": "held",
            "segments": [],
            "artifact": artifact,
            "manifest": str(clip_dir / f"{request_id}.json"),
        }
        (clip_dir / f"{request_id}.json").write_text(json.dumps(receipt))

        with sqlite3.connect(self.recorder._pins) as db:
            db.execute(
                "INSERT OR REPLACE INTO pins(request_id, session_id, owner, start, end, receipt) VALUES (?,?,?,?,?,?)",
                (request_id, event["stream_session_id"], receipt["owner"], 0, 30, json.dumps(receipt)),
            )

        with sqlite3.connect(self.outbox.path) as db:
            db.execute(
                "UPDATE evidence_requests SET state=?, receipt_json=? WHERE request_id=?",
                (state, json.dumps(receipt), request_id),
            )

        return {"event": event, "receipt": receipt, "clip_path": clip_path, "clip_bytes": clip_bytes}

    def test_successful_upload(self) -> None:
        data = self._create_evidence("req-success")
        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
        )

        uploaded_count = uploader.upload_pending()
        self.assertEqual(uploaded_count, 1)

        # Check server received the request
        self.assertEqual(len(self.server_requests), 1)
        req = self.server_requests[0]
        event = data["event"]
        expected_path = f"/v1/evidence/{event['device_id']}/{event['event_id']}/req-success"
        self.assertEqual(req["path"], expected_path)
        self.assertEqual(req["headers"]["Authorization"], f"Bearer {self.device_token}")
        self.assertEqual(req["headers"]["X-Evidence-Sha256"], data["receipt"]["artifact"]["sha256"])
        self.assertEqual(req["headers"]["Content-Type"], "video/x-matroska")
        self.assertEqual(int(req["headers"]["Content-Length"]), len(data["clip_bytes"]))
        self.assertEqual(req["body"], data["clip_bytes"])

        # Check metadata header
        meta = json.loads(req["headers"]["X-Evidence-Metadata"])
        self.assertEqual(meta["request_id"], "req-success")
        self.assertEqual(meta["completeness"], "complete")
        self.assertEqual(meta["sha256"], data["receipt"]["artifact"]["sha256"])

        # Check outbox transitioned to acknowledged
        outbox_requests = self.outbox.evidence_requests()
        self.assertEqual(len(outbox_requests), 1)
        self.assertEqual(outbox_requests[0]["state"], "acknowledged")
        self.assertIsNone(outbox_requests[0]["last_error"])

        # Check recorder recorded transfer
        pin_status = self.recorder.pin_status("req-success")
        self.assertIsNotNone(pin_status)
        assert pin_status is not None
        self.assertEqual(pin_status["transfer_state"], "acknowledged")
        self.assertEqual(pin_status["transfer_receipt"]["sha256"], data["receipt"]["artifact"]["sha256"])

    def test_sha256_verification_mismatch_aborts(self) -> None:
        data = self._create_evidence("req-corrupt")
        # Tamper with the clip file on disk after manifest creation keeping identical size
        tampered = bytearray(data["clip_bytes"])
        tampered[0] = (tampered[0] + 1) % 256
        data["clip_path"].write_bytes(bytes(tampered))

        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
        )

        uploaded_count = uploader.upload_pending()
        self.assertEqual(uploaded_count, 0)

        # Server should not have received any upload request
        self.assertEqual(len(self.server_requests), 0)

        # Outbox request should record integrity mismatch error
        outbox_requests = self.outbox.evidence_requests()
        self.assertEqual(len(outbox_requests), 1)
        self.assertNotEqual(outbox_requests[0]["state"], "acknowledged")
        self.assertIn("integrity", str(outbox_requests[0]["last_error"]).lower())

    def test_missing_clip_file_does_not_crash(self) -> None:
        data = self._create_evidence("req-missing")
        # Delete clip file
        data["clip_path"].unlink()

        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
        )

        # Should not raise exception
        uploaded_count = uploader.upload_pending()
        self.assertEqual(uploaded_count, 0)

        # Server received no request
        self.assertEqual(len(self.server_requests), 0)

        # Outbox should be marked failed or have last_error
        outbox_requests = self.outbox.evidence_requests()
        self.assertEqual(len(outbox_requests), 1)
        self.assertEqual(outbox_requests[0]["state"], "failed")
        self.assertIn("missing", str(outbox_requests[0]["last_error"]).lower())

    def test_503_retry_with_backoff_succeeds(self) -> None:
        data = self._create_evidence("req-503-retry")
        self.server_state["fail_503_count"] = 1  # Fail once with 503, then succeed

        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
            max_retries=3,
            backoff_base=0.01,
        )

        uploaded_count = uploader.upload_pending()
        self.assertEqual(uploaded_count, 1)

        # Server received 2 requests (1 failed 503, 1 succeeded 200)
        self.assertEqual(len(self.server_requests), 2)

        # Successfully transitioned to acknowledged
        outbox_requests = self.outbox.evidence_requests()
        self.assertEqual(outbox_requests[0]["state"], "acknowledged")

    def test_uploader_injectable_sleep_fn(self) -> None:
        data = self._create_evidence("req-sleep-fn")
        self.server_state["fail_503_count"] = 1

        sleep_calls: list[float] = []
        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
            max_retries=2,
            backoff_base=0.1,
            sleep_fn=sleep_calls.append,
        )
        uploaded = uploader.upload_pending()
        self.assertEqual(uploaded, 1)
        self.assertEqual(len(sleep_calls), 1)
        self.assertAlmostEqual(sleep_calls[0], 0.1)

    def test_503_retries_exhausted_records_error_without_crash(self) -> None:
        data = self._create_evidence("req-503-exhausted")
        self.server_state["fail_503_count"] = 5  # Continually fail

        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
            max_retries=2,
            backoff_base=0.01,
        )

        uploaded_count = uploader.upload_pending()
        self.assertEqual(uploaded_count, 0)

        # Attempts reached max_retries + 1 (initial + 2 retries = 3 requests)
        self.assertEqual(len(self.server_requests), 3)

        # Outbox records last_error and is NOT acknowledged
        outbox_requests = self.outbox.evidence_requests()
        self.assertEqual(outbox_requests[0]["state"], "fulfilled")
        self.assertIn("503", str(outbox_requests[0]["last_error"]))

    def test_idempotent_replay(self) -> None:
        data = self._create_evidence("req-idempotent")
        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
        )

        # First upload succeeds
        self.assertEqual(uploader.upload_pending(), 1)
        self.assertEqual(len(self.server_requests), 1)

        # Second upload does not re-upload acknowledged item
        self.assertEqual(uploader.upload_pending(), 0)
        self.assertEqual(len(self.server_requests), 1)

        # Replay single item directly succeeds idempotently
        receipt = uploader.upload_single_request("req-idempotent")
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt["request_id"], "req-idempotent")

    def test_partial_evidence_upload(self) -> None:
        data = self._create_evidence("req-partial", state="partial", completeness="partial")
        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
        )

        self.assertEqual(uploader.upload_pending(), 1)

        req = self.server_requests[0]
        meta = json.loads(req["headers"]["X-Evidence-Metadata"])
        self.assertEqual(meta["completeness"], "partial")

        outbox_requests = self.outbox.evidence_requests()
        self.assertEqual(outbox_requests[0]["state"], "acknowledged")

    def test_batch_size_limits_uploaded_count(self) -> None:
        self._create_evidence("req-batch-1")
        self._create_evidence("req-batch-2")
        self._create_evidence("req-batch-3")

        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
        )

        self.assertEqual(uploader.upload_pending(batch_size=2), 2)
        states = [r["state"] for r in self.outbox.evidence_requests()]
        self.assertEqual(states.count("acknowledged"), 2)
        self.assertEqual(states.count("fulfilled"), 1)

    def test_server_receipt_validation_mismatch(self) -> None:
        self._create_evidence("req-bad-receipt")
        self.server_state["bad_receipt"] = True

        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
            max_retries=1,
            backoff_base=0.01,
        )

        self.assertEqual(uploader.upload_pending(), 0)

        outbox_requests = self.outbox.evidence_requests()
        self.assertNotEqual(outbox_requests[0]["state"], "acknowledged")
        self.assertIn("receipt", str(outbox_requests[0]["last_error"]).lower())

    def test_non_retryable_400_client_error(self) -> None:
        data = self._create_evidence("req-400")
        self.server_state["fail_400"] = True

        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
            max_retries=3,
            backoff_base=0.01,
        )

        uploaded_count = uploader.upload_pending()
        self.assertEqual(uploaded_count, 0)

        # 400 should not retry: only 1 attempt
        self.assertEqual(len(self.server_requests), 1)

        outbox_requests = self.outbox.evidence_requests()
        self.assertEqual(outbox_requests[0]["state"], "fulfilled")
        self.assertIn("400", str(outbox_requests[0]["last_error"]))

    def test_413_is_not_retried_keeps_pin_and_marks_operational_fault(self) -> None:
        data = self._create_evidence("req-413")
        self.server_state["fail_413"] = True
        uploader = EdgeUploader(
            outbox=self.outbox, recorder=self.recorder, server_url=self.server_url,
            device_token="test-token", max_retries=3, backoff_base=0.01,
        )
        self.assertEqual(uploader.upload_pending(), 0)
        self.assertEqual(len(self.server_requests), 1)  # no blind retry

        row = self.outbox.evidence_requests()[0]
        self.assertEqual(row["state"], "failed")
        self.assertIn("upload_413_payload_too_large", row["last_error"])
        self.assertEqual(row["receipt"]["operational_fault"], "upload_413_payload_too_large")
        # clip and pin survive: nothing acknowledged or released
        self.assertTrue(data["clip_path"].is_file())
        status = self.recorder.pin_status("req-413")
        self.assertEqual(status["state"], "held")
        self.assertNotEqual(status.get("transfer_state"), "acknowledged")

        # later passes (including reconcile) neither retry nor revive the request
        uploader.upload_pending(reconcile=True)
        uploader.upload_pending()
        self.assertEqual(len(self.server_requests), 1)
        self.assertEqual(self.outbox.evidence_requests()[0]["state"], "failed")
        self.assertEqual(self.recorder.pin_status("req-413")["state"], "held")

    def test_metadata_ack_does_not_release_clip_after_413(self) -> None:
        data = self._create_evidence("req-413b")
        self.server_state["fail_413"] = True
        uploader = EdgeUploader(
            outbox=self.outbox, recorder=self.recorder, server_url=self.server_url,
            device_token="test-token", max_retries=0, backoff_base=0,
        )
        uploader.upload_pending()
        with sqlite3.connect(self.outbox.path) as db:
            message_id = db.execute("SELECT message_id FROM delivery_outbox").fetchone()[0]
        self.outbox.mark_delivered(message_id, {"status": "committed"})
        uploader.reconcile_and_cleanup()
        self.assertTrue(data["clip_path"].is_file())
        self.assertEqual(self.recorder.pin_status("req-413b")["state"], "held")
        self.assertEqual(self.outbox.evidence_requests()[0]["state"], "failed")

    def test_file_size_mismatch_aborts(self) -> None:
        data = self._create_evidence("req-size-mismatch")
        # Change file size on disk
        data["clip_path"].write_bytes(b"short")

        uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
        )

        uploaded_count = uploader.upload_pending()
        self.assertEqual(uploaded_count, 0)
        self.assertEqual(len(self.server_requests), 0)

        outbox_requests = self.outbox.evidence_requests()
        self.assertIn("size mismatch", str(outbox_requests[0]["last_error"]).lower())

    def test_uploader_initialized_with_str_and_path_objects(self) -> None:
        data = self._create_evidence("req-path-init")
        uploader = EdgeUploader(
            outbox=str(self.outbox_path),
            recorder=str(self.recorder_dir),
            server_url=self.server_url,
            device_token=self.device_token,
        )

        self.assertIsInstance(uploader.outbox, EventOutbox)
        self.assertIsInstance(uploader.recorder, FileRecorder)
        self.assertEqual(uploader.upload_pending(), 1)
        self.assertEqual(self.outbox.evidence_requests()[0]["state"], "acknowledged")

    def test_invalid_server_url_rejected(self) -> None:
        # Credentials in URL rejected
        with self.assertRaises(ValueError):
            EdgeUploader(self.outbox, self.recorder, "https://user:pass@example.com", self.device_token)
        # Query parameters rejected
        with self.assertRaises(ValueError):
            EdgeUploader(self.outbox, self.recorder, "https://example.com/api?foo=bar", self.device_token)
        # Non-loopback plain http rejected
        with self.assertRaises(ValueError):
            EdgeUploader(self.outbox, self.recorder, "http://insecure-domain.com", self.device_token)


if __name__ == "__main__":
    unittest.main()
