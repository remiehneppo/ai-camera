"""Crowd Incident Engine for edge crowd concentration & suspected disorder detection (Ticket #63 / US06).

Evaluates pedestrian tracks (person, pedestrian) in ROI (point_in_polygon) and optional schedule.
Implements two distinct, independent layers (per US06 spec):
1) Layer 1: Crowd Concentration (crowd_concentration):
   - Pedestrian count in ROI N >= min_crowd_count (e.g. 5, configurable) persisting for
     duration T >= min_duration_seconds (e.g. 3.0s).
   - Severity: "low" or "medium" (default "medium" / Thường per requirements §2).
2) Layer 2: Suspected Public Disorder (suspected_disorder):
   - Clustered pedestrians exhibiting rapid dispersive / chaotic motion or aggressive kinetic
     surging (high average speed/acceleration, sudden dispersal divergence, or rapid erratic
     direction changes) among the crowd.
   - Severity: "high" (default "Cao" per requirements §2).
   - Explicitly enforces that crowd concentration alone does NOT imply disorder.

Rejects hard negatives:
1) Normal orderly queue / bus stop line: steady or low velocity does NOT trigger disorder.
2) Isolated individual running or waving hands: single person does NOT trigger crowd concentration or disorder.
3) Transient pedestrian crossing / walking past: brief crossing (T < min_duration_seconds) does NOT trigger crowd concentration.
4) Pedestrians outside restricted ROI: do NOT count towards crowd threshold.
5) Observation gap / track discontinuity: resets persistence timer.

Generates rule facts dictionaries:
- anchor_kind: "alert_condition"
- payload["taxonomy"]: "crowd_concentration" | "suspected_disorder"
- payload["severity"]: "medium" (crowd) | "high" (disorder)
- payload["crowd_count"]: count of pedestrians in cluster
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable, Sequence
from uuid import uuid4

from apps.edge.geometry import is_normalized_polygon, point_in_polygon
from apps.edge.tracker import Track


PEDESTRIAN_LABELS: frozenset[str] = frozenset({"person", "pedestrian"})


def _extract_track_data(track: Any) -> tuple[int | str, str, list[float], float, float, float]:
    """Extract (track_id, label, bbox, score, cx, cy) from Track object or dict."""
    if isinstance(track, dict):
        tid = track["track_id"]
        label = str(track.get("label", "person"))
        bbox = [float(x) for x in track["bbox"]]
        score = float(track.get("score", 0.9))
        cx = float(track.get("cx", (bbox[0] + bbox[2]) / 2.0))
        cy = float(track.get("cy", (bbox[1] + bbox[3]) / 2.0))
        return tid, label, bbox, score, cx, cy

    tid = track.track_id
    label = str(getattr(track, "label", "person"))
    bbox = [float(x) for x in track.bbox]
    score = float(getattr(track, "score", 0.9))
    cx = float(getattr(track, "cx", (bbox[0] + bbox[2]) / 2.0))
    cy = float(getattr(track, "cy", (bbox[1] + bbox[3]) / 2.0))
    return tid, label, bbox, score, cx, cy


@dataclass
class _PedestrianKinematics:
    """Kinematic state of one pedestrian track."""
    track_id: int | str
    timestamp: float
    cx: float
    cy: float
    vx: float = 0.0
    vy: float = 0.0
    speed: float = 0.0
    acceleration: float = 0.0
    heading: float = 0.0


@dataclass
class _PedestrianState:
    """Track state and recent history for crowd & disorder evaluation."""
    track_id: int | str
    label: str
    last_bbox: list[float] = field(default_factory=list)
    last_score: float = 0.9
    last_timestamp: float = 0.0
    kinematics: _PedestrianKinematics | None = None
    history_detections: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CrowdEventContext:
    taxonomy: str
    severity: str
    crowd_count: int
    anchor_time: float
    detection_time: float
    involved_track_ids: list[int | str]
    confidence: float
    pedestrians: list[_PedestrianState]
    extra_payload: dict[str, Any] | None = None


def _pedestrian_scale(p: _PedestrianState) -> float:
    if len(p.last_bbox) == 4:
        return max(1.0, abs(p.last_bbox[2] - p.last_bbox[0]), abs(p.last_bbox[3] - p.last_bbox[1]))
    return 100.0


def _spatial_clusters(pedestrians: list[_PedestrianState]) -> list[list[_PedestrianState]]:
    """Group pedestrians into perspective-aware spatial connected components."""
    valid = [p for p in pedestrians if p.kinematics is not None]
    scales = [_pedestrian_scale(p) for p in valid]
    visited = [False] * len(valid)
    clusters: list[list[_PedestrianState]] = []
    for idx in range(len(valid)):
        if visited[idx]:
            continue
        visited[idx] = True
        queue = [idx]
        comp = [valid[idx]]
        while queue:
            cur = queue.pop()
            k_cur = valid[cur].kinematics
            if k_cur is None:
                continue
            for nxt in range(len(valid)):
                if visited[nxt]:
                    continue
                k_nxt = valid[nxt].kinematics
                if k_nxt is None:
                    continue
                # Link radius scales with the smaller bbox to prevent foreground actors from swallowing distant background
                max_dist = max(120.0, 2.5 * min(scales[cur], scales[nxt]))
                if math.hypot(k_cur.cx - k_nxt.cx, k_cur.cy - k_nxt.cy) <= max_dist:
                    visited[nxt] = True
                    queue.append(nxt)
                    comp.append(valid[nxt])
        clusters.append(comp)
    return clusters


class CrowdIncidentEngine:
    """Independent edge incident detection engine for crowd concentration & suspected disorder (Ticket #63 / US06).

    Factory: "crowd_incident"
    """

    factory: str = "crowd_incident"

    def __init__(
        self,
        camera_id: str = "camera-001",
        device_id: str = "device-edge-001",
        stream_session_id: str | None = None,
        pipeline_id: str = "crowd-incident-pipeline-v1",
        pipeline_version: str = "1",
        config_version: str = "crowd-incident-v1",
        origin: str = "live",
        model_artifact_hash: str = "sha256-crowd-incident-v1",
        calibration_version: str = "uncalibrated-image-v1",
        quality_state: str = "normal",
        roi_polygon: Sequence[Sequence[float]] | None = None,
        # Layer 1: Crowd Concentration
        min_crowd_count: int = 5,
        min_duration_seconds: float = 3.0,
        crowd_severity: str = "medium",
        # Layer 2: Suspected Disorder
        min_disorder_count: int = 3,
        disorder_severity: str = "high",
        disorder_speed_threshold: float = 45.0,
        disorder_acceleration_threshold: float = 60.0,
        disorder_dispersal_threshold: float = 25.0,
        disorder_direction_variance_threshold: float = 0.6,
        # Controls
        max_observation_gap: float = 1.0,
        cooldown_seconds: float = 10.0,
        schedule_filter: Callable[[float], bool] | dict[str, Any] | None = None,
        exceptions: Sequence[Any] | None = None,
        frame_dimensions: tuple[float, float] | None = None,
        module_name: str | None = None,
    ) -> None:
        self.camera_id = str(camera_id)
        self.device_id = str(device_id)
        self.stream_session_id = str(stream_session_id) if stream_session_id is not None else str(uuid4())
        self.pipeline_id = str(pipeline_id)
        self.pipeline_version = str(pipeline_version)
        self.config_version = str(config_version)
        self.origin = str(origin)
        self.model_artifact_hash = str(model_artifact_hash)
        self.module = str(module_name) if module_name is not None else self.factory
        self.rule_lineage: list[dict[str, str]] = [{"role": "crowd_incident", "version": "1.0.0"}]
        self.calibration_version = str(calibration_version)
        self.quality_state = str(quality_state)
        self.frame_dimensions = frame_dimensions
        self.roi_polygon = roi_polygon

        # Layer 1 parameters
        self.min_crowd_count = int(min_crowd_count)
        self.min_duration_seconds = float(min_duration_seconds)
        self.crowd_severity = str(crowd_severity)

        # Layer 2 parameters
        self.min_disorder_count = int(min_disorder_count)
        self.disorder_severity = str(disorder_severity)
        self.disorder_speed_threshold = float(disorder_speed_threshold)
        self.disorder_acceleration_threshold = float(disorder_acceleration_threshold)
        self.disorder_dispersal_threshold = float(disorder_dispersal_threshold)
        self.disorder_direction_variance_threshold = float(disorder_direction_variance_threshold)

        # General controls
        self.max_observation_gap = float(max_observation_gap)
        self.cooldown_seconds = float(cooldown_seconds)
        self.schedule_filter = schedule_filter
        self.exceptions = tuple(exceptions or ())

        # Internal state
        self._tracks: dict[int | str, _PedestrianState] = {}
        self._crowd_start_time: float | None = None
        self._last_crowd_alert_time: float | None = None
        self._last_disorder_alert_time: float | None = None
        self._last_timestamp: float | None = None
        self._current_crowd_count: int = 0

    @property
    def current_crowd_count(self) -> int:
        """Current number of pedestrian tracks within ROI."""
        return self._current_crowd_count

    @property
    def is_crowd_persisting(self) -> bool:
        """Whether a crowd >= min_crowd_count is currently persisting."""
        return self._crowd_start_time is not None

    @property
    def crowd_persistence_duration(self) -> float:
        """Current persistence duration of the crowd in seconds."""
        if self._crowd_start_time is None or self._last_timestamp is None:
            return 0.0
        return max(0.0, self._last_timestamp - self._crowd_start_time)

    def reset(self) -> None:
        """Clear all internal tracking states, persistence timers, and alert history."""
        self._tracks.clear()
        self._crowd_start_time = None
        self._last_crowd_alert_time = None
        self._last_disorder_alert_time = None
        self._last_timestamp = None
        self._current_crowd_count = 0

    def observation_gap(self) -> None:
        """Reset kinematics and crowd persistence timer across an observation gap."""
        self._crowd_start_time = None
        self._current_crowd_count = 0
        for state in self._tracks.values():
            state.kinematics = None
        self._last_timestamp = None

    def _is_schedule_active(self, ts: float) -> bool:
        """Evaluate if the engine is active at given timestamp under optional schedule."""
        if self.schedule_filter is None:
            return True
        if callable(self.schedule_filter):
            return bool(self.schedule_filter(ts))
        if isinstance(self.schedule_filter, dict):
            # Dict form: e.g. {"active_hours": [(8, 17)]}
            active_hours = self.schedule_filter.get("active_hours")
            if active_hours:
                hour = (ts / 3600.0) % 24.0
                return any(start <= hour <= end for start, end in active_hours)
        return True

    def _in_roi(self, bbox: list[float], cx: float, cy: float, frame_dimensions: tuple[float, float] | None = None) -> bool:
        """Check if track center or bottom-center is within configured ROI."""
        if self.roi_polygon is None:
            return True
        foot_x = (bbox[0] + bbox[2]) / 2.0
        foot_y = float(bbox[3])
        dims = frame_dimensions or self.frame_dimensions
        if is_normalized_polygon(self.roi_polygon) and dims is not None and dims[0] > 1.0 and dims[1] > 1.0:
            w, h = float(dims[0]), float(dims[1])
            return (
                point_in_polygon(foot_x / w, foot_y / h, self.roi_polygon)
                or point_in_polygon(cx / w, cy / h, self.roi_polygon)
            )
        return (
            point_in_polygon(foot_x, foot_y, self.roi_polygon)
            or point_in_polygon(cx, cy, self.roi_polygon)
        )
    def _update_kinematics(self, state: _PedestrianState, ts: float, cx: float, cy: float) -> _PedestrianKinematics:
        prev = state.kinematics
        if prev is None or (ts - prev.timestamp) <= 0.0 or (ts - prev.timestamp) > self.max_observation_gap:
            k = _PedestrianKinematics(
                track_id=state.track_id,
                timestamp=ts,
                cx=cx,
                cy=cy,
                vx=0.0,
                vy=0.0,
                speed=0.0,
                acceleration=0.0,
                heading=0.0,
            )
            state.kinematics = k
            return k

        dt = max(0.04, ts - prev.timestamp)
        raw_vx = (cx - prev.cx) / dt
        raw_vy = (cy - prev.cy) / dt
        raw_speed = math.hypot(raw_vx, raw_vy)
        # Suppress single-frame bounding box noise spikes
        raw_acc = max(-150.0, min(150.0, (raw_speed - prev.speed) / dt))

        # Exponential smoothing with alpha ~ 0.6
        alpha = min(0.8, max(0.1, dt / 0.20))
        vx = alpha * raw_vx + (1.0 - alpha) * prev.vx
        vy = alpha * raw_vy + (1.0 - alpha) * prev.vy
        speed = math.hypot(vx, vy)
        acc = alpha * raw_acc + (1.0 - alpha) * prev.acceleration
        heading = math.atan2(vy, vx) if speed > 5.0 else prev.heading

        k = _PedestrianKinematics(
            track_id=state.track_id,
            timestamp=ts,
            cx=cx,
            cy=cy,
            vx=vx,
            vy=vy,
            speed=speed,
            acceleration=acc,
            heading=heading,
        )
        state.kinematics = k
        return k

    def _evaluate_cluster_disorder(
        self,
        cluster: list[_PedestrianState],
    ) -> tuple[bool, dict[str, Any]]:
        kin_list = [p.kinematics for p in cluster if p.kinematics is not None]
        if len(kin_list) < self.min_disorder_count:
            return False, {}

        speeds = [k.speed for k in kin_list]
        mean_speed = sum(speeds) / len(speeds)
        accelerations = [abs(k.acceleration) for k in kin_list]
        mean_acc = sum(accelerations) / len(accelerations)

        # 1. Cluster center of mass & Dispersal Divergence
        cm_x = sum(k.cx for k in kin_list) / len(kin_list)
        cm_y = sum(k.cy for k in kin_list) / len(kin_list)

        radial_velocities: list[float] = []
        for k in kin_list:
            dx = k.cx - cm_x
            dy = k.cy - cm_y
            dist = math.hypot(dx, dy)
            if dist > 1e-3:
                v_radial = (k.vx * dx + k.vy * dy) / dist
                radial_velocities.append(v_radial)
            else:
                radial_velocities.append(0.0)

        mean_dispersal = sum(radial_velocities) / len(radial_velocities) if radial_velocities else 0.0
        dispersing_count = sum(1 for v in radial_velocities if v >= 15.0)

        # 2. Direction variance (circular variance = 1 - R)
        moving_kin = [k for k in kin_list if k.speed >= 10.0]
        if len(moving_kin) >= 2:
            sum_cos = sum(math.cos(k.heading) for k in moving_kin)
            sum_sin = sum(math.sin(k.heading) for k in moving_kin)
            r_norm = math.hypot(sum_cos, sum_sin) / len(moving_kin)
            dir_variance = max(0.0, 1.0 - r_norm)
        else:
            dir_variance = 0.0

        # Dispersal requires >= 2 people scattering outward so 1 fast individual cannot trigger a crowd alert
        is_dispersal = (
            mean_dispersal >= self.disorder_dispersal_threshold
            and mean_speed >= 25.0
            and dispersing_count >= 2
            and any(s >= 30.0 for s in speeds)
        )

        surging_count = sum(
            1 for k in kin_list if k.speed >= self.disorder_speed_threshold and abs(k.acceleration) >= 40.0
        )
        is_surge = (
            mean_speed >= self.disorder_speed_threshold
            and mean_acc >= self.disorder_acceleration_threshold
            and surging_count >= 2
        )

        is_chaotic = (
            dir_variance >= self.disorder_direction_variance_threshold
            and mean_speed >= 30.0
            and any(s >= self.disorder_speed_threshold for s in speeds)
            and len(moving_kin) >= self.min_disorder_count
        )

        is_disorder = is_dispersal or is_surge or is_chaotic

        reason = []
        if is_dispersal:
            reason.append("rapid_dispersal_divergence")
        if is_surge:
            reason.append("aggressive_kinetic_surge")
        if is_chaotic:
            reason.append("chaotic_erratic_motion")

        metrics = {
            "mean_speed": round(mean_speed, 2),
            "mean_acceleration": round(mean_acc, 2),
            "dispersal_rate": round(mean_dispersal, 2),
            "direction_variance": round(dir_variance, 3),
            "reasons": reason,
        }
        return is_disorder, metrics

    def _find_disorder_cluster(
        self,
        pedestrians_in_roi: list[_PedestrianState],
    ) -> tuple[bool, dict[str, Any], list[_PedestrianState]]:
        if len(pedestrians_in_roi) < self.min_disorder_count:
            return False, {}, []
        last_metrics: dict[str, Any] = {}
        for cluster in _spatial_clusters(pedestrians_in_roi):
            if len(cluster) < self.min_disorder_count:
                continue
            is_disorder, metrics = self._evaluate_cluster_disorder(cluster)
            if is_disorder:
                return True, metrics, cluster
            last_metrics = metrics
        return False, last_metrics, []

    def _evaluate_disorder(
        self,
        pedestrians_in_roi: list[_PedestrianState],
        ts: float,
    ) -> tuple[bool, dict[str, Any]]:
        """Evaluate Layer 2: Suspected Public Disorder across local spatial clusters."""
        is_disorder, metrics, _ = self._find_disorder_cluster(pedestrians_in_roi)
        return is_disorder, metrics

    def _create_facts(self, ctx: CrowdEventContext) -> dict[str, Any]:
        """Return rule facts (anchor kind and scenario payload); snapshot assembly belongs to the caller."""
        detections: list[dict[str, Any]] = []
        for p in ctx.pedestrians:
            detections.extend(p.history_detections[-10:])
        if len(detections) > 40:
            detections = detections[-40:]

        payload: dict[str, Any] = {
            "taxonomy": ctx.taxonomy,
            "severity": ctx.severity,
            "crowd_count": int(ctx.crowd_count),
            "confidence": round(float(ctx.confidence), 3),
            "track_id": ctx.involved_track_ids[0] if ctx.involved_track_ids else None,
            "track_ids": ctx.involved_track_ids,
            "anchor_time": float(ctx.anchor_time),
            "detection_time": float(ctx.detection_time),
            "detections": detections,
        }
        if ctx.extra_payload:
            payload.update(ctx.extra_payload)

        return {
            "anchor_kind": "alert_condition",
            "payload": payload,
        }

    def process_tracks(
        self,
        tracks: list[Track] | list[dict[str, Any]],
        timestamp: float,
        frame_dimensions: tuple[float, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate pedestrian tracks at timestamp and return validated event snapshots for any triggered incidents."""
        dims = frame_dimensions or self.frame_dimensions
        ts = float(timestamp)

        # 0. Check observation gap / backwards jump
        if self._last_timestamp is not None:
            if ts < self._last_timestamp or (ts - self._last_timestamp) > self.max_observation_gap:
                self.observation_gap()

        self._last_timestamp = ts

        # 1. Check schedule filter if provided
        if not self._is_schedule_active(ts):
            self._crowd_start_time = None
            self._current_crowd_count = 0
            return []

        # 2. Filter pedestrian tracks in ROI
        active_ids: set[int | str] = set()
        pedestrians_in_roi: list[_PedestrianState] = []

        for track in tracks:
            tid, label, bbox, score, cx, cy = _extract_track_data(track)
            if label not in PEDESTRIAN_LABELS:
                continue

            active_ids.add(tid)

            # Check if in ROI
            if not self._in_roi(bbox, cx, cy, frame_dimensions=dims):
                continue

            state = self._tracks.get(tid)
            if state is None:
                state = _PedestrianState(track_id=tid, label=label)
                self._tracks[tid] = state

            state.last_bbox = bbox
            state.last_score = score
            state.last_timestamp = ts
            state.history_detections.append({
                "bbox": bbox,
                "score": score,
                "timestamp": ts,
                "label": state.label,
            })
            if len(state.history_detections) > 32:
                state.history_detections[:] = state.history_detections[-20:]

            self._update_kinematics(state, ts, cx, cy)
            pedestrians_in_roi.append(state)

        # Prune inactive tracks
        for stale_id in [t for t in self._tracks if t not in active_ids]:
            del self._tracks[stale_id]

        count = len(pedestrians_in_roi)
        self._current_crowd_count = count
        involved_ids = [p.track_id for p in pedestrians_in_roi]
        events: list[dict[str, Any]] = []

        # 3. Layer 1: Crowd Concentration
        has_queue_exception = bool(
            self.exceptions
            and any(
                any(keyword in str(getattr(e, "code", e)).lower() for keyword in ("queue", "bus_stop", "transit", "waiting", "event"))
                for e in self.exceptions
            )
        )
        if count >= self.min_crowd_count and not has_queue_exception:
            if self._crowd_start_time is None:
                self._crowd_start_time = ts

            persistence_duration = ts - self._crowd_start_time
            if persistence_duration >= self.min_duration_seconds:
                # Check cooldown
                if self._last_crowd_alert_time is None or (ts - self._last_crowd_alert_time) >= self.cooldown_seconds:
                    # Active alert-condition anchor: on first trigger, anchor is when threshold was met; on subsequent alerts, anchor is current ts
                    anchor = (self._crowd_start_time + self.min_duration_seconds) if self._last_crowd_alert_time is None else ts
                    ctx = CrowdEventContext(
                        taxonomy="crowd_concentration",
                        severity=self.crowd_severity,
                        crowd_count=count,
                        anchor_time=anchor,
                        detection_time=ts,
                        involved_track_ids=involved_ids,
                        confidence=0.95,
                        pedestrians=pedestrians_in_roi,
                        extra_payload={"persistence_seconds": round(persistence_duration, 2)},
                    )
                    events.append(self._create_facts(ctx))
                    self._last_crowd_alert_time = ts
        else:
            # Drops below threshold or excepted: reset persistence timer
            self._crowd_start_time = None

        # 4. Layer 2: Suspected Public Disorder
        is_disorder, metrics, disorder_cluster = self._find_disorder_cluster(pedestrians_in_roi)
        if is_disorder:
            if self._last_disorder_alert_time is None or (ts - self._last_disorder_alert_time) >= self.cooldown_seconds:
                ctx = CrowdEventContext(
                    taxonomy="suspected_disorder",
                    severity=self.disorder_severity,
                    crowd_count=len(disorder_cluster),
                    anchor_time=ts,
                    detection_time=ts,
                    involved_track_ids=[p.track_id for p in disorder_cluster],
                    confidence=0.92,
                    pedestrians=disorder_cluster,
                    extra_payload={"disorder_metrics": metrics},
                )
                events.append(self._create_facts(ctx))
                self._last_disorder_alert_time = ts

        return events
