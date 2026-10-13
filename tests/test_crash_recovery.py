from __future__ import annotations

import hashlib
import http.server
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from typing import Any
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder
from apps.edge.uploader import EdgeUploader, reconcile_and_cleanup
from apps.server.config import load_server_config
from apps.server.main import cleanup_temp_evidence, create_app
from apps.server.store import EventStore
from domain.evidence_contract import make_evidence_request
from tests.test_event_delivery import event_fixture


class MockEvidenceServer(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_PUT(self) -> None:
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

        if state.get("fail_once", False) and state.get("fail_count", 0) > 0:
            state["fail_count"] -= 1
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "service unavailable"}')
            return

        parts = path.strip("/").split("/")
        request_id = parts[-1] if len(parts) >= 4 else "req-test"
        sha256 = headers.get("X-Evidence-Sha256", hashlib.sha256(body).hexdigest())

        receipt = {
            "request_id": request_id,
            "sha256": sha256,
            "size_bytes": len(body),
            "location": f"{path}/media",
            "status": "committed",
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(receipt).encode("utf-8"))


def server_env(evidence_dir: str, db_name: str) -> dict[str, str]:
    return {
        "DEVICE_TOKENS": json.dumps({"token-edge-1": "lab-edge-01"}),
        "DASHBOARD_TOKEN": "dashboard-secret-token",
        "REVIEWER_TOKENS": json.dumps({"alice": "reviewer-secret-alice"}),
        "MONGO_URI": "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true",
        "MONGO_DATABASE": db_name,
        "EVIDENCE_DIR": evidence_dir,
    }


class TestCrashRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.outbox_path = self.root / "outbox.db"
        self.recorder_dir = self.root / "recorder"
        self.evidence_dir = self.root / "server_evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        self.outbox = EventOutbox(self.outbox_path)
        self.recorder = FileRecorder(self.recorder_dir)

        # Mock HTTP Server
        self.server_state: dict[str, Any] = {"requests": [], "fail_once": False, "fail_count": 0}
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), MockEvidenceServer)
        self.httpd.state = self.server_state  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self.server_url = f"http://127.0.0.1:{self.port}"
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.temp_dir.cleanup()

    def _create_event_with_request(
        self,
        request_id: str,
        *,
        state: str = "pending",
        session_id: str | None = None,
        anchor_time: float = 10.0,
    ) -> dict[str, Any]:
        event = event_fixture()
        eid = str(uuid4())
        sess_id = session_id or str(uuid4())
        event["event_id"] = eid
        event["message_id"] = f"msg-{eid}"
        event["stream_session_id"] = sess_id
        req = make_evidence_request(request_id, sess_id, "synthetic", anchor_time)
        payload = event["payload"]
        if isinstance(payload, dict):
            payload["evidence_requests"] = [req]
        self.outbox.enqueue(event)

        with sqlite3.connect(self.outbox.path) as db:
            db.execute(
                "UPDATE evidence_requests SET state=? WHERE request_id=?",
                (state, request_id),
            )
        return {"event": event, "request": req}

    def test_orphan_temp_file_cleanup_edge(self) -> None:
        manifest_dir = self.recorder_dir / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        session_dir = self.recorder_dir / "sess-crash"
        session_dir.mkdir(parents=True, exist_ok=True)

        # Stray temp files from simulated crash
        tmp_clip = manifest_dir / "abc123.tmp.mkv"
        tmp_clip.write_bytes(b"partial clip")
        tmp_json = manifest_dir / "abc123.json.tmp"
        tmp_json.write_text('{"partial": true}')
        tmp_concat = manifest_dir / "abc123.concat"
        tmp_concat.write_text("file 'foo'")
        session_tmp = session_dir / "seg.tmp"
        session_tmp.write_bytes(b"seg")

        # Legitimate non-temp file
        legit_file = manifest_dir / "valid.mkv"
        legit_file.write_bytes(b"valid clip")

        # Run reconciliation and cleanup
        res = reconcile_and_cleanup(self.outbox, self.recorder)

        # Temp files must be removed
        self.assertFalse(tmp_clip.exists())
        self.assertFalse(tmp_json.exists())
        self.assertFalse(tmp_concat.exists())
        self.assertFalse(session_tmp.exists())

        # Legitimate file must remain
        self.assertTrue(legit_file.exists())

    def test_orphan_temp_file_cleanup_server(self) -> None:
        device_id = "lab-edge-01"
        event_id = str(uuid4())
        req_dir = self.evidence_dir / device_id / event_id
        req_dir.mkdir(parents=True, exist_ok=True)

        # Stray temp files from crash during server upload
        stray1 = req_dir / f".req-01.{uuid4().hex}.tmp"
        stray1.write_bytes(b"incomplete write")
        stray2 = req_dir / "temp_file.tmp"
        stray2.write_bytes(b"temp")

        # Legitimate media file
        valid_media = req_dir / "req-01.mkv"
        valid_media.write_bytes(b"final media")

        cleaned = cleanup_temp_evidence(self.evidence_dir)

        self.assertIn(str(stray1), cleaned)
        self.assertFalse(stray1.exists())
        self.assertFalse(stray2.exists())
        self.assertTrue(valid_media.exists())

    def test_expired_ring_segments_reconciliation(self) -> None:
        # Request interval [0, 30], but ring has rolled forward or has no segments
        req_id = "req-expired-ring"
        sess_id = str(uuid4())
        self._create_event_with_request(req_id, state="pending", session_id=sess_id, anchor_time=10.0)

        # Session has no segments or all segments are past requested interval
        res = reconcile_and_cleanup(self.outbox, self.recorder)

        # Check outbox state: must transition to 'failed' with error about expired ring segments
        reqs = {r["request_id"]: r for r in self.outbox.evidence_requests()}
        target = reqs.get(req_id)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target["state"], "failed")
        self.assertIn("ring segments expired", str(target["last_error"]).lower())

    def test_mid_flight_crash_and_restart_resuming_valid_clips(self) -> None:
        req_id = "req-valid-resume"
        sess_id = str(uuid4())
        created = self._create_event_with_request(req_id, state="in_progress", session_id=sess_id, anchor_time=20.0)
        event = created["event"]

        clip_dir = self.recorder_dir / "manifests"
        clip_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(req_id.encode()).hexdigest()
        clip_path = clip_dir / f"{name}.mkv"
        clip_bytes = b"valid video stream data"
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
            "request_id": req_id,
            "session_id": sess_id,
            "owner": f"{event['device_id']}/{event['event_id']}/{event['revision']}",
            "requested_start": 10.0,
            "requested_end": 40.0,
            "actual_start": 10.0,
            "actual_end": 40.0,
            "actual_ranges": [[10.0, 40.0]],
            "gaps": [],
            "completeness": "complete",
            "reason": None,
            "build_state": "finalized",
            "state": "held",
            "artifact": artifact,
            "manifest": str(clip_dir / f"{name}.json"),
        }
        (clip_dir / f"{name}.json").write_text(json.dumps(receipt))

        with sqlite3.connect(self.recorder._pins) as db:
            db.execute(
                "INSERT OR REPLACE INTO pins(request_id, session_id, owner, start, end, receipt) VALUES (?,?,?,?,?,?)",
                (req_id, sess_id, receipt["owner"], 10.0, 40.0, json.dumps(receipt)),
            )

        with sqlite3.connect(self.outbox.path) as db:
            db.execute(
                "UPDATE evidence_requests SET receipt_json=? WHERE request_id=?",
                (json.dumps(receipt), req_id),
            )

        # Edge reboot: call reconcile_and_cleanup
        uploader = EdgeUploader(
            self.outbox,
            self.recorder,
            self.server_url,
            "test-token",
            backoff_base=0.01,
        )
        count = uploader.upload_pending(reconcile=True)
        self.assertEqual(count, 1)

        reqs = {r["request_id"]: r for r in self.outbox.evidence_requests()}
        self.assertEqual(reqs[req_id]["state"], "acknowledged")
        self.assertEqual(len(self.server_state["requests"]), 1)

    def test_corrupt_clip_marked_failed(self) -> None:
        req_id = "req-corrupt-file"
        sess_id = str(uuid4())
        created = self._create_event_with_request(req_id, state="in_progress", session_id=sess_id, anchor_time=10.0)
        event = created["event"]

        clip_dir = self.recorder_dir / "manifests"
        clip_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(req_id.encode()).hexdigest()
        clip_path = clip_dir / f"{name}.mkv"
        clip_bytes = b"bad corrupted content"
        clip_path.write_bytes(clip_bytes)

        # Receipt expects different hash/size
        expected_digest = hashlib.sha256(b"original real video content").hexdigest()
        artifact = {
            "path": str(clip_path),
            "size_bytes": 100,
            "sha256": expected_digest,
            "content_type": "video/x-matroska",
            "codec": "h264",
        }
        receipt = {
            "request_id": req_id,
            "session_id": sess_id,
            "owner": f"{event['device_id']}/{event['event_id']}/{event['revision']}",
            "requested_start": 0.0,
            "requested_end": 30.0,
            "actual_start": 0.0,
            "actual_end": 30.0,
            "actual_ranges": [[0.0, 30.0]],
            "gaps": [],
            "completeness": "complete",
            "reason": None,
            "build_state": "finalized",
            "state": "held",
            "artifact": artifact,
            "manifest": str(clip_dir / f"{name}.json"),
        }
        (clip_dir / f"{name}.json").write_text(json.dumps(receipt))

        with sqlite3.connect(self.recorder._pins) as db:
            db.execute(
                "INSERT OR REPLACE INTO pins(request_id, session_id, owner, start, end, receipt) VALUES (?,?,?,?,?,?)",
                (req_id, sess_id, receipt["owner"], 0.0, 30.0, json.dumps(receipt)),
            )

        with sqlite3.connect(self.outbox.path) as db:
            db.execute(
                "UPDATE evidence_requests SET receipt_json=? WHERE request_id=?",
                (json.dumps(receipt), req_id),
            )

        reconcile_and_cleanup(self.outbox, self.recorder)

        reqs = {r["request_id"]: r for r in self.outbox.evidence_requests()}
        target = reqs[req_id]
        self.assertEqual(target["state"], "failed")
        self.assertTrue("corrupt" in str(target["last_error"]).lower() or "mismatch" in str(target["last_error"]).lower())

    def test_server_missing_media_file_handling(self) -> None:
        db_name = f"test_crash_recovery_{uuid4().hex[:8]}"
        env = server_env(str(self.evidence_dir), db_name)
        config = load_server_config(env)
        app = create_app(config)
        client = TestClient(app)

        device_id = "lab-edge-01"
        event_id = str(uuid4())
        req_id = "req-missing-media"

        store = EventStore(config.mongo_uri, config.mongo_database)
        missing_path = str(self.evidence_dir / device_id / event_id / f"{req_id}.mkv")
        manifest_data = {
            "sha256": "0" * 64,
            "size_bytes": 100,
            "completeness": "complete",
        }
        store.record_evidence(device_id, event_id, req_id, manifest_data, missing_path)

        # GET manifest: should return 404 when media file is missing on disk
        res_meta = client.get(
            f"/v1/evidence/{device_id}/{event_id}/{req_id}",
            headers={"Authorization": "Bearer dashboard-secret-token"},
        )
        self.assertEqual(res_meta.status_code, 404)

        # GET media: should return 404
        res_media = client.get(
            f"/v1/evidence/{device_id}/{event_id}/{req_id}/media",
            headers={"Authorization": "Bearer dashboard-secret-token"},
        )
        self.assertEqual(res_media.status_code, 404)

        # Store verification check
        checked = store.get_evidence(device_id, event_id, req_id, verify_file=True)
        self.assertIsNotNone(checked)
        assert checked is not None
        self.assertEqual(checked["manifest"]["completeness"], "missing")
        store.close()

    def test_server_corrupt_media_file_handling(self) -> None:
        db_name = f"test_crash_recovery_{uuid4().hex[:8]}"
        env = server_env(str(self.evidence_dir), db_name)
        config = load_server_config(env)
        app = create_app(config)
        client = TestClient(app)

        device_id = "lab-edge-01"
        event_id = str(uuid4())
        req_id = "req-corrupt-media"

        target_dir = self.evidence_dir / device_id / event_id
        target_dir.mkdir(parents=True, exist_ok=True)
        media_path = target_dir / f"{req_id}.mkv"
        media_path.write_bytes(b"tampered-corrupted-bytes")

        store = EventStore(config.mongo_uri, config.mongo_database)
        manifest_data = {
            "sha256": hashlib.sha256(b"original-clean-bytes").hexdigest(),
            "size_bytes": len(b"original-clean-bytes"),
            "completeness": "complete",
        }
        store.record_evidence(device_id, event_id, req_id, manifest_data, str(media_path))

        # GET manifest: should return 404 or mark corrupt, never serve fake complete
        res_meta = client.get(
            f"/v1/evidence/{device_id}/{event_id}/{req_id}",
            headers={"Authorization": "Bearer dashboard-secret-token"},
        )
        self.assertEqual(res_meta.status_code, 404)

        # GET media: must not serve corrupted bytes
        res_media = client.get(
            f"/v1/evidence/{device_id}/{event_id}/{req_id}/media",
            headers={"Authorization": "Bearer dashboard-secret-token"},
        )
        self.assertEqual(res_media.status_code, 404)

        # Store verification check
        checked = store.get_evidence(device_id, event_id, req_id, verify_file=True)
        self.assertIsNotNone(checked)
        assert checked is not None
        self.assertEqual(checked["manifest"]["completeness"], "corrupt")
        store.close()

    def test_idempotent_upload_resumption_after_network_drop(self) -> None:
        req_id = "req-network-drop"
        sess_id = str(uuid4())
        created = self._create_event_with_request(req_id, state="fulfilled", session_id=sess_id, anchor_time=10.0)
        event = created["event"]

        clip_dir = self.recorder_dir / "manifests"
        clip_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(req_id.encode()).hexdigest()
        clip_path = clip_dir / f"{name}.mkv"
        clip_bytes = b"stream-data-bytes"
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
            "request_id": req_id,
            "session_id": sess_id,
            "owner": f"{event['device_id']}/{event['event_id']}/{event['revision']}",
            "requested_start": 0.0,
            "requested_end": 30.0,
            "actual_start": 0.0,
            "actual_end": 30.0,
            "actual_ranges": [[0.0, 30.0]],
            "gaps": [],
            "completeness": "complete",
            "reason": None,
            "build_state": "finalized",
            "state": "held",
            "artifact": artifact,
            "manifest": str(clip_dir / f"{name}.json"),
        }
        (clip_dir / f"{name}.json").write_text(json.dumps(receipt))

        with sqlite3.connect(self.recorder._pins) as db:
            db.execute(
                "INSERT OR REPLACE INTO pins(request_id, session_id, owner, start, end, receipt) VALUES (?,?,?,?,?,?)",
                (req_id, sess_id, receipt["owner"], 0.0, 30.0, json.dumps(receipt)),
            )

        with sqlite3.connect(self.outbox.path) as db:
            db.execute(
                "UPDATE evidence_requests SET state='fulfilled', receipt_json=? WHERE request_id=?",
                (json.dumps(receipt), req_id),
            )

        uploader = EdgeUploader(
            self.outbox,
            self.recorder,
            self.server_url,
            "test-token",
            max_retries=1,
            backoff_base=0.01,
        )

        # Inject 1 transient 503 failure
        self.server_state["fail_once"] = True
        self.server_state["fail_count"] = 1

        # First call succeeds on retry
        uploaded = uploader.upload_pending(reconcile=True)
        self.assertEqual(uploaded, 1)

        reqs = {r["request_id"]: r for r in self.outbox.evidence_requests()}
        self.assertEqual(reqs[req_id]["state"], "acknowledged")

        # Second call is idempotent no-op
        second_run = uploader.upload_pending(reconcile=True)
        self.assertEqual(second_run, 0)
