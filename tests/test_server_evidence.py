from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.server.config import load_server_config
from apps.server.main import create_app
from apps.server.store import EventStore


def server_env(evidence_dir: str, db_name: str) -> dict[str, str]:
    return {
        "DEVICE_TOKENS": json.dumps({"token-edge-1": "lab-edge-01", "token-edge-2": "lab-edge-02"}),
        "DASHBOARD_TOKEN": "dashboard-secret-token",
        "REVIEWER_TOKENS": json.dumps({"alice": "reviewer-secret-alice"}),
        "MONGO_URI": "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true",
        "MONGO_DATABASE": db_name,
        "EVIDENCE_DIR": evidence_dir,
    }


def sample_event(device_id: str = "lab-edge-01", event_id: str | None = None) -> dict[str, object]:
    eid = event_id or str(uuid4())
    session_id = str(uuid4())
    return {
        "schema_version": 1,
        "message_id": f"msg-{uuid4().hex[:8]}",
        "event_id": eid,
        "revision": 1,
        "device_id": device_id,
        "camera_id": "lab-camera-01",
        "stream_session_id": session_id,
        "pipeline_id": "synthetic-fixture",
        "pipeline_version": "1",
        "origin": "synthetic",
        "event_time": "2026-10-13T00:00:00Z",
        "produced_at": "2026-10-13T00:00:01Z",
        "config_version": "synthetic-v1",
        "model_lineage": [{"role": "fixture", "version": "1"}],
        "model_artifact_hash": "unknown_artifact",
        "calibration_version": "uncalibrated",
        "quality_state": "unknown",
        "payload": {
            "taxonomy": "person_fall",
            "lifecycle": "candidate",
            "severity": "high",
            "evidence_requests": [
                {
                    "request_id": "req-001",
                    "session_id": session_id,
                    "evidence_anchor_kind": "synthetic",
                    "evidence_anchor_time": 100.0,
                    "requested_start": 90.0,
                    "requested_end": 120.0,
                    "mapping_uncertainty": 0.0,
                    "policy_version": "lab-pre10-post20-v1",
                    "supersedes_request_id": None,
                }
            ],
        },
    }


class ServerEvidenceConfigTests(unittest.TestCase):
    def test_evidence_dir_defaults_and_custom_override(self) -> None:
        base_env = {
            "DEVICE_TOKENS": '{"tok":"dev-1"}',
            "DASHBOARD_TOKEN": "dash-tok",
            "MONGO_URI": "mongodb://mongo:27017/?replicaSet=rs0",
        }
        cfg_default = load_server_config(base_env)
        self.assertEqual(cfg_default.evidence_dir, "/tmp/ai-camera-evidence")

        env_custom = dict(base_env, EVIDENCE_DIR="/custom/evidence/dir")
        cfg_custom = load_server_config(env_custom)
        self.assertEqual(cfg_custom.evidence_dir, "/custom/evidence/dir")
        self.assertNotEqual(cfg_default.config_hash, cfg_custom.config_hash)

    def test_empty_evidence_dir_fails(self) -> None:
        env = {
            "DEVICE_TOKENS": '{"tok":"dev-1"}',
            "DASHBOARD_TOKEN": "dash-tok",
            "MONGO_URI": "mongodb://mongo:27017/?replicaSet=rs0",
            "EVIDENCE_DIR": "",
        }
        with self.assertRaisesRegex(ValueError, "EVIDENCE_DIR"):
            load_server_config(env)


class ServerEvidenceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_name = f"test_ev_store_{uuid4().hex[:12]}"
        self.store = EventStore(
            "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true",
            self.db_name,
        )
        self.store.ensure_ready()

    def tearDown(self) -> None:
        self.store.database.client.drop_database(self.db_name)
        self.store.close()
        self.temp_dir.cleanup()

    def test_record_and_get_evidence(self) -> None:
        device_id = "lab-edge-01"
        event_id = str(uuid4())
        request_id = "req-101"
        manifest_data = {
            "actual_range": [10.0, 25.0],
            "completeness": "complete",
            "codec": "h264",
            "sha256": "0" * 64,
            "size_bytes": 1024,
        }
        clip_path = os.path.join(self.temp_dir.name, f"{request_id}.mkv")
        with open(clip_path, "wb") as f:
            f.write(b"video-bytes")

        recorded = self.store.record_evidence(device_id, event_id, request_id, manifest_data, clip_path)
        self.assertEqual(recorded["device_id"], device_id)
        self.assertEqual(recorded["event_id"], event_id)
        self.assertEqual(recorded["request_id"], request_id)
        self.assertEqual(recorded["file_path"], clip_path)
        self.assertEqual(recorded["manifest"]["completeness"], "complete")

        fetched = self.store.get_evidence(device_id, event_id, request_id)
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched["request_id"], request_id)
        self.assertEqual(fetched["file_path"], clip_path)

        not_found = self.store.get_evidence(device_id, event_id, "nonexistent-req")
        self.assertIsNone(not_found)

    def test_record_evidence_triggers_re_review_on_confirmed_review(self) -> None:
        device_id = "lab-edge-01"
        event = sample_event(device_id=device_id)
        event_id = str(event["event_id"])
        receipt = self.store.persist(event)

        # Confirm review
        review_req = {
            "action": "confirm",
            "expected_review_version": 0,
            "viewed_event_revision": 1,
            "viewed_event_hash": receipt["event_hash"],
            "viewed_evidence_versions": {},
            "reason": "Initial confirmation",
        }
        reviewed = self.store.record_review({"device_id": device_id, "event_id": event_id}, review_req, "alice")
        self.assertEqual(reviewed["decision"], "confirmed")
        self.assertFalse(reviewed["needs_re_review"])

        # Now record evidence for this event
        manifest = {"actual_range": [90.0, 120.0], "completeness": "complete"}
        clip_path = os.path.join(self.temp_dir.name, "clip.mkv")
        with open(clip_path, "wb") as f:
            f.write(b"data")

        self.store.record_evidence(device_id, event_id, "req-001", manifest, clip_path)

        # Check that review now has needs_re_review = True
        current_rows = self.store.list_current(limit=10)
        matching = [r for r in current_rows if r["event"]["event_id"] == event_id]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]["review"]["needs_re_review"])
        self.assertEqual(matching[0]["review"]["decision"], "confirmed")


class ServerEvidenceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.evidence_dir = os.path.join(self.temp_dir.name, "evidence")
        self.db_name = f"test_ev_api_{uuid4().hex[:12]}"
        self.env = server_env(self.evidence_dir, self.db_name)

        # Monkeypatch environment for create_app
        self._orig_env = dict(os.environ)
        os.environ.clear()
        os.environ.update(self.env)

        self.app = create_app()
        self.client = TestClient(self.app)

        # Create an event in store
        self.device_id = "lab-edge-01"
        self.device_token = "token-edge-1"
        self.dashboard_token = "dashboard-secret-token"
        self.reviewer_token = "reviewer-secret-alice"
        self.event_id = str(uuid4())
        self.request_id = "req-001"

        event = sample_event(device_id=self.device_id, event_id=self.event_id)
        resp = self.client.post(
            "/v1/events",
            headers={
                "Authorization": f"Bearer {self.device_token}",
                "Content-Type": "application/json",
                "Idempotency-Key": str(event["message_id"]),
            },
            json=event,
        )
        self.assertEqual(resp.status_code, 200)

    def tearDown(self) -> None:
        store = getattr(self.app.state, "event_store", None)
        if store:
            store.database.client.drop_database(self.db_name)
            store.close()
        os.environ.clear()
        os.environ.update(self._orig_env)
        self.temp_dir.cleanup()

    def test_put_evidence_upload_validates_and_commits_atomically(self) -> None:
        video_payload = b"\x1a\x45\xdf\xa3" + b"video-content-bytes-for-evidence-clip" * 64
        sha256 = hashlib.sha256(video_payload).hexdigest()
        metadata = {
            "actual_range": [95.0, 115.0],
            "completeness": "complete",
            "codec": "h264",
            "size_bytes": len(video_payload),
        }

        url = f"/v1/evidence/{self.device_id}/{self.event_id}/{self.request_id}"
        headers = {
            "Authorization": f"Bearer {self.device_token}",
            "X-Evidence-Sha256": sha256,
            "X-Evidence-Metadata": json.dumps(metadata),
            "Content-Type": "video/x-matroska",
        }
        res = self.client.put(url, headers=headers, content=video_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["request_id"], self.request_id)
        self.assertEqual(data["sha256"], sha256)
        self.assertEqual(data["size_bytes"], len(video_payload))
        self.assertIn("location", data)

        # Check atomic file exists at expected path
        expected_file = Path(self.evidence_dir) / self.device_id / self.event_id / f"{self.request_id}.mkv"
        self.assertTrue(expected_file.is_file())
        self.assertEqual(expected_file.read_bytes(), video_payload)

    def test_put_evidence_rejects_checksum_and_size_mismatch(self) -> None:
        video_payload = b"valid-bytes"
        wrong_sha256 = "f" * 64
        metadata = {"actual_range": [0, 10], "completeness": "partial", "size_bytes": len(video_payload)}

        url = f"/v1/evidence/{self.device_id}/{self.event_id}/{self.request_id}"
        headers = {
            "Authorization": f"Bearer {self.device_token}",
            "X-Evidence-Sha256": wrong_sha256,
            "X-Evidence-Metadata": json.dumps(metadata),
        }
        res = self.client.put(url, headers=headers, content=video_payload)
        self.assertEqual(res.status_code, 422)

        # Size mismatch in metadata
        correct_sha = hashlib.sha256(video_payload).hexdigest()
        bad_meta = dict(metadata, size_bytes=99999)
        headers["X-Evidence-Sha256"] = correct_sha
        headers["X-Evidence-Metadata"] = json.dumps(bad_meta)
        res2 = self.client.put(url, headers=headers, content=video_payload)
        self.assertEqual(res2.status_code, 422)

    def test_put_evidence_rejects_unauthorized_or_device_mismatch(self) -> None:
        video_payload = b"video-data"
        sha256 = hashlib.sha256(video_payload).hexdigest()
        metadata = {"completeness": "complete"}
        url = f"/v1/evidence/{self.device_id}/{self.event_id}/{self.request_id}"

        # No auth
        res = self.client.put(url, headers={"X-Evidence-Sha256": sha256, "X-Evidence-Metadata": json.dumps(metadata)}, content=video_payload)
        self.assertEqual(res.status_code, 401)

        # Wrong device token (device-2 token trying to upload for device-1)
        headers = {
            "Authorization": "Bearer token-edge-2",
            "X-Evidence-Sha256": sha256,
            "X-Evidence-Metadata": json.dumps(metadata),
        }
        res = self.client.put(url, headers=headers, content=video_payload)
        self.assertEqual(res.status_code, 403)

    def test_get_evidence_manifest_and_media_streaming_with_ranges(self) -> None:
        # First upload
        video_payload = b"0123456789" * 100  # 1000 bytes
        sha256 = hashlib.sha256(video_payload).hexdigest()
        metadata = {"actual_range": [10.0, 20.0], "completeness": "complete"}
        put_url = f"/v1/evidence/{self.device_id}/{self.event_id}/{self.request_id}"
        self.client.put(
            put_url,
            headers={
                "Authorization": f"Bearer {self.device_token}",
                "X-Evidence-Sha256": sha256,
                "X-Evidence-Metadata": json.dumps(metadata),
            },
            content=video_payload,
        )

        # GET manifest
        get_meta_url = f"/v1/evidence/{self.device_id}/{self.event_id}/{self.request_id}"
        meta_res = self.client.get(get_meta_url, headers={"Authorization": f"Bearer {self.dashboard_token}"})
        self.assertEqual(meta_res.status_code, 200)
        self.assertEqual(meta_res.json()["manifest"]["completeness"], "complete")

        # GET media full (200 OK)
        media_url = f"/v1/evidence/{self.device_id}/{self.event_id}/{self.request_id}/media"
        full_res = self.client.get(media_url, headers={"Authorization": f"Bearer {self.dashboard_token}"})
        self.assertEqual(full_res.status_code, 200)
        self.assertEqual(full_res.headers["Accept-Ranges"], "bytes")
        self.assertEqual(full_res.headers["Content-Type"], "video/x-matroska")
        self.assertEqual(len(full_res.content), 1000)

        # GET media with query param token (e.g. for browser <video>)
        query_res = self.client.get(f"{media_url}?token={self.dashboard_token}")
        self.assertEqual(query_res.status_code, 200)
        self.assertEqual(len(query_res.content), 1000)

        # GET media with Range header (206 Partial Content)
        range_res = self.client.get(
            media_url,
            headers={"Authorization": f"Bearer {self.dashboard_token}", "Range": "bytes=0-9"},
        )
        self.assertEqual(range_res.status_code, 206)
        self.assertEqual(range_res.headers["Content-Range"], "bytes 0-9/1000")
        self.assertEqual(range_res.headers["Content-Length"], "10")
        self.assertEqual(range_res.content, b"0123456789")

        # Range suffix bytes=-20
        suffix_res = self.client.get(
            media_url,
            headers={"Authorization": f"Bearer {self.dashboard_token}", "Range": "bytes=-20"},
        )
        self.assertEqual(suffix_res.status_code, 206)
        self.assertEqual(suffix_res.headers["Content-Range"], "bytes 980-999/1000")
        self.assertEqual(len(suffix_res.content), 20)
        self.assertEqual(suffix_res.content, video_payload[-20:])

        # Out-of-bounds range -> 416
        bad_range_res = self.client.get(
            media_url,
            headers={"Authorization": f"Bearer {self.dashboard_token}", "Range": "bytes=1500-2000"},
        )
        self.assertEqual(bad_range_res.status_code, 416)
        self.assertIn("Content-Range", bad_range_res.headers)
        self.assertEqual(bad_range_res.headers["Content-Range"], "bytes */1000")

    def test_dashboard_ui_serves_html_and_list_events_includes_evidence(self) -> None:
        # Check GET / serves index.html with evidence player elements
        index_res = self.client.get("/")
        self.assertEqual(index_res.status_code, 200)
        self.assertIn("evidence-section", index_res.text)
        self.assertIn("Download clip", index_res.text)
        self.assertIn("Pending upload", index_res.text)

        # Upload an evidence clip
        video_payload = b"dummy-mkv-clip"
        sha256 = hashlib.sha256(video_payload).hexdigest()
        metadata = {"actual_range": [0.0, 10.0], "completeness": "complete"}
        put_url = f"/v1/evidence/{self.device_id}/{self.event_id}/req-001"
        self.client.put(
            put_url,
            headers={
                "Authorization": f"Bearer {self.device_token}",
                "X-Evidence-Sha256": sha256,
                "X-Evidence-Metadata": json.dumps(metadata),
            },
            content=video_payload,
        )

        # Check GET /v1/events includes the evidence record
        events_res = self.client.get("/v1/events", headers={"Authorization": f"Bearer {self.dashboard_token}"})
        self.assertEqual(events_res.status_code, 200)
        events = events_res.json()["events"]
        matched = [e for e in events if e["event"]["event_id"] == self.event_id]
        self.assertEqual(len(matched), 1)
        self.assertIn("evidence", matched[0])
        self.assertEqual(len(matched[0]["evidence"]), 1)
        self.assertEqual(matched[0]["evidence"][0]["request_id"], "req-001")


if __name__ == "__main__":
    unittest.main()
