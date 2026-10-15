"""Unit and integration tests for LivePerceptionRunner and RTSP live correlation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
import time
import unittest
from uuid import uuid4

import cv2
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


class TestLiveRuntimeHealth(unittest.TestCase):
    def test_recorder_start_failure_never_reports_running_or_healthy(self):
        with tempfile.TemporaryDirectory() as root:
            runner = LivePerceptionRunner(root, rtsp_url="")
            with patch.object(runner.ring_recorder, "start", side_effect=RuntimeError("recorder failed")):
                with self.assertRaisesRegex(RuntimeError, "recorder failed"):
                    runner.start()
            self.assertEqual(runner.status()["status"], "stopped")
            self.assertEqual(runner.health.get_health_snapshot()["reason"], "system_stopped")

    def test_readiness_stall_shutdown_and_restart_are_truthful(self):
        with tempfile.TemporaryDirectory() as root:
            runner = LivePerceptionRunner(root, rtsp_url="", sample_fps=0.01)
            first_step = threading.Event()
            release_step = threading.Event()
            real_step = runner.step

            def blocked_step():
                first_step.set()
                release_step.wait(2)

            with patch.object(runner.ring_recorder, "start"), patch.object(runner.ring_recorder, "stop"), \
                    patch.object(runner, "step", side_effect=blocked_step):
                self.assertEqual(runner.health.get_health_snapshot()["status"], "starting")
                runner.start()
                try:
                    self.assertTrue(first_step.wait(2))
                    self.assertEqual(runner.health.get_health_snapshot()["reason"], "no_frames_received")
                    with patch("time.time", return_value=100.0):
                        real_step(frame=np.zeros((16, 16, 3), dtype=np.uint8), timestamp=0, frame_id=1,
                                  detections=[])
                        self.assertEqual(runner.health.get_health_snapshot()["status"], "healthy")
                    with patch("time.time", return_value=106.0):
                        self.assertEqual(runner.health.get_health_snapshot()["reason"], "queue_stall")
                    runner.stop(timeout=0)
                    self.assertEqual(runner.health.get_health_snapshot()["reason"], "system_stopped")
                    real_step(frame=np.zeros((16, 16, 3), dtype=np.uint8), timestamp=1, frame_id=2,
                              detections=[])
                    self.assertEqual(runner.health.get_health_snapshot()["reason"], "system_stopped")
                finally:
                    release_step.set()
                    runner.stop()
                first_step.clear()
                runner.start()
                try:
                    self.assertTrue(first_step.wait(2))
                    self.assertEqual(runner.health.get_health_snapshot()["reason"], "no_frames_received")
                finally:
                    runner.stop()


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

        # Trigger at t = 3.3 (> 3.0s persistent lying after track activation)
        frame_id += 1
        t_trigger = 3.3
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


class TestLivePipelineP0P1Improvements(unittest.TestCase):
    """Test suite for P0-03, P1-07, P1-08, P1-09, and Mục 15 specifications."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sample_fixture = Path(".scratch/replay-measurements/h264-10s.mkv")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_bgr_to_rgb_conversion_before_pipeline(self) -> None:
        """P1-07: cv2.VideoCapture BGR frames are converted to RGB (cv2.COLOR_BGR2RGB)
        before being passed to pipeline.process_frame."""
        runner = LivePerceptionRunner(
            root=self.root / "bgr_test",
            rtsp_url="",
            fallback_path=self.sample_fixture,
        )
        # Create a distinct BGR test frame: Blue channel=255, Green=0, Red=0
        bgr_frame = np.zeros((16, 16, 3), dtype=np.uint8)
        bgr_frame[:, :] = (255, 0, 0)

        received_frames: list[np.ndarray] = []
        original_process = runner.pipeline.process_frame

        def capture_process_frame(rgb, *args, **kwargs):
            received_frames.append(np.copy(rgb))
            return original_process(rgb, *args, **kwargs)

        fake_cap = unittest.mock.MagicMock()
        fake_cap.isOpened.return_value = True
        fake_cap.read.return_value = (True, bgr_frame)

        with patch.object(runner, "_ensure_capture", return_value=fake_cap), \
             patch.object(runner.pipeline, "process_frame", side_effect=capture_process_frame):
            runner.step()

        self.assertEqual(len(received_frames), 1)
        # In RGB, BGR (255, 0, 0) becomes (0, 0, 255) (Red=0, Green=0, Blue=255)
        # OpenCV converts BGR [B, G, R] to RGB [R, G, B]
        np.testing.assert_array_equal(received_frames[0][0, 0], np.array([0, 0, 255], dtype=np.uint8))

    def test_low_latency_capture_options_configured(self) -> None:
        """P1-08: OPENCV_FFMPEG_CAPTURE_OPTIONS includes low latency flags
        (rtsp_transport;tcp|fflags;nobuffer|max_delay;500000) before VideoCapture open."""
        runner = LivePerceptionRunner(
            root=self.root / "low_latency",
            rtsp_url="",
            fallback_path=self.sample_fixture,
        )
        with patch("cv2.VideoCapture") as mock_vc:
            mock_inst = unittest.mock.MagicMock()
            mock_inst.isOpened.return_value = True
            mock_vc.return_value = mock_inst

            cap = runner._open_capture("rtsp://camera.test:554/live")
            self.assertIsNotNone(cap)
            opts = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS", "")
            self.assertIn("fflags;nobuffer", opts)
            self.assertIn("max_delay;500000", opts)
            mock_inst.set.assert_any_call(cv2.CAP_PROP_BUFFERSIZE, 1)

    def test_monotonic_timestamp_without_round_collision(self) -> None:
        """P1-09: Timestamp generation removes round(..., 3) and guarantees strict monotonicity."""
        runner = LivePerceptionRunner(
            root=self.root / "mono_ts",
            rtsp_url="",
            fallback_path=self.sample_fixture,
        )
        dummy = np.zeros((16, 16, 3), dtype=np.uint8)

        # Simulate two frames processed at the exact same monotonic time
        fixed_mono = 100.0
        with patch("time.monotonic", return_value=fixed_mono):
            runner.step(frame=dummy)
            ts1 = runner.last_frame_time
            runner.step(frame=dummy)
            ts2 = runner.last_frame_time

        self.assertIsNotNone(ts1)
        self.assertIsNotNone(ts2)
        assert ts1 is not None and ts2 is not None
        self.assertGreater(ts2, ts1)

    def test_eof_stream_loss_emits_missing_status_instead_of_synthetic_gray(self) -> None:
        """Mục 15: When RTSP stream drops / EOF, do NOT inject synthetic gray frame (35,35,35).
        Emit observation status missing/failed instead."""
        runner = LivePerceptionRunner(
            root=self.root / "eof_test",
            rtsp_url="rtsp://camera.test:554/live",
            fallback_path=self.sample_fixture,
        )
        # Mock capture that fails read (stream EOF)
        fake_cap = unittest.mock.MagicMock()
        fake_cap.isOpened.return_value = True
        fake_cap.read.return_value = (False, None)
        runner._cap = fake_cap
        runner._current_source = "rtsp"
        runner.is_connected = True

        runner.step()

        # Last observation must have detection_status 'missing' or 'failed'
        last_obs = runner.pipeline.last_observation
        self.assertIsNotNone(last_obs)
        assert last_obs is not None
        self.assertIn(last_obs["detection_status"], {"missing", "failed"})
        self.assertEqual(last_obs["detections"], [])

        # Camera capability in health must reflect disconnected
        health_snap = runner.health.get_health_snapshot()
        self.assertEqual(health_snap["capabilities"]["camera"], "disconnected")

    def test_failed_rtsp_open_counts_exactly_one_disconnect_per_read(self) -> None:
        """ocr #9: _ensure_capture and _read_next_frame must not both call handle_disconnect."""
        runner = LivePerceptionRunner(
            root=self.root / "dbl_disc",
            rtsp_url="rtsp://camera.test:554/live",
            fallback_path=self.sample_fixture,
        )
        runner._current_source = "rtsp"
        runner._cap = None
        before = runner.disconnect_count
        with patch.object(runner, "_open_capture", return_value=None):
            frame, status = runner._read_next_frame()
        self.assertIsNone(frame)
        self.assertEqual(status, "missing")
        self.assertEqual(runner.disconnect_count - before, 1)

    def test_recorder_rtsp_callback_does_not_hold_runner_lock_during_reconnect(self) -> None:
        """ocr #1: reconnect() does blocking probe/open I/O; it must run without self._lock held.
        The lock is an RLock, so probe it from a different thread."""
        runner = LivePerceptionRunner(
            root=self.root / "cb_lock",
            rtsp_url="rtsp://camera.test:554/live",
            fallback_path=self.sample_fixture,
        )
        runner.is_connected = False
        probe_results: list[bool] = []

        def fake_reconnect() -> bool:
            def try_lock() -> None:
                got = runner._lock.acquire(timeout=0.2)
                if got:
                    runner._lock.release()
                probe_results.append(got)

            worker = threading.Thread(target=try_lock)
            worker.start()
            worker.join()
            return True

        with patch.object(runner, "reconnect", side_effect=fake_reconnect):
            runner._on_recorder_source_change("rtsp", runner.session_id)
        self.assertEqual(probe_results, [True], "runner lock must be free while reconnect() performs I/O")

    def test_stop_joins_reconnect_thread_even_if_run_loop_already_ended(self) -> None:
        """ocr #10: stop() must not early-return and leak a live reconnect thread."""
        runner = LivePerceptionRunner(
            root=self.root / "stop_recon",
            rtsp_url="rtsp://camera.test:554/live",
            fallback_path=self.sample_fixture,
        )
        runner._is_running = False
        runner._thread = None
        runner._stop_event.clear()
        reconnect_thread = threading.Thread(target=lambda: runner._stop_event.wait(5.0), daemon=True)
        reconnect_thread.start()
        runner._reconnect_thread = reconnect_thread

        runner.stop(timeout=2.0)

        self.assertTrue(runner._stop_event.is_set())
        self.assertFalse(reconnect_thread.is_alive(), "reconnect thread must be stopped and joined")

    def test_rtsp_reconnect_exponential_backoff_and_epoch_increment(self) -> None:
        """P0-03: When RTSP drops, runner does not switch permanently to fallback.
        Reconnect backoff retries RTSP, and on success calls handle_reconnect()
        (epoch incremented, new session_id, health restored)."""
        sleep_durations: list[float] = []
        runner = LivePerceptionRunner(
            root=self.root / "recon_test",
            rtsp_url="rtsp://camera.test:554/live",
            fallback_path=self.sample_fixture,
            reconnect_initial_delay=0.01,
            sleeper=lambda d: sleep_durations.append(d),
        )
        initial_epoch = runner.pipeline.core_epoch
        initial_session = runner.session_id

        # 1. Trigger disconnect
        runner.handle_disconnect("network_drop")
        self.assertFalse(runner.is_connected)
        health_snap = runner.health.get_health_snapshot()
        self.assertEqual(health_snap["capabilities"]["camera"], "disconnected")

        # 2. Simulate RTSP recovery: probe succeeds and capture opens
        fake_cap = unittest.mock.MagicMock()
        fake_cap.isOpened.return_value = True

        with patch("apps.edge.live_pipeline.probe_rtsp_stream", return_value=None), \
             patch.object(runner, "_open_capture", return_value=fake_cap):
            reconnected = runner.reconnect()

        self.assertTrue(reconnected)
        self.assertTrue(runner.is_connected)
        self.assertEqual(runner.pipeline.core_epoch, initial_epoch + 1)
        self.assertNotEqual(runner.session_id, initial_session)
        self.assertEqual(runner.current_source, "rtsp")
        self.assertEqual(runner.health.get_health_snapshot()["capabilities"]["camera"], "active")

    def test_session_id_invariant_across_disconnect_fallback_and_reconnect(self) -> None:
        """Requirement 2 & 3: Invariant must hold across the entire sequence:
        rtsp -> disconnect -> fallback -> reconnect success:
        pipeline.stream_session_id == ring_recorder.session_id == health.recorder_session_id.
        """
        runner = LivePerceptionRunner(
            root=self.root / "invariant_test",
            rtsp_url="rtsp://camera.test:554/live",
            fallback_path=self.sample_fixture,
            reconnect_initial_delay=0.01,
            sleeper=lambda d: None,
        )
        # Step 1: Initial state on RTSP
        runner._current_source = "rtsp"
        runner.is_connected = True
        s1 = runner.session_id
        self.assertEqual(runner.pipeline.stream_session_id, s1)
        self.assertEqual(runner.ring_recorder.session_id, s1)
        self.assertEqual(runner.health.recorder_session_id, s1)
        epoch1 = runner.pipeline.core_epoch

        # Step 2: RTSP disconnects -> recorder enters fallback
        runner.handle_disconnect("network_drop")
        # When ring_recorder enters fallback, rollover_session generates fallback session
        # and notifies runner via on_source_change callback
        if runner.ring_recorder is not None:
            runner.ring_recorder._current_source = "fallback"
            fallback_id = runner.ring_recorder.rollover_session()
            if getattr(runner.ring_recorder, "on_source_change", None) is not None:
                runner.ring_recorder.on_source_change("fallback", fallback_id)

        # Invariant must hold in fallback
        self.assertEqual(runner.pipeline.stream_session_id, runner.ring_recorder.session_id)
        self.assertEqual(runner.ring_recorder.session_id, runner.health.recorder_session_id)
        self.assertEqual(runner.session_id, runner.ring_recorder.session_id)
        s2 = runner.session_id
        self.assertNotEqual(s2, s1)
        # Core epoch must NOT increment on disconnect/fallback
        self.assertEqual(runner.pipeline.core_epoch, epoch1)

        # Step 3: Reconnect succeeds
        fake_cap = unittest.mock.MagicMock()
        fake_cap.isOpened.return_value = True
        with patch("apps.edge.live_pipeline.probe_rtsp_stream", return_value=None), \
             patch.object(runner, "_open_capture", return_value=fake_cap):
            reconnected = runner.reconnect()

        self.assertTrue(reconnected)
        self.assertTrue(runner.is_connected)
        s3 = runner.session_id
        self.assertNotEqual(s3, s2)
        self.assertNotEqual(s3, s1)
        # Invariant must hold after reconnect:
        self.assertEqual(runner.pipeline.stream_session_id, s3)
        self.assertEqual(runner.ring_recorder.session_id, s3)
        self.assertEqual(runner.health.recorder_session_id, s3)
        # Core epoch must have incremented by exactly 1
        self.assertEqual(runner.pipeline.core_epoch, epoch1 + 1)

    def test_reconnect_increments_core_epoch_exactly_once_no_double_increment(self) -> None:
        """Requirement 4: Each successful reconnect increments core_epoch exactly once,
        even if reconnect is triggered from multiple paths (e.g. reconnect() and recorder callback).
        """
        runner = LivePerceptionRunner(
            root=self.root / "epoch_test",
            rtsp_url="rtsp://camera.test:554/live",
            fallback_path=self.sample_fixture,
            reconnect_initial_delay=0.01,
            sleeper=lambda d: None,
        )
        initial_epoch = runner.pipeline.core_epoch

        # Disconnect
        runner.handle_disconnect("network_drop")
        self.assertFalse(runner.is_connected)

        fake_cap = unittest.mock.MagicMock()
        fake_cap.isOpened.return_value = True

        with patch("apps.edge.live_pipeline.probe_rtsp_stream", return_value=None), \
             patch.object(runner, "_open_capture", return_value=fake_cap):
            # Path 1: reconnect() is called
            ok1 = runner.reconnect()
            self.assertTrue(ok1)
            # Path 2: simulate secondary path (e.g. second call or recorder callback)
            if runner.ring_recorder and getattr(runner.ring_recorder, "on_source_change", None):
                runner.ring_recorder.on_source_change("rtsp", runner.ring_recorder.session_id)
            ok2 = runner.reconnect()
            self.assertTrue(ok2)

        # core_epoch must increment exactly ONCE (initial_epoch + 1), NOT twice
        self.assertEqual(runner.pipeline.core_epoch, initial_epoch + 1)
        self.assertEqual(runner.discontinuity_count, 1)


if __name__ == "__main__":
    unittest.main()
