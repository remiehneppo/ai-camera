import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from apps.edge.health import EdgeHealthMonitor, HealthStatus, ALLOWED_METRIC_LABELS
from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.live_pipeline import LivePerceptionRunner


class TestEdgeHealthMonitor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initial_starting_state(self):
        monitor = EdgeHealthMonitor()
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "starting")
        self.assertEqual(snapshot["reason"], "system_starting")
        self.assertIn("system_starting", snapshot["all_reasons"])
        self.assertIn("capabilities", snapshot)
        self.assertIn("metrics", snapshot)

    def test_mark_started_without_frames_is_unavailable(self):
        monitor = EdgeHealthMonitor()
        monitor.mark_started()
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "unavailable")
        self.assertEqual(snapshot["reason"], "no_frames_received")
        self.assertEqual(snapshot["capabilities"]["camera"], "unavailable")

    def test_healthy_transition_with_frames(self):
        monitor = EdgeHealthMonitor()
        monitor.mark_started()
        now = time.time()
        monitor.record_frame_received(receive_time=now)
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "healthy")
        self.assertIsNone(snapshot["reason"])
        self.assertEqual(snapshot["capabilities"]["camera"], "active")

    def test_truthful_frame_age_without_clock_mapping(self):
        monitor = EdgeHealthMonitor()
        monitor.mark_started()
        t0 = time.time() - 1.5
        # Capture time provided but clock_mapping_valid is False
        monitor.record_frame_received(receive_time=t0, capture_time=100.0, clock_mapping_valid=False)
        snapshot = monitor.get_health_snapshot()
        metrics = snapshot["metrics"]
        self.assertFalse(metrics["clock_mapping_valid"])
        self.assertIsNone(metrics["capture_age_seconds"])
        self.assertIsNotNone(metrics["receive_age_seconds"])
        self.assertAlmostEqual(metrics["receive_age_seconds"], 1.5, delta=0.5)
        # Truthful frame_age_seconds falls back to receive_age_seconds, never inventing fake capture age
        self.assertEqual(metrics["frame_age_seconds"], metrics["receive_age_seconds"])

    def test_truthful_frame_age_with_valid_clock_mapping(self):
        monitor = EdgeHealthMonitor()
        monitor.mark_started()
        t_now = time.time()
        t_capture = t_now - 0.25
        t_receive = t_now - 0.10
        monitor.record_frame_received(receive_time=t_receive, capture_time=t_capture, clock_mapping_valid=True)
        snapshot = monitor.get_health_snapshot()
        metrics = snapshot["metrics"]
        self.assertTrue(metrics["clock_mapping_valid"])
        self.assertIsNotNone(metrics["capture_age_seconds"])
        self.assertAlmostEqual(metrics["capture_age_seconds"], 0.25, delta=0.2)
        self.assertEqual(metrics["frame_age_seconds"], metrics["capture_age_seconds"])

    def test_frame_drop_count_metric(self):
        monitor = EdgeHealthMonitor()
        monitor.record_frame_drop(3)
        monitor.record_frame_drop(2)
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["metrics"]["frame_drop_count"], 5)

    def test_queue_stall_or_analytics_hung_fault_injection(self):
        monitor = EdgeHealthMonitor(analytics_stall_timeout=1.0)
        monitor.mark_started()
        # Old frame received 2 seconds ago
        monitor.record_frame_received(receive_time=time.time() - 2.0)
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["reason"], "queue_stall")
        self.assertEqual(snapshot["capabilities"]["camera"], "stalled")

        # Explicit analytics hung
        monitor.record_frame_received(receive_time=time.time())
        monitor.set_component_capability("analytics", "hung")
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "degraded")
        self.assertIn("analytics_hung", snapshot["all_reasons"])

    def test_analytics_crash_or_failure_marks_degraded(self):
        monitor = EdgeHealthMonitor()
        monitor.mark_started()
        monitor.record_frame_received(receive_time=time.time())
        monitor.set_component_capability("analytics", "failed")
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["reason"], "analytics_failed")

    def test_recorder_gap_fault_injection(self):
        # Mock recorder with segment gap
        mock_recorder = MagicMock()
        mock_seg1 = MagicMock()
        mock_seg1.start_seconds = 0.0
        mock_seg1.end_seconds = 2.0
        mock_seg2 = MagicMock()
        mock_seg2.start_seconds = 7.0  # 5.0s gap
        mock_seg2.end_seconds = 9.0
        mock_recorder.segments.return_value = [mock_seg1, mock_seg2]

        monitor = EdgeHealthMonitor(
            recorder=mock_recorder,
            recorder_session_id="test-session",
            recorder_gap_threshold=3.0,
        )
        monitor.mark_started()
        monitor.record_frame_received(receive_time=time.time())
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["metrics"]["recorder_gap_seconds"], 5.0)
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["reason"], "recorder_gap_exceeded")
        self.assertEqual(snapshot["capabilities"]["recorder"], "gap_detected")

    def test_disk_near_capacity_and_disk_full_fault_injection(self):
        monitor = EdgeHealthMonitor(disk_warning_percent=80.0, disk_critical_percent=95.0)
        monitor.mark_started()
        monitor.record_frame_received(receive_time=time.time())

        # Mock _measure_disk to return 85%
        monitor._measure_disk = lambda: (85.0, 1500000, 10000000)
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["reason"], "disk_near_capacity")

        # Mock _measure_disk to return 96%
        monitor._measure_disk = lambda: (96.0, 400000, 10000000)
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "unavailable")
        self.assertEqual(snapshot["reason"], "disk_full")

    def test_backend_unreachable_fault_injection(self):
        monitor = EdgeHealthMonitor(backend_checker=lambda: False)
        monitor.mark_started()
        monitor.record_frame_received(receive_time=time.time())
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["reason"], "backend_unreachable")
        self.assertFalse(snapshot["metrics"]["backend_reachable"])
        self.assertEqual(snapshot["capabilities"]["backend"], "unreachable")

    def test_outbox_pending_count_metric(self):
        db_path = self.root / "events.sqlite3"
        outbox = EventOutbox(db_path)
        monitor = EdgeHealthMonitor(outbox=outbox)
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["metrics"]["outbox_pending_count"], 0)

    def test_secrets_masking_in_health_output_and_telemetry(self):
        monitor = EdgeHealthMonitor()
        raw_url = "rtsp://admin:super_secret_password@192.168.1.50:554/live/ch0"
        token = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret"

        telemetry_payload = {
            "source_url": raw_url,
            "auth_token": token,
            "nested": {
                "api_key": "12345-secret-key",
                "normal_field": "ok_value",
            },
        }
        monitor.record_telemetry_event("config_loaded", telemetry_payload)
        events = monitor.get_telemetry_events()
        self.assertEqual(len(events), 1)
        data = events[0]["data"]

        # Secrets must be masked
        self.assertNotIn("super_secret_password", json.dumps(data))
        self.assertNotIn("secret", data["auth_token"])
        self.assertEqual(data["auth_token"], "<redacted>")
        self.assertEqual(data["nested"]["api_key"], "<redacted>")
        self.assertEqual(data["nested"]["normal_field"], "ok_value")
        self.assertIn("rtsp://192.168.1.50:554/live/ch0", data["source_url"])

    def test_bounded_spool_cap_never_grows_unboundedly(self):
        cap = 5
        monitor = EdgeHealthMonitor(spool_max_len=cap)
        for i in range(20):
            monitor.record_telemetry_event("ping", {"index": i})
        events = monitor.get_telemetry_events()
        self.assertEqual(len(events), cap)
        # Should retain only the newest 5 events (15 to 19)
        indices = [e["data"]["index"] for e in events]
        self.assertEqual(indices, [15, 16, 17, 18, 19])

    def test_bounded_metric_labels(self):
        # Acceptance: Bounded cardinality: metric labels are fixed (component, status, reason);
        # NEVER use event_id, frame_id, or track_id as metric labels.
        self.assertEqual(ALLOWED_METRIC_LABELS, frozenset({"component", "status", "reason"}))
        for forbidden in ("event_id", "frame_id", "track_id"):
            self.assertNotIn(forbidden, ALLOWED_METRIC_LABELS)

    def test_integration_live_runner_and_pipeline(self):
        # Create pipeline and runner, verify health snapshot integration
        db_path = self.root / "events.sqlite3"
        outbox = EventOutbox(db_path)
        recorder = FileRecorder(self.root / "ring", ring_seconds=60)
        pipeline = PerceptionPipeline(recorder=recorder, outbox=outbox)

        # Pipeline health property
        self.assertTrue(hasattr(pipeline, "health"))
        self.assertIsInstance(pipeline.health, EdgeHealthMonitor)
        snapshot = pipeline.health.get_health_snapshot()
        self.assertEqual(snapshot["status"], "starting")

        runner = LivePerceptionRunner(
            root=self.root / "live",
            pipeline=pipeline,
            rtsp_url="",
        )
        self.assertTrue(hasattr(runner, "health"))
        self.assertIsInstance(runner.health, EdgeHealthMonitor)
        self.assertIn("health", runner.status())

    def test_operational_fault_surfaced_as_degraded_in_health_snapshot(self):
        db_path = self.root / "events_fault.sqlite3"
        outbox = EventOutbox(db_path)
        with outbox._connect() as db:
            db.execute(
                "INSERT INTO evidence_requests (request_id, device_id, event_id, revision, state, request_json, receipt_json, last_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "req-fault-1",
                    "dev-1",
                    "ev-1",
                    1,
                    "failed",
                    json.dumps({"request_id": "req-fault-1"}),
                    json.dumps({"operational_fault": "upload_413_payload_too_large"}),
                    "HTTP 413: payload too large",
                ),
            )
        monitor = EdgeHealthMonitor(outbox=outbox)
        monitor.mark_started()
        monitor.record_frame_received()
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "degraded")
        self.assertIn("upload_413_payload_too_large", snapshot["all_reasons"])
        self.assertEqual(snapshot["metrics"]["operational_fault_count"], 1)
