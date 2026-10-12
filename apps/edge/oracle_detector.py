"""Lab-only canonical detector for the pinned YOLOX release."""

from copy import deepcopy
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

import hashlib
import json
import math
from fractions import Fraction
from time import perf_counter


class OracleDetector:
    def __init__(self, manifest_path: str | Path, model_path: str | Path, *, environment: str = "lab",
                 expected_artifact: dict[str, Any] | None = None) -> None:
        from domain.model_manifest import load_manifest
        import onnxruntime as ort  # type: ignore[import-untyped]

        try:
            self._manifest = load_manifest(manifest_path, model_path, environment=environment,
                                           expected_artifact=expected_artifact)
        except (KeyError, TypeError) as exc:
            raise ValueError("invalid model manifest") from exc
        if self._manifest.get("schema_version") != 1:
            raise ValueError("unsupported model manifest schema")
        import numpy as np
        from importlib.metadata import version

        runtime = self._manifest["runtime"]
        if (ort.__version__ != runtime["onnxruntime"] or np.__version__ != runtime["numpy"] or
                version("opencv-python-headless") != runtime["opencv_python_headless"]):
            raise ValueError("installed oracle runtime differs from manifest")
        self.session = ort.InferenceSession(str(model_path), providers=[runtime["provider"]])
        if self.session.get_providers() != [runtime["provider"]]:
            raise ValueError("runtime provider differs from manifest")
        for key, tensors in (("input", self.session.get_inputs()), ("output", self.session.get_outputs())):
            expected = self._manifest[key]
            if len(tensors) != 1 or tensors[0].name != expected["name"] or tensors[0].shape != expected["shape"] or tensors[0].type != "tensor(float)":
                raise ValueError("model tensor contract differs from manifest")
        config = {key: self._manifest[key] for key in ("input", "output", "labels", "preprocess", "postprocess", "runtime")}
        self._provenance = dict(model_id=self._manifest["model_id"],
                               model_sha256=self._manifest["artifact"]["sha256"],
                               config_sha256=hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                               runtime=dict(name="onnxruntime", version=ort.__version__),
                               provider=self.session.get_providers()[0])

    def detect(self, rgb: "np.ndarray", frame: dict[str, Any]) -> dict[str, Any]:
        import cv2
        import numpy as np

        fields = ("camera_id", "stream_session_id", "core_epoch", "origin", "frame_id", "pts", "time_base", "event_time")
        metadata = {name: frame.get(name) for name in fields} if isinstance(frame, dict) else {}
        result: dict[str, Any] = dict(schema_version=1, **metadata, detection_status="failed", detections=[],
                      transform=None, provenance=deepcopy(self._provenance),
                      timings=dict(preprocess_ms=0.0, inference_ms=0.0, postprocess_ms=0.0), error=None)
        try:
            if not isinstance(frame, dict) or any(name not in frame for name in fields):
                raise ValueError("missing frame lineage metadata")
            if any(not isinstance(frame[name], str) or not frame[name] for name in ("camera_id", "stream_session_id")):
                raise ValueError("camera and stream session must be nonempty strings")
            if frame["origin"] != "replay":
                raise ValueError("oracle accepts replay lineage only")
            if any(type(frame[name]) is not int for name in ("core_epoch", "frame_id", "pts")) or frame["core_epoch"] < 1 or frame["frame_id"] < 0:
                raise ValueError("invalid frame integer metadata")
            if not isinstance(frame["time_base"], str) or Fraction(frame["time_base"]) <= 0:
                raise ValueError("time_base must be a positive rational string")
            if type(frame["event_time"]) not in (int, float) or not math.isfinite(frame["event_time"]):
                raise ValueError("event_time must be finite")
            if frame["event_time"] != float(frame["pts"] * Fraction(frame["time_base"])):
                raise ValueError("event_time must equal source PTS time")
            if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) <= 0:
                raise ValueError("rgb must be nonempty uint8 HWC RGB")
            started = perf_counter()
            height, width = rgb.shape[:2]
            model_height, model_width = self._manifest["input"]["shape"][2:]
            scale = min(model_height / height, model_width / width)
            resized = cv2.resize(rgb[:, :, ::-1], (int(width * scale), int(height * scale)), interpolation=cv2.INTER_LINEAR)
            config = self._manifest["preprocess"]
            padded = np.full((model_height, model_width, 3), config["pad_value"], dtype=np.uint8)
            padded[:resized.shape[0], :resized.shape[1]] = resized.astype(np.float32)
            tensor = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32)
            result["transform"] = dict(original_size=[height, width], model_size=[model_height, model_width], scale=scale, pad=[0, 0])
            result["timings"]["preprocess_ms"] = (perf_counter() - started) * 1000
            started = perf_counter()
            raw = self.session.run([self._manifest["output"]["name"]], {self._manifest["input"]["name"]: tensor})[0]
            result["timings"]["inference_ms"] = (perf_counter() - started) * 1000
            started = perf_counter()
            if raw.shape != tuple(self._manifest["output"]["shape"]) or raw.dtype != np.float32 or not np.isfinite(raw).all():
                raise ValueError("invalid nonfinite or malformed model output")
            if np.any(raw[..., 4:] < 0) or np.any(raw[..., 4:] > 1):
                raise ValueError("model probabilities outside [0,1]")
            predictions = raw[0].copy()
            offset = 0
            config = self._manifest["postprocess"]
            for stride in config["strides"]:
                rows, columns = model_height // stride, model_width // stride
                x, y = np.meshgrid(np.arange(columns), np.arange(rows))
                count = rows * columns
                chunk = predictions[offset:offset + count]
                chunk[:, :2] = (chunk[:, :2] + np.stack((x, y), axis=2).reshape(-1, 2)) * stride
                chunk[:, 2:4] = np.exp(chunk[:, 2:4]) * stride
                offset += count
            if not np.isfinite(predictions).all() or np.any(predictions[:, 2:4] <= 0):
                raise ValueError("invalid decoded model geometry")
            boxes = np.concatenate((predictions[:, :2] - predictions[:, 2:4] / 2,
                                    predictions[:, :2] + predictions[:, 2:4] / 2), axis=1) / scale
            scores = predictions[:, 4:5] * predictions[:, 5:]
            for class_id, label in enumerate(self._manifest["labels"]):
                candidates = np.flatnonzero(scores[:, class_id] > config["candidate_threshold"])
                order = candidates[np.argsort(scores[candidates, class_id])[::-1]]
                while order.size:
                    index = order[0]
                    if scores[index, class_id] >= config["confidence_threshold"]:
                        clipped = boxes[index].copy()
                        clipped[[0, 2]] = np.clip(clipped[[0, 2]], 0, width)
                        clipped[[1, 3]] = np.clip(clipped[[1, 3]], 0, height)
                        result["detections"].append(dict(class_id=class_id, label=label,
                                                         score=float(scores[index, class_id]), bbox_xyxy=clipped.tolist()))
                    rest = order[1:]
                    intersection = np.maximum(0, np.minimum(boxes[index, 2:], boxes[rest, 2:]) -
                                              np.maximum(boxes[index, :2], boxes[rest, :2]) + 1)
                    intersection = intersection[:, 0] * intersection[:, 1]
                    area = np.prod(boxes[index, 2:] - boxes[index, :2] + 1)
                    areas = np.prod(boxes[rest, 2:] - boxes[rest, :2] + 1, axis=1)
                    iou = intersection / (area + areas - intersection)
                    order = rest[iou <= config["nms_threshold"]]
            result["detections"].sort(key=lambda item: (-item["score"], item["class_id"], *item["bbox_xyxy"]))
            result["detection_status"] = "ok" if result["detections"] else "ok_empty"
            result["timings"]["postprocess_ms"] = (perf_counter() - started) * 1000
            return result
        except Exception as exc:
            result.update(detection_status="failed", detections=[], error=dict(type=type(exc).__name__, message=str(exc)))
            return result
