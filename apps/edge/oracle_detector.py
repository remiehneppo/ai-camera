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


class OnnxDetector:
    accepted_origins: tuple[str, ...] = ()
    def __init__(self, manifest_path: str | Path, model_path: str | Path, *, environment: str = "lab",
                 expected_artifact: dict[str, Any] | None = None,
                 providers: list[str] | None = None,
                 strict_runtime: bool = True,
                 allow_custom_manifest: bool = False) -> None:
        from domain.model_manifest import load_civiwatch_manifest, load_manifest
        import onnxruntime as ort  # type: ignore[import-untyped]

        try:
            if allow_custom_manifest or environment == "civiwatch":
                self._manifest = load_civiwatch_manifest(manifest_path, model_path)
            else:
                self._manifest = load_manifest(manifest_path, model_path, environment=environment,
                                               expected_artifact=expected_artifact)
        except (KeyError, TypeError) as exc:
            raise ValueError("invalid model manifest") from exc
        if self._manifest.get("schema_version") != 1:
            raise ValueError("unsupported model manifest schema")
        import numpy as np
        from importlib.metadata import version

        runtime = self._manifest.get("runtime", {})
        if strict_runtime and runtime:
            if (
                ort.__version__ != runtime.get("onnxruntime", ort.__version__)
                or np.__version__ != runtime.get("numpy", np.__version__)
                or version("opencv-python-headless") != runtime.get("opencv_python_headless", version("opencv-python-headless"))
            ):
                raise ValueError("installed oracle runtime differs from manifest")
        default_provider = runtime.get("provider", "CPUExecutionProvider")
        requested_providers = providers or [default_provider]
        self.session = ort.InferenceSession(str(model_path), providers=requested_providers)
        if strict_runtime and providers is None and self.session.get_providers() != [default_provider]:
            raise ValueError("runtime provider differs from manifest")
        for key, tensors in (("input", self.session.get_inputs()), ("output", self.session.get_outputs())):
            expected = self._manifest[key]
            if len(tensors) != 1 or tensors[0].name != expected["name"] or tensors[0].shape != expected["shape"] or tensors[0].type != "tensor(float)":
                raise ValueError("model tensor contract differs from manifest")
        config = {key: self._manifest[key] for key in ("input", "output", "labels", "preprocess", "postprocess", "runtime") if key in self._manifest}
        self._provenance = dict(model_id=self._manifest["model_id"],
                               model_sha256=self._manifest["artifact"]["sha256"],
                               config_sha256=hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                               runtime=dict(name="onnxruntime", version=ort.__version__),
                               provider=self.session.get_providers()[0])
        # Precompute YOLOX stride grids if using yolox_grid postprocessing
        self.decode_mode = self._manifest.get("postprocess", {}).get("decode", "yolox_grid")
        model_height, model_width = self._manifest["input"]["shape"][2:]
        if self.decode_mode == "yolox_grid" and "strides" in self._manifest.get("postprocess", {}):
            xy_parts = []
            stride_parts = []
            for stride in self._manifest["postprocess"]["strides"]:
                rows, columns = model_height // stride, model_width // stride
                x, y = np.meshgrid(np.arange(columns, dtype=np.float32), np.arange(rows, dtype=np.float32))
                xy_parts.append(np.stack((x, y), axis=2).reshape(-1, 2))
                stride_parts.append(np.full((rows * columns, 1), float(stride), dtype=np.float32))
            self._grid_xy = np.concatenate(xy_parts, axis=0)
            self._grid_strides = np.concatenate(stride_parts, axis=0)
        else:
            self._grid_xy = np.empty((0, 2), dtype=np.float32)
            self._grid_strides = np.empty((0, 1), dtype=np.float32)

    @property
    def provenance(self):
        return deepcopy(self._provenance)

    def detect(self, rgb: "np.ndarray", frame: dict[str, Any]) -> dict[str, Any]:
        import cv2
        import numpy as np

        fields = ("camera_id", "stream_session_id", "core_epoch", "origin", "frame_id", "pts", "time_base", "event_time")
        metadata = {name: frame.get(name) for name in fields} if isinstance(frame, dict) else {}
        if isinstance(frame, dict) and "clock_domain" in frame:
            metadata["clock_domain"] = frame["clock_domain"]
        result: dict[str, Any] = dict(schema_version=1, **metadata, detection_status="failed", detections=[],
                      transform=None, provenance=deepcopy(self._provenance),
                      timings=dict(preprocess_ms=0.0, inference_ms=0.0, postprocess_ms=0.0), error=None)
        try:
            if not isinstance(frame, dict) or any(name not in frame for name in fields):
                raise ValueError("missing frame lineage metadata")
            if any(not isinstance(frame[name], str) or not frame[name] for name in ("camera_id", "stream_session_id")):
                raise ValueError("camera and stream session must be nonempty strings")
            if frame["origin"] not in self.accepted_origins:
                raise ValueError("detector does not support this source origin")
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
            config = self._manifest.get("preprocess", {})
            input_color = config.get("color", "BGR")
            src_pixels = rgb if input_color == "RGB" else rgb[:, :, ::-1]
            resized = cv2.resize(src_pixels, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_LINEAR)
            padded = np.full((model_height, model_width, 3), config.get("pad_value", 114), dtype=np.uint8)
            padded[:resized.shape[0], :resized.shape[1]] = resized
            scale_factor = float(config.get("scale", 1.0))
            tensor = np.ascontiguousarray((padded.astype(np.float32) * scale_factor).transpose(2, 0, 1)[None], dtype=np.float32)
            result["transform"] = dict(original_size=[height, width], model_size=[model_height, model_width], scale=scale, pad=[0, 0])
            result["timings"]["preprocess_ms"] = (perf_counter() - started) * 1000
            started = perf_counter()
            raw = self.session.run([self._manifest["output"]["name"]], {self._manifest["input"]["name"]: tensor})[0]
            result["timings"]["inference_ms"] = (perf_counter() - started) * 1000
            started = perf_counter()
            if raw.shape != tuple(self._manifest["output"]["shape"]) or raw.dtype != np.float32 or not np.isfinite(raw).all():
                raise ValueError("invalid nonfinite or malformed model output")
            predictions = raw[0].copy()
            config = self._manifest.get("postprocess", {})
            labels = self._manifest["labels"]

            if self.decode_mode == "nms_free":
                if np.any(raw[..., 4:5] < 0) or np.any(raw[..., 4:5] > 1):
                    raise ValueError("model probabilities outside [0,1]")
                conf_thresh = config.get("confidence_threshold", 0.25)
                # NMS-free direct predictions: [N, 6] -> [x1, y1, x2, y2, score, class_id]
                for pred in predictions:
                    if len(pred) < 6:
                        continue
                    score = float(pred[4])
                    if score >= conf_thresh:
                        cid = int(round(float(pred[5])))
                        if 0 <= cid < len(labels):
                            lbl = labels[cid]
                            bx = pred[:4] / scale
                            clipped_box = [
                                float(np.clip(bx[0], 0, width)),
                                float(np.clip(bx[1], 0, height)),
                                float(np.clip(bx[2], 0, width)),
                                float(np.clip(bx[3], 0, height)),
                            ]
                            result["detections"].append(
                                dict(class_id=cid, label=lbl, score=round(score, 4), bbox_xyxy=clipped_box)
                            )
            else:
                if np.any(raw[..., 4:] < 0) or np.any(raw[..., 4:] > 1):
                    raise ValueError("model probabilities outside [0,1]")
                predictions[:, :2] = (predictions[:, :2] + self._grid_xy) * self._grid_strides
                predictions[:, 2:4] = np.exp(predictions[:, 2:4]) * self._grid_strides
                if not np.isfinite(predictions).all() or np.any(predictions[:, 2:4] <= 0):
                    raise ValueError("invalid decoded model geometry")
                boxes = np.concatenate((predictions[:, :2] - predictions[:, 2:4] / 2,
                                        predictions[:, :2] + predictions[:, 2:4] / 2), axis=1) / scale
                scores = predictions[:, 4:5] * predictions[:, 5:]
                cand_thresh = config["candidate_threshold"]
                conf_thresh = config["confidence_threshold"]
                nms_thresh = config["nms_threshold"]
                active_classes = np.flatnonzero(np.max(scores, axis=0) > cand_thresh)
                for class_id_np in active_classes:
                    class_id = int(class_id_np)
                    label = labels[class_id]
                    candidates = np.flatnonzero(scores[:, class_id] > cand_thresh)
                    order = candidates[np.argsort(scores[candidates, class_id])[::-1]]
                    while order.size:
                        index = order[0]
                        if scores[index, class_id] >= conf_thresh:
                            clipped = boxes[index].copy()
                            clipped[[0, 2]] = np.clip(clipped[[0, 2]], 0, width)
                            clipped[[1, 3]] = np.clip(clipped[[1, 3]], 0, height)
                            result["detections"].append(dict(class_id=class_id, label=label,
                                                             score=float(scores[index, class_id]), bbox_xyxy=clipped.tolist()))
                        rest = order[1:]
                        if not rest.size:
                            break
                        intersection = np.maximum(0, np.minimum(boxes[index, 2:], boxes[rest, 2:]) -
                                                  np.maximum(boxes[index, :2], boxes[rest, :2]) + 1)
                        intersection = intersection[:, 0] * intersection[:, 1]
                        area = np.prod(boxes[index, 2:] - boxes[index, :2] + 1)
                        areas = np.prod(boxes[rest, 2:] - boxes[rest, :2] + 1, axis=1)
                        iou = intersection / (area + areas - intersection)
                        order = rest[iou <= nms_thresh]
            result["detections"].sort(key=lambda item: (-item["score"], item["class_id"], *item["bbox_xyxy"]))
            result["detection_status"] = "ok" if result["detections"] else "ok_empty"
            result["timings"]["postprocess_ms"] = (perf_counter() - started) * 1000
            return result
        except Exception as exc:
            result.update(detection_status="failed", detections=[], error=dict(type=type(exc).__name__, message=str(exc)))
            return result


class OracleDetector(OnnxDetector):
    """Reference adapter: replay lineage only."""
    accepted_origins = ("replay",)


class LiveDetector(OnnxDetector):
    """Live adapter sharing the pinned ONNX inference implementation."""
    accepted_origins = ("live",)


class CiviWatchDetector(OnnxDetector):
    """General CiviWatch multi-resolution (416x416 / 640x640 / NMS-free) detector supporting all origins."""
    accepted_origins = ("live", "replay", "synthetic")

    def __init__(self, manifest_path: str | Path, model_path: str | Path, **kwargs: Any) -> None:
        kwargs.setdefault("allow_custom_manifest", True)
        kwargs.setdefault("environment", "civiwatch")
        super().__init__(manifest_path, model_path, **kwargs)
