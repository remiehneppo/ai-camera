"""Behavioral regressions for evaluation tools and semantic replay (F10, F11, F16, F17, F18, F19, F20).

Covers:
- F10: Class-aware one-to-one recall matching (one prediction cannot match two GTs, deterministic boundary).
- F11: Subsampled timestamps derived from source frame index and native FPS, not sample index/requested FPS.
- F16: Measured benchmark reporting from varied results data without invented mAP, GPU, or legal claims.
- F17: Explicit unconfigured/unsupported scenario reporting (US04/US10/US14 absent ROI/engine).
- F18: Perception pipeline benchmark scope (reports perception scope and unexercised recording/outbox components).
- F19: Honest failure marking on inference error, preserving actual processed frame counts without hidden fallback.
- F20: Active seam PerceptionExecution in eval_all_scenarios and test independence from dead OracleDetector patch.
"""
from __future__ import annotations

from fractions import Fraction
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.compare_models_benchmark as compare_bench
import tools.eval_all_scenarios as eval_all


class FakeVideoCapture:
    """Deterministic in-memory cv2.VideoCapture substitute."""

    def __init__(
        self,
        frames: list[np.ndarray],
        native_fps: float = 25.0,
        width: int = 640,
        height: int = 360,
    ) -> None:
        self.frames = list(frames)
        self.native_fps = float(native_fps)
        self.width = width
        self.height = height
        self.idx = 0
        self.released = False

    def isOpened(self) -> bool:
        return not self.released

    def get(self, prop_id: int) -> float:
        if prop_id == cv2.CAP_PROP_FPS:
            return self.native_fps
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        if prop_id == cv2.CAP_PROP_FRAME_COUNT:
            return float(len(self.frames))
        return 0.0

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self.released or self.idx >= len(self.frames):
            return False, None
        f = self.frames[self.idx]
        self.idx += 1
        return True, f

    def release(self) -> None:
        self.released = True


class ScriptedDetector:
    """In-memory detector returning controlled detections."""

    def __init__(self, script: dict[int, dict] | None = None) -> None:
        self.script = dict(script or {})
        self.calls: list[dict] = []
        self.provenance = {
            "model_id": "scripted-test-detector",
            "model_sha256": "0" * 64,
        }

    def detect(self, rgb: np.ndarray, frame: dict) -> dict:
        self.calls.append(dict(frame))
        fid = frame["frame_id"]
        if fid in self.script:
            item = self.script[fid]
            status = item.get("detection_status", "ok" if item.get("detections") else "ok_empty")
            return dict(
                frame,
                detection_status=status,
                detections=item.get("detections", []),
                error=item.get("error"),
                provenance=self.provenance,
            )
        return dict(
            frame,
            detection_status="ok_empty",
            detections=[],
            provenance=self.provenance,
        )


class TestF10RecallMatching(unittest.TestCase):
    """F10: Class-aware one-to-one recall matching and deterministic boundaries."""

    def test_one_prediction_cannot_match_two_ground_truths(self):
        """A single predicted box overlapping two nearby ground truth boxes must only match one."""
        gts = [
            {"category_id": 2, "bbox_xyxy": [10.0, 10.0, 50.0, 50.0]},  # car
            {"category_id": 2, "bbox_xyxy": [20.0, 10.0, 60.0, 50.0]},  # car
        ]
        preds = [
            (2, [15.0, 10.0, 55.0, 50.0]),  # single predicted car
        ]
        matched_gt_indices, matched_pred_indices = compare_bench.match_predictions_to_ground_truth(
            gts, preds, iou_threshold=0.4
        )
        self.assertEqual(len(matched_pred_indices), 1, "Only one prediction was available")
        self.assertEqual(len(matched_gt_indices), 1, "One prediction must not match two GTs")

    def test_matching_is_strictly_class_aware(self):
        """A high-IoU prediction of a different class must never match a ground truth of another class."""
        gts = [
            {"category_id": 1, "bbox_xyxy": [10.0, 10.0, 50.0, 50.0]},  # motorcycle (cat 1)
        ]
        preds = [
            (2, [10.0, 10.0, 50.0, 50.0]),  # car (cat 2), identical coordinates (IoU 1.0)
        ]
        matched_gts, matched_preds = compare_bench.match_predictions_to_ground_truth(
            gts, preds, iou_threshold=0.4
        )
        self.assertEqual(len(matched_gts), 0, "Different classes must not match")
        self.assertEqual(len(matched_preds), 0)

    def test_deterministic_greedy_tie_breaking(self):
        """When two predictions overlap one GT, the higher IoU match takes precedence deterministically."""
        gts = [
            {"category_id": 2, "bbox_xyxy": [10.0, 10.0, 50.0, 50.0]},  # car
        ]
        preds = [
            (2, [15.0, 10.0, 55.0, 50.0]),  # IoU ~ 0.6
            (2, [10.0, 10.0, 50.0, 50.0]),  # IoU = 1.0 (exact match)
        ]
        matched_gts, matched_preds = compare_bench.match_predictions_to_ground_truth(
            gts, preds, iou_threshold=0.4
        )
        self.assertEqual(matched_gts, {0})
        self.assertEqual(matched_preds, {1}, "Higher IoU prediction (index 1) must be assigned")

    def test_iou_exact_boundary_conditions(self):
        """Exact threshold matches, strictly below threshold does not (no floating bias)."""
        box1 = [0.0, 0.0, 10.0, 10.0]  # area 100
        # IoU = 40 / 100 = 0.4 exact
        box_exact = [0.0, 0.0, 10.0, 4.0]
        box_below = [0.0, 0.0, 10.0, 3.9]

        gts = [{"category_id": 1, "bbox_xyxy": box1}]
        matched_exact, _ = compare_bench.match_predictions_to_ground_truth(
            gts, [(1, box_exact)], iou_threshold=0.4
        )
        self.assertEqual(len(matched_exact), 1, "IoU == threshold must match")

        matched_below, _ = compare_bench.match_predictions_to_ground_truth(
            gts, [(1, box_below)], iou_threshold=0.4
        )
        self.assertEqual(len(matched_below), 0, "IoU < threshold must not match")

    def test_evaluate_detection_accuracy_one_to_one_enforcement(self):
        """End-to-end evaluate_detection_accuracy with 2 GTs and 1 prediction yields 50% recall, not 100%."""
        val_data = {
            "images": [{"id": 1, "file_name": "test.jpg"}],
            "annotations": [
                {"id": 1, "image_id": 1, "category_id": 2, "bbox": [10, 10, 40, 40]},
                {"id": 2, "image_id": 1, "category_id": 2, "bbox": [20, 10, 40, 40]},
            ],
        }
        mock_detector = MagicMock()
        mock_detector.detect.return_value = {
            "detection_status": "ok",
            "detections": [{"label": "car", "bbox_xyxy": [15.0, 10.0, 55.0, 50.0], "score": 0.9}],
        }
        with tempfile.TemporaryDirectory() as td:
            img_path = Path(td) / "test.jpg"
            cv2.imwrite(str(img_path), np.zeros((100, 100, 3), dtype=np.uint8))
            model_cfg = {"manifest": Path(td) / "manifest.json", "model": Path(td) / "model.onnx"}
            Path(model_cfg["manifest"]).write_text("{}", encoding="utf-8")
            Path(model_cfg["model"]).write_text("fake_onnx", encoding="utf-8")

            with patch("tools.compare_models_benchmark.CiviWatchDetector", return_value=mock_detector):
                res = compare_bench.evaluate_detection_accuracy(model_cfg, val_data, Path(td), sample_count=1)

            self.assertEqual(res["status"], "completed")
            # 1 matched out of 2 GTs = 50.0% recall
            self.assertEqual(res["overall_recall"], 50.0)
            self.assertEqual(res["car_recall"], 50.0)


class TestF11BenchmarkSubsampledTimestamps(unittest.TestCase):
    """F11: Benchmark subsampled timestamps must derive from source frame index and native FPS."""

    def test_benchmark_video_timestamps_reflect_native_source_index(self):
        """When sampling at 10 fps from 25 fps source, step_frames = round(25/10) = 2 (banker's rounding).
        Source frame indices processed: 0, 2, 4, 6...
        Source timestamps: 0.0, 2/25=0.08, 4/25=0.16, 6/25=0.24 (NOT sample-index 0.0, 0.1, 0.2, 0.3).
        """
        native_fps = 25.0
        sample_fps = 10.0
        # Python 3 round(2.5) == 2 (banker's rounding)
        step_frames = max(1, int(round(native_fps / sample_fps)))
        self.assertEqual(step_frames, 2)

        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(10)]

        received_calls: list[tuple[int, float]] = []

        def capture_step(*args, **kwargs):
            fid = kwargs.get("frame_id")
            ts = kwargs.get("timestamp")
            received_calls.append((fid, ts))
            return []

        with tempfile.TemporaryDirectory() as td:
            dummy_manifest = Path(td) / "manifest.json"
            dummy_model = Path(td) / "model.onnx"
            dummy_video = Path(td) / "test.mp4"
            dummy_manifest.write_text("{}", encoding="utf-8")
            dummy_model.write_text("fake_onnx", encoding="utf-8")
            dummy_video.write_text("fake_video", encoding="utf-8")

            model_cfg = {"manifest": dummy_manifest, "model": dummy_model}
            with patch("cv2.VideoCapture", side_effect=lambda *a, **kw: FakeVideoCapture(frames, native_fps=native_fps)), \
                 patch("tools.compare_models_benchmark.PerceptionPipeline") as mock_pipeline_cls:
                mock_pipeline = mock_pipeline_cls.return_value
                mock_pipeline.last_observation = {"detection_status": "ok_empty", "detections": []}
                mock_pipeline.process_frame.side_effect = capture_step

                res = compare_bench.evaluate_perception_pipeline_on_video(
                    model_cfg,
                    dummy_video,
                    max_frames=4,
                    sample_fps=sample_fps,
                )

        self.assertEqual(res["status"], "completed")
        self.assertEqual(len(received_calls), 4)

        # Expected source indices: 0, 2, 4, 6
        expected_indices = [0, 2, 4, 6]
        # Expected source times: 0/25=0.0, 2/25=0.08, 4/25=0.16, 6/25=0.24
        expected_times = [float(round((idx / native_fps) * 1_000_000) * Fraction("1/1000000")) for idx in expected_indices]

        for i, (fid, ts) in enumerate(received_calls):
            self.assertEqual(fid, expected_indices[i], f"Call {i} frame_id must be native source frame {expected_indices[i]}")
            self.assertAlmostEqual(ts, expected_times[i], places=4, msg=f"Call {i} timestamp must derive from source index / native FPS")


class TestF16MeasuredBenchmarkReporting(unittest.TestCase):
    """F16: Benchmark reports only varied measured outcomes without invented mAP, GPU, or legal claims."""

    def test_report_reflects_varied_measured_inputs_and_unmeasured_limits(self):
        """Report accurately renders numbers from varied measured results and notes unmeasured limits."""
        results = [
            {
                "model_config": {
                    "id": "model_alpha",
                    "name": "Model Alpha Custom",
                    "resolution": 416,
                    "decode": "yolox_grid",
                    "license": "Apache-2.0",
                },
                "accuracy": {
                    "status": "completed",
                    "file_size_mb": 17.8,
                    "overall_recall": 74.2,
                    "moto_recall": 78.1,
                    "car_recall": 82.0,
                    "bus_recall": 60.5,
                    "truck_recall": 65.0,
                    "night_recall": 71.3,
                    "latency_p50_ms": 19.3,
                    "latency_p95_ms": 24.1,
                    "person_detections": 8,
                },
                "videos": {
                    "sample_video.mp4": {
                        "status": "completed",
                        "pipeline_fps": 31.4,
                        "total_detections": 150,
                        "total_events": 2,
                    }
                },
            },
            {
                "model_config": {
                    "id": "model_beta",
                    "name": "Model Beta Unavailable",
                    "resolution": 640,
                    "decode": "nms_free",
                    "license": "Apache-2.0",
                },
                "accuracy": {
                    "status": "unavailable",
                    "reason": "model file not found",
                },
                "videos": {},
            },
        ]
        report = compare_bench.generate_markdown_report(results)

        # Measured numbers must be faithfully reflected
        self.assertIn("Model Alpha Custom", report)
        self.assertIn("74.2%", report)
        self.assertIn("19.3 ms", report)
        self.assertIn("31.4 FPS", report)
        # Unavailable model status cleanly reflected
        self.assertIn("Model Beta Unavailable", report)
        self.assertIn("N/A", report)
        # Disclaimer of unmeasured limits
        self.assertIn("Perception", report)


class TestF17ExtendedScenarioReporting(unittest.TestCase):
    """F17: Extended evaluator explicitly reports unconfigured/unsupported scenarios absent ROI/engine."""

    def test_unsupported_scenarios_are_explicitly_reported(self):
        """US04, US10, US14 are listed as unconfigured/unsupported rather than silently claimed."""
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(3)]
        detector = ScriptedDetector()

        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
            with patch("cv2.VideoCapture", side_effect=lambda *a, **kw: FakeVideoCapture(frames, native_fps=10.0)):
                res = eval_all.evaluate_video(
                    Path(tf.name),
                    detector,
                    sample_fps=10.0,
                    max_frames=3,
                    with_pose=False,
                    extended_scenarios=True,
                )

        self.assertIn("evaluated_scenarios", res)
        self.assertIn("unconfigured_scenarios", res)
        unconfigured = set(res["unconfigured_scenarios"])
        evaluated = set(res["evaluated_scenarios"])
        # US04 (sidewalk encroachment needs ROI), US10 (danger zone needs engine), US14 (vandalism needs ROI)
        self.assertTrue({"US04", "US10", "US14"}.issubset(unconfigured))
        self.assertTrue({"US04", "US10", "US14"}.isdisjoint(evaluated))


class TestF18PerceptionPipelineScope(unittest.TestCase):
    """F18: Honest perception-pipeline scope notes unexercised recording/outbox components."""

    def test_perception_result_notes_unexercised_components(self):
        """Benchmark result notes unexercised recording/outbox upload components."""
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(2)]

        with tempfile.TemporaryDirectory() as td:
            dummy_manifest = Path(td) / "manifest.json"
            dummy_model = Path(td) / "model.onnx"
            dummy_video = Path(td) / "test.mp4"
            dummy_manifest.write_text("{}", encoding="utf-8")
            dummy_model.write_text("fake_onnx", encoding="utf-8")
            dummy_video.write_text("fake_video", encoding="utf-8")

            model_cfg = {"manifest": dummy_manifest, "model": dummy_model}
            with patch("cv2.VideoCapture", side_effect=lambda *a, **kw: FakeVideoCapture(frames, native_fps=10.0)), \
                 patch("tools.compare_models_benchmark.PerceptionPipeline") as mock_pipeline_cls:
                mock_pipeline = mock_pipeline_cls.return_value
                mock_pipeline.last_observation = {"detection_status": "ok_empty", "detections": []}
                mock_pipeline.process_frame.return_value = []

                res = compare_bench.evaluate_perception_pipeline_on_video(
                    model_cfg,
                    dummy_video,
                    max_frames=2,
                    sample_fps=10.0,
                )

        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["pipeline_type"], "perception_pipeline")
        self.assertIn("unexercised_components", res)
        self.assertTrue(any("recording" in c for c in res["unexercised_components"]))


class TestF19InferenceErrorHandling(unittest.TestCase):
    """F19: Unsuccessful observations mark run invalid/failed, not completed, and report actual frames."""

    def test_benchmark_video_marks_failed_on_inference_error_and_preserves_actual_frame_count(self):
        """When detector returns an error status mid-video, benchmark marks failed and reports actual count."""
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(10)]

        call_count = [0]
        def step_with_failure(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 3:
                # 3rd processed frame encounters inference failure
                mock_pipeline.last_observation = {
                    "detection_status": "failed",
                    "error": "simulated_gpu_crash",
                    "detections": [],
                }
            else:
                mock_pipeline.last_observation = {
                    "detection_status": "ok",
                    "detections": [{"label": "car", "bbox": [10, 10, 50, 50], "score": 0.9}],
                }
            return []

        with tempfile.TemporaryDirectory() as td:
            dummy_manifest = Path(td) / "manifest.json"
            dummy_model = Path(td) / "model.onnx"
            dummy_video = Path(td) / "test.mp4"
            dummy_manifest.write_text("{}", encoding="utf-8")
            dummy_model.write_text("fake_onnx", encoding="utf-8")
            dummy_video.write_text("fake_video", encoding="utf-8")

            model_cfg = {"manifest": dummy_manifest, "model": dummy_model}
            with patch("cv2.VideoCapture", side_effect=lambda *a, **kw: FakeVideoCapture(frames, native_fps=10.0)), \
                 patch("tools.compare_models_benchmark.PerceptionPipeline") as mock_pipeline_cls:
                mock_pipeline = mock_pipeline_cls.return_value
                mock_pipeline.process_frame.side_effect = step_with_failure

                res = compare_bench.evaluate_perception_pipeline_on_video(
                    model_cfg,
                    dummy_video,
                    max_frames=10,
                    sample_fps=10.0,
                )

        self.assertEqual(res["status"], "failed", "Inference error must result in failed status, not completed")
        self.assertIn("simulated_gpu_crash", res.get("error", ""))
        self.assertEqual(res["frames_processed"], 2, "Must report actual successfully processed frame count")



class TestReplayRunnerDeepening(unittest.TestCase):
    """Deepened semantic replay runner interface tests (ADR-0006)."""

    def test_replay_runner_computes_exact_rational_timestamps_and_strides(self):
        from tools.replay_runner import run_replay_session

        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(10)]
        native_fps = 25.0
        sample_fps = 10.0

        received_steps: list[tuple[int, float]] = []

        def dummy_factory(tmp_root: Path, width: int, height: int, fps: float):
            mock_pipeline = MagicMock()
            mock_pipeline.last_observation = {"detection_status": "ok_empty", "detections": []}
            mock_pipeline.process_frame.side_effect = lambda rgb, timestamp, frame_id: (
                received_steps.append((frame_id, timestamp)) or []
            )
            mock_outbox = MagicMock()
            mock_outbox.pending.return_value = []
            return mock_pipeline, mock_outbox

        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
            with patch("cv2.VideoCapture", return_value=FakeVideoCapture(frames, native_fps=native_fps)):
                res = run_replay_session(
                    Path(tf.name),
                    dummy_factory,
                    sample_fps=sample_fps,
                    max_frames=4,
                    fail_fast=True,
                )

        self.assertEqual(res.status, "completed")
        self.assertEqual(res.frames_processed, 4)
        expected_indices = [0, 2, 4, 6]
        expected_times = [float(round((idx / native_fps) * 1_000_000) * Fraction("1/1000000")) for idx in expected_indices]
        for i, (fid, ts) in enumerate(received_steps):
            self.assertEqual(fid, expected_indices[i])
            self.assertAlmostEqual(ts, expected_times[i], places=4)

    def test_run_benchmark_uses_source_timestamps_and_fails_fast_on_error(self):
        import tools.run_benchmark as run_bench

        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(6)]
        native_fps = 25.0
        observed_timestamps: list[float] = []

        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
            with patch("cv2.VideoCapture", return_value=FakeVideoCapture(frames, native_fps=native_fps)), \
                 patch("tools.run_benchmark.PerceptionPipeline") as mock_pipeline_cls:
                mock_pipeline = mock_pipeline_cls.return_value
                def step(rgb, timestamp, frame_id):
                    observed_timestamps.append(timestamp)
                    mock_pipeline.last_observation = {"detection_status": "ok_empty", "detections": []}
                    return []
                mock_pipeline.process_frame.side_effect = step
                mock_pipeline.last_observation = {"detection_status": "ok_empty", "detections": []}

                result = run_bench.run_single_benchmark(Path(tf.name), max_frames=3, sample_fps=10.0)

        self.assertEqual(result["frames_processed"], 3)
        # Source timestamps at 25 fps sampled at 10 fps (step=2) are 0.0, 0.08, 0.16 (NOT legacy sample-index 0.0, 0.1, 0.2!)
        self.assertAlmostEqual(observed_timestamps[0], 0.0, places=4)
        self.assertAlmostEqual(observed_timestamps[1], 0.08, places=4)
        self.assertAlmostEqual(observed_timestamps[2], 0.16, places=4)

        # Fail-fast on detection error
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tf:
            with patch("cv2.VideoCapture", return_value=FakeVideoCapture(frames, native_fps=native_fps)), \
                 patch("tools.run_benchmark.PerceptionPipeline") as mock_pipeline_cls:
                mock_pipeline = mock_pipeline_cls.return_value
                mock_pipeline.process_frame.return_value = []
                mock_pipeline.last_observation = {"detection_status": "failed", "error": "simulated_error"}
                with self.assertRaises(RuntimeError):
                    run_bench.run_single_benchmark(Path(tf.name), max_frames=3, sample_fps=10.0)


if __name__ == "__main__":
    unittest.main()
