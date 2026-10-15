"""Test suite for StorageQuotaManager (Ticket #18)."""
from __future__ import annotations

from collections import namedtuple
import errno
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any
import unittest
from unittest import mock
from unittest.mock import patch
from uuid import uuid4

from apps.edge.evidence import EvidenceLifecycle
from apps.edge.health import EdgeHealthMonitor, HealthStatus
from apps.edge.outbox import EventOutbox
from apps.edge.quota import StorageBreakdown, StorageQuotaManager
from apps.edge.recorder import FileRecorder
from domain.evidence_contract import make_evidence_request
from tests.test_event_delivery import event_fixture

DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


class StorageQuotaManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.recorder_dir = self.root / "recorder"
        self.recorder_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_path = self.root / "outbox.db"

        self.recorder = FileRecorder(self.recorder_dir)
        self.outbox = EventOutbox(self.outbox_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_dummy_segment(
        self,
        session_id: str,
        name: str,
        start: float,
        end: float,
        size_bytes: int = 1000,
    ) -> Path:
        sdir = self.recorder_dir / session_id
        sdir.mkdir(parents=True, exist_ok=True)
        media_path = sdir / f"{name}.mkv"
        meta_path = sdir / f"{name}.json"
        media_path.write_bytes(b"x" * size_bytes)
        meta = {
            "path": str(media_path),
            "session_id": session_id,
            "codec": "h264",
            "time_base": "1/1000",
            "start_pts": int(start * 1000),
            "end_pts": int(end * 1000),
            "start_seconds": start,
            "end_seconds": end,
            "keyframe_pts": [int(start * 1000)],
            "frame_interval_seconds": 0.04,
        }
        meta_path.write_text(json.dumps(meta))
        return media_path

    def _create_dummy_manifest(
        self,
        request_id: str,
        session_id: str,
        size_bytes: int = 5000,
    ) -> Path:
        import hashlib
        mdir = self.recorder_dir / "manifests"
        mdir.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(request_id.encode()).hexdigest()
        clip_path = mdir / f"{h}.mkv"
        json_path = mdir / f"{h}.json"
        clip_path.write_bytes(b"c" * size_bytes)
        digest = hashlib.sha256(b"c" * size_bytes).hexdigest()
        manifest = {
            "request_id": request_id,
            "session_id": session_id,
            "owner": "test/1/1",
            "requested_start": 10.0,
            "requested_end": 20.0,
            "actual_start": 10.0,
            "actual_end": 20.0,
            "build_state": "finalized",
            "state": "held",
            "artifact": {
                "path": str(clip_path),
                "size_bytes": size_bytes,
                "sha256": digest,
                "content_type": "video/x-matroska",
                "codec": "h264",
            },
            "transfer_state": "not_started",
        }
        json_path.write_text(json.dumps(manifest))
        return clip_path

    def test_storage_breakdown_accounting(self) -> None:
        # 1. Unpinned ring segment (session-1, 0.0 - 8.0)
        self._create_dummy_segment("sess-1", "seg-001", 0.0, 8.0, size_bytes=10000)

        # 2. Pinned segment (session-1, covered by pin 10.0 - 20.0)
        self._create_dummy_segment("sess-1", "seg-002", 10.0, 20.0, size_bytes=20000)
        self.recorder.pin("req-1", "sess-1", 10.0, 20.0, "owner-1")

        # 3. Finalized evidence clip in manifests
        self._create_dummy_manifest("req-finalized", "sess-1", size_bytes=30000)

        # 4. Temp files: .part in session, .tmp.mkv in manifests, .json.tmp
        temp_part = self.recorder_dir / "sess-1" / ".segment-00003.part.mkv"
        temp_part.write_bytes(b"t" * 4000)
        temp_clip = self.recorder_dir / "manifests" / "scratch.tmp.mkv"
        temp_clip.write_bytes(b"t" * 5000)
        temp_concat = self.recorder_dir / "manifests" / "scratch.concat"
        temp_concat.write_bytes(b"t" * 1000)

        # Mock disk usage: total=100MB, used=60MB, free=40MB
        total = 100 * 1024 * 1024
        used = 60 * 1024 * 1024
        free = 40 * 1024 * 1024
        mock_disk = lambda path: DiskUsage(total=total, used=used, free=free)

        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            disk_usage_fn=mock_disk,
        )

        breakdown = qm.get_storage_breakdown()
        self.assertIsInstance(breakdown, StorageBreakdown)

        # Check ring bytes: seg-001 media + sidecar json
        seg1_media = self.recorder_dir / "sess-1" / "seg-001.mkv"
        seg1_json = self.recorder_dir / "sess-1" / "seg-001.json"
        expected_ring = seg1_media.stat().st_size + seg1_json.stat().st_size
        self.assertEqual(breakdown.ring_bytes, expected_ring)

        # Check pinned bytes: seg-002 (media+json) + finalized clip (media+json)
        seg2_media = self.recorder_dir / "sess-1" / "seg-002.mkv"
        seg2_json = self.recorder_dir / "sess-1" / "seg-002.json"
        import hashlib
        h = hashlib.sha256("req-finalized".encode()).hexdigest()
        fin_media = self.recorder_dir / "manifests" / f"{h}.mkv"
        fin_json = self.recorder_dir / "manifests" / f"{h}.json"
        expected_pinned = (
            seg2_media.stat().st_size
            + seg2_json.stat().st_size
            + fin_media.stat().st_size
            + fin_json.stat().st_size
        )
        self.assertEqual(breakdown.pinned_bytes, expected_pinned)

        # Check temp bytes: temp_part (4000) + temp_clip (5000) + temp_concat (1000) = 10000
        expected_temp = (
            temp_part.stat().st_size
            + temp_clip.stat().st_size
            + temp_concat.stat().st_size
        )
        self.assertEqual(breakdown.temp_bytes, expected_temp)

        # Check wal bytes: pins.sqlite3 and outbox.db (and journals/wal)
        self.assertGreater(breakdown.wal_bytes, 0)

        # Check free/total/used_percent
        self.assertEqual(breakdown.free_bytes, free)
        self.assertEqual(breakdown.total_bytes, total)
        self.assertEqual(breakdown.used_percent, 60.0)

    def test_cleanup_eligible_under_pressure_preserves_unack_evidence(self) -> None:
        # Setup:
        # - unpinned segment (should be deleted under pressure)
        seg1 = self._create_dummy_segment("sess-1", "seg-unpinned", 0.0, 10.0, size_bytes=15000)
        # - unknown scratch (must be preserved under pressure)
        temp_file = self.recorder_dir / "manifests" / "dummy.tmp.mkv"
        self.recorder_dir.joinpath("manifests").mkdir(parents=True, exist_ok=True)
        temp_file.write_bytes(b"tempdata")

        # - pinned unACK segment (MUST NOT be deleted)
        seg_pinned = self._create_dummy_segment("sess-1", "seg-pinned", 20.0, 30.0, size_bytes=20000)
        self.recorder.pin("req-unack-pin", "sess-1", 20.0, 30.0, "owner-unack")

        # - finalized unACK clip (MUST NOT be deleted)
        unack_clip = self._create_dummy_manifest("req-unack-clip", "sess-1", size_bytes=25000)

        # Simulate storage pressure: used 92% (>= 90% warning)
        mock_disk = lambda path: DiskUsage(total=100_000_000, used=92_000_000, free=8_000_000)
        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            disk_usage_fn=mock_disk,
        )
        self.assertTrue(qm.is_storage_pressured())

        cleanup_result = qm.cleanup_eligible()
        self.assertGreater(cleanup_result["cleaned_bytes"], 0)

        # Verify: suffix alone does not establish scratch ownership
        self.assertTrue(temp_file.exists())

        # Verify: unpinned segment deleted
        self.assertFalse(seg1.exists())
        self.assertFalse(seg1.with_suffix(".json").exists())

        # STRICT UNACK PRESERVATION:
        # Pinned segment MUST exist
        self.assertTrue(seg_pinned.exists())
        self.assertTrue(seg_pinned.with_suffix(".json").exists())

        # Finalized unACK clip MUST exist
        self.assertTrue(unack_clip.exists())
        self.assertTrue(unack_clip.with_suffix(".json").exists())

    def test_cleanup_not_triggered_when_not_pressured_unless_forced(self) -> None:
        seg1 = self._create_dummy_segment("sess-1", "seg-unpinned", 0.0, 8.0, size_bytes=1000)
        temp_file = self.recorder_dir / "manifests" / "scratch.tmp.mkv"
        self.recorder_dir.joinpath("manifests").mkdir(parents=True, exist_ok=True)
        temp_file.write_bytes(b"123")

        # Healthy disk (50% used, 250MB free >> 50MB reserve)
        mock_disk = lambda path: DiskUsage(total=500 * 1024 * 1024, used=250 * 1024 * 1024, free=250 * 1024 * 1024)
        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            disk_usage_fn=mock_disk,
        )
        self.assertFalse(qm.is_storage_pressured())

        # Without force, cleanup does not run
        res = qm.cleanup_eligible()
        self.assertEqual(res["cleaned_bytes"], 0)
        self.assertTrue(seg1.exists())
        self.assertTrue(temp_file.exists())

        # With force=True, eligible data is cleaned
        res_forced = qm.cleanup_eligible(force=True)
        self.assertGreater(res_forced["cleaned_bytes"], 0)
        self.assertTrue(temp_file.exists())

    def test_24h_wan_outage_does_not_purge_unack_evidence(self) -> None:
        # Simulate an event created 36 hours ago (129600 seconds ago)
        now = time.time()
        old_time = now - 129600.0

        # Create old unpinned segment (ends before pin starts)
        old_unpinned = self._create_dummy_segment("sess-1", "old-unpinned", old_time, old_time + 8, size_bytes=10000)

        # Create old pinned segment (covered by pin from 36h ago)
        old_pinned = self._create_dummy_segment("sess-1", "old-pinned", old_time + 10, old_time + 20, size_bytes=15000)
        self.recorder.pin("req-outage-36h", "sess-1", old_time + 10, old_time + 20, "outage-owner")

        # Create old finalized clip from 36h ago
        old_clip = self._create_dummy_manifest("req-outage-clip-36h", "sess-1", size_bytes=20000)

        # Even with severe storage pressure (98% critical)
        mock_disk = lambda path: DiskUsage(total=100_000_000, used=98_000_000, free=2_000_000)
        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            disk_usage_fn=mock_disk,
        )

        res = qm.cleanup_eligible()
        self.assertIn(str(old_unpinned), res["cleaned_files"])
        self.assertFalse(old_unpinned.exists())

        # CRITICAL ACCEPTANCE: 24h+ outage MUST NOT purge unACK evidence
        self.assertTrue(old_pinned.exists())
        self.assertTrue(old_pinned.with_suffix(".json").exists())
        self.assertTrue(old_clip.exists())
        self.assertTrue(old_clip.with_suffix(".json").exists())

    def test_can_accept_new_evidence_refuses_when_exhausted(self) -> None:
        # Default reserve is 50MB
        qm = StorageQuotaManager(
            storage_path=self.root,
            min_state_reserve_bytes=50 * 1024 * 1024,
            warning_percent=90.0,
            critical_percent=95.0,
        )

        # 1. Healthy: 60% used, 200MB free -> can accept
        qm.disk_usage_fn = lambda path: DiskUsage(total=500 * 1024 * 1024, used=300 * 1024 * 1024, free=200 * 1024 * 1024)
        self.assertFalse(qm.is_storage_pressured())
        self.assertFalse(qm.is_storage_exhausted())
        self.assertTrue(qm.can_accept_new_evidence())

        # 2. Critical threshold reached: >= 95% used -> REFUSE
        qm.disk_usage_fn = lambda path: DiskUsage(total=1000 * 1024 * 1024, used=955 * 1024 * 1024, free=45 * 1024 * 1024)
        self.assertTrue(qm.is_storage_pressured())
        self.assertTrue(qm.is_storage_exhausted())
        self.assertFalse(qm.can_accept_new_evidence())

        # 3. Free bytes below min_state_reserve_bytes (e.g. 40MB < 50MB) even if percentage < 95% -> REFUSE
        qm.disk_usage_fn = lambda path: DiskUsage(total=100 * 1024 * 1024, used=60 * 1024 * 1024, free=40 * 1024 * 1024)
        self.assertTrue(qm.is_storage_exhausted())
        self.assertFalse(qm.can_accept_new_evidence())

        # 4. Large estimated clip (e.g. 30MB) when free is 60MB (remaining 30MB < 50MB reserve) -> REFUSE
        qm.disk_usage_fn = lambda path: DiskUsage(total=200 * 1024 * 1024, used=140 * 1024 * 1024, free=60 * 1024 * 1024)
        self.assertFalse(qm.can_accept_new_evidence(estimated_bytes=30 * 1024 * 1024))

    def test_evidence_lifecycle_refusal_under_storage_exhaustion_no_fake_ack(self) -> None:
        # Exhausted disk: 96% used
        mock_disk = lambda path: DiskUsage(total=100 * 1024 * 1024, used=96 * 1024 * 1024, free=4 * 1024 * 1024)
        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            disk_usage_fn=mock_disk,
        )

        lifecycle = EvidenceLifecycle(self.outbox, self.recorder, quota_manager=qm)

        # Enqueue event with evidence request
        event = event_fixture()
        sess_id = str(uuid4())
        event["stream_session_id"] = sess_id
        req_id = f"req-{uuid4()}"
        event["payload"]["evidence_requests"] = [
            make_evidence_request(req_id, sess_id, "synthetic", 50.0)
        ]

        with self.assertRaises(OSError) as raised:
            lifecycle.persist(event)
        self.assertEqual(raised.exception.errno, errno.ENOSPC)
        with sqlite3.connect(self.outbox_path) as db:
            for table in ("event_revisions", "delivery_outbox", "evidence_requests"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        with sqlite3.connect(self.recorder._pins) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM pins").fetchone()[0], 0)
        self.assertIsNone(self.recorder.pin_status(req_id))
        self.assertIsNone(lifecycle.upload_single_request(req_id))

    def test_evidence_lifecycle_reconcile_cleans_eligible_under_pressure(self) -> None:
        # Setup unpinned segment and temp file
        seg1 = self._create_dummy_segment("sess-p", "seg-p1", 0.0, 10.0, size_bytes=8000)
        temp_file = self.recorder_dir / "manifests" / "dummy.tmp.mkv"
        self.recorder_dir.joinpath("manifests").mkdir(parents=True, exist_ok=True)
        temp_file.write_bytes(b"temp")

        # Pressure at 91%
        mock_disk = lambda path: DiskUsage(total=100 * 1024 * 1024, used=91 * 1024 * 1024, free=9 * 1024 * 1024)
        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            disk_usage_fn=mock_disk,
        )

        lifecycle = EvidenceLifecycle(self.outbox, self.recorder, quota_manager=qm)
        lifecycle.reconcile()

        # Under pressure, eligible cleanup was triggered
        self.assertTrue(temp_file.exists())
        self.assertFalse(seg1.exists())

    def test_enospc_write_failure_graceful_handling_without_fake_success(self) -> None:
        # Create a valid pin and segments
        sess_id = str(uuid4())
        self._create_dummy_segment(sess_id, "seg-1", 10.0, 20.0, size_bytes=5000)
        self._create_dummy_segment(sess_id, "seg-2", 20.0, 30.0, size_bytes=5000)

        req_id = f"req-enospc-{uuid4()}"
        event = event_fixture()
        event["stream_session_id"] = sess_id
        event["payload"]["evidence_requests"] = [
            make_evidence_request(req_id, sess_id, "synthetic", 20.0)
        ]

        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            # Healthy disk initially
            disk_usage_fn=lambda path: DiskUsage(total=500 * 1024 * 1024, used=200 * 1024 * 1024, free=300 * 1024 * 1024),
        )
        lifecycle = EvidenceLifecycle(self.outbox, self.recorder, quota_manager=qm)
        lifecycle.persist(event)

        # Inject ENOSPC into finalize_pin
        with patch.object(self.recorder, "finalize_pin", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            result = lifecycle.reconcile(finish_sessions=(sess_id,))
            self.assertEqual(result["failed_requests"], 1)

        # Check outbox state: marked failed, error recorded, outbox intact
        requests = {r["request_id"]: r for r in self.outbox.evidence_requests()}
        self.assertEqual(requests[req_id]["state"], "failed")
        self.assertIn("No space left on device", requests[req_id]["last_error"])

        # Never emit fake receipt
        self.assertIsNone(lifecycle.upload_single_request(req_id))

    def test_edge_health_monitor_integration(self) -> None:
        # 1. Normal storage: 50%
        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            disk_usage_fn=lambda path: DiskUsage(total=1_000_000_000, used=500_000_000, free=500_000_000),
        )
        monitor = EdgeHealthMonitor(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            quota_manager=qm,
        )
        monitor.mark_started()
        now = time.time()
        monitor.record_frame_received(receive_time=now, capture_time=now, clock_mapping_valid=True)
        monitor.set_component_capability("analytics", "active")
        monitor.set_component_capability("recorder", "active")

        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], HealthStatus.HEALTHY.value)
        self.assertEqual(snapshot["metrics"]["disk_usage_percent"], 50.0)
        self.assertEqual(snapshot["metrics"]["disk_free_bytes"], 500_000_000)

        # 2. Pressured storage: 92% (>= 90%) and free 80MB (> 50MB reserve) -> DEGRADED with reason "disk_near_capacity"
        qm.disk_usage_fn = lambda path: DiskUsage(total=1_000_000_000, used=920_000_000, free=80_000_000)
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], HealthStatus.DEGRADED.value)
        self.assertIn("disk_near_capacity", snapshot["all_reasons"])

        # 3. Exhausted storage: 96% (>= 95%) -> UNAVAILABLE with reason "storage_exhausted"
        qm.disk_usage_fn = lambda path: DiskUsage(total=1_000_000_000, used=960_000_000, free=40_000_000)
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], HealthStatus.UNAVAILABLE.value)
        self.assertIn("storage_exhausted", snapshot["all_reasons"])

    def test_cleanup_storage_reclaims_released_and_acked_manifests(self) -> None:
        import hashlib
        # 1. Active pin (released=0)
        self.recorder.pin("req-active", "sess-1", 0.0, 10.0, "owner-1")
        clip_active = self._create_dummy_manifest("req-active", "sess-1", size_bytes=1000)

        # 2. Released pin without ACK in transfers (released=1, no transfer ACK)
        self.recorder.pin("req-unack", "sess-1", 10.0, 20.0, "owner-2")
        clip_unack = self._create_dummy_manifest("req-unack", "sess-1", size_bytes=2000)
        self.recorder.release_pin("req-unack")

        # 3. Released pin WITH ACK in transfers (released=1, has transfer receipt)
        self.recorder.pin("req-acked", "sess-1", 20.0, 30.0, "owner-3")
        clip_acked = self._create_dummy_manifest("req-acked", "sess-1", size_bytes=3000)
        with sqlite3.connect(self.recorder._pins) as db:
            db.execute("INSERT INTO transfers VALUES(?,?)", ("req-acked", json.dumps({"receipt": "ok"})))
        self.recorder.release_pin("req-acked")

        # 4. Unknown file in manifests/ (must never be deleted)
        unknown_file = self.recorder_dir / "manifests" / "unknown_recording.mkv"
        unknown_file.write_bytes(b"stranger")

        # Mock storage pressure
        mock_disk = lambda path: DiskUsage(total=100_000_000, used=95_000_000, free=5_000_000)
        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
            disk_usage_fn=mock_disk,
        )

        res = qm.cleanup_eligible(force=True)

        # Verified: req-acked manifest is reclaimed
        self.assertFalse(clip_acked.exists())
        self.assertFalse(clip_acked.with_suffix(".json").exists())
        self.assertIn(str(clip_acked), res["cleaned_files"])

        # Preserved: unreleased pin manifest
        self.assertTrue(clip_active.exists())
        self.assertTrue(clip_active.with_suffix(".json").exists())

        # Preserved: released but unACKed pin manifest
        self.assertTrue(clip_unack.exists())
        self.assertTrue(clip_unack.with_suffix(".json").exists())

        # Preserved: unknown file
        self.assertTrue(unknown_file.exists())

    def test_quota_pinned_bytes_excludes_released_and_acked_manifests(self) -> None:
        # Active pin in manifests
        clip_active = self._create_dummy_manifest("req-p-active", "sess-1", size_bytes=1000)
        self.recorder.pin("req-p-active", "sess-1", 0.0, 10.0, "owner-1")

        # Released + ACKed pin in manifests
        clip_acked = self._create_dummy_manifest("req-p-acked", "sess-1", size_bytes=2000)
        self.recorder.pin("req-p-acked", "sess-1", 10.0, 20.0, "owner-2")
        with sqlite3.connect(self.recorder._pins) as db:
            db.execute("INSERT INTO transfers VALUES(?,?)", ("req-p-acked", json.dumps({"receipt": "ok"})))
        self.recorder.release_pin("req-p-acked")

        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
        )
        breakdown = qm.get_storage_breakdown()

        # pinned_bytes must only include active (unreleased or unACKed) manifest
        active_size = clip_active.stat().st_size + clip_active.with_suffix(".json").stat().st_size
        self.assertEqual(breakdown.pinned_bytes, active_size)

        # ring_bytes should include the released+ACKed manifest (reclaimable)
        acked_size = clip_acked.stat().st_size + clip_acked.with_suffix(".json").stat().st_size
        self.assertGreaterEqual(breakdown.ring_bytes, acked_size)

    def test_get_active_pins_error_marks_metric_degraded(self) -> None:
        qm = StorageQuotaManager(
            storage_path=self.root,
            recorder=self.recorder,
            outbox=self.outbox,
        )
        with mock.patch("apps.edge.quota.sqlite3.connect", side_effect=sqlite3.OperationalError("db busy")):
            breakdown = qm.get_storage_breakdown()

        self.assertTrue(qm.degraded)
        self.assertIn("active_pins_query_failed", qm.degraded_reason or "")
        self.assertTrue(breakdown.degraded)
        self.assertIn("active_pins_query_failed", breakdown.degraded_reason or "")


if __name__ == "__main__":
    unittest.main()
