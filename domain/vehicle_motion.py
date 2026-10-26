"""Vehicle kinematics, trajectory smoothing, and pairwise interaction risk (Tasks M01 & M02).

Pure domain module: no I/O, no framework imports.
Provides:
- KinematicState: position, velocity, speed, acceleration, heading.
- KinematicsTracker: time-aware trajectory smoother resilient to variable dt,
  timestamp jitter, track gaps, predictions, and epoch/session resets.
- PairwiseInteractionRisk: relative position/velocity, closing speed, IoU,
  expansion rate, TTC risk classification, and non-proof of collision.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

__all__ = [
    "KinematicState",
    "KinematicsTracker",
    "PairwiseInteractionRisk",
    "bbox_iou",
    "check_collision_evidence",
    "compute_pairwise_risk",
]


def bbox_iou(box1: Sequence[float], box2: Sequence[float]) -> float:
    """Compute Intersection-over-Union (IoU) between two bounding boxes [x1, y1, x2, y2]."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0.0:
        return 0.0
    area1 = max(0.0, box1[2] - box1[0]) * max(0.0, box1[3] - box1[1])
    area2 = max(0.0, box2[2] - box2[0]) * max(0.0, box2[3] - box2[1])
    union_area = area1 + area2 - inter_area
    if union_area <= 0.0:
        return 0.0
    return inter_area / union_area


@dataclass(frozen=True)
class KinematicState:
    """Kinematic representation of a tracked object at a discrete timestamp."""

    timestamp: float
    cx: float
    cy: float
    vx: float
    vy: float
    speed: float
    ax: float
    ay: float
    acceleration: float  # Signed tangential acceleration: d(speed)/dt (< 0 indicates braking/deceleration)
    scalar_acceleration: float  # Magnitude of acceleration vector: hypot(ax, ay)
    heading: float  # Direction in radians in [-pi, pi], 0.0 if stationary
    is_stationary: bool
    is_valid: bool = True
    is_predicted: bool = False


@dataclass
class _ObservationRecord:
    timestamp: float
    cx: float
    cy: float
    vx: float | None = None
    vy: float | None = None


class KinematicsTracker:
    """Time-aware kinematics and trajectory smoothing filter (Task M01).

    Guarantees:
    - Variable dt, timestamp jitter, and track gaps do NOT create false acceleration spikes.
    - History resets on epoch change, session discontinuity, or observation gap > max_observation_gap.
    - Constant velocity predictions advance state with zero acceleration spike.
    """

    def __init__(
        self,
        max_observation_gap: float = 1.0,
        stationary_speed_threshold: float = 8.0,
        derivative_window: float = 0.20,
        min_derivative_dt: float = 0.03,
    ) -> None:
        self.max_observation_gap = float(max_observation_gap)
        self.stationary_speed_threshold = float(stationary_speed_threshold)
        self.derivative_window = float(derivative_window)
        self.min_derivative_dt = float(min_derivative_dt)

        self._last_timestamp: float | None = None
        self._last_epoch: int | None = None
        self._last_session_id: str | None = None
        self._last_vx: float = 0.0
        self._last_vy: float = 0.0
        self._last_cx: float = 0.0
        self._last_cy: float = 0.0
        self._history: list[_ObservationRecord] = []
        self._is_initialized: bool = False

    def reset(self) -> None:
        """Reset all trajectory and kinematics history."""
        self._last_timestamp = None
        self._last_epoch = None
        self._last_session_id = None
        self._last_vx = 0.0
        self._last_vy = 0.0
        self._last_cx = 0.0
        self._last_cy = 0.0
        self._history.clear()
        self._is_initialized = False

    def update(
        self,
        timestamp: float,
        cx: float,
        cy: float,
        is_predicted: bool = False,
        epoch: int | None = None,
        session_id: str | None = None,
    ) -> KinematicState:
        """Incorporate a new observation or prediction and return the updated kinematic state."""
        ts = float(timestamp)
        raw_cx = float(cx)
        raw_cy = float(cy)

        # Check for discontinuity: first frame, time regression, track gap, epoch or session change
        gap_or_time_jump = (
            self._last_timestamp is None
            or ts <= self._last_timestamp
            or (ts - self._last_timestamp) > self.max_observation_gap
        )
        epoch_change = (
            epoch is not None
            and self._last_epoch is not None
            and epoch != self._last_epoch
        )
        session_change = (
            session_id is not None
            and self._last_session_id is not None
            and session_id != self._last_session_id
        )

        if not self._is_initialized or gap_or_time_jump or epoch_change or session_change:
            self.reset()
            self._is_initialized = True
            self._last_timestamp = ts
            self._last_epoch = epoch
            self._last_session_id = session_id
            self._last_cx = raw_cx
            self._last_cy = raw_cy
            self._last_vx = 0.0
            self._last_vy = 0.0
            self._history.append(_ObservationRecord(ts, raw_cx, raw_cy))
            return KinematicState(
                timestamp=ts,
                cx=raw_cx,
                cy=raw_cy,
                vx=0.0,
                vy=0.0,
                speed=0.0,
                ax=0.0,
                ay=0.0,
                acceleration=0.0,
                scalar_acceleration=0.0,
                heading=0.0,
                is_stationary=True,
                is_valid=True,
                is_predicted=is_predicted,
            )

        assert self._last_timestamp is not None
        dt = ts - self._last_timestamp
        self._last_timestamp = ts
        self._last_epoch = epoch
        self._last_session_id = session_id

        # Prediction branch: extrapolate with constant velocity, 0 acceleration spike
        if is_predicted:
            pred_cx = self._last_cx + self._last_vx * dt
            pred_cy = self._last_cy + self._last_vy * dt
            self._last_cx = pred_cx
            self._last_cy = pred_cy
            speed = math.hypot(self._last_vx, self._last_vy)
            is_stat = speed <= self.stationary_speed_threshold
            heading = math.atan2(self._last_vy, self._last_vx) if not is_stat else 0.0
            obs = _ObservationRecord(ts, pred_cx, pred_cy, self._last_vx, self._last_vy)
            self._history.append(obs)
            if len(self._history) > 64:
                self._history[:] = self._history[-32:]
            return KinematicState(
                timestamp=ts,
                cx=pred_cx,
                cy=pred_cy,
                vx=self._last_vx,
                vy=self._last_vy,
                speed=speed,
                ax=0.0,
                ay=0.0,
                acceleration=0.0,
                scalar_acceleration=0.0,
                heading=heading,
                is_stationary=is_stat,
                is_valid=True,
                is_predicted=True,
            )

        # Measurement branch: windowed differentiation with jitter guard
        obs = _ObservationRecord(ts, raw_cx, raw_cy)
        self._history.append(obs)
        if len(self._history) > 64:
            self._history[:] = self._history[-32:]

        # 1. Compute velocity relative to window reference
        target_t = ts - self.derivative_window
        ref_v: _ObservationRecord | None = None
        for o in self._history[:-1]:
            if o.timestamp <= target_t:
                ref_v = o
            else:
                break
        if ref_v is None:
            ref_v = self._history[0]

        dt_v = ts - ref_v.timestamp
        if dt_v >= 0.01:
            curr_vx = (raw_cx - ref_v.cx) / dt_v
            curr_vy = (raw_cy - ref_v.cy) / dt_v
        else:
            curr_vx = self._last_vx
            curr_vy = self._last_vy

        obs.vx = curr_vx
        obs.vy = curr_vy
        self._last_vx = curr_vx
        self._last_vy = curr_vy
        self._last_cx = raw_cx
        self._last_cy = raw_cy

        # 2. Compute acceleration relative to window reference with valid velocity
        valid_v_obs = [o for o in self._history[:-1] if o.vx is not None and o.vy is not None]
        if len(valid_v_obs) >= 1:
            ref_a: _ObservationRecord | None = None
            for o in valid_v_obs:
                if o.timestamp <= target_t:
                    ref_a = o
                else:
                    break
            if ref_a is None:
                ref_a = valid_v_obs[0]

            dt_a = ts - ref_a.timestamp
            if dt_a >= self.min_derivative_dt and ref_a.vx is not None and ref_a.vy is not None:
                curr_ax = (curr_vx - ref_a.vx) / dt_a
                curr_ay = (curr_vy - ref_a.vy) / dt_a
            else:
                curr_ax = 0.0
                curr_ay = 0.0
        else:
            curr_ax = 0.0
            curr_ay = 0.0

        speed = math.hypot(curr_vx, curr_vy)
        is_stat = speed <= self.stationary_speed_threshold
        heading = math.atan2(curr_vy, curr_vx) if not is_stat else 0.0

        # Tangential acceleration: projection of acceleration vector along velocity direction
        if speed > 1e-3:
            tangential_acc = (curr_ax * curr_vx + curr_ay * curr_vy) / speed
        else:
            tangential_acc = 0.0

        scalar_acc = math.hypot(curr_ax, curr_ay)

        return KinematicState(
            timestamp=ts,
            cx=raw_cx,
            cy=raw_cy,
            vx=curr_vx,
            vy=curr_vy,
            speed=speed,
            ax=curr_ax,
            ay=curr_ay,
            acceleration=tangential_acc,
            scalar_acceleration=scalar_acc,
            heading=heading,
            is_stationary=is_stat,
            is_valid=True,
            is_predicted=False,
        )


@dataclass(frozen=True)
class PairwiseInteractionRisk:
    """Pairwise interaction and TTC risk features in image space (Task M02)."""

    track_id_1: int | str
    track_id_2: int | str
    relative_position: tuple[float, float]  # (cx2 - cx1, cy2 - cy1)
    distance: float  # hypot(dx, dy)
    relative_velocity: tuple[float, float]  # (vx2 - vx1, vy2 - vy1)
    closing_speed: float  # -d(distance)/dt (> 0 when converging)
    iou: float  # Bounding box IoU
    expansion_rate: float  # Rate of change of IoU or relative scale
    ttc: float  # Estimated time to collision in seconds (inf if not converging)
    risk_level: str  # "none" | "low" | "high" | "critical"
    is_collision_proven: bool = False  # TTC/overlap alone does NOT prove collision!


def compute_pairwise_risk(
    track_id_1: int | str,
    k1: KinematicState,
    bbox_1: Sequence[float],
    track_id_2: int | str,
    k2: KinematicState,
    bbox_2: Sequence[float],
    prev_iou: float = 0.0,
    dt: float = 0.1,
) -> PairwiseInteractionRisk:
    """Compute pairwise interaction and TTC risk between two tracks in image space.

    Enforces that TTC and bounding box overlap alone do NOT prove collision.
    """
    dx = k2.cx - k1.cx
    dy = k2.cy - k1.cy
    dist = math.hypot(dx, dy)

    rel_vx = k2.vx - k1.vx
    rel_vy = k2.vy - k1.vy

    # Rate of change of distance: d(dist)/dt = (dx * rel_vx + dy * rel_vy) / dist
    # Closing speed is -d(dist)/dt (> 0 indicates closing in on each other)
    if dist > 1e-4:
        closing_speed = - (dx * rel_vx + dy * rel_vy) / dist
    else:
        closing_speed = 0.0

    iou = bbox_iou(bbox_1, bbox_2)
    dt_safe = max(float(dt), 1e-4)
    expansion_rate = (iou - float(prev_iou)) / dt_safe

    # Time To Collision (TTC) in seconds
    if closing_speed > 1e-2 and dist > 0.0:
        ttc = dist / closing_speed
    else:
        ttc = float("inf")

    # Risk level classification
    if closing_speed <= 0.0 or ttc > 5.0:
        if iou > 0.2:
            risk_level = "low"
        else:
            risk_level = "none"
    elif ttc <= 1.0 or (iou > 0.25 and closing_speed > 20.0):
        risk_level = "critical"
    elif ttc <= 2.5 or (iou > 0.10 and closing_speed > 10.0):
        risk_level = "high"
    else:
        risk_level = "low"

    return PairwiseInteractionRisk(
        track_id_1=track_id_1,
        track_id_2=track_id_2,
        relative_position=(dx, dy),
        distance=dist,
        relative_velocity=(rel_vx, rel_vy),
        closing_speed=closing_speed,
        iou=iou,
        expansion_rate=expansion_rate,
        ttc=ttc,
        risk_level=risk_level,
        is_collision_proven=False,  # Explicitly False: TTC/overlap alone does NOT prove collision!
    )


def check_collision_evidence(
    risk: PairwiseInteractionRisk,
    k1: KinematicState,
    k2: KinematicState,
    deceleration_threshold: float = 120.0,
    deflection_threshold: float = 0.5,
    halt_speed: float = 8.0,
) -> tuple[bool, str]:
    """Evaluate whether kinetic collision evidence exists between two interacting tracks.

    Near-misses and perspective overlaps have low TTC and/or high IoU but lack
    kinetic collision signatures (abrupt deceleration spike, deflection, or post-collision halt).
    """
    # 1. Did both vehicles converge or come into close contact?
    converged = risk.closing_speed > 5.0 or risk.iou > 0.05 or risk.ttc <= 2.5
    if not converged and risk.distance > 80.0:
        return False, "no_convergence"

    # 2. Check for sudden deceleration spike (braking/impact) in either vehicle
    decel_spike_1 = k1.acceleration <= -deceleration_threshold
    decel_spike_2 = k2.acceleration <= -deceleration_threshold

    # 3. Check for post-collision halt
    halt_1 = k1.speed <= halt_speed
    halt_2 = k2.speed <= halt_speed

    # 4. Impact with halt
    if (decel_spike_1 or decel_spike_2) and (halt_1 or halt_2):
        return True, "deceleration_spike_with_halt"

    # 5. High closing speed convergence resulting in mutual stoppage
    if risk.closing_speed > 20.0 and halt_1 and halt_2:
        return True, "mutual_halt_after_closing"

    # 6. Both halted with significant bounding box contact
    if risk.iou > 0.15 and (halt_1 or halt_2) and (decel_spike_1 or decel_spike_2):
        return True, "contact_with_deceleration"

    return False, "insufficient_kinetic_evidence"
