"""Behavioral regressions for Evidence ownership and observation continuity."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from apps.edge.evidence import EvidenceLifecycle
from apps.edge.incident import IncidentEngine, _TrackIncidentState
from apps.edge.outbox import EventOutbox
from apps.edge.perception import PerceptionExecution
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import Track
from apps.server.live_stream import LiveStreamService
from domain.evidence_contract import make_evidence_request
from tests.test_event_delivery import event_fixture


class DeepeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.outbox = EventOutbox(self.root / "outbox.sqlite3")
        self.recorder = FileRecorder(self.root / "ring")
        self.lifecycle = EvidenceLifecycle(self.outbox, self.recorder)
        self.event = event_fixture()
        self.request = make_evidence_request("intent", self.event["stream_session_id"], "onset", 10)
        self.event["payload"]["evidence_requests"] = [self.request]
        self.rgb = np.zeros((64, 64, 3), dtype=np.uint8)

    def test_intent_survives_pin_failure_and_recovers_without_ending_postroll(self):
        def fail_after_commit(*args):
            self.assertEqual(len(self.outbox.evidence_requests()), 1)
            raise OSError("recorder offline")
        with patch.object(self.recorder, "pin", side_effect=fail_after_commit):
            self.lifecycle.persist(self.event)
        self.assertTrue(self.outbox.evidence_requests()[0]["last_error"])
        self.lifecycle.reconcile()
        self.assertEqual(self.outbox.evidence_requests()[0]["state"], "collecting")
        self.assertIsNotNone(self.recorder.pin_status("intent"))
        self.assertEqual(self.outbox.ended_sessions(), set())

    def test_persist_retry_does_not_regress_acknowledged_request(self):
        self.lifecycle.persist(self.event)
        self.outbox.update_evidence("intent", state="acknowledged", receipt={"transfer_state": "acknowledged"})
        self.lifecycle.persist(self.event)
        self.assertEqual(self.outbox.evidence_requests()[0]["state"], "acknowledged")

    def test_live_adapter_preserves_live_lineage_and_oracle_rejects_it(self):
        from apps.edge.oracle_detector import LiveDetector
        from tests.test_oracle_detector import OracleDetectorTests
        with tempfile.TemporaryDirectory() as directory:
            oracle = OracleDetectorTests().detector_fixture(directory, np.zeros((1, 3549, 85)))
            model = Path(directory) / "vector.onnx"
            live = LiveDetector(Path(directory) / "manifest.json", model, environment="numeric-test",
                                expected_artifact={"sha256": oracle.provenance["model_sha256"],
                                                   "size_bytes": model.stat().st_size})
            frame = PerceptionExecution.frame("camera", "session", 1, "live", 0, 1)
            result = PerceptionExecution(live).execute(self.rgb, frame)
            self.assertEqual(result["detection_status"], "ok_empty")
            self.assertEqual(result["origin"], "live")
            self.assertEqual(PerceptionExecution(oracle).execute(self.rgb, frame)["detection_status"], "failed")

    def test_pin_commit_before_outbox_receipt_is_idempotent_on_restart(self):
        self.outbox.enqueue(self.event)
        owner = f'{self.event["device_id"]}/{self.event["event_id"]}/1'
        saved = self.recorder.pin("intent", self.request["session_id"], 0, 30, owner)
        restarted = EvidenceLifecycle(EventOutbox(self.outbox.path), FileRecorder(self.recorder.root))
        restarted.reconcile()
        self.assertEqual(self.outbox.evidence_requests()[0]["receipt"], saved)

    def test_worker_lock_serializes_two_coordinators(self):
        entered = threading.Event()
        attempted = threading.Event()
        done = threading.Event()
        def other():
            attempted.set()
            with EvidenceLifecycle(self.outbox, self.recorder)._worker():
                entered.set()
            done.set()
        with self.lifecycle._worker():
            thread = threading.Thread(target=other)
            thread.start()
            self.assertTrue(attempted.wait(1))
            self.assertFalse(entered.wait(.05))
        self.assertTrue(done.wait(2))
        thread.join()

    def test_cleanup_removes_only_known_recorder_scratch(self):
        self.lifecycle.persist(self.event)
        directory = self.recorder.root / "manifests"
        directory.mkdir()
        name = hashlib.sha256(b"intent").hexdigest()
        owned = directory / (name + ".tmp.mkv")
        unknown = directory / "other.tmp.mkv"
        owned.write_bytes(b"partial")
        unknown.write_bytes(b"unknown owner")
        result = self.lifecycle.reconcile()
        self.assertEqual(result["cleaned_files"], [str(owned)])
        self.assertTrue(unknown.exists())

    def test_upload_does_not_end_active_session(self):
        pipeline = PerceptionPipeline(recorder=self.recorder, outbox=self.outbox,
                                      stream_session_id=self.request["session_id"])
        self.lifecycle.persist(self.event)
        pipeline.uploader = object()
        with patch.object(pipeline.evidence, "upload_pending", return_value=0), \
             patch("apps.edge.send_synthetic.deliver_pending", return_value=0):
            pipeline.trigger_upload()
        self.assertEqual(self.outbox.ended_sessions(), set())
        self.assertEqual(self.outbox.evidence_requests()[0]["state"], "collecting")

    def test_status_lineage_and_inference_reuse(self):
        class Detector:
            provenance = {"model_id": "model", "model_sha256": "hash"}
            calls = 0
            def detect(self, rgb, frame):
                self.calls += 1
                return dict(frame, detection_status="ok_empty", detections=[], provenance=self.provenance)
        detector = Detector()
        execution = PerceptionExecution(detector)
        frame = execution.frame("camera", "session", 1, "live", 0, 1.25)
        first = execution.execute(self.rgb, frame)
        second = execution.execute(self.rgb, deepcopy(frame))
        self.assertEqual(detector.calls, 1)
        self.assertEqual(first["origin"], "live")
        self.assertEqual(second["detection_status"], "ok_empty")
        changed = dict(frame, core_epoch=2)
        execution.execute(self.rgb, changed)
        self.assertEqual(detector.calls, 2)
        self.assertEqual(execution.execute(self.rgb, changed, status="failed")["detection_status"], "failed")

    def test_missing_detector_and_forged_lineage_are_not_empty_success(self):
        execution = PerceptionExecution()
        frame = execution.frame("camera", "session", 1, "live", 0, 0)
        self.assertEqual(execution.execute(self.rgb, frame)["detection_status"], "missing")
        class Detector:
            def detect(self, rgb, frame):
                return dict(frame, origin="replay", detection_status="ok_empty", detections=[])
        result = PerceptionExecution(Detector()).execute(self.rgb, frame)
        self.assertEqual(result["detection_status"], "failed")
        self.assertEqual(result["origin"], "live")

    def test_gap_clears_onset_and_track_history_but_retains_cooldown(self):
        pipeline = PerceptionPipeline(recorder=self.recorder, outbox=self.outbox)
        standing = [{"bbox": [0, 0, 20, 60], "score": .9, "label": "person"}]
        pipeline.process_frame(self.rgb, 1, 1, detections=standing)
        track = pipeline.tracker.tracks[0]
        pipeline.incident_engine._states[track.track_id] = _TrackIncidentState(
            had_standing=True, in_fall_candidate=True, onset_time=1, lying_start_time=1,
            last_alert_time=.5)
        pipeline.process_frame(self.rgb, 2, 2, observation_status="failed")
        state = pipeline.incident_engine._states[track.track_id]
        self.assertIsNone(state.onset_time)
        self.assertFalse(state.had_standing)
        self.assertEqual(state.last_alert_time, .5)
        self.assertEqual(track.history, [])
        self.assertEqual(pipeline.last_observation["detection_status"], "failed")

    def test_no_fall_can_bridge_failed_observation(self):
        engine = IncidentEngine(min_lying_duration=1, max_motion_speed=1000)
        track = Track(1, [0, 0, 20, 60], .9, "person", 0)
        engine.process_tracks([track], 0)
        track.update([0, 30, 60, 60], .9, .5)
        self.assertEqual(engine.process_tracks([track], .5), [])
        self.assertTrue(engine._states[1].in_fall_candidate)
        engine.observation_gap()
        track.history.clear()
        for ts in (1, 2, 3, 4):
            track.update([0, 30, 60, 60], .9, ts)
            self.assertEqual(engine.process_tracks([track], ts), [])

    def test_frame_duplicate_does_not_update_tracker_twice_and_epoch_resets(self):
        pipeline = PerceptionPipeline(recorder=self.recorder, outbox=self.outbox)
        with patch.object(pipeline.tracker, "update", wraps=pipeline.tracker.update) as update:
            pipeline.process_frame(self.rgb, 1, 1, detections=[])
            pipeline.process_frame(self.rgb, 1, 1, detections=[])
            self.assertEqual(update.call_count, 1)
            pipeline.core_epoch += 1
            pipeline.process_frame(self.rgb, 0, 0, detections=[])
            self.assertEqual(update.call_count, 2)

    def test_unreadable_fallback_is_synthetic_even_when_file_exists(self):
        fixture = self.root / "broken.mkv"
        fixture.write_bytes(b"not video")
        preview = LiveStreamService(rtsp_url="", fallback_path=fixture, enable_detection=False)
        with patch.object(preview, "_open_capture", return_value=None):
            frame, source = preview.read_frame()
        preview.process_and_annotate(frame, source)
        self.assertEqual(preview.last_observation["origin"], "synthetic")
        self.assertEqual(preview.last_observation["detection_status"], "missing")

    def test_preview_source_switch_changes_session_and_preserves_origin(self):
        fixture = self.root / "fixture.mkv"
        fixture.write_bytes(b"fixture")
        preview = LiveStreamService(rtsp_url="", fallback_path=fixture, enable_detection=False)
        preview.process_and_annotate(self.rgb, "rtsp")
        live_session = preview.get_status()["stream_session_id"]
        self.assertEqual(preview.last_observation["origin"], "live")
        preview.process_and_annotate(self.rgb, "fallback")
        self.assertEqual(preview.last_observation["origin"], "replay")
        self.assertNotEqual(preview.get_status()["stream_session_id"], live_session)
        self.assertEqual(preview.get_status()["detection_status"], "missing")
