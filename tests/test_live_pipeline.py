"""Unit and integration tests for LivePerceptionRunner and RTSP live correlation."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

import numpy as np

from apps.edge.incident import IncidentEngine
from apps.edge.live_pipeline import LivePerceptionRunner
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder
from apps.edge.rtsp import redact_rtsp_url
from apps.edge.rtsp_recorder import RtspRingRecorder
from apps.edge.tracker import ByteTracker
from domain.event_contract import validate_event


class TestLivePerceptionRunnerInit(unittest.TestCase):
    """Test suite for LivePerceptionRunner initialization, configuration, and redaction."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sample_fixture = Path(".scratch/replay-measurements/h264-10s.mkv")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_runner_initialization_with_unreachable_rtsp_and_redaction(self) -> None:
        """RTSP credentials must never leak in repr or status, and fallback is selected."""
        credentialed_url = "rtsp://camera_admin:super_secret_pwd@127.0.0.1:54321/ch1/main"
        runner = LivePerceptionRunner(
            root=self.root / "live_init",
            rtsp_url=credentialed_url,
            fallback_path=self.sample_fixture,
            probe_timeout_seconds=0.5,
        )

        # 1. Credentials must never leak in repr
        self.assertNotIn("super_secret_pwd", repr(runner))
        self.assertNotIn("camera_admin", repr(runner))

        # 2. Status must be safe and redacted
        status = runner.status()
        self.assertEqual(status["status"], "stopped")
        self.assertNotIn("super_secret_pwd", json.dumps(status))
        self.assertNotIn("camera_admin", json.dumps(status))
        self.assertIn("127.0.0.1:54321", status.get("redacted_rtsp_url", ""))

        # 3. Stream session id must be shared between runner, pipeline, and ring recorder
        self.assertEqual(runner.session_id, runner.pipeline.stream_session_id)
        self.assertIsNotNone(runner.ring_recorder)
        assert runner.ring_recorder is not None
        self.assertEqual(runner.session_id, runner.ring_recorder.session_id)
        self.assertIs(runner.pipeline.recorder, runner.ring_recorder.recorder)

    def test_runner_initialization_defaults_fallback(self) -> None:
        """When RTSP is empty, falls back gracefully to sample fixture."""
        runner = LivePerceptionRunner(
            root=self.root / "live_fallback",
            rtsp_url="",
            fallback_path=self.sample_fixture,
            sample_fps=4.0,
        )
        self.assertEqual(runner.sample_fps, 4.0)
        self.assertEqual(runner.current_source, "fallback")
        self.assertEqual(runner.pipeline.origin, "replay")

    def test_runner_wrapping_existing_pipeline_and_recorder(self) -> None:
        """LivePerceptionRunner can orchestrate an existing PerceptionPipeline and FileRecorder."""
        recorder_dir = self.root / "existing_rec"
        recorder = FileRecorder(recorder_dir, ring_seconds=600.0)
        outbox = EventOutbox(self.root / "existing_outbox.sqlite3")
        session_id = str(uuid4())

        pipeline = PerceptionPipeline(
            recorder=recorder,
            outbox=outbox,
            stream_session_id=session_id,
            camera_id="cam-test-01",
            device_id="edge-test-01",
        )

        runner = LivePerceptionRunner(
            root=self.root / "existing_runner",
            pipeline=pipeline,
            rtsp_url="",
            fallback_path=self.sample_fixture,
        )
        self.assertIs(runner.pipeline, pipeline)
        self.assertEqual(runner.session_id, session_id)
        self.assertEqual(runner.camera_id, "cam-test-01")
        self.assertEqual(runner.device_id, "edge-test-01")


class TestLivePerceptionRunnerProcessing(unittest.TestCase):
    """Test suite for live frame processing and timestamp correlation with recorder segments."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sample_fixture = Path(".scratch/replay-measurements/h264-10s.mkv")

        self.runner = LivePerceptionRunner(
            root=self.root / "proc_runner",
            rtsp_url="",
            fallback_path=self.sample_fixture,
            sample_fps=2.0,
        )
        # Pre-record fixture segments into the session so recorder segments correlate
        assert self.runner.ring_recorder is not None
        self.runner.recorder.record_file(
            self.sample_fixture, self.runner.session_id, segment_seconds=2.0
        )

    def tearDown(self) -> None:
        self.runner.stop()
        self.temp_dir.cleanup()

    def test_step_processing_updates_metrics_and_monotonic_tracking(self) -> None:
        """Stepping frames updates frame count, honest monotonic timestamps, and tracking."""
        dummy_frame = np.zeros((416, 416, 3), dtype=np.uint8)

        # Step 5 frames across 1.0 second (t = 0.2, 0.4, 0.6, 0.8, 1.0)
        for i in range(1, 6):
            t = round(i * 0.2, 2)
            dets = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.95, "label": "person"}]
            events = self.runner.step(frame=dummy_frame, timestamp=t, frame_id=i, detections=dets)
            self.assertEqual(events, [])

        self.assertEqual(self.runner.frames_processed, 5)
        self.assertAlmostEqual(self.runner.last_frame_time or 0.0, 1.0)
        self.assertIsNotNone(self.runner.last_capture_time)

        # Check track state
        tracks = self.runner.pipeline.tracker.tracks
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].state, "active")

        # Segments in recorder exist and span the frame timestamps
        segments = self.runner.recorder.segments(self.runner.session_id)
        self.assertGreaterEqual(len(segments), 1)
        self.assertLessEqual(segments[0].start_seconds, 1.0)


class TestLivePerceptionRunnerIncidents(unittest.TestCase):
    """Test incident detection during live stream triggers valid event, clip pin, and outbox enqueue."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sample_fixture = Path(".scratch/replay-measurements/h264-10s.mkv")

        self.runner = LivePerceptionRunner(
            root=self.root / "incident_runner",
            rtsp_url="",
            fallback_path=self.sample_fixture,
            sample_fps=3.0,
        )
        # Ingest segments into session
        self.runner.recorder.record_file(
            self.sample_fixture, self.runner.session_id, segment_seconds=2.0
        )

    def tearDown(self) -> None:
        self.runner.stop()
        self.temp_dir.cleanup()

    def test_fall_incident_triggers_event_pin_and_outbox(self) -> None:
        """Fall pattern (standing -> rapid drop -> lying stationary >=3s) triggers event and pin."""
        dummy_rgb = np.zeros((416, 416, 3), dtype=np.uint8)
        frame_id = 0

        # 1. Standing frames (t = 0.1 to 1.0)
        for i in range(1, 11):
            frame_id += 1
            t = round(i * 0.1, 2)
            dets = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.92, "label": "person"}]
            events = self.runner.step(frame=dummy_rgb, timestamp=t, frame_id=frame_id, detections=dets)
            self.assertEqual(events, [])

        # 2. Downward drop (t = 1.1 to 1.5)
        fall_steps = [
            (1.1, [100.0, 120.0, 165.0, 260.0]),
            (1.2, [100.0, 150.0, 175.0, 260.0]),
            (1.3, [100.0, 180.0, 200.0, 265.0]),
            (1.4, [100.0, 210.0, 230.0, 270.0]),
            (1.5, [100.0, 220.0, 260.0, 280.0]),
        ]
        for t, bbox in fall_steps:
            frame_id += 1
            dets = [{"bbox": bbox, "score": 0.92, "label": "person"}]
            events = self.runner.step(frame=dummy_rgb, timestamp=t, frame_id=frame_id, detections=dets)
            self.assertEqual(events, [])

        # 3. Lying stationary for 3.0s (t = 1.6 to 4.5)
        for i in range(16, 46):
            frame_id += 1
            t = round(i * 0.1, 2)
            dets = [{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.92, "label": "person"}]
            events = self.runner.step(frame=dummy_rgb, timestamp=t, frame_id=frame_id, detections=dets)
            self.assertEqual(events, [])

        # 4. Confirmation frame at t = 4.6 (>3s lying)
        frame_id += 1
        t_confirm = 4.6
        dets = [{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.92, "label": "person"}]
        events = self.runner.step(frame=dummy_rgb, timestamp=t_confirm, frame_id=frame_id, detections=dets)

        self.assertEqual(len(events), 1)
        event = events[0]

        # Verify event contract conformance
        validated = validate_event(event)
        self.assertEqual(validated["event_id"], event["event_id"])
        self.assertEqual(validated["stream_session_id"], self.runner.session_id)
        self.assertEqual(validated["payload"]["taxonomy"], "person_fall")
        self.assertEqual(validated["payload"]["severity"], "critical")

        # Verify evidence request and clip pin in recorder
        req = validated["payload"]["evidence_requests"][0]
        self.assertEqual(req["evidence_anchor_kind"], "onset")
        pin = self.runner.recorder.pin_status(req["request_id"])
        self.assertIsNotNone(pin)
        assert pin is not None
        self.assertEqual(pin["session_id"], self.runner.session_id)

        # Verify outbox has pending event
        pending = self.runner.outbox.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event"]["event_id"], event["event_id"])

    def test_persistent_lying_triggers_event_and_pin(self) -> None:
        """Person already lying (missing rapid onset) for >3s triggers person_lying_persistent."""
        dummy_rgb = np.zeros((416, 416, 3), dtype=np.uint8)
        frame_id = 0

        # Lying on floor (AR = 160 / 60 = 2.67 >= 1.2) without prior standing
        # min_lying_duration = 3.0s (frames 1 to 30: t = 0.1 to 3.0)
        for i in range(1, 31):
            frame_id += 1
            t = round(i * 0.1, 2)
            dets = [{"bbox": [100.0, 200.0, 260.0, 260.0], "score": 0.88, "label": "person"}]
            events = self.runner.step(frame=dummy_rgb, timestamp=t, frame_id=frame_id, detections=dets)
            self.assertEqual(events, [])

        # Trigger at t = 3.2 (> 3.0s persistent lying)
        frame_id += 1
        t_trigger = 3.2
        dets = [{"bbox": [100.0, 200.0, 260.0, 260.0], "score": 0.88, "label": "person"}]
        events = self.runner.step(frame=dummy_rgb, timestamp=t_trigger, frame_id=frame_id, detections=dets)

        self.assertEqual(len(events), 1)
        event = events[0]
        validated = validate_event(event)
        self.assertEqual(validated["payload"]["taxonomy"], "person_lying_persistent")
        self.assertEqual(validated["payload"]["severity"], "high")

        req = validated["payload"]["evidence_requests"][0]
        self.assertEqual(req["evidence_anchor_kind"], "first_qualifying_observation")
        pin = self.runner.recorder.pin_status(req["request_id"])
        self.assertIsNotNone(pin)


class TestLivePerceptionRunnerDisconnectReconnect(unittest.TestCase):
    """Test stream disconnect and reconnect handling per contract docs/architecture/contracts.md:24."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sample_fixture = Path(".scratch/replay-measurements/h264-10s.mkv")

        self.runner = LivePerceptionRunner(
            root=self.root / "recon_runner",
            rtsp_url="",
            fallback_path=self.sample_fixture,
        )

    def tearDown(self) -> None:
        self.runner.stop()
        self.temp_dir.cleanup()

    def test_disconnect_triggers_observation_gap_clearing_track_motion(self) -> None:
        """Disconnect marks observation gap, preventing fake velocity jump across missing time."""
        dummy_rgb = np.zeros((416, 416, 3), dtype=np.uint8)

        # 1. Establish track at t=1.0
        dets1 = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.9, "label": "person"}]
        self.runner.step(frame=dummy_rgb, timestamp=1.0, frame_id=1, detections=dets1)
        tracks = self.runner.pipeline.tracker.tracks
        self.assertEqual(len(tracks), 1)
        self.assertGreaterEqual(len(tracks[0].history), 1)

        # 2. Stream disconnect happens
        self.runner.handle_disconnect(reason="network_timeout")
        status = self.runner.status()
        self.assertFalse(status["is_connected"])
        self.assertEqual(status["disconnect_count"], 1)

        # 3. Track history should be cleared by observation_gap so no fake velocity is calculated
        for trk in self.runner.pipeline.tracker.get_all_tracks():
            self.assertEqual(len(trk.history), 0)

    def test_reconnect_increments_core_epoch_and_resets_lineage(self) -> None:
        """Reconnect increments core_epoch and resets tracker/incident state on next frame."""
        dummy_rgb = np.zeros((416, 416, 3), dtype=np.uint8)

        # 1. First epoch frames
        self.assertEqual(self.runner.pipeline.core_epoch, 1)
        dets1 = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.9, "label": "person"}]
        self.runner.step(frame=dummy_rgb, timestamp=1.0, frame_id=1, detections=dets1)
        self.assertEqual(len(self.runner.pipeline.tracker.tracks), 1)

        # 2. Reconnect
        new_epoch = self.runner.handle_reconnect()
        self.assertEqual(new_epoch, 2)
        self.assertEqual(self.runner.pipeline.core_epoch, 2)
        self.assertEqual(self.runner.discontinuity_count, 1)
        status = self.runner.status()
        self.assertTrue(status["is_connected"])
        self.assertEqual(status["core_epoch"], 2)
        self.assertEqual(status["discontinuity_count"], 1)

        # 3. First frame of new epoch starts fresh with frame_id=1
        dets2 = [{"bbox": [120.0, 120.0, 180.0, 280.0], "score": 0.9, "label": "person"}]
        events = self.runner.step(frame=dummy_rgb, timestamp=2.0, frame_id=1, detections=dets2)
        self.assertEqual(events, [])
        # Observation reflects new epoch in provenance
        self.assertIsNotNone(self.runner.pipeline.last_observation)
        assert self.runner.pipeline.last_observation is not None
        self.assertEqual(self.runner.pipeline.last_observation["core_epoch"], 2)


class TestLivePerceptionRunnerLifecycle(unittest.TestCase):
    """Test start, status, and clean shutdown lifecycle."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sample_fixture = Path(".scratch/replay-measurements/h264-10s.mkv")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_background_start_and_bounded_stop(self) -> None:
        """Background runner starts, processes frames, and shuts down cleanly within timeout."""
        runner = LivePerceptionRunner(
            root=self.root / "lifecycle_runner",
            rtsp_url="",
            fallback_path=self.sample_fixture,
            sample_fps=5.0,
        )

        runner.start()
        status_running = runner.status()
        self.assertEqual(status_running["status"], "running")

        # Let it run briefly
        time.sleep(0.5)

        # Stop runner cleanly
        runner.stop(timeout=3.0)
        status_stopped = runner.status()
        self.assertEqual(status_stopped["status"], "stopped")
        self.assertFalse(runner._is_running)

    def test_context_manager_clean_exit(self) -> None:
        """Runner functions as context manager with guaranteed cleanup on exit."""
        with LivePerceptionRunner(
            root=self.root / "ctx_runner",
            rtsp_url="",
            fallback_path=self.sample_fixture,
            sample_fps=5.0,
        ) as runner:
            status = runner.status()
            self.assertEqual(status["status"], "running")

        self.assertEqual(runner.status()["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
