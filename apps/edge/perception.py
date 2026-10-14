"""Shared observation execution and lineage validation, without incident state."""
from copy import deepcopy
from fractions import Fraction
import math
import threading

from apps.edge.oracle_detector import LiveDetector, OracleDetector


class PerceptionExecution:
    def __init__(self, detector=None, *, manifest_path=None, model_path=None, origin="replay"):
        if detector is None and manifest_path and model_path:
            adapter = LiveDetector if origin == "live" else OracleDetector
            detector = adapter(manifest_path, model_path)
        self.detector = detector
        self._lock = threading.Lock()
        self._cached_frame = None
        self._cached_result = None

    @property
    def provenance(self):
        return deepcopy(getattr(self.detector, "provenance", {}))

    @staticmethod
    def frame(camera_id, session_id, epoch, origin, frame_id, timestamp):
        if not math.isfinite(timestamp):
            raise ValueError("frame timestamp must be finite")
        pts = round(timestamp * 1_000_000)
        return dict(camera_id=camera_id, stream_session_id=session_id, core_epoch=epoch,
                    origin=origin, frame_id=frame_id, pts=pts, time_base="1/1000000",
                    event_time=float(pts * Fraction("1/1000000")))

    def execute(self, rgb, frame, *, detections=None, status=None):
        result = dict(frame, schema_version=1, detection_status="failed", detections=[],
                      provenance=self.provenance, error=None)
        try:
            if (not frame["camera_id"] or not frame["stream_session_id"] or
                type(frame["core_epoch"]) is not int or frame["core_epoch"] < 1 or
                type(frame["frame_id"]) is not int or frame["frame_id"] < 0 or
                frame["origin"] not in {"live", "replay", "synthetic"} or
                type(frame["pts"]) is not int or Fraction(frame["time_base"]) <= 0 or
                not math.isfinite(frame["event_time"]) or
                frame["event_time"] != float(frame["pts"] * Fraction(frame["time_base"]))):
                raise ValueError("invalid observation lineage")
            if status is not None and status not in {"ok", "ok_empty", "failed", "missing", "stale", "skipped"}:
                raise ValueError("invalid detection status")
            if status in {"failed", "missing", "stale", "skipped"}:
                return {**result, "detection_status": status}
            if detections is not None:
                if status == "ok_empty" and detections:
                    raise ValueError("ok_empty observation contains detections")
                result.update(detections=deepcopy(detections), detection_status="ok" if detections else "ok_empty")
            elif self.detector is None:
                return {**result, "detection_status": "missing", "error": "detector unavailable"}
            else:
                with self._lock:
                    if frame == self._cached_frame:
                        observed = deepcopy(self._cached_result)
                    else:
                        observed = self.detector.detect(rgb, frame)
                        self._cached_frame = deepcopy(frame)
                        self._cached_result = deepcopy(observed)
                if any(observed.get(k) != v for k, v in frame.items()):
                    raise ValueError("detector changed observation lineage")
                result.update(observed)
            if result["detection_status"] not in {"ok", "ok_empty", "failed", "missing", "stale", "skipped"}:
                raise ValueError("invalid detector status")
            if result["detection_status"] not in {"ok", "ok_empty"}:
                result["detections"] = []
                return result
            normalized = []
            for det in result["detections"]:
                bbox = det.get("bbox_xyxy", det.get("bbox"))
                score = det.get("score", 0.0)
                if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or
                    not all(type(v) in (int, float) and math.isfinite(v) for v in bbox) or
                    bbox[2] <= bbox[0] or bbox[3] <= bbox[1] or
                    type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1):
                    raise ValueError("invalid detection geometry or score")
                normalized.append({**det, "bbox": list(bbox), "bbox_xyxy": list(bbox),
                                   "score": float(score), "label": str(det.get("label", "person"))})
            if result["detection_status"] == "ok_empty" and normalized:
                raise ValueError("ok_empty observation contains detections")
            result.update(detections=normalized, detection_status="ok" if normalized else "ok_empty")
        except Exception as exc:
            result.update(detection_status="failed", detections=[], error=str(exc))
        return result
