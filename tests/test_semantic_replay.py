"""Semantic replay behavior tests (Tasks 3.1-3.3, Scenarios R01-R10).

Verifies PerceptionPipeline reuse in tools/eval_vehicle.py, tools/eval_all_scenarios.py,
and tools/eval_clip.py using controlled detectors and video captures with real pipeline
and local SQLite/ring storage. Follows unittest.TestCase and subTest.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
from fractions import Fraction
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.edge.oracle_detector import OracleDetector
from apps.edge.danger_zone import DangerZoneIncidentEngine
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.pose import PoseManager, PoseScheduler, RtmposeEstimator
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import ByteTracker
from apps.edge.vehicle_incident import VehicleIncidentEngine
from tools import eval_all_scenarios, eval_clip, eval_vehicle


class ScriptedDetector:
    """Deterministic in-memory detector returning scripted observations with real provenance."""

    def __init__(
        self,
        script: dict[int, dict[str, Any]] | None = None,
        default_status: str = "ok_empty",
    ) -> None:
        self.script = dict(script or {})
        self.default_status = default_status
        self.calls: list[dict[str, Any]] = []
        self.provenance = {
            "model_id": "yolox_tiny_scripted",
            "model_sha256": "fake_sha256_scripted_model_hash_value_12345678",
        }

    def detect(self, rgb: np.ndarray, frame: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(frame))
        fid = frame["frame_id"]
        if fid in self.script:
            item = self.script[fid]
            status = item.get(
                "detection_status",
                "ok" if item.get("detections") else self.default_status,
            )
            dets = item.get("detections", [])
            err = item.get("error")
            return dict(
                frame,
                detection_status=status,
                detections=dets,
                error=err,
                provenance=self.provenance,
            )
        return dict(
            frame,
            detection_status=self.default_status,
            detections=[],
            provenance=self.provenance,
        )


class FakeCapture:
    """In-memory cv2.VideoCapture substitute supporting controlled frames and failures."""

    def __init__(
        self,
        frames: list[np.ndarray | None],
        native_fps: float = 10.0,
        width: int = 640,
        height: int = 360,
        fail_open: bool = False,
    ) -> None:
        self.frames = list(frames)
        self.native_fps = float(native_fps)
        self.width = width
        self.height = height
        self.fail_open = fail_open
        self.idx = 0
        self.released = False

    def isOpened(self) -> bool:
        return not self.fail_open and not self.released

    def get(self, prop_id: int) -> float:
        if prop_id == cv2.CAP_PROP_FPS:
            return self.native_fps
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        return 0.0

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self.released or self.fail_open or self.idx >= len(self.frames):
            return False, None
        f = self.frames[self.idx]
        self.idx += 1
        if f is None:
            return False, None
        return True, f

    def release(self) -> None:
        self.released = True


def make_blank_frames(count: int, width: int = 640, height: int = 360) -> list[np.ndarray]:
    """Generate minimal test frames with non-identical pixel values."""
    frames = []
    for i in range(count):
        img = np.zeros((height, width, 3), dtype=np.uint8)
        img[0, 0, 0] = (i % 250) + 1
        frames.append(img)
    return frames


def build_vehicle_stop_script(
    total_frames: int = 40,
    speed: float = 22.0,
    stop_at_frame: int = 20,
    dt: float = 0.1,
    score: float = 0.9,
) -> dict[int, dict[str, Any]]:
    """Build detections for a vehicle moving at constant speed then abruptly halting."""
    script: dict[int, dict[str, Any]] = {}
    x = 100.0
    for fid in range(total_frames):
        if fid < stop_at_frame:
            x = 100.0 + speed * (fid * dt)
        bbox = [x, 150.0, x + 80.0, 200.0]
        script[fid] = {
            "detection_status": "ok",
            "detections": [{"bbox": bbox, "score": score, "label": "car"}],
        }
    return script


def build_parking_script(
    total_frames: int = 250,
    bbox: list[float] | None = None,
    score: float = 0.9,
) -> dict[int, dict[str, Any]]:
    """Build detections for a stationary vehicle persisting across frames."""
    box = bbox or [200.0, 150.0, 300.0, 220.0]
    script: dict[int, dict[str, Any]] = {}
    for fid in range(total_frames):
        script[fid] = {
            "detection_status": "ok",
            "detections": [{"bbox": list(box), "score": score, "label": "car"}],
        }
    return script


class SemanticReplayTests(unittest.TestCase):
    """Test suite covering scenarios R01 through R10."""

    def test_r01_replay_and_runtime_have_matching_semantic_outcomes(self):
        """R01: Replay and runtime have matching taxonomy, anchor, status, and persistence."""
        script = build_vehicle_stop_script(total_frames=35, speed=22.0, stop_at_frame=15)
        detector = ScriptedDetector(script)
        frames = make_blank_frames(35)
        fake_cap = FakeCapture(frames, native_fps=10.0)

        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
            with patch("cv2.VideoCapture", return_value=fake_cap):
                replay_res = eval_vehicle.evaluate_clip(
                    Path(tf.name),
                    detector,
                    sample_fps=10.0,
                    max_frames=300,
                    min_moving_speed=8.0,
                    impact_deceleration=50.0,
                )

        # Run direct runtime pipeline with same sequence and configuration
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            recorder = FileRecorder(tmp_path / "ring", ring_seconds=60)
            outbox = EventOutbox(tmp_path / "events.sqlite3")
            tracker = ByteTracker(high_threshold=0.25, low_threshold=0.08, match_threshold=0.3)
            engine = VehicleIncidentEngine(
                min_moving_speed=8.0,
                impact_deceleration_threshold=50.0,
            )
            runtime_pipeline = PerceptionPipeline(
                recorder=recorder,
                outbox=outbox,
                detector=detector,
                tracker=tracker,
                incident_engines=[engine],
                origin="live",
            )
            runtime_emitted = []
            runtime_statuses = {}
            for fid, img in enumerate(frames):
                ts = float(round((fid / 10.0) * 1_000_000) * Fraction("1/1000000"))
                evs = runtime_pipeline.process_frame(
                    cv2.cvtColor(img, cv2.COLOR_BGR2RGB),
                    timestamp=ts,
                    frame_id=fid,
                )
                runtime_emitted.extend(evs)
                status = runtime_pipeline.last_observation["detection_status"]
                runtime_statuses[status] = runtime_statuses.get(status, 0) + 1
            runtime_persisted = outbox.pending()

        self.assertEqual(replay_res["event_count"], len(runtime_persisted))
        self.assertEqual(replay_res["event_count_emitted"], len(runtime_emitted))
        self.assertGreater(replay_res["event_count"], 0)

        # Match semantic properties (taxonomy, severity, interaction_type) ignoring UUIDs
        replay_ev = replay_res["events"][0]
        runtime_snap = runtime_persisted[0]["event"]["payload"]
        self.assertEqual(replay_ev["taxonomy"], runtime_snap["taxonomy"])
        self.assertEqual(replay_ev["severity"], runtime_snap["severity"])
        self.assertEqual(replay_ev["interaction_type"], runtime_snap.get("interaction_type"))
        self.assertEqual(replay_res["detection_status_counts"], runtime_statuses)
        self.assertEqual(
            {key: value for key, value in replay_ev["details"].items() if key != "evidence_requests"},
            {key: value for key, value in runtime_snap.items() if key != "evidence_requests"},
        )
        replay_request = replay_ev["details"]["evidence_requests"][0]
        runtime_request = runtime_snap["evidence_requests"][0]
        for key in ("evidence_anchor_kind", "evidence_anchor_time", "requested_start", "requested_end"):
            self.assertEqual(replay_request[key], runtime_request[key])

    def test_r02_command_and_function_effective_policies_are_preserved(self):
        """Exercise parser and function defaults through real decisions at caller-specific thresholds."""
        def run_cli(module, option, script, frames):
            results = []
            function_name = "evaluate_clip" if module is eval_vehicle else "evaluate_video"
            real_evaluate = getattr(module, function_name)

            def observe_result(*args, **kwargs):
                result = real_evaluate(*args, **kwargs)
                results.append(result)
                return result

            with tempfile.NamedTemporaryFile(suffix=".mp4") as tf, \
                 patch("cv2.VideoCapture", return_value=FakeCapture(frames)), \
                 patch.object(module, "OracleDetector", return_value=ScriptedDetector(script)), \
                 patch.object(module, function_name, observe_result), \
                 patch("sys.argv", [module.__name__, option, tf.name] + (["--no-pose"] if module is eval_all_scenarios else [])), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(), 0)
            return results[0]

        vehicle_script = build_vehicle_stop_script(total_frames=35, speed=22.0, stop_at_frame=15)
        vehicle_frames = make_blank_frames(35)
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf, \
             patch("cv2.VideoCapture", return_value=FakeCapture(vehicle_frames)):
            direct = eval_vehicle.evaluate_clip(Path(tf.name), ScriptedDetector(vehicle_script))
        cli = run_cli(eval_vehicle, "--video", vehicle_script, vehicle_frames)
        self.assertEqual(direct["event_count"], 1)
        self.assertEqual(cli["event_count"], 0)
        for result, speed, deceleration in ((direct, 8.0, 50.0), (cli, 20.0, 150.0)):
            config = result["effective_config"]
            self.assertEqual(config["engines"]["vehicle_incident"]["min_moving_speed"], speed)
            self.assertEqual(config["engines"]["vehicle_incident"]["impact_deceleration_threshold"], deceleration)
            self.assertEqual(config["evaluator"]["max_frames"], 300)

        parking_script = build_parking_script(total_frames=250)
        parking_frames = make_blank_frames(250)
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf, \
             patch("cv2.VideoCapture", return_value=FakeCapture(parking_frames)):
            direct = eval_all_scenarios.evaluate_video(Path(tf.name), ScriptedDetector(parking_script), with_pose=False)
        cli = run_cli(eval_all_scenarios, "--videos", parking_script, parking_frames)
        self.assertEqual(direct["events_by_taxonomy"], {"illegal_parking": 1})
        self.assertEqual(cli["events"], [])
        self.assertEqual(direct["effective_config"]["evaluator"]["max_frames"], 300)
        self.assertEqual(cli["effective_config"]["evaluator"]["max_frames"], 200)
        self.assertEqual(direct["effective_config"]["engines"]["illegal_parking"]["max_dwell_seconds"], 20.0)

        for observation in parking_script.values():
            for detection in observation["detections"]:
                detection["score"] = 0.35  # Above parking's 0.3 gate, below the runtime tracker's 0.5 default.
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf, \
             patch("cv2.VideoCapture", return_value=FakeCapture(parking_frames)):
            low_score = eval_all_scenarios.evaluate_video(Path(tf.name), ScriptedDetector(parking_script), with_pose=False)
        self.assertEqual(low_score["events_by_taxonomy"], {"illegal_parking": 1})
        self.assertEqual(low_score["effective_config"]["tracker"]["high_threshold"], 0.25)
        self.assertEqual(low_score["effective_config"]["tracker"]["low_threshold"], 0.08)

        output = io.StringIO()
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf, \
             patch("cv2.VideoCapture", return_value=FakeCapture(make_blank_frames(5))), \
             patch("apps.edge.perception.OracleDetector", return_value=ScriptedDetector()), \
             patch("sys.argv", ["eval_clip", "--video", tf.name]), redirect_stdout(output):
            self.assertEqual(eval_clip.main(), 0)
        clip_result = json.loads(output.getvalue())[0]
        self.assertEqual(clip_result["frames_processed"], 5)
        self.assertFalse(clip_result["with_pose"])
        self.assertEqual(clip_result["effective_config"]["evaluator"]["max_frames"], 0)


    def test_multi_scenario_keeps_effective_pose_processing_budget(self):
        """Nine eligible people retain the former manager's budget, rather than truncating at eight."""
        script = {}
        for frame_id in range(3):
            script[frame_id] = {"detections": [
                {"bbox": [x, 0, x + 45, 90] if frame_id < 2 else [x, 45, x + 60, 90],
                 "score": 0.9, "label": "person"}
                for x in range(0, 630, 70)
            ]}

        class PoseEstimator:
            manifest = {"model_id": "controlled-pose"}

            def estimate(self, rgb, bbox):
                return [{"name": "nose", "x": bbox[0], "y": bbox[1], "score": 0.9}]

        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf, \
             patch("cv2.VideoCapture", return_value=FakeCapture(make_blank_frames(3))), \
             patch.object(eval_all_scenarios, "RtmposeEstimator", return_value=PoseEstimator()):
            result = eval_all_scenarios.evaluate_video(Path(tf.name), ScriptedDetector(script))
        self.assertEqual(result["total_pose_inferences"], 9)
        self.assertEqual(result["pose_status_counts"], {"ok": 9})
        self.assertEqual(result["effective_config"]["pose"]["scheduler"]["batch_budget"], 30)
        self.assertEqual(result["effective_config"]["pose"]["scheduler"]["max_queue_size"], 30)

    def test_explicit_missing_video_returns_cli_failure(self):
        for module, option in ((eval_clip, "--video"), (eval_vehicle, "--video"), (eval_all_scenarios, "--videos")):
            with self.subTest(command=module.__name__), tempfile.TemporaryDirectory() as root:
                missing = Path(root) / "missing.mp4"
                with patch("sys.argv", [module.__name__, option, str(missing)]), \
                     patch("tools.eval_vehicle.OracleDetector", return_value=ScriptedDetector()), \
                     patch("tools.eval_all_scenarios.OracleDetector", return_value=ScriptedDetector()), \
                     redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                    self.assertEqual(module.main(), 1)

    def test_r03_fractional_fps_replay_keeps_valid_observation_time(self):
        """R03: Fractional FPS (30000/1001) produces rational timestamp float(pts * Fraction(time_base))."""
        native_fps = 30000.0 / 1001.0
        frames = make_blank_frames(20)
        fake_cap = FakeCapture(frames, native_fps=native_fps)
        detector = ScriptedDetector()

        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
            with patch("cv2.VideoCapture", return_value=fake_cap):
                res = eval_vehicle.evaluate_clip(
                    Path(tf.name),
                    detector,
                    sample_fps=10.0,
                    max_frames=5,
                )

        self.assertEqual(res["frames_processed"], 5)
        # Check that detector received rational event_time matching pts * Fraction(time_base)
        self.assertGreater(len(detector.calls), 0)
        for call in detector.calls:
            pts = call["pts"]
            expected_ts = float(pts * Fraction("1/1000000"))
            self.assertEqual(call["event_time"], expected_ts)

    def test_r04_detection_failure_is_not_successful_evaluation(self):
        """R04: Detection failure (failed/missing/stale/skipped) raises RuntimeError with frame/status."""
        error_statuses = ["failed", "missing", "stale", "skipped"]
        frames = make_blank_frames(10)

        for status in error_statuses:
            with self.subTest(detection_status=status):
                script = {
                    0: {"detection_status": "ok_empty", "detections": []},
                    1: {"detection_status": status, "detections": [], "error": "sensor_fault"},
                }
                detector = ScriptedDetector(script)
                fake_cap = FakeCapture(frames, native_fps=10.0)

                with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
                    with patch("cv2.VideoCapture", return_value=fake_cap):
                        with self.assertRaises(RuntimeError) as ctx:
                            eval_vehicle.evaluate_clip(
                                Path(tf.name),
                                detector,
                                sample_fps=10.0,
                                max_frames=5,
                            )
                        self.assertIn(f"status={status}", str(ctx.exception))
                        self.assertIn("Detection failed on frame 1", str(ctx.exception))

                # Also verify eval_all_scenarios fail-fast
                fake_cap_all = FakeCapture(frames, native_fps=10.0)
                detector_all = ScriptedDetector(script)
                with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
                    with patch("cv2.VideoCapture", return_value=fake_cap_all):
                        with patch(
                            "tools.eval_all_scenarios.RtmposeEstimator",
                            return_value=MagicMock(),
                        ):
                            with self.assertRaises(RuntimeError) as ctx_all:
                                eval_all_scenarios.evaluate_video(
                                    Path(tf.name),
                                    detector_all,
                                    sample_fps=10.0,
                                    max_frames=5,
                                    with_pose=False,
                                )
                            self.assertIn(f"status={status}", str(ctx_all.exception))

    def test_r05_empty_detection_and_pose_failure_remain_distinct(self):
        """R05: ok_empty observation is valid, and pose failure does not abort or mask detection."""
        # Frames 0: ok_empty; Frame 1: person detected (tentative); Frame 2: person active lying (pose scheduled)
        script = {
            0: {"detection_status": "ok_empty", "detections": []},
            1: {
                "detection_status": "ok",
                "detections": [
                    {
                        "bbox": [100.0, 100.0, 300.0, 150.0],  # ar = 4.0 >= 1.2 lying
                        "score": 0.9,
                        "label": "person",
                    }
                ],
            },
            2: {
                "detection_status": "ok",
                "detections": [
                    {
                        "bbox": [100.0, 100.0, 300.0, 150.0],
                        "score": 0.9,
                        "label": "person",
                    }
                ],
            },
        }
        frames = make_blank_frames(5)
        fake_cap = FakeCapture(frames, native_fps=10.0)
        detector = ScriptedDetector(script)

        # Pose estimator that raises an inference error
        failing_estimator = MagicMock()
        failing_estimator.estimate.side_effect = RuntimeError("pose_onnx_internal_error")

        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
            with patch("cv2.VideoCapture", return_value=fake_cap):
                with patch(
                    "tools.eval_all_scenarios.RtmposeEstimator",
                    return_value=failing_estimator,
                ):
                    res = eval_all_scenarios.evaluate_video(
                        Path(tf.name),
                        detector,
                        sample_fps=10.0,
                        max_frames=3,
                        with_pose=True,
                    )

        self.assertEqual(res["frames_processed"], 3)
        # Empty detection recorded as ok_empty, not an error
        self.assertEqual(res["detection_status_counts"].get("ok_empty"), 1)
        self.assertEqual(res["detection_status_counts"].get("ok"), 2)
        # Pose failure recorded in pose_status_counts
        self.assertGreaterEqual(res["pose_status_counts"].get("failed", 0), 1)

    def test_r06_replay_origin_is_local_only(self):
        """R06: Origin is 'replay' and evaluation has no outbound network connections."""
        script = build_vehicle_stop_script(total_frames=30, speed=22.0, stop_at_frame=15)
        frames = make_blank_frames(30)
        fake_cap = FakeCapture(frames, native_fps=10.0)
        detector = ScriptedDetector(script)

        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
            with patch("cv2.VideoCapture", return_value=fake_cap):
                with patch.object(
                    socket.socket,
                    "connect",
                    side_effect=AssertionError("outbound network call forbidden in replay"),
                ):
                    res = eval_vehicle.evaluate_clip(
                        Path(tf.name),
                        detector,
                        sample_fps=10.0,
                        min_moving_speed=8.0,
                        impact_deceleration=50.0,
                    )

        self.assertEqual(res["origin"], "replay")
        self.assertGreater(res["event_count"], 0)
        for ev in res["events"]:
            self.assertEqual(ev["origin"], "replay")
            self.assertIsNotNone(ev.get("stream_session_id"))

    def test_r07_reported_events_match_persisted_snapshots(self):
        """Observe actual SQLite snapshots before cleanup, then compare identity, payload and anchors."""
        real_pending = EventOutbox.pending
        for evaluator in ("clip", "vehicle", "all"):
            with self.subTest(evaluator=evaluator):
                persisted = {}

                def observe_pending(outbox, *args, **kwargs):
                    rows = real_pending(outbox, *args, **kwargs)
                    for row in rows:
                        persisted[row["event"]["event_id"]] = deepcopy(row["event"])
                    return rows

                script = build_vehicle_stop_script(total_frames=40, speed=22.0, stop_at_frame=15)
                if evaluator == "clip":
                    script = {i: {"detections": [{"bbox": [10, 40, 70, 70], "score": 0.9, "label": "person"}]} for i in range(40)}
                detector = ScriptedDetector(script)
                with tempfile.NamedTemporaryFile(suffix=".mp4") as tf, \
                     patch("cv2.VideoCapture", return_value=FakeCapture(make_blank_frames(40))), \
                     patch("apps.edge.perception.OracleDetector", return_value=detector), \
                     patch.object(EventOutbox, "pending", observe_pending):
                    if evaluator == "clip":
                        result = eval_clip.evaluate(Path(tf.name), sample_fps=10.0, max_frames=40, with_pose=False)
                    elif evaluator == "vehicle":
                        result = eval_vehicle.evaluate_clip(Path(tf.name), detector)
                    else:
                        result = eval_all_scenarios.evaluate_video(Path(tf.name), detector, with_pose=False, impact_deceleration=50.0)
                self.assertEqual(result["event_count"], 1)
                self.assertEqual({event["event_id"] for event in result["events"]}, set(persisted))
                for event in result["events"]:
                    snapshot = persisted[event["event_id"]]
                    self.assertEqual(event["details"], snapshot["payload"])
                    self.assertEqual(event["stream_session_id"], snapshot["stream_session_id"])
                    self.assertEqual(event["origin"], "replay")
                    self.assertEqual(event["taxonomy"], snapshot["payload"]["taxonomy"])
                    request = event["details"]["evidence_requests"][0]
                    self.assertEqual(request["session_id"], snapshot["stream_session_id"])
                    self.assertEqual(request["evidence_anchor_time"], event["details"]["anchor_time"])
                    self.assertEqual(request["requested_start"], event["details"]["anchor_time"] - 10)
                    self.assertEqual(request["requested_end"], event["details"]["anchor_time"] + 20)

    def test_r08_zero_events_do_not_claim_review_or_coverage(self):
        """R08: Zero events report describes zero events without clean/negative/coverage claims."""
        frames = make_blank_frames(10)
        fake_cap = FakeCapture(frames, native_fps=10.0)
        detector = ScriptedDetector()  # produces ok_empty

        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
            with patch("cv2.VideoCapture", return_value=fake_cap):
                res = eval_vehicle.evaluate_clip(Path(tf.name), detector, max_frames=5)

        self.assertEqual(res["event_count"], 0)
        self.assertEqual(res["events"], [])

        self.assertTrue({"negative_pass", "complete_evidence", "coverage_gate", "server_review"}.isdisjoint(res))

    def test_r09_latency_measures_pipeline_work_not_decode(self):
        """Detection and real local persistence contribute latency; decode does not."""
        fake_cap = FakeCapture(make_blank_frames(5), native_fps=10.0)
        current_time = [1000.0]
        script = {i: {"detections": [{"bbox": [10, 10, 30, 60], "score": 0.9, "label": "person"}]} for i in range(5)}

        class TimedDetector(ScriptedDetector):
            def detect(self, rgb, frame):
                current_time[0] += 0.002
                return super().detect(rgb, frame)

        real_read = fake_cap.read
        real_enqueue = EventOutbox.enqueue

        def slow_read():
            current_time[0] += 0.100
            return real_read()

        def timed_enqueue(outbox, event):
            result = real_enqueue(outbox, event)
            current_time[0] += 0.005
            return result

        fake_cap.read = slow_read
        detector = TimedDetector(script)
        engine = DangerZoneIncidentEngine(consecutive_hits=1, cooldown_seconds=0)
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf, \
             patch("cv2.VideoCapture", return_value=fake_cap), \
             patch("apps.edge.perception.OracleDetector", return_value=detector), \
             patch("apps.edge.pipeline.IncidentEngine", return_value=engine), \
             patch.object(EventOutbox, "enqueue", timed_enqueue), \
             patch("time.perf_counter", side_effect=lambda: current_time[0]):
            res = eval_clip.evaluate(Path(tf.name), sample_fps=10.0, max_frames=5, with_pose=False)

        self.assertEqual(res["event_count"], 4)
        self.assertEqual(res["latency_ms"]["p50"], 7.0)
        self.assertEqual(res["latency_ms"]["p95"], 7.0)


    def test_r10_replay_releases_resources_on_failure_and_completion(self):
        """All evaluators release captures and remove local storage on every exit path."""
        real_tempdir = tempfile.TemporaryDirectory
        for evaluator in ("clip", "vehicle", "all"):
            for mode in ("normal", "open_failure", "initialization_failure", "first_detection_failure", "mid_detection_failure", "persistence_failure"):
                with self.subTest(evaluator=evaluator, mode=mode):
                    frames = make_blank_frames(35)
                    script = build_vehicle_stop_script(total_frames=35, speed=22.0, stop_at_frame=15)
                    if evaluator == "clip":
                        script = {i: {"detections": [{"bbox": [10, 10, 30, 60], "score": 0.9, "label": "person"}]} for i in range(35)}
                    if mode in {"first_detection_failure", "mid_detection_failure"}:
                        script[0 if mode == "first_detection_failure" else 1] = {"detection_status": "failed", "error": "controlled_failure"}
                    detector = ScriptedDetector(script)
                    capture = FakeCapture(frames, fail_open=mode == "open_failure")
                    roots = []

                    def tracked_tempdir(*args, **kwargs):
                        temporary = real_tempdir(*args, **kwargs)
                        roots.append(Path(temporary.name))
                        return temporary

                    def evaluate(path):
                        if evaluator == "clip":
                            return eval_clip.evaluate(path, sample_fps=10.0, max_frames=20, with_pose=False)
                        if evaluator == "vehicle":
                            return eval_vehicle.evaluate_clip(path, detector, max_frames=20)
                        return eval_all_scenarios.evaluate_video(path, detector, max_frames=20, with_pose=False, impact_deceleration=50.0)

                    with tempfile.NamedTemporaryFile(suffix=".mp4") as tf, \
                         patch("cv2.VideoCapture", return_value=capture), \
                         patch("tempfile.TemporaryDirectory", side_effect=tracked_tempdir), \
                         patch("apps.edge.perception.OracleDetector", return_value=detector), \
                         patch("apps.edge.pipeline.IncidentEngine", return_value=DangerZoneIncidentEngine(consecutive_hits=1, cooldown_seconds=0)):
                        if mode == "initialization_failure":
                            module = {"clip": eval_clip, "vehicle": eval_vehicle, "all": eval_all_scenarios}[evaluator]
                            with patch.object(module, "FileRecorder", side_effect=OSError("controlled_init_failure")):
                                with self.assertRaises(OSError):
                                    evaluate(Path(tf.name))
                        elif mode == "persistence_failure":
                            with patch.object(EventOutbox, "enqueue", side_effect=OSError("controlled_storage_failure")):
                                with self.assertRaises(OSError):
                                    evaluate(Path(tf.name))
                        elif mode == "normal":
                            result = evaluate(Path(tf.name))
                            self.assertGreater(result["event_count"], 0)
                        else:
                            with self.assertRaises(RuntimeError):
                                evaluate(Path(tf.name))
                    self.assertTrue(capture.released)
                    self.assertTrue(all(not root.exists() for root in roots))

    def test_session_isolation_across_video_evaluations(self):
        """Replay pipelines instantiate independent sessions; no leaked temporal state."""
        script = build_parking_script(total_frames=50)
        frames = make_blank_frames(50)
        detector = ScriptedDetector(script)

        # Run 1: 50 frames
        fake_cap1 = FakeCapture(frames, native_fps=10.0)
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf1:
            with patch("cv2.VideoCapture", return_value=fake_cap1):
                res1 = eval_all_scenarios.evaluate_video(
                    Path(tf1.name),
                    detector,
                    sample_fps=10.0,
                    max_frames=10,
                    with_pose=False,
                )

        # Run 2: 50 frames
        fake_cap2 = FakeCapture(frames, native_fps=10.0)
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf2:
            with patch("cv2.VideoCapture", return_value=fake_cap2):
                res2 = eval_all_scenarios.evaluate_video(
                    Path(tf2.name),
                    detector,
                    sample_fps=10.0,
                    max_frames=10,
                    with_pose=False,
                )

        self.assertEqual(res1["event_count"], 0)
        self.assertEqual(res2["event_count"], 0)
        # Verify pipelines were fresh (neither inherited dwell accumulation from the other)
        # Even after 10 + 10 = 20 frames, run 2 starts dwell timer fresh at frame 0


if __name__ == "__main__":
    unittest.main()
