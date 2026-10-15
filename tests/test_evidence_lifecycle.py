"""Evidence admission must protect durable state before accepting events."""
import errno
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.edge.evidence import EvidenceLifecycle
from apps.edge.outbox import EventOutbox
from apps.edge.quota import StorageQuotaManager
from apps.edge.recorder import FileRecorder
from domain.evidence_contract import make_evidence_request
from tests.test_event_delivery import event_fixture


class EvidenceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.outbox = EventOutbox(self.root / "outbox.sqlite3")
        self.recorder = FileRecorder(self.root / "recorder")
        self.disk = SimpleNamespace(total=1000, used=500, free=500)
        self.quota = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            min_state_reserve_bytes=100,
            disk_usage_fn=lambda path: self.disk,
        )
        self.lifecycle = EvidenceLifecycle(self.outbox, self.recorder, quota_manager=self.quota)

    def _event(self, request_id=None):
        event = event_fixture()
        if request_id:
            event["payload"]["evidence_requests"] = [
                make_evidence_request(request_id, event["stream_session_id"], "synthetic", 20)
            ]
        return event

    def _durable_rows(self):
        rows = {}
        with sqlite3.connect(self.outbox.path) as db:
            for table in ("event_revisions", "delivery_outbox", "evidence_requests", "ended_recorder_sessions"):
                rows[table] = db.execute(f"SELECT * FROM {table}").fetchall()
        with sqlite3.connect(self.recorder.root / "pins.sqlite3") as db:
            for table in ("pins", "transfers"):
                rows[table] = db.execute(f"SELECT * FROM {table}").fetchall()
        return rows

    def test_reserve_exhaustion_rejects_before_enqueue_with_or_without_evidence(self):
        for free in (100, 99, 0):
            for request_id in (None, "new-request"):
                with self.subTest(free=free, evidence=request_id):
                    self.disk.free = free
                    self.disk.used = self.disk.total - free
                    with patch.object(self.outbox, "enqueue", wraps=self.outbox.enqueue) as enqueue, \
                            patch.object(self.recorder, "pin", wraps=self.recorder.pin) as pin:
                        with self.assertRaisesRegex(OSError, "storage_exhausted") as raised:
                            self.lifecycle.persist(self._event(request_id))
                        self.assertEqual(raised.exception.errno, errno.ENOSPC)
                        enqueue.assert_not_called()
                        pin.assert_not_called()
                    self.assertTrue(all(not rows for rows in self._durable_rows().values()))

    def test_outbox_volume_reserve_exhaustion_rejects_with_healthy_recorder(self):
        self.quota.storage_path = self.recorder.root.resolve()
        outbox_dir = Path(self.outbox.path).resolve().parent
        outbox_disk = SimpleNamespace(total=1000, used=900, free=100)
        self.quota.disk_usage_fn = lambda path: outbox_disk if Path(path) == outbox_dir else self.disk
        self.assertGreater(self.quota.get_storage_breakdown().free_bytes, self.quota.min_state_reserve_bytes)
        for request_id in (None, "outbox-exhausted"):
            with self.subTest(evidence=request_id):
                with patch.object(self.outbox, "enqueue", wraps=self.outbox.enqueue) as enqueue:
                    with self.assertRaisesRegex(OSError, "storage_exhausted") as raised:
                        self.lifecycle.persist(self._event(request_id))
                    self.assertEqual(raised.exception.errno, errno.ENOSPC)
                    enqueue.assert_not_called()
                self.assertTrue(all(not rows for rows in self._durable_rows().values()))

    def test_minimal_injected_quota_without_disk_usage_hook_remains_supported(self):
        self.lifecycle.quota_manager = SimpleNamespace(
            min_state_reserve_bytes=100,
            get_storage_breakdown=lambda: SimpleNamespace(free_bytes=500),
            can_accept_new_evidence=lambda: True,
        )
        self.lifecycle.persist(self._event("injected-quota"))
        self.assertEqual(len(self.outbox.pending()), 1)
        self.assertEqual(self.outbox.evidence_requests()[0]["state"], "collecting")

    def test_rejected_event_can_retry_idempotently_after_capacity_recovers(self):
        event = self._event("retry-request")
        self.disk.free = 100
        with self.assertRaises(OSError):
            self.lifecycle.persist(event)
        self.disk.free = 500
        self.assertIs(self.lifecycle.persist(event), event)
        first_rows = self._durable_rows()
        self.assertIs(self.lifecycle.persist(event), event)
        self.assertEqual(self._durable_rows(), first_rows)
        for table in ("event_revisions", "delivery_outbox", "evidence_requests", "pins"):
            self.assertEqual(len(first_rows[table]), 1)
        self.assertEqual(self.outbox.evidence_requests()[0]["state"], "collecting")

    def test_rejection_preserves_existing_event_intent_and_protected_pin(self):
        self.lifecycle.persist(self._event("protected-request"))
        before = self._durable_rows()
        self.disk.free = 100
        event = self._event("rejected-request")
        event["event_id"] = "00000000-0000-4000-8000-000000000003"
        event["message_id"] = "msg-rejected"
        with self.assertRaises(OSError):
            self.lifecycle.persist(event)
        self.assertEqual(self._durable_rows(), before)
        self.assertEqual(self.recorder.pin_status("protected-request")["state"], "collecting")

    def test_media_pressure_does_not_reject_event_with_state_reserve_available(self):
        self.disk.total = 10000
        self.disk.used = 9800
        self.disk.free = 200
        self.assertTrue(self.quota.is_storage_exhausted())
        self.assertFalse(self.quota.can_accept_new_evidence())
        self.lifecycle.persist(self._event("media-pressure"))
        self.assertEqual(len(self.outbox.pending()), 1)
        self.assertEqual(self.outbox.evidence_requests()[0]["state"], "failed")
        self.assertIsNone(self.recorder.pin_status("media-pressure"))

    def test_can_accept_new_evidence_receives_estimated_bytes_from_actual_range(self):
        event = self._event("req-est-test")
        session_id = event["stream_session_id"]
        session_dir = self.recorder.root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        seg_media = session_dir / "segment-00000.mkv"
        seg_media.write_bytes(b"x" * 3500)
        import json
        seg_media.with_suffix(".json").write_text(json.dumps({
            "path": str(seg_media),
            "session_id": session_id,
            "codec": "h264",
            "time_base": "1/1000",
            "start_pts": 0,
            "end_pts": 40000,
            "start_seconds": 10.0,
            "end_seconds": 40.0,
            "keyframe_pts": [0],
            "frame_interval_seconds": 0.04,
        }))

        recorded_calls = []
        original_can_accept = self.quota.can_accept_new_evidence

        def spy_can_accept(estimated_bytes=0):
            recorded_calls.append(estimated_bytes)
            return original_can_accept(estimated_bytes)

        with patch.object(self.quota, "can_accept_new_evidence", side_effect=spy_can_accept):
            self.lifecycle.persist(event)

        self.assertTrue(recorded_calls, "can_accept_new_evidence should have been called")
        self.assertEqual(recorded_calls[0], 3500, "estimated_bytes should match total segment bytes in actual range")

    def test_reconcile_quota_rejection_does_not_leave_orphan_active_pin(self):
        """A request refused for storage must not stay pinned: the pin would block ring reclamation forever."""
        event = self._event("req-quota-reject")
        self.lifecycle.persist(event)
        session_id = event["stream_session_id"]
        # persist() pinned the request; simulate the pin having been released before reconcile
        # was refused, and confirm refusal does not (re)create an unreleased pin.
        self.recorder.release_pin("req-quota-reject")
        with sqlite3.connect(self.recorder.root / "pins.sqlite3") as db:
            db.execute("DELETE FROM pins WHERE request_id=?", ("req-quota-reject",))
        self.outbox.update_evidence("req-quota-reject", state="requested")

        with patch.object(self.quota, "can_accept_new_evidence", return_value=False):
            result = self.lifecycle.reconcile(finish_sessions=(session_id,))

        self.assertEqual(result["failed_requests"], 1)
        self.assertIsNone(self.recorder.pin_status("req-quota-reject"),
                          "quota-rejected request must not leave a pin behind")
        with sqlite3.connect(self.recorder.root / "pins.sqlite3") as db:
            active = db.execute("SELECT COUNT(*) FROM pins WHERE released=0").fetchone()[0]
        self.assertEqual(active, 0)

    def test_reconcile_quota_rejection_releases_pin_made_earlier(self):
        event = self._event("req-quota-reject-2")
        self.lifecycle.persist(event)
        session_id = event["stream_session_id"]
        self.assertIsNotNone(self.recorder.pin_status("req-quota-reject-2"))

        with patch.object(self.quota, "can_accept_new_evidence", return_value=False):
            result = self.lifecycle.reconcile(finish_sessions=(session_id,))

        self.assertEqual(result["failed_requests"], 1)
        with sqlite3.connect(self.recorder.root / "pins.sqlite3") as db:
            active = db.execute("SELECT COUNT(*) FROM pins WHERE released=0").fetchone()[0]
        self.assertEqual(active, 0, "failed request must not keep an unreleased pin")

    def test_reconcile_calls_can_accept_new_evidence_with_estimated_bytes(self):
        self.disk.total = 100000
        self.disk.free = 50000
        self.disk.used = 50000
        event = self._event("req-reconcile-est")
        session_id = event["stream_session_id"]
        session_dir = self.recorder.root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        seg_media = session_dir / "segment-00000.mkv"
        seg_media.write_bytes(b"y" * 4200)
        import json
        seg_media.with_suffix(".json").write_text(json.dumps({
            "path": str(seg_media),
            "session_id": session_id,
            "codec": "h264",
            "time_base": "1/1000",
            "start_pts": 0,
            "end_pts": 40000,
            "start_seconds": 10.0,
            "end_seconds": 40.0,
            "keyframe_pts": [0],
            "frame_interval_seconds": 0.04,
        }))

        self.lifecycle.persist(event)

        recorded_calls = []
        original_can_accept = self.quota.can_accept_new_evidence

        def spy_can_accept(estimated_bytes=0):
            recorded_calls.append(estimated_bytes)
            return original_can_accept(estimated_bytes)

        with patch.object(self.quota, "can_accept_new_evidence", side_effect=spy_can_accept), \
                patch.object(self.recorder, "finalize_pin", return_value={"manifest": "mock", "state": "held"}):
            self.lifecycle.reconcile(finish_sessions=(session_id,))

        self.assertTrue(recorded_calls, "can_accept_new_evidence should have been called during reconcile")
        self.assertEqual(recorded_calls[0], 4200, "estimated_bytes during reconcile should match segment bytes")


if __name__ == "__main__":
    unittest.main()
