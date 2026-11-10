"""Tests for HCMC Traffic Hard-Negative Filtering, Mixed Dataset Pipeline, and 640x640 NMS-Free CiviWatchDetector."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from apps.edge.homography import GroundPlaneHomography
from apps.edge.oracle_detector import CiviWatchDetector
from apps.edge.tracker import Track
from apps.edge.urban_safety_engine import UrbanSafetyScenarioEngine
from apps.edge.vehicle_incident import VehicleIncidentEngine
from tools.prepare_mixed_traffic_dataset import (
    AIC_TO_CIVIWATCH,
    CIVIWATCH_CLASSES,
    build_dataset_yaml,
    convert_and_copy_split,
)
from tools.train_civiwatch_detector import generate_civiwatch_manifest
from tools.train_yolox_detector import write_yolox_experiment_file, yolo_split_to_coco_json


def _make_track(tid: int, bbox: list[float], ts: float, label: str = "car", score: float = 0.9) -> Track:
    tr = Track(track_id=tid, bbox=bbox, score=score, label=label, timestamp=ts)
    tr.state = "active"
    return tr


class HCMCTrafficHardNegativeTests(unittest.TestCase):
    """Verify false-positive elimination on dense Vietnamese motorbike/intersection traffic."""

    def test_same_direction_queueing_and_perspective_separation_rejected(self) -> None:
        hom = GroundPlaneHomography.default_urban_cctv(1280, 720, road_width_m=15.0, road_depth_m=45.0)
        engine = VehicleIncidentEngine(homography=hom, enable_vlm=False)

        # Two motorbikes moving together in same lane, stopping smoothly at red light with 2D overlap
        m1 = _make_track(1, [400.0, 400.0, 450.0, 480.0], 0.0, label="motorcycle")
        m2 = _make_track(2, [420.0, 360.0, 470.0, 440.0], 0.0, label="motorcycle")

        events = []
        for i in range(1, 15):
            ts = i * 0.1
            dy = min(i * 4.0, 28.0)  # decelerates and stops by t=0.8s
            m1.update([400.0, 400.0 + dy, 450.0, 480.0 + dy], score=0.9, timestamp=ts)
            m2.update([420.0, 360.0 + dy, 470.0, 440.0 + dy], score=0.9, timestamp=ts)
            events.extend(engine.process_tracks([m1, m2], timestamp=ts, frame_dimensions=(1280.0, 720.0)))

        self.assertEqual(events, [], "Same-direction intersection stopping must not emit crash events")

    def test_comoving_motorbike_rider_rejected(self) -> None:
        engine = VehicleIncidentEngine(enable_vlm=False)
        moto = _make_track(10, [300.0, 300.0, 360.0, 390.0], 0.0, label="motorcycle")
        rider = _make_track(11, [310.0, 280.0, 350.0, 360.0], 0.0, label="person")

        events = []
        for i in range(1, 12):
            ts = i * 0.1
            dx = i * 6.0 if i < 7 else 42.0  # moto and rider stop together at intersection
            moto.update([300.0 + dx, 300.0, 360.0 + dx, 390.0], score=0.92, timestamp=ts)
            rider.update([310.0 + dx, 280.0, 350.0 + dx, 360.0], score=0.90, timestamp=ts)
            events.extend(engine.process_tracks([moto, rider], timestamp=ts))

        self.assertEqual(events, [], "Co-moving rider on motorcycle must not trigger vehicle_pedestrian crash")

    def test_linear_walking_pedestrian_rejected_for_vandalism(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="property_vandalism",
            roi_polygon=[[0.05, 0.05], [0.95, 0.05], [0.95, 0.95], [0.05, 0.95]],
            frame_dimensions=(1280.0, 720.0),
            min_persistence_seconds=1.0,
            motion_energy_threshold=30.0,
        )
        ped = _make_track(1, [100.0, 300.0, 150.0, 420.0], 0.0, label="person")
        events = []
        for i in range(1, 25):
            ts = i * 0.1
            ped.update([100.0 + i * 10.0, 300.0, 150.0 + i * 10.0, 420.0], score=0.92, timestamp=ts)
            events.extend(engine.process_tracks([ped], timestamp=ts, frame_dimensions=(1280.0, 720.0)))

        self.assertEqual(events, [], "Linear pedestrian walking must not trigger property_vandalism")


class MixedDatasetPipelineTests(unittest.TestCase):
    """Verify mixed dataset conversion, label mapping, and dataset.yaml creation."""

    def test_convert_and_build_mixed_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_imgs = root / "src/images"
            src_lbls = root / "src/labels"
            src_imgs.mkdir(parents=True)
            src_lbls.mkdir(parents=True)

            (src_imgs / "cam_01_000001.jpg").write_bytes(b"fake-jpg")
            (src_lbls / "cam_01_000001.txt").write_text(
                "0 0.5 0.5 0.1 0.2\n"
                "1 0.3 0.4 0.2 0.2\n"
                "2 0.7 0.6 0.3 0.3\n"
                "3 0.2 0.8 0.2 0.2\n",
                encoding="utf-8",
            )

            out_dir = root / "mixed_traffic"
            yaml_path = build_dataset_yaml(out_dir)
            self.assertTrue(yaml_path.is_file())
            yaml_txt = yaml_path.read_text(encoding="utf-8")
            for idx, cname in enumerate(CIVIWATCH_CLASSES):
                self.assertIn(f"{idx}: {cname}", yaml_txt)

            stats = convert_and_copy_split(
                "train",
                src_images_dir=src_imgs,
                src_labels_dir=src_lbls,
                dst_images_dir=out_dir / "images/train",
                dst_labels_dir=out_dir / "labels/train",
                max_samples=10,
            )
            self.assertEqual(stats["images"], 1)
            self.assertEqual(stats["boxes"], 4)

            converted = (out_dir / "labels/train/cam_01_000001.txt").read_text(encoding="utf-8").splitlines()
            mapped_classes = [int(line.split()[0]) for line in converted]
            self.assertEqual(mapped_classes, [AIC_TO_CIVIWATCH[i] for i in range(4)])


@unittest.skipUnless(
    all(importlib.util.find_spec(m) for m in ("onnx", "onnxruntime", "cv2")),
    "requires onnx + onnxruntime + opencv",
)
class CiviWatch640DetectorTests(unittest.TestCase):
    """Verify 640x640 NMS-free CiviWatchDetector end-to-end execution."""

    def test_640x640_nms_free_onnx_inference_and_manifest(self) -> None:
        import onnx
        from onnx import TensorProto, helper, numpy_helper

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create dummy [1, 300, 6] NMS-free output covering classes 0..5:
            # 0: person, 1: two_wheeler, 2: car, 3: bus, 4: truck, 5: obstacle_object
            out_arr = np.zeros((1, 300, 6), dtype=np.float32)
            out_arr[0, 0] = [64.0, 64.0, 192.0, 320.0, 0.92, 0.0]
            out_arr[0, 1] = [320.0, 192.0, 448.0, 384.0, 0.88, 1.0]
            out_arr[0, 2] = [100.0, 100.0, 220.0, 240.0, 0.91, 2.0]
            out_arr[0, 3] = [240.0, 100.0, 360.0, 240.0, 0.89, 5.0]

            tensor = numpy_helper.from_array(out_arr, "raw")
            graph = helper.make_graph(
                [helper.make_node("Identity", ["raw"], ["output0"])],
                "civiwatch-640-nmsfree-test",
                [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
                [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 300, 6])],
                initializer=[tensor],
            )
            model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
            model.ir_version = 9
            onnx_path = root / "yolo26s_640.onnx"
            onnx.save(model, onnx_path)

            manifest = generate_civiwatch_manifest("yolo26s", onnx_path, input_size=640, nms_free=True)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            detector = CiviWatchDetector(manifest_path, onnx_path, strict_runtime=False)
            rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
            frame = {
                "camera_id": "civi-cam-01",
                "stream_session_id": "sess-1",
                "core_epoch": 1,
                "origin": "live",
                "frame_id": 1,
                "pts": 1000,
                "time_base": "1/1000",
                "event_time": 1.0,
            }
            res = detector.detect(rgb, frame)
            self.assertEqual(res["detection_status"], "ok")
            self.assertEqual(res["transform"]["model_size"], [640, 640])
            self.assertEqual(len(res["detections"]), 4)
            labels = {d["label"] for d in res["detections"]}
            self.assertEqual(labels, {"person", "two_wheeler", "car", "obstacle_object"})
            # Scale = 640 / 1280 = 0.5, so box [64, 64, 192, 320] maps back to [128, 128, 384, 640]
            person_det = next(d for d in res["detections"] if d["label"] == "person")
            np.testing.assert_allclose(person_det["bbox_xyxy"], [128.0, 128.0, 384.0, 640.0], atol=1e-3)


class CodeReviewRegressionTests(unittest.TestCase):
    """Regression tests for all code-review findings (Spec & Standards axes)."""

    def test_us01_smoke_triggers_independently_without_fire_and_respects_roi(self) -> None:
        # ROI covers left half [0.0..0.45]; smoke in right half must NOT trigger, smoke in left half MUST trigger
        engine = UrbanSafetyScenarioEngine(
            factory="fire_smoke_suspected",
            roi_polygon=[[0.05, 0.05], [0.45, 0.05], [0.45, 0.95], [0.05, 0.95]],
            frame_dimensions=(640.0, 360.0),
            min_persistence_seconds=1.0,
            smoke_ratio_threshold=0.05,
        )
        # Smoke only in right half (outside ROI)
        outside_rgb = np.zeros((360, 640, 3), dtype=np.uint8)
        outside_rgb[:, 400:600] = [165, 168, 170]
        self.assertEqual(engine.process_tracks([], timestamp=1.0, rgb=outside_rgb), [])
        self.assertEqual(engine.process_tracks([], timestamp=2.5, rgb=outside_rgb), [])

        # Smoke inside ROI (left half) with ZERO fire pixels
        inside_rgb = np.zeros((360, 640, 3), dtype=np.uint8)
        inside_rgb[50:250, 50:250] = [165, 168, 170]
        self.assertEqual(engine.process_tracks([], timestamp=3.0, rgb=inside_rgb), [])
        evs = engine.process_tracks([], timestamp=4.2, rgb=inside_rgb)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["taxonomy"], "smoke_suspected")
        self.assertEqual(evs[0]["payload"]["fire_pixel_ratio"], 0.0)

    def test_us01_and_us13_do_not_clobber_each_other_in_multi_scenario_mode(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="urban_safety_vlm",
            min_persistence_seconds=1.0,
            min_dark_duration_seconds=1.0,
            luminance_threshold=30.0,
        )
        # Dark frame (luma = 5.0 < 30.0) with no fire/smoke
        dark_rgb = np.full((180, 320, 3), 5, dtype=np.uint8)
        self.assertEqual(engine.process_tracks([], timestamp=1.0, rgb=dark_rgb), [])
        evs = engine.process_tracks([], timestamp=2.5, rgb=dark_rgb)
        taxonomies = {e["payload"]["taxonomy"] for e in evs}
        self.assertIn("streetlight_outage", taxonomies, "US01 must not reset US13 dark timer")

    def test_us09_anchor_kind_is_valid_in_evidence_contract(self) -> None:
        from domain.evidence_contract import make_evidence_request
        from domain.urban_scenarios import SCENARIO_BY_ID

        us09 = SCENARIO_BY_ID["US09"]
        req = make_evidence_request("req-1", "sess-1", us09.anchor_kind, 100.0)
        self.assertEqual(req["evidence_anchor_kind"], "onset")

    def test_pose_manager_uses_estimate_batch_for_same_frame_requests(self) -> None:
        from apps.edge.pose import PoseManager, PoseRequest

        batch_calls: list[int] = []

        class SpyBatchEstimator:
            def estimate_batch(self, rgb: np.ndarray, bboxes: list[list[float]]) -> list[list[dict[str, float]]]:
                batch_calls.append(len(bboxes))
                return [[{"name": "nose", "x": 10.0, "y": 20.0, "score": 0.9}] for _ in bboxes]

            def estimate(self, rgb: np.ndarray, bbox: list[float]) -> list[dict[str, float]]:
                raise AssertionError("Sequential estimate() should not be called when estimate_batch succeeds")

        mgr = PoseManager(estimator=SpyBatchEstimator())  # type: ignore[arg-type]
        rgb = np.zeros((240, 320, 3), dtype=np.uint8)
        mgr.cache_frame("cam-1", "sess-1", 1, 10, rgb)
        for tid in (1, 2, 3):
            mgr.submit_request(
                PoseRequest(
                    request_id=f"req-{tid}",
                    camera_id="cam-1",
                    stream_session_id="sess-1",
                    core_epoch=1,
                    frame_id=10,
                    track_id=tid,
                    bbox=[10.0 * tid, 10.0, 50.0 * tid, 100.0],
                    deadline=50.0,
                    branch="fast_fall",
                )
            )
        outcomes = mgr.process_pending(current_time=1.0)
        self.assertEqual(len(outcomes), 3)
        self.assertEqual(batch_calls, [3])

    def test_go2rtc_media_engine_clip_extraction_and_recorder_fallback(self) -> None:
        from apps.edge.media_engine import Go2RtcMediaEngine
        from apps.edge.recorder import FileRecorder

        with tempfile.TemporaryDirectory() as tmp:
            rec = FileRecorder(Path(tmp) / "ring", ring_seconds=60)

            def failing_http(url: str, timeout: float) -> bytes:
                raise ConnectionError("go2rtc offline")

            media = Go2RtcMediaEngine(http_getter=failing_http, fallback_recorder=rec)
            res = media.extract_evidence_clip(
                "civi-cam-01",
                request_id="req-fallback-1",
                session_id="sess-fallback-1",
                start_seconds=10.0,
                end_seconds=40.0,
            )
            self.assertEqual(res["provider"], "file_recorder_fallback")
            self.assertEqual(res["request_id"], "req-fallback-1")

    def test_yolox_dataset_coco_conversion_and_experiment_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imgs = root / "images"
            lbls = root / "labels"
            imgs.mkdir()
            lbls.mkdir()

            # Create sample 640x360 image and label
            dummy_bgr = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.imwrite(str(imgs / "cam_01.jpg"), dummy_bgr)
            (lbls / "cam_01.txt").write_text("0 0.5 0.5 0.2 0.4\n1 0.7 0.6 0.1 0.2\n", encoding="utf-8")

            coco_out = root / "instances.json"
            res = yolo_split_to_coco_json(imgs, lbls, coco_out)
            self.assertEqual(res["images"], 1)
            self.assertEqual(res["annotations"], 2)

            data = json.loads(coco_out.read_text(encoding="utf-8"))
            self.assertEqual(len(data["categories"]), 6)
            self.assertEqual(data["annotations"][0]["category_id"], 1)  # person
            self.assertEqual(data["annotations"][1]["category_id"], 2)  # two_wheeler

            exp_file = root / "civiwatch_yolox_tiny_exp.py"
            write_yolox_experiment_file(exp_file, dataset_dir=root, variant="yolox_tiny", input_size=416)
            self.assertTrue(exp_file.is_file())
            exp_txt = exp_file.read_text(encoding="utf-8")
            self.assertIn("self.input_size = (416, 416)", exp_txt)
            self.assertIn("self.num_classes = 6", exp_txt)


    def test_perception_execution_seamlessly_switches_between_yolox_and_civiwatch_models(self) -> None:
        from apps.edge.perception import PerceptionExecution

        yolox_model = Path("data/oracle/yolox_tiny.onnx")
        civi_model = Path("models/civiwatch-640/yolo26s_civiwatch_640.onnx")
        if not yolox_model.is_file() or not civi_model.is_file():
            self.skipTest("Model binaries not present on disk")

        # 1. Load baseline YOLOX-Tiny
        pe_yolox = PerceptionExecution(
            manifest_path=Path("models/yolox-tiny/manifest.json"),
            model_path=yolox_model,
            origin="replay",
        )
        self.assertEqual(pe_yolox.detector.provenance["model_id"], "yolox-tiny-0.1.1rc0")

        # 2. Hot-swap to CiviWatch 640 NMS-free detector without touching any pipeline code
        pe_civi = PerceptionExecution(
            manifest_path=Path("models/civiwatch-640/manifest.json"),
            model_path=civi_model,
            origin="live",
        )
        self.assertEqual(pe_civi.detector.provenance["model_id"], "civiwatch-yolo26s-640")

        # Both detectors run through the exact same execute() interface
        rgb = np.zeros((360, 640, 3), dtype=np.uint8)
        frame_rep = pe_yolox.frame("cam-1", "sess-1", 1, "replay", 0, 0.0)
        res_yolox = pe_yolox.execute(rgb, frame_rep)
        self.assertIn(res_yolox["detection_status"], {"ok", "ok_empty"})

        frame_live = pe_civi.frame("cam-1", "sess-1", 1, "live", 0, 0.0)
        res_civi = pe_civi.execute(rgb, frame_live)
        self.assertIn(res_civi["detection_status"], {"ok", "ok_empty"})


if __name__ == "__main__":
    unittest.main()
