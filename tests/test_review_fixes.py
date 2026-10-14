"""Regressions for whole-working-tree review findings."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pymongo.errors import AutoReconnect

from apps.edge.evidence import EvidenceLifecycle
from apps.edge.incident import IncidentEngine
from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import ByteTracker, Track
from apps.server.config import load_server_config
from apps.server.dataset import export_dataset_records
from apps.server.main import create_app
from apps.server.store import EventStore, ReviewConflict
from domain.evidence_contract import make_evidence_request
from tests.test_server_evidence import sample_event, server_env


class EvidenceReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = "review_fixes_" + uuid4().hex
        self.config = load_server_config(server_env(str(self.root / "evidence"), self.database))
        self.app = create_app(self.config)
        self.store = self.app.state.event_store
        self.store.ensure_ready()
        self.addCleanup(self.store.close)
        self.addCleanup(self.store.database.client.drop_database, self.database)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.event = sample_event()
        self.receipt = self.store.persist(self.event)
        self.key = {name: self.event[name] for name in ("device_id", "event_id")}
        self.url = f"/v1/evidence/{self.event['device_id']}/{self.event['event_id']}/req-001"

    def upload(self, data=b"original video", url=None, metadata=None):
        return self.client.put(url or self.url, content=data, headers={
            "Authorization": "Bearer token-edge-1",
            "X-Evidence-Sha256": hashlib.sha256(data).hexdigest(),
            "X-Evidence-Metadata": json.dumps(metadata or {"completeness": "complete"}),
        })

    def review(self, versions=None, action="confirm", expected=0):
        return self.store.record_review(self.key, {
            "action": action, "expected_review_version": expected,
            "viewed_event_revision": 1, "viewed_event_hash": self.receipt["event_hash"],
            "viewed_evidence_versions": versions or {}, "reason": "verified",
        }, "alice")

    def test_upload_is_immutable_and_identical_retry_preserves_receipt(self):
        first = self.upload()
        self.assertEqual(first.status_code, 200)
        stored = self.store.get_evidence(**self.key, request_id="req-001")
        self.assertEqual(self.upload().json(), first.json())
        self.assertEqual(self.store.get_evidence(**self.key, request_id="req-001"), stored)
        self.assertEqual(self.upload(b"replacement").status_code, 409)
        self.assertEqual(Path(stored["file_path"]).read_bytes(), b"original video")

    def test_concurrent_different_uploads_commit_only_one_artifact(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(self.upload, (b"first", b"second")))
        self.assertEqual(sorted(item.status_code for item in responses), [200, 409])
        record = self.store.get_evidence(**self.key, request_id="req-001")
        self.assertEqual(hashlib.sha256(Path(record["file_path"]).read_bytes()).hexdigest(),
                         record["manifest"]["sha256"])

    def test_retry_recovers_file_published_before_database_commit(self):
        with patch.object(self.store, "record_evidence", side_effect=AutoReconnect("commit unavailable")):
            self.assertEqual(self.upload().status_code, 503)
        self.assertIsNone(self.store.get_evidence(**self.key, request_id="req-001"))
        self.assertEqual(self.upload().status_code, 200)
        record = self.store.get_evidence(**self.key, request_id="req-001")
        self.assertEqual(Path(record["file_path"]).read_bytes(), b"original video")

    def test_concurrent_review_and_upload_cannot_lose_freshness_flag(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            review = pool.submit(self.review)
            upload = pool.submit(self.upload)
            self.assertEqual(upload.result().status_code, 200)
            try:
                review.result()
            except ReviewConflict:
                pass
        state = self.store.reviews.find_one(self.key)
        if state:
            self.assertTrue(state["needs_re_review"])

    def test_upload_rejects_unknown_owner_metadata_and_parent_paths(self):
        self.assertEqual(self.upload(url=self.url.replace("req-001", "undeclared")).status_code, 404)
        self.assertEqual(self.upload(url=self.url.replace(str(self.event["event_id"]), "unknown")).status_code, 404)
        self.assertEqual(self.upload(metadata={"session_id": "wrong"}).status_code, 422)
        self.assertEqual(self.upload(metadata={"owner": "someone/else/1"}).status_code, 422)
        self.assertEqual(self.upload(url=self.url.replace(str(self.event["event_id"]), "%2e%2e")).status_code, 422)
        self.assertFalse((self.root / "evidence").exists())

    def test_old_review_conflicts_and_retry_does_not_invalidate_new_review(self):
        self.assertEqual(self.upload().status_code, 200)
        with self.assertRaises(ReviewConflict):
            self.review()
        reviewed = self.review({"req-001": 1})
        self.assertFalse(reviewed["needs_re_review"])
        self.assertEqual(self.upload().status_code, 200)
        state = self.store.reviews.find_one(self.key)
        self.assertFalse(state["needs_re_review"])
        self.assertEqual(state["review_version"], 1)

    def test_export_uses_reviewed_manifest_snapshot_after_metadata_update(self):
        self.assertEqual(self.upload(metadata={"completeness": "partial"}).status_code, 200)
        self.review({"req-001": 1})
        self.assertEqual(self.upload(metadata={"completeness": "complete"}).status_code, 200)
        current = self.store.get_evidence(**self.key, request_id="req-001")
        self.assertEqual(current["manifest_version"], 2)
        records = export_dataset_records(self.store, include_ambiguous=True)
        self.assertTrue(records[0]["is_ambiguous"])
        self.assertEqual(records[0]["viewed_evidence_versions"], {"req-001": 1})
        self.assertEqual(records[0]["evidence_manifests"][0]["completeness"], "partial")
        self.assertEqual(records[0]["evidence_manifests"][0]["manifest_version"], 1)
        self.assertNotIn(self.temp.name, json.dumps(records))

    def test_export_excludes_evidence_added_after_review(self):
        self.review()
        self.assertEqual(self.upload().status_code, 200)
        records = export_dataset_records(self.store, include_ambiguous=True)
        self.assertEqual(records[0]["evidence_manifests"], [])

    def test_metadata_only_retry_does_not_request_re_review(self):
        self.assertEqual(self.upload().status_code, 200)
        self.review({"req-001": 1})
        self.assertEqual(self.upload(metadata={"completeness": "complete", "transport_time": "later"}).status_code, 200)
        self.assertFalse(self.store.reviews.find_one(self.key)["needs_re_review"])

    def test_corrupt_evidence_persists_freshness_change_and_preserves_review_snapshot(self):
        self.assertEqual(self.upload().status_code, 200)
        self.review({"req-001": 1})
        record = self.store.get_evidence(**self.key, request_id="req-001")
        Path(record["file_path"]).write_bytes(b"broken")
        response = self.client.get(self.url + "/media", headers={"Authorization": "Bearer dashboard-secret-token"})
        self.assertEqual(response.status_code, 404)
        state = self.store.reviews.find_one(self.key)
        self.assertTrue(state["needs_re_review"])
        self.assertEqual(state["reviewed_evidence_manifests"][0]["manifest"]["completeness"], "complete")
        unavailable = self.store.get_evidence(**self.key, request_id="req-001")
        self.assertEqual(unavailable["manifest_version"], 2)
        self.assertEqual(unavailable["manifest"]["file_status"], "corrupt")


class EdgeReviewFixTests(unittest.TestCase):
    def test_subprocess_timeout_and_failure_retry_without_losing_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recorder = FileRecorder(root / "ring")
            outbox = EventOutbox(root / "outbox.sqlite3")
            event = sample_event()
            request = make_evidence_request("req-001", event["stream_session_id"], "onset", 10)
            event["payload"]["evidence_requests"] = [request]
            lifecycle = EvidenceLifecycle(outbox, recorder)
            lifecycle.persist(event)
            for failure in (subprocess.TimeoutExpired("ffmpeg", 1), subprocess.CalledProcessError(1, "ffmpeg")):
                with patch.object(recorder, "finalize_pin", side_effect=failure) as finalize:
                    lifecycle.reconcile(finish_sessions=[event["stream_session_id"]])
                    lifecycle.reconcile()
                self.assertEqual(finalize.call_count, 2)
                self.assertNotEqual(outbox.evidence_requests()[0]["state"], "failed")
                self.assertIsNotNone(recorder.pin_status("req-001"))

    def test_history_removed_tracks_and_incident_states_are_bounded(self):
        tracker = ByteTracker(max_lost_time=1)
        engine = IncidentEngine()
        det = {"bbox": [0, 0, 20, 80], "score": .9, "label": "person"}
        for index in range(1000):
            engine.process_tracks(tracker.update([det], index * 3), index * 3)
            engine.process_tracks(tracker.update([], index * 3 + 2), index * 3 + 2)
        self.assertEqual(tracker.get_all_tracks(), [])
        self.assertEqual(engine._states, {})
        track = Track(1, det["bbox"], .9, "person", 0)
        for index in range(5000):
            track.update(det["bbox"], .9, index / 1000)
        self.assertLessEqual(len(track.history), 256)
        track.update(det["bbox"], .9, 100)
        self.assertEqual(len(track.history), 1)

    def test_recovery_and_second_fall_during_cooldown_are_observed(self):
        engine = IncidentEngine(max_motion_speed=1000)
        standing = [100, 100, 160, 260]
        lying = [100, 220, 260, 280]
        track = Track(1, standing, .9, "person", 0)
        def observe(time, bbox):
            track.update(bbox, .9, time)
            return engine.process_tracks([track], time)
        observe(.5, standing)
        observe(1, lying)
        self.assertEqual(len(observe(4.1, lying)), 1)
        observe(10, standing)
        observe(19.5, standing)
        self.assertEqual(observe(20, lying), [])
        self.assertEqual(observe(24, lying), [])
        second = observe(35, lying)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["anchor_time"], 20)
