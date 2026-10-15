"""Tests for RtspRingRecorder and PerceptionPipeline end-to-end delivery."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
from typing import Any
import unittest
from uuid import uuid4

import numpy as np

from apps.edge.incident import IncidentEngine
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder
from apps.edge.rtsp import redact_rtsp_url
from apps.edge.rtsp_recorder import RtspRingRecorder
from apps.edge.tracker import ByteTracker
from apps.edge.uploader import EdgeUploader
from apps.server.config import ServerConfig
from apps.server.main import create_app
from domain.event_contract import validate_event


class TestRtspRingRecorder(unittest.TestCase):
    """Unit and lifecycle tests for RtspRingRecorder."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sample_fixture = Path(".scratch/replay-measurements/h264-10s.mkv")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_recorder_initialization_defaults_and_references(self) -> None:
        recorder = RtspRingRecorder(self.root, ring_seconds=600.0)
        self.assertIsInstance(recorder.recorder, FileRecorder)
        self.assertEqual(recorder.recorder.ring_seconds, 600.0)
        self.assertIsInstance(recorder.session_id, str)
        self.assertTrue(len(recorder.session_id) > 0)

    def test_recorder_fallback_on_unreachable_rtsp_and_redaction(self) -> None:
        credentialed_url = "rtsp://camera_user:super_s3cret_pass@127.0.0.1:54321/live/stream"
        ring_recorder = RtspRingRecorder(
            root=self.root / "ring",
            ring_seconds=600.0,
            rtsp_url=credentialed_url,
            fallback_path=self.sample_fixture,
            probe_timeout_seconds=0.5,
        )

        # Credentials must not leak in repr
        self.assertNotIn("super_s3cret_pass", repr(ring_recorder))
        self.assertNotIn("camera_user", repr(ring_recorder))

        # Start recorder (must gracefully fall back to sample fixture without raising)
        ring_recorder.start()

        status = ring_recorder.status()
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["source"], "fallback")
        self.assertNotIn("super_s3cret_pass", json.dumps(status))
        self.assertNotIn("camera_user", json.dumps(status))
        self.assertIn("127.0.0.1:54321", status.get("redacted_rtsp_url", ""))

        # Verify segments were recorded from fallback fixture into the session
        segments = ring_recorder.recorder.segments(ring_recorder.session_id)
        self.assertGreaterEqual(len(segments), 1)

        # Stop recorder
        ring_recorder.stop()
        stopped_status = ring_recorder.status()
        self.assertEqual(stopped_status["status"], "stopped")

    def test_recorder_context_manager(self) -> None:
        with RtspRingRecorder(
            root=self.root / "ring_ctx",
            ring_seconds=600.0,
            fallback_path=self.sample_fixture,
        ) as recorder:
            status = recorder.status()
            self.assertEqual(status["status"], "running")
            self.assertGreaterEqual(len(recorder.recorder.segments(recorder.session_id)), 1)
        self.assertEqual(recorder.status()["status"], "stopped")

    def test_recorder_synthetic_fallback_generation(self) -> None:
        """When fallback file is missing, generates synthetic video fixture cleanly."""
        missing_fixture = self.root / "does_not_exist.mkv"
        ring_recorder = RtspRingRecorder(
            root=self.root / "ring_syn",
            ring_seconds=600.0,
            rtsp_url="",
            fallback_path=missing_fixture,
        )
        ring_recorder.start()
        status = ring_recorder.status()
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["source"], "fallback")
        segments = ring_recorder.recorder.segments(ring_recorder.session_id)
        self.assertGreaterEqual(len(segments), 1)
        ring_recorder.stop()

    def test_recorder_rollover_session_on_fallback_prevents_file_exists_error(self) -> None:
        """P1-04: When transitioning between rtsp and fallback, a new session_id is used.
        Pre-populating the initial session_id with segments must not cause FileExistsError.
        """
        initial_session = str(uuid4())
        recorder = FileRecorder(self.root / "ring_rollover", ring_seconds=600.0)
        # Pre-populate initial_session with segments to simulate prior recording
        recorder.record_file(self.sample_fixture, initial_session, segment_seconds=2.0)
        self.assertGreaterEqual(len(recorder.segments(initial_session)), 1)

        credentialed_url = "rtsp://camera_user:super_pass@127.0.0.1:54321/live"
        sleep_durations: list[float] = []
        ring_recorder = RtspRingRecorder(
            root=self.root / "ring_rollover",
            ring_seconds=600.0,
            rtsp_url=credentialed_url,
            fallback_path=self.sample_fixture,
            session_id=initial_session,
            probe_timeout_seconds=0.1,
            recorder=recorder,
            reconnect_initial_delay=0.05,
            sleeper=lambda d: sleep_durations.append(d),
        )
        # Starting recorder with unreachable RTSP must rollover session_id,
        # avoiding FileExistsError on initial_session.
        ring_recorder.start()
        try:
            status = ring_recorder.status()
            self.assertEqual(status["status"], "running")
            self.assertEqual(status["source"], "fallback")
            # session_id must have rolled over to a new ID different from initial_session
            self.assertNotEqual(ring_recorder.session_id, initial_session)
            # And fallback segments must be recorded under the new session_id
            new_segments = ring_recorder.recorder.segments(ring_recorder.session_id)
            self.assertGreaterEqual(len(new_segments), 1)
        finally:
            ring_recorder.stop()

    def test_recorder_reconnect_loop_recovers_to_rtsp_with_new_session(self) -> None:
        """P0-03 & P1-04: RtspRingRecorder attempts reconnect with backoff;
        when RTSP becomes available, it switches back to rtsp with a new session_id.
        """
        initial_session = str(uuid4())
        recorder = FileRecorder(self.root / "ring_recon", ring_seconds=600.0)
        fake_url = "rtsp://camera.test:554/live"

        probes = [False, False, True]  # fail twice, then succeed
        def fake_probe(url: str, timeout_seconds: float = 2.0):
            if probes:
                ok = probes.pop(0)
                if not ok:
                    raise RuntimeError("connection refused")
            return None

        recorded_rtsp_sessions: list[str] = []
        def fake_record_rtsp():
            recorded_rtsp_sessions.append(ring_recorder.session_id)
            # Sleep until stopped
            while not ring_recorder._stop_event.is_set():
                ring_recorder._stop_event.wait(0.01)

        sleep_delays: list[float] = []
        from unittest.mock import patch
        with patch("apps.edge.rtsp_recorder.probe_rtsp_stream", side_effect=fake_probe):
            ring_recorder = RtspRingRecorder(
                root=self.root / "ring_recon",
                ring_seconds=600.0,
                rtsp_url=fake_url,
                fallback_path=self.sample_fixture,
                session_id=initial_session,
                probe_timeout_seconds=0.1,
                recorder=recorder,
                reconnect_initial_delay=0.01,
                sleeper=lambda d: sleep_delays.append(d),
            )
            with patch.object(ring_recorder, "_record_rtsp_stream", side_effect=fake_record_rtsp):
                ring_recorder.start()
                # Wait until RTSP reconnect is reached and recorded
                for _ in range(50):
                    if ring_recorder.status()["source"] == "rtsp":
                        break
                    time.sleep(0.02)
                try:
                    status = ring_recorder.status()
                    self.assertEqual(status["source"], "rtsp")
                    self.assertGreaterEqual(len(recorded_rtsp_sessions), 1)
                    # The RTSP session must be different from initial_session and fallback session
                    self.assertNotEqual(recorded_rtsp_sessions[0], initial_session)
                    self.assertGreaterEqual(len(sleep_delays), 1)
                finally:
                    ring_recorder.stop()

    def test_fallback_multiple_backoff_cycles_no_file_exists_error_and_no_overwriting(self) -> None:
        """Fallback running through multiple backoff cycles does not cause FileExistsError,
        does not overwrite segments on the same session, and maintains a stable session_id.
        """
        initial_session = str(uuid4())
        recorder = FileRecorder(self.root / "ring_multi_backoff", ring_seconds=600.0)
        fake_url = "rtsp://camera.invalid:554/live"

        sleep_delays: list[float] = []
        stop_after_cycles = 4
        cycle_count = 0

        def failing_probe(url: str, timeout_seconds: float = 2.0):
            nonlocal cycle_count
            cycle_count += 1
            if cycle_count >= stop_after_cycles:
                ring_recorder._stop_event.set()
            raise RuntimeError("camera offline")

        from unittest.mock import patch
        with patch("apps.edge.rtsp_recorder.probe_rtsp_stream", side_effect=failing_probe):
            ring_recorder = RtspRingRecorder(
                root=self.root / "ring_multi_backoff",
                ring_seconds=600.0,
                rtsp_url=fake_url,
                fallback_path=self.sample_fixture,
                session_id=initial_session,
                probe_timeout_seconds=0.05,
                recorder=recorder,
                reconnect_initial_delay=0.01,
                sleeper=lambda d: sleep_delays.append(d),
            )
            ring_recorder.start()
            try:
                if ring_recorder._thread:
                    ring_recorder._thread.join(timeout=3.0)
                status = ring_recorder.status()
                self.assertEqual(status["source"], "fallback")
                # Must have run multiple backoff waits
                self.assertGreaterEqual(len(sleep_delays), 2)
                # Session must have rolled over from initial_session once when entering fallback
                fallback_session = ring_recorder.session_id
                self.assertNotEqual(fallback_session, initial_session)
                # Segments must exist for fallback_session
                segments = recorder.segments(fallback_session)
                self.assertGreaterEqual(len(segments), 1)
                # No FileExistsError in last_error
                self.assertNotIn("FileExistsError", status.get("error") or "")
            finally:
                ring_recorder.stop()


class TestPerceptionPipeline(unittest.TestCase):
    """Test suite for PerceptionPipeline integration."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.recorder_dir = self.root / "recorder"
        self.recorder = FileRecorder(self.recorder_dir, ring_seconds=600.0)
        self.outbox_path = self.root / "events.sqlite3"
        self.outbox = EventOutbox(self.outbox_path)
        self.sample_fixture = Path(".scratch/replay-measurements/h264-10s.mkv")

        # Record sample fixture into recorder so segments exist for pins
        self.session_id = str(uuid4())
        self.recorder.record_file(self.sample_fixture, self.session_id, segment_seconds=2.0)

        self.pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            stream_session_id=self.session_id,
            camera_id="lab-camera-01",
            device_id="lab-edge-01",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_standing_and_walking_sequence_produces_no_incidents(self) -> None:
        """Walking across frames produces track updates without false positive fall incidents."""
        dummy_rgb = np.zeros((416, 416, 3), dtype=np.uint8)
        for i in range(1, 25):
            t = round(i * 0.1, 2)
            x = 100.0 + i * 2.0
            # Standing box: AR = 60/160 = 0.375
            dets = [{"bbox": [x, 100.0, x + 60.0, 260.0], "score": 0.92, "label": "person"}]
            events = self.pipeline.process_frame(dummy_rgb, timestamp=t, frame_id=i, detections=dets)
            self.assertEqual(events, [])

        tracks = self.pipeline.tracker.tracks
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].state, "active")

    def test_fall_sequence_triggers_atomic_event_pin_and_outbox(self) -> None:
        """Standing -> drop -> lying >= 3s triggers fall event, durable pin, and outbox enqueue."""
        dummy_rgb = np.zeros((416, 416, 3), dtype=np.uint8)
        frame_id = 0

        # Phase 1: Standing (t = 0.1 to 1.0)
        for i in range(1, 11):
            frame_id += 1
            t = round(i * 0.1, 2)
            dets = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.92, "label": "person"}]
            events = self.pipeline.process_frame(dummy_rgb, timestamp=t, frame_id=frame_id, detections=dets)
            self.assertEqual(events, [])

        # Phase 2: Rapid downward drop between t=1.1 and 1.5
        fall_steps = [
            (1.1, [100.0, 120.0, 165.0, 260.0]),
            (1.2, [100.0, 150.0, 175.0, 260.0]),
            (1.3, [100.0, 180.0, 200.0, 265.0]),
            (1.4, [100.0, 210.0, 230.0, 270.0]),
            (1.5, [100.0, 220.0, 260.0, 280.0]),  # on floor, AR=160/60 = 2.67
        ]
        for t, bbox in fall_steps:
            frame_id += 1
            dets = [{"bbox": bbox, "score": 0.92, "label": "person"}]
            events = self.pipeline.process_frame(dummy_rgb, timestamp=t, frame_id=frame_id, detections=dets)
            self.assertEqual(events, [])

        # Phase 3: Lying stationary on floor for 3.0s (t=1.6 to 4.5)
        for i in range(16, 45):
            frame_id += 1
            t = round(i * 0.1, 2)
            dets = [{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.92, "label": "person"}]
            events = self.pipeline.process_frame(dummy_rgb, timestamp=t, frame_id=frame_id, detections=dets)
            self.assertEqual(events, [])

        # Phase 4: Confirmation at t=4.6 (>3s lying)
        frame_id += 1
        t_confirm = 4.6
        dets = [{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.92, "label": "person"}]
        events = self.pipeline.process_frame(dummy_rgb, timestamp=t_confirm, frame_id=frame_id, detections=dets)

        # 1. Verify Event was emitted
        self.assertEqual(len(events), 1)
        event = events[0]

        # 2. Verify Schema Conformance via domain.event_contract.validate_event
        validated = validate_event(event)
        self.assertEqual(validated["event_id"], event["event_id"])
        self.assertEqual(validated["origin"], "live")
        self.assertEqual(validated["device_id"], "lab-edge-01")
        self.assertEqual(validated["camera_id"], "lab-camera-01")
        self.assertEqual(validated["stream_session_id"], self.session_id)

        # 3. Payload and Evidence Request verification
        payload = validated["payload"]
        self.assertEqual(payload["taxonomy"], "person_fall")
        self.assertEqual(payload["severity"], "critical")
        self.assertEqual(len(payload["evidence_requests"]), 1)

        req = payload["evidence_requests"][0]
        self.assertEqual(req["evidence_anchor_kind"], "onset")
        anchor_time = req["evidence_anchor_time"]
        self.assertAlmostEqual(req["requested_start"], anchor_time - 10.0)
        self.assertAlmostEqual(req["requested_end"], anchor_time + 20.0)
        self.assertEqual(req["session_id"], self.session_id)

        # 4. Verify FileRecorder pin exists
        pin_status = self.recorder.pin_status(req["request_id"])
        self.assertIsNotNone(pin_status)
        assert pin_status is not None
        self.assertEqual(pin_status["request_id"], req["request_id"])
        self.assertEqual(pin_status["session_id"], self.session_id)

        # 5. Verify EventOutbox atomic persistence
        pending = self.outbox.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event"]["event_id"], event["event_id"])

        evidence_reqs = self.outbox.evidence_requests()
        self.assertEqual(len(evidence_reqs), 1)
        self.assertEqual(evidence_reqs[0]["request_id"], req["request_id"])

    def test_pipeline_with_real_oracle_detector_inference(self) -> None:
        """Pipeline executes real OracleDetector inference on frames seamlessly."""
        manifest = Path("models/yolox-tiny/manifest.json")
        model = Path("data/oracle/yolox_tiny.onnx")
        if manifest.is_file() and model.is_file():
            from apps.edge.oracle_detector import OracleDetector
            detector = OracleDetector(manifest, model)
            pipeline = PerceptionPipeline(
                recorder=self.recorder,
                outbox=self.outbox,
                detector=detector,
                origin="replay",
                stream_session_id=self.session_id,
            )
            # Process a blank frame through OracleDetector
            frame = np.zeros((416, 416, 3), dtype=np.uint8)
            events = pipeline.process_frame(frame, timestamp=1.0, frame_id=1)
            self.assertEqual(events, [])
            self.assertEqual(len(pipeline.tracker.tracks), 0)
            self.assertEqual(pipeline.last_observation["detection_status"], "ok_empty")

    def test_pipeline_cooldown_suppresses_rapid_duplicate_events(self) -> None:
        """Cooldown period (30s) prevents repeated alerts for same track."""
        dummy_rgb = np.zeros((416, 416, 3), dtype=np.uint8)
        frame_id = 0

        # Standing
        for i in range(1, 11):
            frame_id += 1
            self.pipeline.process_frame(dummy_rgb, timestamp=round(i * 0.1, 2), frame_id=frame_id,
                                        detections=[{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.95, "label": "person"}])

        # Drop
        for t, bbox in [
            (1.1, [100.0, 120.0, 165.0, 260.0]),
            (1.2, [100.0, 150.0, 175.0, 260.0]),
            (1.3, [100.0, 180.0, 200.0, 265.0]),
            (1.4, [100.0, 210.0, 230.0, 270.0]),
            (1.5, [100.0, 220.0, 260.0, 280.0]),
        ]:
            frame_id += 1
            self.pipeline.process_frame(dummy_rgb, timestamp=t, frame_id=frame_id,
                                        detections=[{"bbox": bbox, "score": 0.95, "label": "person"}])

        # Lying to trigger first event at t=4.6
        first_events: list[dict[str, Any]] = []
        for i in range(16, 47):
            frame_id += 1
            evs = self.pipeline.process_frame(dummy_rgb, timestamp=round(i * 0.1, 2), frame_id=frame_id,
                                              detections=[{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.95, "label": "person"}])
            if evs:
                first_events = evs
                break

        self.assertEqual(len(first_events), 1)

        # Still lying within cooldown (e.g. t = 5.0 to 15.0), no second event should be emitted
        for i in range(50, 70):
            frame_id += 1
            evs = self.pipeline.process_frame(dummy_rgb, timestamp=round(i * 0.2, 2), frame_id=frame_id,
                                              detections=[{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.95, "label": "person"}])
            self.assertEqual(evs, [], f"Unexpected duplicate event at frame {frame_id}")


class TestEndToEndDelivery(unittest.TestCase):
    """End-to-End integration test: Pipeline -> Outbox -> Server Store & Dashboard."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.evidence_dir = self.root / "server_evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.db_name = f"test_e2e_{uuid4().hex[:12]}"
        self.device_token = "edge-token-01"
        self.device_id = "lab-edge-01"
        self.dashboard_token = "dashboard-token-01"
        self.reviewer_token = "reviewer-token-01"

        # Allow loopback HTTP
        os.environ["ALLOW_INSECURE_LAB"] = "1"

        # Setup real FastAPI server app with EventStore
        self.server_cfg = ServerConfig(
            device_tokens={self.device_token: self.device_id},
            reviewer_tokens={"reviewer": self.reviewer_token},
            dashboard_token=self.dashboard_token,
            mongo_uri="mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true",
            mongo_database=self.db_name,
            evidence_dir=str(self.evidence_dir),
            config_hash="e2e-cfg-hash",
        )
        self.app = create_app(self.server_cfg)

        # Start uvicorn in background thread on ephemeral port
        import uvicorn
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.server_port = s.getsockname()[1]
        s.close()

        self.server_url = f"http://127.0.0.1:{self.server_port}"
        u_cfg = uvicorn.Config(self.app, host="127.0.0.1", port=self.server_port, log_level="error")
        self.server = uvicorn.Server(u_cfg)
        self.server_thread = threading.Thread(target=self.server.run, daemon=True)
        self.server_thread.start()

        # Wait for server to start responding
        import urllib.request
        deadline = time.time() + 5.0
        started = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{self.server_url}/healthz", timeout=0.5) as r:
                    if r.status == 200:
                        started = True
                        break
            except Exception:
                time.sleep(0.05)
        self.assertTrue(started, "Test server failed to start within 5s")

        # Edge components
        self.recorder_dir = self.root / "recorder"
        self.recorder = FileRecorder(self.recorder_dir, ring_seconds=600.0)
        self.session_id = str(uuid4())
        self.sample_fixture = Path(".scratch/replay-measurements/h264-10s.mkv")
        self.recorder.record_file(self.sample_fixture, self.session_id, segment_seconds=2.0)

        self.outbox = EventOutbox(self.root / "edge_events.sqlite3")
        self.uploader = EdgeUploader(
            outbox=self.outbox,
            recorder=self.recorder,
            server_url=self.server_url,
            device_token=self.device_token,
            timeout_seconds=5.0,
        )

        self.pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            uploader=self.uploader,
            stream_session_id=self.session_id,
            camera_id="lab-camera-01",
            device_id=self.device_id,
        )

    def tearDown(self) -> None:
        self.server.should_exit = True
        self.server_thread.join(timeout=3.0)

        # Drop test Mongo database using a fresh client
        from pymongo import MongoClient
        try:
            cleanup_client: MongoClient[Any] = MongoClient(
                "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true",
                serverSelectionTimeoutMS=2000,
            )
            cleanup_client.drop_database(self.db_name)
            cleanup_client.close()
        except Exception:
            pass

        self.temp_dir.cleanup()

    def test_pipeline_end_to_end_fall_upload_and_server_visibility(self) -> None:
        """Pipeline detects fall -> outbox & pin -> trigger_upload -> server stores event + clip."""
        dummy_rgb = np.zeros((416, 416, 3), dtype=np.uint8)
        frame_id = 0

        # Feed fall sequence
        for i in range(1, 11):
            frame_id += 1
            self.pipeline.process_frame(dummy_rgb, timestamp=round(i * 0.1, 2), frame_id=frame_id,
                                        detections=[{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.95, "label": "person"}])

        for t, bbox in [
            (1.1, [100.0, 120.0, 165.0, 260.0]),
            (1.2, [100.0, 150.0, 175.0, 260.0]),
            (1.3, [100.0, 180.0, 200.0, 265.0]),
            (1.4, [100.0, 210.0, 230.0, 270.0]),
            (1.5, [100.0, 220.0, 260.0, 280.0]),
        ]:
            frame_id += 1
            self.pipeline.process_frame(dummy_rgb, timestamp=t, frame_id=frame_id,
                                        detections=[{"bbox": bbox, "score": 0.95, "label": "person"}])

        for i in range(16, 47):
            frame_id += 1
            events = self.pipeline.process_frame(dummy_rgb, timestamp=round(i * 0.1, 2), frame_id=frame_id,
                                                 detections=[{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.95, "label": "person"}])
            if events:
                break

        self.assertEqual(len(events), 1)
        event = events[0]
        event_id = event["event_id"]
        request_id = event["payload"]["evidence_requests"][0]["request_id"]

        # Trigger end-to-end upload
        uploaded = self.pipeline.trigger_upload(finish_sessions=[self.pipeline.stream_session_id])
        self.assertGreaterEqual(uploaded, 1)

        # Query server GET /v1/events with dashboard credentials
        import urllib.request
        req = urllib.request.Request(
            f"{self.server_url}/v1/events?limit=10",
            headers={"Authorization": f"Bearer {self.dashboard_token}"},
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        server_events = data.get("events", [])
        matched = [e for e in server_events if e["event"]["event_id"] == event_id]
        self.assertEqual(len(matched), 1)
        server_event_entry = matched[0]

        # Verify server event content
        self.assertEqual(server_event_entry["event"]["payload"]["taxonomy"], "person_fall")
        self.assertEqual(server_event_entry["event"]["payload"]["severity"], "critical")

        # Verify evidence clip is attached and committed on server
        self.assertIn("evidence", server_event_entry)
        self.assertEqual(len(server_event_entry["evidence"]), 1)
        server_evidence = server_event_entry["evidence"][0]
        self.assertEqual(server_evidence["request_id"], request_id)

        # Verify physical clip exists on server storage
        server_clip = self.evidence_dir / self.device_id / event_id / f"{request_id}.mkv"
        self.assertTrue(server_clip.is_file())
        self.assertGreater(server_clip.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
