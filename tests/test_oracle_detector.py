import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


DEPENDENCIES = all(importlib.util.find_spec(name) for name in ("numpy", "cv2", "onnxruntime"))


@unittest.skipUnless(DEPENDENCIES, "requires pinned oracle runtime")
class OracleDetectorTests(unittest.TestCase):
    frame = dict(camera_id="camera", stream_session_id="session", core_epoch=1,
                 origin="replay", frame_id=0, pts=42, time_base="1/10", event_time=4.2)

    def detector_fixture(self, directory, output, nodes=None):
        import numpy as np
        import onnx
        from onnx import helper, numpy_helper, TensorProto
        from apps.edge.oracle_detector import OracleDetector

        manifest = json.loads(Path("models/yolox-tiny/manifest.json").read_text())
        tensor = numpy_helper.from_array(np.asarray(output, dtype=np.float32), "raw")
        graph = helper.make_graph(nodes or [helper.make_node("Identity", ["raw"], ["output"])],
                                  "independent-numeric-vector",
                                  [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 416, 416])],
                                  [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3549, 85])],
                                  initializer=[tensor])
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        model.ir_version = 9
        model_path = Path(directory) / "vector.onnx"
        onnx.save(model, model_path)
        blob = model_path.read_bytes()
        expected_artifact = dict(sha256=hashlib.sha256(blob).hexdigest(), size_bytes=len(blob))
        manifest["model_id"] = "synthetic-yolox-numeric-test"
        manifest["artifact"].update(**expected_artifact, source_url="generated:test-vector",
                                    source_commit="not-applicable", release="test-vector")
        manifest["rights"] = dict(source_license="not-applicable", weights_license="generated-test-data",
                                  lab_use_approved=False, production_use_approved=False)
        manifest_path = Path(directory) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        return OracleDetector(manifest_path, model_path, environment="numeric-test", expected_artifact=expected_artifact)

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_zero_probability_output_is_successful_empty_with_frame_lineage(self):
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            detector = self.detector_fixture(directory, np.zeros((1, 3549, 85)))
            result = detector.detect(np.zeros((100, 200, 3), dtype=np.uint8), self.frame)
        self.assertEqual(result["detection_status"], "ok_empty")
        self.assertEqual(result["detections"], [])
        self.assertIsNone(result["error"])
        self.assertEqual(result["schema_version"], 1)
        for name, value in self.frame.items():
            self.assertEqual(result[name], value)
        self.assertEqual(result["transform"], dict(original_size=[100, 200], model_size=[416, 416], scale=2.08, pad=[0, 0]))
        self.assertEqual(result["provenance"]["provider"], "CPUExecutionProvider")
        self.assertEqual(result["provenance"]["model_id"], "synthetic-yolox-numeric-test")
        self.assertEqual(set(result["timings"]), {"preprocess_ms", "inference_ms", "postprocess_ms"})

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_raw_three_stride_vectors_decode_multilabel_clip_and_sort(self):
        import numpy as np

        raw = np.zeros((1, 3549, 85), dtype=np.float32)
        # Stride8 cell(1,1): center(12,12), size(8,8) -> [8,8,16,16].
        raw[0, 53, :7] = [.5, .5, 0, 0, 1, .3, .7]
        # Stride16 first cell: center(32,32), size(16,16).
        raw[0, 2704, :6] = [2, 2, 0, 0, 1, .8]
        # Stride32 first cell negative center clips lower coordinates to zero.
        raw[0, 3380, :6] = [0, 0, 0, 0, 1, .9]
        with tempfile.TemporaryDirectory() as directory:
            detector = self.detector_fixture(directory, raw)
            result = detector.detect(np.zeros((208, 416, 3), dtype=np.uint8), self.frame)
        self.assertEqual(result["detection_status"], "ok")
        self.assertEqual([(d["class_id"], d["label"], d["bbox_xyxy"]) for d in result["detections"]],
                         [(0, "person", [0, 0, 16, 16]), (0, "person", [24, 24, 40, 40]),
                          (1, "bicycle", [8, 8, 16, 16]), (0, "person", [8, 8, 16, 16])])
        self.assertAlmostEqual(result["detections"][-1]["score"], .3, places=7)

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_nms_uses_original_coordinate_inclusive_pixels_and_per_class(self):
        import numpy as np

        raw = np.zeros((1, 3549, 85), dtype=np.float32)
        # Original 2x2 boxes [0,0,2,2] and [1,0,3,2]: inclusive IoU=6/12=.5.
        # Continuous IoU=2/6=.333 would wrongly retain the second person.
        raw[0, 0, :7] = [.25, .25, -0.69314718056, -0.69314718056, 1, .9, .7]
        raw[0, 1, :7] = [-.5, .25, -0.69314718056, -0.69314718056, 1, .8, 0]
        with tempfile.TemporaryDirectory() as directory:
            detector = self.detector_fixture(directory, raw)
            result = detector.detect(np.zeros((208, 208, 3), dtype=np.uint8), self.frame)
        self.assertEqual([d["class_id"] for d in result["detections"]], [0, 1])
        np.testing.assert_allclose(result["detections"][0]["bbox_xyxy"], [0, 0, 2, 2], atol=1e-6)

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_invalid_output_and_invalid_inputs_are_failed_not_negative_evidence(self):
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            raw = np.zeros((1, 3549, 85), dtype=np.float32)
            raw[0, 0, 0] = np.nan
            detector = self.detector_fixture(directory, raw)
            for rgb, frame in [(np.zeros((20, 20, 3), dtype=np.uint8), self.frame),
                               (np.zeros((20, 20, 3), dtype=np.float32), self.frame),
                               (np.zeros((0, 20, 3), dtype=np.uint8), self.frame),
                               (np.zeros((20, 20, 3), dtype=np.uint8), {**self.frame, "pts": "42"}),
                               (np.zeros((20, 20, 3), dtype=np.uint8), {**self.frame, "time_base": "0/1"})]:
                with self.subTest(shape=rgb.shape, frame=frame):
                    result = detector.detect(rgb, frame)
                    self.assertEqual(result["detection_status"], "failed")
                    self.assertEqual(result["detections"], [])
                    self.assertTrue(result["error"]["message"])

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_constructor_rejects_artifact_tensor_mismatch(self):
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                self.detector_fixture(directory, np.zeros((1, 2, 85)))

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_rgb_is_converted_once_to_raw_bgr_through_input_sensitive_model(self):
        import numpy as np
        from onnx import helper, numpy_helper

        raw = np.zeros((1, 3549, 85), dtype=np.float32)
        raw[0, 0, 4:6] = 1
        nodes = [helper.make_node("Constant", [], ["index"], value=numpy_helper.from_array(np.array([[0, 0, 0, 0]], dtype=np.int64))),
                 helper.make_node("GatherND", ["images", "index"], ["red_channel"]),
                 helper.make_node("Sigmoid", ["red_channel"], ["probability"]),
                 helper.make_node("Mul", ["raw", "probability"], ["output"])]
        rgb = np.full((13, 27, 3), [255, 0, 0], dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            detector = self.detector_fixture(directory, raw, nodes)
            result = detector.detect(rgb, self.frame)
        # RGB red's BGR first channel is zero, sigmoid(0)^2=.25 < final .30.
        self.assertEqual(result["detection_status"], "ok_empty")
        self.assertEqual(result["detections"], [])
        with tempfile.TemporaryDirectory() as directory:
            detector = self.detector_fixture(directory, raw, nodes)
            blue = np.full((13, 27, 3), [0, 0, 255], dtype=np.uint8)
            result = detector.detect(blue, self.frame)
        self.assertEqual(result["detection_status"], "ok")
        self.assertEqual(result["detections"][0]["score"], 1.0)

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_returned_provenance_cannot_mutate_subsequent_batches(self):
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            detector = self.detector_fixture(directory, np.zeros((1, 3549, 85)))
            first = detector.detect(np.zeros((20, 20, 3), dtype=np.uint8), self.frame)
            first["provenance"]["runtime"]["version"] = "tampered"
            second = detector.detect(np.zeros((20, 20, 3), dtype=np.uint8), self.frame)
        self.assertEqual(second["provenance"]["runtime"]["version"], "1.20.1")

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_letterbox_is_top_left_114_with_opencv_bilinear_pixels(self):
        import numpy as np
        from onnx import helper, numpy_helper

        raw = np.zeros((1, 3549, 85), dtype=np.float32)
        raw[0, 0, 4:6] = 1
        for index, expected in [([0, 0, 415, 415], .793212890625),
                                ([0, 0, 0, 208], .5625)]:
            nodes = [helper.make_node("Constant", [], ["index"], value=numpy_helper.from_array(np.array([index], dtype=np.int64))),
                     helper.make_node("Constant", [], ["divisor"], value=numpy_helper.from_array(np.array(128, dtype=np.float32))),
                     helper.make_node("GatherND", ["images", "index"], ["pixel"]),
                     helper.make_node("Div", ["pixel", "divisor"], ["probability"]),
                     helper.make_node("Mul", ["raw", "probability"], ["output"])]
            # Blue-channel ramp 0,64,128,192. Target x208 maps to1.50480769;
            # OpenCV bilinear rounds the interpolated96.3076923 to96.
            rgb = np.zeros((2, 4, 3), dtype=np.uint8)
            rgb[:, :, 2] = [0, 64, 128, 192]
            with tempfile.TemporaryDirectory() as directory:
                detector = self.detector_fixture(directory, raw, nodes)
                result = detector.detect(rgb, self.frame)
            if index[3] == 415:
                self.assertEqual(result["detection_status"], "ok")
                self.assertEqual(result["detections"][0]["score"], expected)
            else:
                self.assertEqual(result["detection_status"], "ok")
                self.assertEqual(result["detections"][0]["score"], expected)

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_invalid_probability_and_overflowed_geometry_are_failed(self):
        import numpy as np

        for column, value in [(4, 1.1), (5, -.1), (2, 1000), (3, -1000)]:
            raw = np.zeros((1, 3549, 85), dtype=np.float32)
            raw[0, 0, column] = value
            with tempfile.TemporaryDirectory() as directory:
                detector = self.detector_fixture(directory, raw)
                with np.errstate(over="ignore", under="ignore"):
                    result = detector.detect(np.zeros((20, 20, 3), dtype=np.uint8), self.frame)
            self.assertEqual(result["detection_status"], "failed")
            self.assertEqual(result["detections"], [])

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_event_time_must_equal_float_source_pts_exactly(self):
        import numpy as np

        with tempfile.TemporaryDirectory() as directory:
            detector = self.detector_fixture(directory, np.zeros((1, 3549, 85)))
            rgb = np.zeros((20, 20, 3), dtype=np.uint8)
            failed = detector.detect(rgb, {**self.frame, "event_time": 99.0})
            self.assertEqual(failed["detection_status"], "failed")
            fractional = {**self.frame, "pts": 1, "time_base": "1/3", "event_time": 1 / 3}
            accepted = detector.detect(rgb, fractional)
            self.assertEqual(accepted["detection_status"], "ok_empty")
            rounded = detector.detect(rgb, {**fractional, "event_time": .333333333})
            self.assertEqual(rounded["detection_status"], "failed")

    @unittest.skipUnless(importlib.util.find_spec("onnx"), "requires ONNX test fixture generator")
    def test_synthetic_vector_cannot_impersonate_official_lab_artifact(self):
        import numpy as np
        from apps.edge.oracle_detector import OracleDetector

        with tempfile.TemporaryDirectory() as directory:
            self.detector_fixture(directory, np.zeros((1, 3549, 85)))
            manifest_path = Path(directory) / "manifest.json"
            model_path = Path(directory) / "vector.onnx"
            with self.assertRaises(ValueError):
                OracleDetector(manifest_path, model_path)
            manifest = json.loads(manifest_path.read_text())
            with self.assertRaises(ValueError):
                OracleDetector(manifest_path, model_path, environment="numeric-test")
            manifest["model_id"] = "yolox-tiny-0.1.1rc0"
            manifest_path.write_text(json.dumps(manifest))
            pin = {key: manifest["artifact"][key] for key in ("sha256", "size_bytes")}
            with self.assertRaises(ValueError):
                OracleDetector(manifest_path, model_path, environment="numeric-test", expected_artifact=pin)

    def test_constructor_rejects_invalid_manifest_before_detection(self):
        from apps.edge.oracle_detector import OracleDetector

        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({}))
            model = Path(directory) / "model.onnx"
            model.write_bytes(b"not an ONNX model")
            with self.assertRaises(ValueError):
                OracleDetector(manifest, model)
