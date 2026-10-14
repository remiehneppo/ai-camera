"""RTMPose estimation and Pose Request lifecycle management.

Follows integration contracts (docs/architecture/contracts.md):
- Exact affine transform to 192x256 and SimCC decoding (split_ratio=2.0).
- 17 COCO keypoints mapped back to original image coordinates.
- Pose request lifecycle: request ID, camera, session, epoch, frame, track, deadline, clock domain.
- Bounded request queue and frame buffer cache.
- Single terminal outcome for every request: ok, skipped, failed, or cancelled, with explicit reason.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PoseRequest:
    """Pose request carrying association lineage, bbox, deadline and clock domain."""

    request_id: str
    camera_id: str
    stream_session_id: str
    core_epoch: int
    frame_id: int
    bbox: list[float]
    deadline: float
    track_id: int | None = None
    clock_domain: str = "event_time"
    created_at: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PoseRequest:
        bbox_raw = data.get("bbox") or data.get("bbox_xyxy")
        if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) != 4:
            raise ValueError("pose request must contain 4-element bbox")
        return cls(
            request_id=str(data["request_id"]),
            camera_id=str(data["camera_id"]),
            stream_session_id=str(data["stream_session_id"]),
            core_epoch=int(data["core_epoch"]),
            frame_id=int(data["frame_id"]),
            bbox=[float(v) for v in bbox_raw],
            deadline=float(data["deadline"]),
            track_id=int(data["track_id"]) if data.get("track_id") is not None else None,
            clock_domain=str(data.get("clock_domain", "event_time")),
            created_at=float(data.get("created_at", time.time())),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PoseOutcome:
    """Terminal outcome for an accepted pose request."""

    request_id: str
    camera_id: str
    stream_session_id: str
    core_epoch: int
    frame_id: int
    status: str  # "ok" | "skipped" | "failed" | "cancelled"
    track_id: int | None = None
    reason: str | None = None
    keypoints: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float | None = None
    executed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RtmposeEstimator:
    """RTMPose model inference with affine transform and SimCC coordinate decoding."""

    # Standard ImageNet normalization for RGB input
    IMAGENET_MEAN = np.array([123.675, 116.28, 103.53], dtype=np.float32)
    IMAGENET_STD = np.array([58.395, 57.12, 57.375], dtype=np.float32)

    def __init__(
        self,
        manifest_path: str | Path = "models/rtmpose-tiny/manifest.json",
        model_path: str | Path = "models/rtmpose-tiny/rtmpose_tiny.onnx",
        providers: list[str] | None = None,
    ) -> None:
        import onnxruntime as ort  # type: ignore[import-untyped]

        manifest_file = Path(manifest_path)
        model_file = Path(model_path)

        if not manifest_file.is_file():
            raise FileNotFoundError(f"Manifest file not found: {manifest_file}")
        if not model_file.is_file():
            raise FileNotFoundError(f"Model file not found: {model_file}")

        with open(manifest_file, "r", encoding="utf-8") as f:
            self.manifest: dict[str, Any] = json.load(f)

        # Verify artifact hash if specified in manifest
        expected_sha = self.manifest.get("sha256")
        if expected_sha:
            actual_sha = hashlib.sha256(model_file.read_bytes()).hexdigest()
            if actual_sha != expected_sha:
                raise ValueError(
                    f"Model artifact sha256 mismatch: expected {expected_sha}, got {actual_sha}"
                )

        # Target input shape: [batch, 3, height, width] -> [batch, 3, 256, 192]
        input_size = self.manifest.get("input_size", [256, 192])
        self.input_height = int(input_size[0])
        self.input_width = int(input_size[1])
        self.simcc_split_ratio = float(self.manifest.get("simcc_split_ratio", 2.0))
        self.num_keypoints = int(self.manifest.get("num_keypoints", 17))
        self.keypoint_labels: list[str] = list(self.manifest.get("keypoint_labels", []))

        sess_providers = providers or ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(str(model_file), providers=sess_providers)
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]

    def preprocess(
        self, rgb: np.ndarray, bbox: list[float] | tuple[float, ...]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Crop and warp ROI with TopDownAffine transform to (192, 256), normalizing with ImageNet mean/std."""
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        w = max(0.0, x2 - x1)
        h = max(0.0, y2 - y1)
        if w <= 0.0 or h <= 0.0:
            raise ValueError(f"Invalid bounding box dimensions: w={w}, h={h}")

        center = np.array([(x1 + x2) * 0.5, (y1 + y2) * 0.5], dtype=np.float32)
        scale = np.array([w, h], dtype=np.float32) * 1.25

        aspect_ratio = float(self.input_width) / float(self.input_height)  # 192 / 256 = 0.75
        if scale[0] > aspect_ratio * scale[1]:
            scale[1] = scale[0] / aspect_ratio
        else:
            scale[0] = scale[1] * aspect_ratio

        # 3-point affine transformation
        src = np.zeros((3, 2), dtype=np.float32)
        src[0, :] = center
        src[1, :] = center + np.array([0, -0.5 * scale[1]], dtype=np.float32)
        src[2, :] = center + np.array([0.5 * scale[0], 0], dtype=np.float32)

        dst = np.zeros((3, 2), dtype=np.float32)
        dst[0, :] = [self.input_width * 0.5, self.input_height * 0.5]
        dst[1, :] = [self.input_width * 0.5, 0.0]
        dst[2, :] = [float(self.input_width), self.input_height * 0.5]

        trans = cv2.getAffineTransform(src, dst)
        inv_trans = cv2.getAffineTransform(dst, src)

        warped = cv2.warpAffine(
            rgb, trans, (self.input_width, self.input_height), flags=cv2.INTER_LINEAR
        )

        norm = (warped.astype(np.float32) - self.IMAGENET_MEAN) / self.IMAGENET_STD
        tensor = np.transpose(norm, (2, 0, 1))[None, ...]
        return tensor, inv_trans

    def decode_simcc(
        self, simcc_x: np.ndarray, simcc_y: np.ndarray, inv_trans: np.ndarray
    ) -> list[dict[str, Any]]:
        """Decode SimCC heatmaps (split_ratio=2.0) and map back to original frame coordinates."""
        # simcc_x: [K, Wx] (e.g. 17, 384), simcc_y: [K, Wy] (e.g. 17, 512)
        x_locs = np.argmax(simcc_x, axis=-1).astype(np.float32) / self.simcc_split_ratio
        y_locs = np.argmax(simcc_y, axis=-1).astype(np.float32) / self.simcc_split_ratio

        max_val_x = np.max(simcc_x, axis=-1)
        max_val_y = np.max(simcc_y, axis=-1)
        scores = np.maximum(max_val_x, max_val_y)

        # Invert affine transform back to original image space
        pts = np.stack([x_locs, y_locs], axis=-1)  # [K, 2]
        orig_pts = cv2.transform(pts[None, ...], inv_trans)[0]

        num_kps = len(scores)
        keypoints: list[dict[str, Any]] = []
        for i in range(num_kps):
            name = self.keypoint_labels[i] if i < len(self.keypoint_labels) else f"kp_{i}"
            keypoints.append(
                {
                    "name": name,
                    "x": float(orig_pts[i, 0]),
                    "y": float(orig_pts[i, 1]),
                    "score": float(np.clip(scores[i], 0.0, 1.0)),
                }
            )
        return keypoints

    def estimate(
        self, rgb: np.ndarray, bbox: list[float] | tuple[float, ...]
    ) -> list[dict[str, Any]]:
        """Run RTMPose estimation on an image bounding box."""
        tensor, inv_trans = self.preprocess(rgb, bbox)
        outputs = self.session.run(self.output_names, {self.input_name: tensor})
        simcc_x = outputs[0][0]
        simcc_y = outputs[1][0]
        return self.decode_simcc(simcc_x, simcc_y, inv_trans)


class PoseManager:
    """Manages pose request queuing, buffer caching, deadlines, epochs and terminal outcomes."""

    def __init__(
        self,
        estimator: RtmposeEstimator | None = None,
        max_queue_size: int = 64,
        max_cached_frames: int = 30,
    ) -> None:
        self.estimator = estimator
        self.max_queue_size = max_queue_size
        self.max_cached_frames = max_cached_frames
        self.current_epoch: int = 1

        self._lock = threading.Lock()
        # Key: (camera_id, stream_session_id, core_epoch, frame_id) -> np.ndarray
        self._frame_cache: OrderedDict[tuple[str, str, int, int], np.ndarray] = OrderedDict()
        self._request_queue: deque[PoseRequest] = deque()
        self._terminal_outcomes: deque[PoseOutcome] = deque(maxlen=max_queue_size * 4)

    def cache_frame(
        self,
        camera_id: str,
        stream_session_id: str,
        core_epoch: int,
        frame_id: int,
        rgb: np.ndarray,
    ) -> None:
        """Cache decoded frame RGB for late/asynchronous pose evaluation."""
        key = (camera_id, stream_session_id, core_epoch, frame_id)
        with self._lock:
            if key in self._frame_cache:
                self._frame_cache.move_to_end(key)
                return
            if len(self._frame_cache) >= self.max_cached_frames:
                self._frame_cache.popitem(last=False)
            self._frame_cache[key] = rgb

    def set_epoch(self, new_epoch: int) -> list[PoseOutcome]:
        """Epoch invalidation: cancels outstanding requests from older epochs with epoch_mismatch."""
        with self._lock:
            self.current_epoch = new_epoch
            cancelled_outcomes: list[PoseOutcome] = []
            remaining_requests: deque[PoseRequest] = deque()

            while self._request_queue:
                req = self._request_queue.popleft()
                if req.core_epoch < new_epoch:
                    outcome = PoseOutcome(
                        request_id=req.request_id,
                        camera_id=req.camera_id,
                        stream_session_id=req.stream_session_id,
                        core_epoch=req.core_epoch,
                        frame_id=req.frame_id,
                        track_id=req.track_id,
                        status="cancelled",
                        reason="epoch_mismatch",
                        executed_at=time.time(),
                    )
                    self._terminal_outcomes.append(outcome)
                    cancelled_outcomes.append(outcome)
                else:
                    remaining_requests.append(req)

            self._request_queue = remaining_requests
            return cancelled_outcomes

    def submit_request(self, request: PoseRequest | dict[str, Any]) -> bool:
        """Enqueue pose request if within capacity, otherwise emit 'skipped' ('queue_full')."""
        req = PoseRequest.from_dict(request) if isinstance(request, dict) else request

        with self._lock:
            # Check epoch immediately
            if req.core_epoch < self.current_epoch:
                outcome = PoseOutcome(
                    request_id=req.request_id,
                    camera_id=req.camera_id,
                    stream_session_id=req.stream_session_id,
                    core_epoch=req.core_epoch,
                    frame_id=req.frame_id,
                    track_id=req.track_id,
                    status="cancelled",
                    reason="epoch_mismatch",
                    executed_at=time.time(),
                )
                self._terminal_outcomes.append(outcome)
                return False

            if len(self._request_queue) >= self.max_queue_size:
                outcome = PoseOutcome(
                    request_id=req.request_id,
                    camera_id=req.camera_id,
                    stream_session_id=req.stream_session_id,
                    core_epoch=req.core_epoch,
                    frame_id=req.frame_id,
                    track_id=req.track_id,
                    status="skipped",
                    reason="queue_full",
                    executed_at=time.time(),
                )
                self._terminal_outcomes.append(outcome)
                return False

            self._request_queue.append(req)
            return True

    def process_pending(self, current_time: float) -> list[PoseOutcome]:
        """Drain and process queued requests evaluating deadline, cache existence, and estimation."""
        with self._lock:
            requests_to_process = list(self._request_queue)
            self._request_queue.clear()

        outcomes: list[PoseOutcome] = []
        for req in requests_to_process:
            start_t = time.perf_counter()

            # 1. Epoch check
            if req.core_epoch < self.current_epoch:
                outcome = PoseOutcome(
                    request_id=req.request_id,
                    camera_id=req.camera_id,
                    stream_session_id=req.stream_session_id,
                    core_epoch=req.core_epoch,
                    frame_id=req.frame_id,
                    track_id=req.track_id,
                    status="cancelled",
                    reason="epoch_mismatch",
                    executed_at=time.time(),
                )
                outcomes.append(outcome)
                continue

            # 2. Deadline check
            if current_time > req.deadline:
                outcome = PoseOutcome(
                    request_id=req.request_id,
                    camera_id=req.camera_id,
                    stream_session_id=req.stream_session_id,
                    core_epoch=req.core_epoch,
                    frame_id=req.frame_id,
                    track_id=req.track_id,
                    status="skipped",
                    reason="deadline_exceeded",
                    executed_at=time.time(),
                )
                outcomes.append(outcome)
                continue

            # 3. Frame buffer lookup
            key = (req.camera_id, req.stream_session_id, req.core_epoch, req.frame_id)
            with self._lock:
                frame_rgb = self._frame_cache.get(key)

            if frame_rgb is None:
                outcome = PoseOutcome(
                    request_id=req.request_id,
                    camera_id=req.camera_id,
                    stream_session_id=req.stream_session_id,
                    core_epoch=req.core_epoch,
                    frame_id=req.frame_id,
                    track_id=req.track_id,
                    status="skipped",
                    reason="frame_buffer_expired",
                    executed_at=time.time(),
                )
                outcomes.append(outcome)
                continue

            # 4. Estimation
            if self.estimator is None:
                outcome = PoseOutcome(
                    request_id=req.request_id,
                    camera_id=req.camera_id,
                    stream_session_id=req.stream_session_id,
                    core_epoch=req.core_epoch,
                    frame_id=req.frame_id,
                    track_id=req.track_id,
                    status="failed",
                    reason="estimator_unavailable",
                    executed_at=time.time(),
                )
                outcomes.append(outcome)
                continue

            try:
                kps = self.estimator.estimate(frame_rgb, req.bbox)
                latency = (time.perf_counter() - start_t) * 1000.0
                outcome = PoseOutcome(
                    request_id=req.request_id,
                    camera_id=req.camera_id,
                    stream_session_id=req.stream_session_id,
                    core_epoch=req.core_epoch,
                    frame_id=req.frame_id,
                    track_id=req.track_id,
                    status="ok",
                    reason=None,
                    keypoints=kps,
                    latency_ms=latency,
                    executed_at=time.time(),
                )
            except Exception as exc:
                outcome = PoseOutcome(
                    request_id=req.request_id,
                    camera_id=req.camera_id,
                    stream_session_id=req.stream_session_id,
                    core_epoch=req.core_epoch,
                    frame_id=req.frame_id,
                    track_id=req.track_id,
                    status="failed",
                    reason=str(exc),
                    executed_at=time.time(),
                )
            outcomes.append(outcome)

        with self._lock:
            self._terminal_outcomes.extend(outcomes)
        return outcomes

    def request_pose(
        self,
        request: PoseRequest | dict[str, Any],
        rgb: np.ndarray | None = None,
        current_time: float | None = None,
    ) -> PoseOutcome:
        """Synchronously evaluate a pose request immediately."""
        req = PoseRequest.from_dict(request) if isinstance(request, dict) else request
        eval_time = current_time if current_time is not None else time.time()
        start_t = time.perf_counter()

        # Epoch check
        if req.core_epoch < self.current_epoch:
            outcome = PoseOutcome(
                request_id=req.request_id,
                camera_id=req.camera_id,
                stream_session_id=req.stream_session_id,
                core_epoch=req.core_epoch,
                frame_id=req.frame_id,
                track_id=req.track_id,
                status="cancelled",
                reason="epoch_mismatch",
                executed_at=time.time(),
            )
            with self._lock:
                self._terminal_outcomes.append(outcome)
            return outcome

        # Deadline check
        if eval_time > req.deadline:
            outcome = PoseOutcome(
                request_id=req.request_id,
                camera_id=req.camera_id,
                stream_session_id=req.stream_session_id,
                core_epoch=req.core_epoch,
                frame_id=req.frame_id,
                track_id=req.track_id,
                status="skipped",
                reason="deadline_exceeded",
                executed_at=time.time(),
            )
            with self._lock:
                self._terminal_outcomes.append(outcome)
            return outcome

        # Frame resolution
        frame_rgb = rgb
        if frame_rgb is None:
            key = (req.camera_id, req.stream_session_id, req.core_epoch, req.frame_id)
            with self._lock:
                frame_rgb = self._frame_cache.get(key)

        if frame_rgb is None:
            outcome = PoseOutcome(
                request_id=req.request_id,
                camera_id=req.camera_id,
                stream_session_id=req.stream_session_id,
                core_epoch=req.core_epoch,
                frame_id=req.frame_id,
                track_id=req.track_id,
                status="skipped",
                reason="frame_buffer_expired",
                executed_at=time.time(),
            )
            with self._lock:
                self._terminal_outcomes.append(outcome)
            return outcome

        if self.estimator is None:
            outcome = PoseOutcome(
                request_id=req.request_id,
                camera_id=req.camera_id,
                stream_session_id=req.stream_session_id,
                core_epoch=req.core_epoch,
                frame_id=req.frame_id,
                track_id=req.track_id,
                status="failed",
                reason="estimator_unavailable",
                executed_at=time.time(),
            )
            with self._lock:
                self._terminal_outcomes.append(outcome)
            return outcome

        try:
            kps = self.estimator.estimate(frame_rgb, req.bbox)
            latency = (time.perf_counter() - start_t) * 1000.0
            outcome = PoseOutcome(
                request_id=req.request_id,
                camera_id=req.camera_id,
                stream_session_id=req.stream_session_id,
                core_epoch=req.core_epoch,
                frame_id=req.frame_id,
                track_id=req.track_id,
                status="ok",
                reason=None,
                keypoints=kps,
                latency_ms=latency,
                executed_at=time.time(),
            )
        except Exception as exc:
            outcome = PoseOutcome(
                request_id=req.request_id,
                camera_id=req.camera_id,
                stream_session_id=req.stream_session_id,
                core_epoch=req.core_epoch,
                frame_id=req.frame_id,
                track_id=req.track_id,
                status="failed",
                reason=str(exc),
                executed_at=time.time(),
            )

        with self._lock:
            self._terminal_outcomes.append(outcome)
        return outcome

    def poll_terminal_outcomes(self) -> list[PoseOutcome]:
        """Retrieve and drain all settled terminal outcomes."""
        with self._lock:
            outcomes = list(self._terminal_outcomes)
            self._terminal_outcomes.clear()
            return outcomes

    def queued_count(self) -> int:
        """Count outstanding requests in queue."""
        with self._lock:
            return len(self._request_queue)
