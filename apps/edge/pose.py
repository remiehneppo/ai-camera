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

from apps.edge.tracker import Track

logger = logging.getLogger(__name__)


@dataclass
class BranchMetrics:
    """Metrics tracking for a single pose scheduling branch."""

    scheduled: int = 0
    attempted: int = 0
    skipped: int = 0
    failed: int = 0
    stale: int = 0

    @property
    def coverage(self) -> float:
        return self.attempted / max(1, self.scheduled)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduled": self.scheduled,
            "attempted": self.attempted,
            "skipped": self.skipped,
            "failed": self.failed,
            "stale": self.stale,
            "coverage": round(self.coverage, 4),
        }


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
    branch: str = "fast_fall"
    priority: int = 1

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
            branch=str(data.get("branch", "fast_fall")),
            priority=int(data.get("priority", 1)),
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
    branch: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_executed_at(req: PoseRequest, current_time: float | None = None) -> float:
    """Resolve outcome executed_at according to the request's clock domain."""
    if req.clock_domain == "event_time":
        if current_time is not None:
            return float(current_time)
        if req.created_at is not None:
            if req.deadline is not None and req.created_at > req.deadline and req.deadline < 1e8:
                return float(req.deadline)
            return float(req.created_at)
        return float(req.deadline) if req.deadline is not None else 0.0
    return time.time()


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
        scores = np.minimum(max_val_x, max_val_y)

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


BRANCH_PRIORITIES = {
    "fast_fall": 1,
    "slow_collapse": 2,
    "persistent_lying": 3,
}

BRANCH_DEADLINES = {
    "fast_fall": 0.5,
    "slow_collapse": 1.5,
    "persistent_lying": 3.0,
}


class PoseScheduler:
    """Fair Pose Scheduler across fast-fall, slow-collapse, and persistent-lying branches."""

    def __init__(
        self,
        *,
        fast_fall_deadline: float = 0.5,
        slow_collapse_deadline: float = 1.5,
        persistent_lying_deadline: float = 3.0,
        persistent_sample_interval: float = 1.0,
        min_drop_velocity: float = 15.0,
        min_ar_change: float = 0.35,
        slow_drop_velocity: float = 3.0,
        slow_ar_change: float = 0.15,
        standing_aspect_ratio: float = 0.85,
        lying_aspect_ratio: float = 1.2,
        max_queue_size: int = 20,
        batch_budget: int = 5,
        min_shares: dict[str, int] | None = None,
        recovery_cycles: int = 3,
        overload_queue_threshold: float = 0.8,
    ) -> None:
        self.fast_fall_deadline = float(fast_fall_deadline)
        self.slow_collapse_deadline = float(slow_collapse_deadline)
        self.persistent_lying_deadline = float(persistent_lying_deadline)
        self.persistent_sample_interval = float(persistent_sample_interval)
        self.min_drop_velocity = float(min_drop_velocity)
        self.min_ar_change = float(min_ar_change)
        self.slow_drop_velocity = float(slow_drop_velocity)
        self.slow_ar_change = float(slow_ar_change)
        self.standing_aspect_ratio = float(standing_aspect_ratio)
        self.lying_aspect_ratio = float(lying_aspect_ratio)
        self.max_queue_size = int(max_queue_size)
        self.batch_budget = int(batch_budget)
        self.min_shares = dict(min_shares) if min_shares is not None else {
            "fast_fall": 1,
            "slow_collapse": 1,
            "persistent_lying": 1,
        }
        self.recovery_cycles = int(recovery_cycles)
        self.overload_queue_threshold = float(overload_queue_threshold)

        self.current_epoch: int = 1
        self.capability_status: str = "full"
        self.degraded_reason: str | None = None
        self._consecutive_calm_cycles: int = 0
        self._last_scheduled_time: dict[int, float] = {}

        self._metrics: dict[str, BranchMetrics] = {
            "fast_fall": BranchMetrics(),
            "slow_collapse": BranchMetrics(),
            "persistent_lying": BranchMetrics(),
        }
        self._branch_queues: dict[str, deque[PoseRequest]] = {
            "fast_fall": deque(),
            "slow_collapse": deque(),
            "persistent_lying": deque(),
        }
        self._shed_outcomes: list[PoseOutcome] = []
        self._lock = threading.RLock()

    def classify_track(self, track: Track, current_time: float) -> str | None:
        """Classify track into fast_fall, slow_collapse, or persistent_lying branch."""
        if getattr(track, "label", None) != "person":
            return None

        v_y = track.vertical_velocity(window_seconds=1.0)
        ar_change = track.aspect_ratio_change(window_seconds=1.0)
        ar = track.aspect_ratio

        # 1. fast_fall: Kinematic onset / rapid drop / sudden aspect ratio change
        if v_y >= self.min_drop_velocity or ar_change >= self.min_ar_change:
            return "fast_fall"

        # 2. slow_collapse: Gradual posture lower / progressive aspect ratio increase towards horizontal
        v_y_slow = track.vertical_velocity(window_seconds=1.5)
        ar_change_slow = track.aspect_ratio_change(window_seconds=1.5)
        if (
            v_y_slow >= self.slow_drop_velocity
            or ar_change_slow >= self.slow_ar_change
            or (self.standing_aspect_ratio <= ar < self.lying_aspect_ratio and (v_y_slow > 0 or ar_change_slow > 0))
        ):
            return "slow_collapse"

        # 3. persistent_lying: Continuous lying without onset / already down on road
        if ar >= self.lying_aspect_ratio:
            return "persistent_lying"

        return None

    def schedule_tracks(
        self,
        tracks: list[Track],
        current_time: float,
        frame_id: int,
        camera_id: str,
        stream_session_id: str,
        core_epoch: int,
    ) -> list[PoseRequest]:
        """Identify candidate tracks across 3 branches and instantiate PoseRequests."""
        new_requests: list[PoseRequest] = []
        with self._lock:
            for track in tracks:
                branch = self.classify_track(track, current_time)
                if branch is None:
                    continue

                if branch == "persistent_lying":
                    last_t = self._last_scheduled_time.get(track.track_id, -1e9)
                    if current_time - last_t < self.persistent_sample_interval:
                        continue

                deadline_offset = (
                    self.fast_fall_deadline
                    if branch == "fast_fall"
                    else (self.slow_collapse_deadline if branch == "slow_collapse" else self.persistent_lying_deadline)
                )
                priority = BRANCH_PRIORITIES.get(branch, 2)
                req = PoseRequest(
                    request_id=f"req-{branch}-{track.track_id}-{frame_id}-{int(current_time * 1000)}",
                    camera_id=camera_id,
                    stream_session_id=stream_session_id,
                    core_epoch=core_epoch,
                    frame_id=frame_id,
                    bbox=list(track.bbox),
                    deadline=current_time + deadline_offset,
                    track_id=track.track_id,
                    clock_domain="event_time",
                    created_at=current_time,
                    branch=branch,
                    priority=priority,
                )
                self._last_scheduled_time[track.track_id] = current_time
                if len(self._last_scheduled_time) > 1000:
                    cutoff = current_time - max(self.persistent_sample_interval * 10, 60.0)
                    self._last_scheduled_time = {
                        tid: t for tid, t in self._last_scheduled_time.items() if t >= cutoff
                    }
                new_requests.append(req)
        return new_requests

    def submit_request(self, request: PoseRequest) -> bool:
        """Enqueue request with overload shedding of lower-priority work and capacity bounds."""
        with self._lock:
            branch = request.branch if request.branch in self._branch_queues else "fast_fall"
            self.record_scheduled(branch, 1)

            total_queued = self.queued_count()

            # Overload check: shed routine / low priority work if queue is at capacity
            if total_queued >= self.max_queue_size:
                shed_success = self._try_shed_lower_priority(request)
                if not shed_success:
                    outcome = PoseOutcome(
                        request_id=request.request_id,
                        camera_id=request.camera_id,
                        stream_session_id=request.stream_session_id,
                        core_epoch=request.core_epoch,
                        frame_id=request.frame_id,
                        track_id=request.track_id,
                        status="skipped",
                        reason="queue_full",
                        executed_at=_resolve_executed_at(request),
                        branch=branch,
                    )
                    self._shed_outcomes.append(outcome)
                    self.record_outcome(outcome)
                    return False

            self._branch_queues[branch].append(request)

            # Check queue capacity threshold after enqueue
            if self.queued_count() >= int(self.overload_queue_threshold * self.max_queue_size):
                if self.capability_status != "degraded":
                    self.capability_status = "degraded"
                    self.degraded_reason = "queue_near_capacity"
                self._consecutive_calm_cycles = 0

            return True

    def _try_shed_lower_priority(self, incoming_request: PoseRequest) -> bool:
        """Shed lower priority work to make room for higher priority request."""
        # 1. Shed persistent_lying if incoming request has priority <= 2
        if incoming_request.priority <= 2 and len(self._branch_queues["persistent_lying"]) > 0:
            shed_req = self._branch_queues["persistent_lying"].popleft()
            outcome = PoseOutcome(
                request_id=shed_req.request_id,
                camera_id=shed_req.camera_id,
                stream_session_id=shed_req.stream_session_id,
                core_epoch=shed_req.core_epoch,
                frame_id=shed_req.frame_id,
                track_id=shed_req.track_id,
                status="skipped",
                reason="overload_shedding_routine_pose",
                executed_at=_resolve_executed_at(shed_req),
                branch="persistent_lying",
            )
            self._shed_outcomes.append(outcome)
            self.record_outcome(outcome)
            self.capability_status = "degraded"
            self.degraded_reason = "overload_shedding_routine_pose"
            self._consecutive_calm_cycles = 0
            return True

        # 2. Shed slow_collapse if incoming is fast_fall (priority 1)
        if incoming_request.priority == 1 and len(self._branch_queues["slow_collapse"]) > 0:
            shed_req = self._branch_queues["slow_collapse"].popleft()
            outcome = PoseOutcome(
                request_id=shed_req.request_id,
                camera_id=shed_req.camera_id,
                stream_session_id=shed_req.stream_session_id,
                core_epoch=shed_req.core_epoch,
                frame_id=shed_req.frame_id,
                track_id=shed_req.track_id,
                status="skipped",
                reason="overload_shedding_slow_collapse",
                executed_at=_resolve_executed_at(shed_req),
                branch="slow_collapse",
            )
            self._shed_outcomes.append(outcome)
            self.record_outcome(outcome)
            self.capability_status = "degraded"
            self.degraded_reason = "overload_shedding_slow_collapse"
            self._consecutive_calm_cycles = 0
            return True

        return False

    def schedule_batch(
        self,
        current_time: float,
        budget: int | None = None,
    ) -> tuple[list[PoseRequest], list[PoseOutcome]]:
        """Extract next batch using fair budget allocation across active branches."""
        alloc_budget = budget if budget is not None else self.batch_budget
        with self._lock:
            initial_queue_count = self.queued_count()
            expired_outcomes: list[PoseOutcome] = []
            for branch in ("fast_fall", "slow_collapse", "persistent_lying"):
                queue = self._branch_queues[branch]
                survivors: deque[PoseRequest] = deque()
                while queue:
                    req = queue.popleft()
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
                            executed_at=_resolve_executed_at(req, current_time),
                            branch=branch,
                        )
                        expired_outcomes.append(outcome)
                        self.record_outcome(outcome)
                    elif current_time > req.deadline:
                        outcome = PoseOutcome(
                            request_id=req.request_id,
                            camera_id=req.camera_id,
                            stream_session_id=req.stream_session_id,
                            core_epoch=req.core_epoch,
                            frame_id=req.frame_id,
                            track_id=req.track_id,
                            status="skipped",
                            reason="deadline_exceeded",
                            executed_at=_resolve_executed_at(req, current_time),
                            branch=branch,
                        )
                        expired_outcomes.append(outcome)
                        self.record_outcome(outcome)
                    else:
                        survivors.append(req)
                self._branch_queues[branch] = survivors

            # Identify active branches
            active_branches = [b for b in ("fast_fall", "slow_collapse", "persistent_lying") if len(self._branch_queues[b]) > 0]
            selected: list[PoseRequest] = []
            remaining = alloc_budget

            # Phase 1: Guaranteed minimum shares
            for b in active_branches:
                if remaining <= 0:
                    break
                share = min(len(self._branch_queues[b]), self.min_shares.get(b, 1), remaining)
                for _ in range(share):
                    selected.append(self._branch_queues[b].popleft())
                    remaining -= 1

            # Phase 2: Priority-based distribution of remaining budget
            for b in ("fast_fall", "slow_collapse", "persistent_lying"):
                if remaining <= 0:
                    break
                while self._branch_queues[b] and remaining > 0:
                    selected.append(self._branch_queues[b].popleft())
                    remaining -= 1

            # Calm check for hysteresis evaluated against pre-dispatch queue occupancy
            calm = (
                initial_queue_count < int(self.overload_queue_threshold * self.max_queue_size)
                and len(self._shed_outcomes) == 0
            )
            self.step_evaluation_cycle(calm=calm)

            outcomes = list(self._shed_outcomes) + expired_outcomes
            self._shed_outcomes.clear()
            return selected, outcomes

    def step_evaluation_cycle(self, calm: bool = True, overload_reason: str | None = None) -> None:
        """Step evaluation cycle updating hysteresis recovery ramp."""
        with self._lock:
            if not calm:
                self.capability_status = "degraded"
                self.degraded_reason = overload_reason or self.degraded_reason or "overload_shedding_routine_pose"
                self._consecutive_calm_cycles = 0
            else:
                if self.capability_status == "degraded":
                    self._consecutive_calm_cycles += 1
                    if self._consecutive_calm_cycles >= self.recovery_cycles:
                        self.capability_status = "full"
                        self.degraded_reason = None

    def trigger_overload(self, reason: str = "queue_near_capacity") -> None:
        """Explicitly trigger degradation state."""
        with self._lock:
            self.capability_status = "degraded"
            self.degraded_reason = reason
            self._consecutive_calm_cycles = 0

    def record_scheduled(self, branch: str, count: int = 1) -> None:
        """Increment scheduled request count for branch."""
        with self._lock:
            if branch in self._metrics:
                self._metrics[branch].scheduled += count

    def record_outcome(self, outcome: PoseOutcome) -> None:
        """Record terminal outcome against corresponding branch metrics."""
        with self._lock:
            branch = outcome.branch if outcome.branch in self._metrics else "fast_fall"
            m = self._metrics[branch]
            if outcome.status == "ok":
                m.attempted += 1
            elif outcome.status == "failed":
                m.attempted += 1
                m.failed += 1
            elif outcome.status == "skipped":
                m.skipped += 1
            elif outcome.status == "cancelled":
                m.stale += 1

    def get_metrics(self) -> dict[str, Any]:
        """Return metrics dict for each branch and overall summary."""
        with self._lock:
            res: dict[str, Any] = {
                b: self._metrics[b].to_dict()
                for b in ("fast_fall", "slow_collapse", "persistent_lying")
            }
            tot_sched = sum(self._metrics[b].scheduled for b in ("fast_fall", "slow_collapse", "persistent_lying"))
            tot_att = sum(self._metrics[b].attempted for b in ("fast_fall", "slow_collapse", "persistent_lying"))
            tot_skip = sum(self._metrics[b].skipped for b in ("fast_fall", "slow_collapse", "persistent_lying"))
            tot_fail = sum(self._metrics[b].failed for b in ("fast_fall", "slow_collapse", "persistent_lying"))
            tot_stale = sum(self._metrics[b].stale for b in ("fast_fall", "slow_collapse", "persistent_lying"))
            res["overall"] = {
                "scheduled": tot_sched,
                "attempted": tot_att,
                "skipped": tot_skip,
                "failed": tot_fail,
                "stale": tot_stale,
                "coverage": round(tot_att / max(1, tot_sched), 4),
            }
            return res

    def queued_count(self) -> int:
        """Count active queued requests across all branches."""
        with self._lock:
            return sum(len(q) for q in self._branch_queues.values())

    def get_queued_branches(self) -> list[str]:
        """Return branches that currently have queued requests."""
        with self._lock:
            return [b for b, q in self._branch_queues.items() if len(q) > 0]

    def poll_shed_outcomes(self) -> list[PoseOutcome]:
        """Drain and return shed outcomes."""
        with self._lock:
            outcomes = list(self._shed_outcomes)
            self._shed_outcomes.clear()
            return outcomes

    def set_epoch(self, new_epoch: int) -> list[PoseOutcome]:
        """Cancel queued requests from older epochs."""
        with self._lock:
            self.current_epoch = int(new_epoch)
            cancelled: list[PoseOutcome] = []
            for branch, q in self._branch_queues.items():
                survivors: deque[PoseRequest] = deque()
                while q:
                    req = q.popleft()
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
                            executed_at=_resolve_executed_at(req),
                            branch=branch,
                        )
                        cancelled.append(outcome)
                        self.record_outcome(outcome)
                    else:
                        survivors.append(req)
                self._branch_queues[branch] = survivors
            return cancelled


class PoseManager:
    """Manages pose request queuing, buffer caching, deadlines, epochs and terminal outcomes."""

    def __init__(
        self,
        estimator: RtmposeEstimator | None = None,
        max_queue_size: int = 64,
        max_cached_frames: int = 30,
        scheduler: PoseScheduler | None = None,
    ) -> None:
        self.estimator = estimator
        self.max_queue_size = int(max_queue_size)
        self.max_cached_frames = int(max_cached_frames)
        self.current_epoch: int = 1

        self._lock = threading.RLock()
        # Key: (camera_id, stream_session_id, core_epoch, frame_id) -> np.ndarray
        self._frame_cache: OrderedDict[tuple[str, str, int, int], np.ndarray] = OrderedDict()
        self.scheduler = scheduler or PoseScheduler(
            max_queue_size=self.max_queue_size,
            batch_budget=self.max_queue_size,
        )
        self._terminal_outcomes: deque[PoseOutcome] = deque(maxlen=self.max_queue_size * 4)

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
            cancelled_outcomes = self.scheduler.set_epoch(new_epoch)
            self._terminal_outcomes.extend(cancelled_outcomes)
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
                    executed_at=_resolve_executed_at(req),
                    branch=req.branch,
                )
                self._terminal_outcomes.append(outcome)
                self.scheduler.record_scheduled(req.branch, 1)
                self.scheduler.record_outcome(outcome)
                return False

            accepted = self.scheduler.submit_request(req)
            shed = self.scheduler.poll_shed_outcomes()
            if shed:
                self._terminal_outcomes.extend(shed)
            return accepted

    def process_pending(self, current_time: float) -> list[PoseOutcome]:
        """Drain and process queued requests evaluating deadline, cache existence, and estimation."""
        with self._lock:
            requests_to_process, shed_outcomes = self.scheduler.schedule_batch(current_time)
            terminal_outcomes = list(self._terminal_outcomes)
            self._terminal_outcomes.clear()

        outcomes: list[PoseOutcome] = terminal_outcomes + list(shed_outcomes)
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
                    executed_at=_resolve_executed_at(req, current_time),
                    branch=req.branch,
                )
                self.scheduler.record_outcome(outcome)
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
                    executed_at=_resolve_executed_at(req, current_time),
                    branch=req.branch,
                )
                self.scheduler.record_outcome(outcome)
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
                    executed_at=_resolve_executed_at(req, current_time),
                    branch=req.branch,
                )
                self.scheduler.record_outcome(outcome)
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
                    executed_at=_resolve_executed_at(req, current_time),
                    branch=req.branch,
                )
                self.scheduler.record_outcome(outcome)
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
                    executed_at=_resolve_executed_at(req, current_time),
                    branch=req.branch,
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
                    executed_at=_resolve_executed_at(req, current_time),
                    branch=req.branch,
                )
            self.scheduler.record_outcome(outcome)
            outcomes.append(outcome)

        return outcomes

    def request_pose(
        self,
        request: PoseRequest | dict[str, Any],
        rgb: np.ndarray | None = None,
        current_time: float | None = None,
    ) -> PoseOutcome:
        """Synchronously evaluate a pose request immediately."""
        req = PoseRequest.from_dict(request) if isinstance(request, dict) else request
        self.scheduler.record_scheduled(req.branch, 1)
        eval_time = (
            current_time
            if current_time is not None
            else (time.time() if req.clock_domain != "event_time" else None)
        )
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
                executed_at=_resolve_executed_at(req, eval_time),
                branch=req.branch,
            )
            self.scheduler.record_outcome(outcome)
            return outcome

        # Deadline check
        if eval_time is not None and eval_time > req.deadline:
            outcome = PoseOutcome(
                request_id=req.request_id,
                camera_id=req.camera_id,
                stream_session_id=req.stream_session_id,
                core_epoch=req.core_epoch,
                frame_id=req.frame_id,
                track_id=req.track_id,
                status="skipped",
                reason="deadline_exceeded",
                executed_at=_resolve_executed_at(req, eval_time),
                branch=req.branch,
            )
            self.scheduler.record_outcome(outcome)
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
                executed_at=_resolve_executed_at(req, eval_time),
                branch=req.branch,
            )
            self.scheduler.record_outcome(outcome)
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
                executed_at=_resolve_executed_at(req, eval_time),
                branch=req.branch,
            )
            self.scheduler.record_outcome(outcome)
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
                executed_at=_resolve_executed_at(req, eval_time),
                branch=req.branch,
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
                executed_at=_resolve_executed_at(req, eval_time),
                branch=req.branch,
            )

        self.scheduler.record_outcome(outcome)
        return outcome

    def poll_terminal_outcomes(self) -> list[PoseOutcome]:
        """Retrieve and drain all settled terminal outcomes."""
        with self._lock:
            outcomes = list(self._terminal_outcomes)
            self._terminal_outcomes.clear()
            return outcomes

    def queued_count(self) -> int:
        """Count outstanding requests in queue."""
        return self.scheduler.queued_count()

    def get_metrics(self) -> dict[str, Any]:
        """Return metrics dict for each branch and overall summary."""
        return self.scheduler.get_metrics()

    def get_capability_status(self) -> str:
        """Return overall capability status."""
        if self.estimator is None:
            return "unsupported"
        return self.scheduler.capability_status

    def get_degraded_reason(self) -> str | None:
        """Return degradation reason if any."""
        if self.estimator is None:
            return "estimator_unavailable"
        return self.scheduler.degraded_reason
