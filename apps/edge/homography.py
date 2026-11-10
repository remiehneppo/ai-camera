"""Ground-Plane Homography & Metric Kinematics for CiviWatch v2.

Maps 2D image foot coordinates (u, v) to 2D world ground-plane coordinates (X_m, Y_m)
in meters using a 4-point perspective homography matrix H (3x3).
Provides perspective-invariant velocity (m/s) and acceleration (m/s^2) estimation
to eliminate false positives caused by near-camera vs far-camera pixel scaling.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class GroundPoint:
    """Metric ground-plane coordinate with validity flag."""

    x_m: float
    y_m: float
    valid: bool = True


@dataclass(frozen=True)
class MetricKinematics:
    """Perspective-corrected metric velocity and acceleration on the ground plane."""

    x_m: float
    y_m: float
    vx_mps: float
    vy_mps: float
    speed_mps: float
    accel_mps2: float


class GroundPlaneHomography:
    """3x3 perspective homography between image pixel space and road ground plane (meters)."""

    def __init__(
        self,
        image_points: Sequence[Sequence[float]],
        world_points_meters: Sequence[Sequence[float]],
        *,
        calibration_id: str = "civi-homography-v2",
    ) -> None:
        if len(image_points) != 4 or len(world_points_meters) != 4:
            raise ValueError("GroundPlaneHomography requires exactly 4 image points and 4 world points")
        src = np.asarray(image_points, dtype=np.float32)
        dst = np.asarray(world_points_meters, dtype=np.float32)
        if src.shape != (4, 2) or dst.shape != (4, 2):
            raise ValueError("Homography point arrays must have shape (4, 2)")
        if not (np.isfinite(src).all() and np.isfinite(dst).all()):
            raise ValueError("Homography points must be finite numbers")

        matrix = cv2.getPerspectiveTransform(src, dst)
        if not np.isfinite(matrix).all() or abs(float(np.linalg.det(matrix))) < 1e-12:
            raise ValueError("Degenerate homography configuration: points are collinear or singular")

        self.matrix: np.ndarray = matrix.astype(np.float64)
        self.inv_matrix: np.ndarray = np.linalg.inv(self.matrix)
        self.calibration_id = str(calibration_id)

    @classmethod
    def default_urban_cctv(
        cls,
        width: int = 1920,
        height: int = 1080,
        road_width_m: float = 12.0,
        road_depth_m: float = 35.0,
    ) -> GroundPlaneHomography:
        """Create a standard fixed-CCTV trapezoid homography for a 1080p roadway view."""
        w, h = float(width), float(height)
        image_pts = [
            [w * 0.15, h * 0.92],  # bottom-left near camera
            [w * 0.85, h * 0.92],  # bottom-right near camera
            [w * 0.65, h * 0.35],  # top-right far horizon
            [w * 0.35, h * 0.35],  # top-left far horizon
        ]
        world_pts = [
            [0.0, 0.0],
            [road_width_m, 0.0],
            [road_width_m, road_depth_m],
            [0.0, road_depth_m],
        ]
        return cls(image_pts, world_pts, calibration_id="civi-default-cctv-1080p")

    def pixel_to_ground(self, u: float, v: float) -> GroundPoint:
        """Project pixel coordinate (u, v) onto ground plane (X_m, Y_m) in meters."""
        vec = np.array([float(u), float(v), 1.0], dtype=np.float64)
        transformed = self.matrix @ vec
        denom = float(transformed[2])
        if abs(denom) < 1e-9 or not math.isfinite(denom):
            return GroundPoint(0.0, 0.0, valid=False)
        x_m = float(transformed[0] / denom)
        y_m = float(transformed[1] / denom)
        return GroundPoint(x_m=x_m, y_m=y_m, valid=math.isfinite(x_m) and math.isfinite(y_m))

    def ground_to_pixel(self, x_m: float, y_m: float) -> tuple[float, float]:
        """Project metric ground coordinate (X_m, Y_m) back to image pixel space (u, v)."""
        vec = np.array([float(x_m), float(y_m), 1.0], dtype=np.float64)
        transformed = self.inv_matrix @ vec
        denom = float(transformed[2])
        if abs(denom) < 1e-9:
            return (0.0, 0.0)
        return (float(transformed[0] / denom), float(transformed[1] / denom))

    def bbox_foot_to_ground(self, bbox: Sequence[float]) -> GroundPoint:
        """Project the bottom-center contact point of a bounding box to ground meters."""
        if len(bbox) < 4:
            return GroundPoint(0.0, 0.0, valid=False)
        foot_u = (float(bbox[0]) + float(bbox[2])) * 0.5
        foot_v = float(bbox[3])
        return self.pixel_to_ground(foot_u, foot_v)

    def estimate_track_kinematics(
        self,
        observations: Sequence[tuple[Sequence[float], float]],
    ) -> MetricKinematics | None:
        """Compute ground-plane metric velocity (m/s) and acceleration (m/s^2) from (bbox, timestamp) history."""
        if not observations:
            return None
        pts: list[tuple[float, float, float]] = []
        for bbox, ts in observations:
            gp = self.bbox_foot_to_ground(bbox)
            if gp.valid:
                pts.append((gp.x_m, gp.y_m, float(ts)))
        if not pts:
            return None
        if len(pts) == 1:
            return MetricKinematics(pts[0][0], pts[0][1], 0.0, 0.0, 0.0, 0.0)

        x_now, y_now, t_now = pts[-1]
        x_prev, y_prev, t_prev = pts[-2]
        dt = t_now - t_prev
        if dt <= 1e-6:
            return MetricKinematics(x_now, y_now, 0.0, 0.0, 0.0, 0.0)

        vx = (x_now - x_prev) / dt
        vy = (y_now - y_prev) / dt
        speed = math.hypot(vx, vy)
        accel = 0.0
        if len(pts) >= 3:
            x_0, y_0, t_0 = pts[-3]
            dt_prev = t_prev - t_0
            if dt_prev > 1e-6:
                prev_speed = math.hypot((x_prev - x_0) / dt_prev, (y_prev - y_0) / dt_prev)
                accel = (speed - prev_speed) / dt

        return MetricKinematics(
            x_m=round(x_now, 4),
            y_m=round(y_now, 4),
            vx_mps=round(vx, 4),
            vy_mps=round(vy, 4),
            speed_mps=round(speed, 4),
            accel_mps2=round(accel, 4),
        )
