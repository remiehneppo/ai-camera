"""Vehicle Incident Engine for edge vehicle accident detection (Task I06 / US08).

Evaluates vehicle tracks (car, motorcycle, bicycle, bus, truck) and pedestrian tracks in
roadway ROI (point_in_polygon).
3 US08 Branches:
1) vehicle_vehicle: Two moving vehicles converging with sudden deceleration, post-collision halt
   or trajectory deflection.
2) vehicle_pedestrian: Moving vehicle and pedestrian with convergence, rapid deceleration,
   or proximity followed by person down/impact.
3) vehicle_rollover_or_barrier: Vehicle experiencing sudden aspect ratio inversion (two-wheeler
   fallen over or car rollover) or abrupt deceleration into stationary state within roadway ROI.

Rejects hard negatives:
- Red-light stop / traffic jam: smooth deceleration into upright stationary state without
  impact deceleration spike.
- Near-miss: vehicles converge but pass each other smoothly without collision impact or stoppage.
- Perspective overlap: distant/background overlap without convergence velocity or abrupt motion change.
- Stationary vehicle without prior motion: not treated as a crash confirmation.

Generates valid event snapshots passing domain.event_contract.validate_event:
- pipeline_id: "vehicle-incident-pipeline-v1"
- pipeline_version: "1"
- payload["taxonomy"]: "vehicle_incident"
- payload["interaction_type"]: "vehicle_vehicle" | "vehicle_pedestrian" | "vehicle_rollover_or_barrier"
- payload["severity"]: "critical" or "high"
- evidence_requests with Q36 anchor: evidence_anchor_kind="alert_condition",
  requested_start = anchor - 10, requested_end = anchor + 20.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Sequence
from uuid import uuid4

from apps.edge.tracker import Track
from domain.event_contract import validate_event
from domain.evidence_contract import make_evidence_request
from apps.edge.geometry import point_in_polygon
from domain.vehicle_motion import (
    KinematicsTracker,
    KinematicState,
    PairwiseInteractionRisk,
    bbox_iou,
    compute_pairwise_risk,
)

VEHICLE_LABELS: frozenset[str] = frozenset({"car", "motorcycle", "bicycle", "bus", "truck"})
TWO_WHEELER_LABELS: frozenset[str] = frozenset({"motorcycle", "bicycle"})
PEDESTRIAN_LABELS: frozenset[str] = frozenset({"person", "pedestrian"})


@dataclass
class _TrackState:
    track_id: int | str
    label: str
    tracker: KinematicsTracker
    last_kinematics: KinematicState | None = None
    last_bbox: list[float] = field(default_factory=list)
    last_score: float = 0.9
    last_timestamp: float = 0.0
    history_detections: list[dict[str, Any]] = field(default_factory=list)
    was_moving: bool = False
    max_speed: float = 0.0
    is_stationary: bool = True
    stationary_since: float | None = None
    initial_aspect_ratio: float | None = None
    last_aspect_ratio: float | None = None
    initial_is_upright: bool = True
    heading_before_convergence: float | None = None
    last_deceleration_spike_time: float | None = None
    last_alert_time: float | None = None


@dataclass
class _PairState:
    id1: int | str
    id2: int | str
    had_convergence: bool = False
    last_convergence_time: float | None = None
    prev_iou: float = 0.0
    max_closing_speed: float = 0.0
    last_alert_time: float | None = None


class VehicleIncidentEngine:
    """Independent edge incident detection engine for vehicle accidents (factory: 'vehicle_incident')."""

    factory: str = "vehicle_incident"

    def __init__(
        self,
        camera_id: str = "camera-001",
        device_id: str = "device-edge-001",
        stream_session_id: str | None = None,
        pipeline_id: str = "vehicle-incident-pipeline-v1",
        pipeline_version: str = "1",
        config_version: str = "vehicle-incident-v1",
        origin: str = "live",
        model_artifact_hash: str = "sha256-vehicle-incident-v1",
        calibration_version: str = "uncalibrated-image-v1",
        quality_state: str = "nominal",
        roi_polygon: Sequence[Sequence[float]] | None = None,
        max_observation_gap: float = 1.0,
        cooldown_seconds: float = 10.0,
        min_moving_speed: float = 20.0,
        stationary_speed: float = 8.0,
        impact_deceleration_threshold: float = 120.0,
        deflection_threshold: float = 0.5,
        two_wheeler_rollover_ar: float = 1.2,
        two_wheeler_upright_ar: float = 1.15,
        car_rollover_ar_delta: float = 0.5,
        pedestrian_drop_velocity: float = 15.0,
        pedestrian_lying_ar: float = 1.2,
        proximity_distance: float = 80.0,
    ) -> None:
        self.camera_id = str(camera_id)
        self.device_id = str(device_id)
        self.stream_session_id = str(stream_session_id) if stream_session_id is not None else str(uuid4())
        self.pipeline_id = str(pipeline_id)
        self.pipeline_version = str(pipeline_version)
        self.config_version = str(config_version)
        self.origin = str(origin)
        self.model_artifact_hash = str(model_artifact_hash)
        self.calibration_version = str(calibration_version)
        self.quality_state = str(quality_state)
        self.roi_polygon = roi_polygon
        self.max_observation_gap = float(max_observation_gap)
        self.cooldown_seconds = float(cooldown_seconds)
        self.min_moving_speed = float(min_moving_speed)
        self.stationary_speed = float(stationary_speed)
        self.impact_deceleration_threshold = float(impact_deceleration_threshold)
        self.deflection_threshold = float(deflection_threshold)
        self.two_wheeler_rollover_ar = float(two_wheeler_rollover_ar)
        self.two_wheeler_upright_ar = float(two_wheeler_upright_ar)
        self.car_rollover_ar_delta = float(car_rollover_ar_delta)
        self.pedestrian_drop_velocity = float(pedestrian_drop_velocity)
        self.pedestrian_lying_ar = float(pedestrian_lying_ar)
        self.proximity_distance = float(proximity_distance)

        self._tracks: dict[int | str, _TrackState] = {}
        self._pairs: dict[tuple[int | str, int | str], _PairState] = {}

    def reset(self) -> None:
        """Clear all internal tracking states and history."""
        self._tracks.clear()
        self._pairs.clear()

    def observation_gap(self) -> None:
        """Reset kinematics and continuous history across an observation gap."""
        for state in self._tracks.values():
            state.tracker.reset()
            state.last_kinematics = None
            state.heading_before_convergence = None
            state.last_deceleration_spike_time = None
        self._pairs.clear()

    def _in_roi(self, track: Track) -> bool:
        if self.roi_polygon is None:
            return True
        foot_x = (track.bbox[0] + track.bbox[2]) / 2.0
        foot_y = float(track.bbox[3])
        return (
            point_in_polygon(foot_x, foot_y, self.roi_polygon)
            or point_in_polygon(track.cx, track.cy, self.roi_polygon)
        )

    def _get_or_create_track(self, track: Track, ts: float) -> _TrackState:
        tid = track.track_id
        state = self._tracks.get(tid)
        if state is None:
            ar = float(track.aspect_ratio)
            if track.label in TWO_WHEELER_LABELS:
                is_upright = ar < self.two_wheeler_upright_ar
            elif track.label in PEDESTRIAN_LABELS:
                is_upright = ar < self.pedestrian_lying_ar
            else:
                is_upright = True
            state = _TrackState(
                track_id=tid,
                label=track.label,
                tracker=KinematicsTracker(max_observation_gap=self.max_observation_gap),
                initial_aspect_ratio=ar,
                last_aspect_ratio=ar,
                initial_is_upright=is_upright,
            )
            self._tracks[tid] = state
        return state

    def _get_or_create_pair(self, id1: int | str, id2: int | str) -> _PairState:
        key = (id1, id2) if str(id1) <= str(id2) else (id2, id1)
        pair = self._pairs.get(key)
        if pair is None:
            pair = _PairState(id1=key[0], id2=key[1])
            self._pairs[key] = pair
        return pair

    def _build_event(
        self,
        interaction_type: str,
        severity: str,
        anchor_time: float,
        detection_time: float,
        primary_track_id: int | str,
        involved_track_ids: list[int | str],
        confidence: float,
        tracks: list[_TrackState],
    ) -> dict[str, Any]:
        """Construct, validate, and return a validated full-snapshot event contract dictionary."""
        event_id = str(uuid4())
        message_id = f"msg-{uuid4().hex[:12]}"
        request_id = f"req-{uuid4().hex[:12]}"
        now_iso = (
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

        evidence_request = make_evidence_request(
            request_id=request_id,
            session_id=self.stream_session_id,
            anchor_kind="alert_condition",
            anchor_time=anchor_time,
        )

        detections: list[dict[str, Any]] = []
        for t in tracks:
            detections.extend(t.history_detections[-10:])

        payload: dict[str, Any] = {
            "quality": {
                "state": self.quality_state,
                "odd_supported": True if self.quality_state == "normal" else None,
            },
            "taxonomy": "vehicle_incident",
            "interaction_type": interaction_type,
            "severity": severity,
            "confidence": round(float(confidence), 3),
            "track_id": primary_track_id,
            "track_ids": involved_track_ids,
            "anchor_time": anchor_time,
            "detection_time": detection_time,
            "detections": detections,
            "evidence_requests": [evidence_request],
        }

        event_snapshot: dict[str, Any] = {
            "schema_version": 1,
            "message_id": message_id,
            "event_id": event_id,
            "revision": 1,
            "device_id": self.device_id,
            "camera_id": self.camera_id,
            "stream_session_id": self.stream_session_id,
            "pipeline_id": self.pipeline_id,
            "pipeline_version": self.pipeline_version,
            "origin": self.origin,
            "event_time": now_iso,
            "produced_at": now_iso,
            "config_version": self.config_version,
            "model_lineage": [
                {"role": "vehicle_motion", "version": "1.0.0"},
                {"role": "vehicle_incident", "version": "1.0.0"},
            ],
            "model_artifact_hash": self.model_artifact_hash,
            "calibration_version": self.calibration_version,
            "quality_state": self.quality_state,
            "payload": payload,
        }

        return validate_event(event_snapshot)

    def process_tracks(
        self,
        tracks: list[Track],
        timestamp: float,
    ) -> list[dict[str, Any]]:
        """Evaluate tracks at timestamp and return validated event snapshots for any triggered incidents."""
        ts = float(timestamp)
        events: list[dict[str, Any]] = []

        # 1. Update kinematics and track state for tracks in ROI
        active_track_ids: set[int | str] = set()
        for track in tracks:
            tid = track.track_id
            active_track_ids.add(tid)
            if not self._in_roi(track):
                continue

            state = self._get_or_create_track(track, ts)
            k = state.tracker.update(ts, track.cx, track.cy)
            state.last_kinematics = k
            state.last_bbox = list(track.bbox)
            state.last_score = float(track.score)
            state.last_timestamp = ts
            state.last_aspect_ratio = float(track.aspect_ratio)

            state.history_detections.append({
                "bbox": list(track.bbox),
                "score": float(track.score),
                "timestamp": ts,
                "label": track.label,
            })
            if len(state.history_detections) > 32:
                state.history_detections[:] = state.history_detections[-20:]

            # Prior motion tracking
            if k.speed >= self.min_moving_speed:
                state.was_moving = True
                state.max_speed = max(state.max_speed, k.speed)

            # Stationary tracking
            if k.speed <= self.stationary_speed:
                state.is_stationary = True
                if state.stationary_since is None:
                    state.stationary_since = ts
            else:
                state.is_stationary = False
                state.stationary_since = None

            # Deceleration spike tracking (< -120 px/s^2)
            if k.acceleration <= -self.impact_deceleration_threshold:
                state.last_deceleration_spike_time = ts

        # Clean up stale tracks outside current frame
        for stale_id in [tid for tid in self._tracks if tid not in active_track_ids]:
            del self._tracks[stale_id]
        # Clean up stale pairs whose tracks are no longer active (bounded memory)
        for pair_key in [k for k in self._pairs if k[0] not in active_track_ids or k[1] not in active_track_ids]:
            del self._pairs[pair_key]

        # 2. Branch 1: vehicle_vehicle (pairwise vehicle interaction) evaluated first
        vehicle_states = [s for s in self._tracks.values() if s.label in VEHICLE_LABELS and s.last_kinematics is not None]
        for i in range(len(vehicle_states)):
            for j in range(i + 1, len(vehicle_states)):
                v1 = vehicle_states[i]
                v2 = vehicle_states[j]
                k1 = v1.last_kinematics
                k2 = v2.last_kinematics
                if k1 is None or k2 is None:
                    continue

                pair = self._get_or_create_pair(v1.track_id, v2.track_id)
                risk = compute_pairwise_risk(
                    v1.track_id, k1, v1.last_bbox,
                    v2.track_id, k2, v2.last_bbox,
                    prev_iou=pair.prev_iou,
                    dt=0.1,
                )
                pair.prev_iou = risk.iou

                # Filter duplicate detections of the same physical vehicle under multiple classes (e.g. bus vs truck)
                # Two distinct vehicles cannot physically occupy >= 65% of each other's 2D bounding box
                if risk.iou >= 0.65:
                    continue

                # Convergence detection
                if risk.closing_speed > 10.0 or risk.iou > 0.05 or risk.risk_level in ("high", "critical"):
                    if not pair.had_convergence:
                        v1.heading_before_convergence = k1.heading
                        v2.heading_before_convergence = k2.heading
                    pair.had_convergence = True
                    pair.last_convergence_time = ts
                    pair.max_closing_speed = max(pair.max_closing_speed, risk.closing_speed)

                if not pair.had_convergence or pair.last_convergence_time is None:
                    continue
                if (ts - pair.last_convergence_time) > 2.0:
                    continue

                # Hard negative: Both vehicles must have had prior motion!
                if not (v1.was_moving and v2.was_moving):
                    continue

                # Check cooldown
                if pair.last_alert_time is not None and (ts - pair.last_alert_time) < self.cooldown_seconds:
                    continue
                if v1.last_alert_time is not None and (ts - v1.last_alert_time) < self.cooldown_seconds:
                    continue
                if v2.last_alert_time is not None and (ts - v2.last_alert_time) < self.cooldown_seconds:
                    continue

                # Kinetic collision evidence:
                # Evidence 1: Deceleration spike in either vehicle with halt
                decel_1 = (
                    v1.last_deceleration_spike_time is not None
                    and (ts - v1.last_deceleration_spike_time) <= 1.5
                )
                decel_2 = (
                    v2.last_deceleration_spike_time is not None
                    and (ts - v2.last_deceleration_spike_time) <= 1.5
                )
                one_halted = v1.is_stationary or v2.is_stationary
                both_halted = v1.is_stationary and v2.is_stationary

                # Evidence 2: Trajectory deflection
                deflected = False
                if v1.heading_before_convergence is not None and not v1.is_stationary:
                    dh1 = abs((k1.heading - v1.heading_before_convergence + math.pi) % (2 * math.pi) - math.pi)
                    if dh1 >= self.deflection_threshold:
                        deflected = True
                if v2.heading_before_convergence is not None and not v2.is_stationary:
                    dh2 = abs((k2.heading - v2.heading_before_convergence + math.pi) % (2 * math.pi) - math.pi)
                    if dh2 >= self.deflection_threshold:
                        deflected = True

                has_collision = False
                # Collision requires mutual impact evidence:
                # 1) At least one vehicle experienced an impact deceleration spike and halted
                if (decel_1 and decel_2) and one_halted:
                    has_collision = True
                elif (decel_1 or decel_2) and both_halted and (pair.max_closing_speed > 20.0 or risk.iou > 0.1):
                    has_collision = True
                elif (decel_1 or decel_2 or risk.iou > 0.15) and deflected:
                    has_collision = True
                elif both_halted and risk.iou > 0.2 and pair.max_closing_speed > 25.0:
                    has_collision = True

                if has_collision:
                    pair.last_alert_time = ts
                    v1.last_alert_time = ts
                    v2.last_alert_time = ts
                    sev = "critical" if (pair.max_closing_speed > 30.0 or risk.iou > 0.2) else "high"
                    conf = min(0.99, max(0.85, (v1.last_score + v2.last_score) / 2.0))
                    event = self._build_event(
                        interaction_type="vehicle_vehicle",
                        severity=sev,
                        anchor_time=ts,
                        detection_time=ts,
                        primary_track_id=v1.track_id,
                        involved_track_ids=[v1.track_id, v2.track_id],
                        confidence=conf,
                        tracks=[v1, v2],
                    )
                    events.append(event)

        # 3. Branch 3: vehicle_rollover_or_barrier (single-vehicle accident)
        for state in list(self._tracks.values()):
            if state.label not in VEHICLE_LABELS:
                continue
            if state.last_kinematics is None:
                continue
            if not state.was_moving:
                # Rule: Stationary vehicle without prior motion is NOT a crash confirmation
                continue
            if state.last_alert_time is not None and (ts - state.last_alert_time) < self.cooldown_seconds:
                continue

            triggered = False
            severity = "critical"

            # Case 3a: Two-wheeler fallen over (was moving upright, aspect ratio inverted to horizontal)
            if state.label in TWO_WHEELER_LABELS:
                ar = state.last_aspect_ratio or 0.0
                if state.initial_is_upright and ar >= self.two_wheeler_rollover_ar:
                    triggered = True
                    severity = "critical"

            # Case 3b: Car rollover
            elif state.label in ("car", "truck", "bus"):
                ar = state.last_aspect_ratio or 1.8
                init_ar = state.initial_aspect_ratio or 1.8
                # Rollover requires aspect ratio inversion from wide to narrow/tall while stopped or impacting
                had_halt_or_impact = state.is_stationary or (
                    state.last_deceleration_spike_time is not None
                    and (ts - state.last_deceleration_spike_time) <= 1.5
                )
                if (init_ar - ar) >= self.car_rollover_ar_delta and had_halt_or_impact:
                    triggered = True
                    severity = "critical"

            # Case 3c: Abrupt deceleration into stationary state (barrier crash)
            if not triggered:
                # Barrier crash applies to single vehicle not involved in a multi-vehicle convergence
                had_pair_convergence = any(
                    pair.had_convergence
                    and pair.last_convergence_time is not None
                    and (ts - pair.last_convergence_time) <= 1.5
                    for pair in self._pairs.values()
                    if pair.id1 == state.track_id or pair.id2 == state.track_id
                )
                had_spike = (
                    state.last_deceleration_spike_time is not None
                    and (ts - state.last_deceleration_spike_time) <= 1.5
                )
                if had_spike and state.is_stationary and not had_pair_convergence:
                    triggered = True
                    severity = "high"

            if triggered:
                state.last_alert_time = ts
                event = self._build_event(
                    interaction_type="vehicle_rollover_or_barrier",
                    severity=severity,
                    anchor_time=ts,
                    detection_time=ts,
                    primary_track_id=state.track_id,
                    involved_track_ids=[state.track_id],
                    confidence=round(float(state.last_score), 3),
                    tracks=[state],
                )
                events.append(event)

        # 4. Branch 2: vehicle_pedestrian
        pedestrian_states = [s for s in self._tracks.values() if s.label in PEDESTRIAN_LABELS and s.last_kinematics is not None]
        for v in vehicle_states:
            if not v.was_moving:
                continue
            vk = v.last_kinematics
            if vk is None:
                continue

            for p in pedestrian_states:
                pk = p.last_kinematics
                if pk is None:
                    continue

                dist = math.hypot(vk.cx - pk.cx, vk.cy - pk.cy)
                iou = bbox_iou(v.last_bbox, p.last_bbox)
                in_proximity = dist <= self.proximity_distance or iou > 0.0

                pair = self._get_or_create_pair(v.track_id, p.track_id)
                if in_proximity or (vk.speed > 15.0 and dist <= self.proximity_distance * 1.5):
                    pair.had_convergence = True
                    pair.last_convergence_time = ts

                if not pair.had_convergence or pair.last_convergence_time is None:
                    continue
                if (ts - pair.last_convergence_time) > 2.0:
                    continue

                if pair.last_alert_time is not None and (ts - pair.last_alert_time) < self.cooldown_seconds:
                    continue
                if v.last_alert_time is not None and (ts - v.last_alert_time) < self.cooldown_seconds:
                    continue
                if p.last_alert_time is not None and (ts - p.last_alert_time) < self.cooldown_seconds:
                    continue

                # Evidence 1: Vehicle experienced rapid deceleration in close proximity
                v_decel = (
                    v.last_deceleration_spike_time is not None
                    and (ts - v.last_deceleration_spike_time) <= 1.5
                )

                # Evidence 2: Pedestrian down / impact (was upright and fell down during interaction)
                p_fell_during_interaction = (
                    p.initial_is_upright
                    and (p.last_aspect_ratio or 0.0) >= self.pedestrian_lying_ar
                )

                # Pre-existing lying person near vehicle without deceleration is NOT a crash confirmation
                if (p_fell_during_interaction and in_proximity) or (v_decel and iou > 0.15 and dist <= self.proximity_distance * 0.8):
                    pair.last_alert_time = ts
                    v.last_alert_time = ts
                    p.last_alert_time = ts
                    conf = min(0.99, max(0.88, (v.last_score + p.last_score) / 2.0))
                    event = self._build_event(
                        interaction_type="vehicle_pedestrian",
                        severity="critical",
                        anchor_time=ts,
                        detection_time=ts,
                        primary_track_id=v.track_id,
                        involved_track_ids=[v.track_id, p.track_id],
                        confidence=conf,
                        tracks=[v, p],
                    )
                    events.append(event)

        return events
