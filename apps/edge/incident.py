"""Behavioral Incident Engine for edge fall detection."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from apps.edge.geometry import is_normalized_polygon, point_in_polygon
from apps.edge.tracker import Track, bbox_iou

_VEHICLE_LABELS = {"motorcycle", "bicycle"}
_TWO_WHEELER_LABELS = {"motorcycle", "bicycle"}


def _normalize_pose_outcome(outcome: Any) -> dict[str, Any] | None:
    """Return the mapping form of a PoseOutcome (or dict) that carries a track id."""
    if isinstance(outcome, dict):
        data = outcome
    else:
        to_dict = getattr(outcome, "to_dict", None)
        if not callable(to_dict):
            return None
        data = to_dict()
    if not isinstance(data, dict) or data.get("track_id") is None:
        return None
    return data


@dataclass
class _TrackIncidentState:
    had_standing: bool = False
    in_fall_candidate: bool = False
    onset_time: float | None = None
    lying_start_time: float | None = None
    lying_onset_time: float | None = None
    on_vehicle_track_id: int | str | None = None
    vehicle_danger: bool = False
    association_iou: float | None = None
    first_qualifying_time: float | None = None
    moving_frames: int = 0
    last_cx: float | None = None
    last_cy: float | None = None
    last_timestamp: float | None = None
    last_alert_time: float | None = None
    triggered: bool = False
    last_valid_pose: dict[str, Any] | None = None
    last_pose_outcome: dict[str, Any] | None = None


def _reset_vehicle_association(state: _TrackIncidentState) -> None:
    state.lying_onset_time = None
    state.on_vehicle_track_id = None
    state.vehicle_danger = False
    state.association_iou = None



@dataclass
class _VehicleState:
    """Stationarity/uprightness history of one vehicle track for on-vehicle association."""

    track_id: int
    label: str
    last_timestamp: float | None = None
    last_bbox: list[float] | None = None
    is_stationary: bool = False
    is_upright: bool = True
    is_fallen: bool = False
    stationary_since: float | None = None
    stable_frames: int = 0
    last_high_speed_time: float | None = None



class IncidentEngine:
    """Behavioral incident detection engine."""

    def __init__(
        self,
        standing_aspect_ratio: float = 0.85,
        lying_aspect_ratio: float = 1.2,
        min_drop_velocity: float = 15.0,
        min_lying_duration: float = 3.0,
        cooldown_seconds: float = 30.0,
        max_motion_speed: float = 50.0,
        persistent_lying_duration: float | None = None,
        persistent_lying_severity: str = "high",
        roi_polygon: list[list[float]] | list[tuple[float, float]] | None = None,
        max_observation_gap: float = 1.0,
        vehicle_upright_aspect_ratio: float = 1.15,
        vehicle_fallen_aspect_ratio: float = 1.2,
        vehicle_stable_duration: float = 1.0,
        vehicle_min_stable_frames: int = 2,
        vehicle_overlap_iou: float = 0.1,
        on_vehicle_severity: str = "low",
        frame_dimensions: tuple[float, float] | None = None,
    ) -> None:
        self.max_observation_gap: float = float(max_observation_gap)
        self.standing_aspect_ratio: float = float(standing_aspect_ratio)
        self.lying_aspect_ratio: float = float(lying_aspect_ratio)
        self.min_drop_velocity: float = float(min_drop_velocity)
        self.min_lying_duration: float = float(min_lying_duration)
        self.cooldown_seconds: float = float(cooldown_seconds)
        self.max_motion_speed: float = float(max_motion_speed)
        self.persistent_lying_duration: float = (
            float(persistent_lying_duration)
            if persistent_lying_duration is not None
            else 3.0
        )
        self.persistent_lying_severity: str = str(persistent_lying_severity)
        self.roi_polygon = roi_polygon
        self.vehicle_upright_aspect_ratio: float = float(vehicle_upright_aspect_ratio)
        self.vehicle_fallen_aspect_ratio: float = float(vehicle_fallen_aspect_ratio)
        self.vehicle_stable_duration: float = float(vehicle_stable_duration)
        self.vehicle_min_stable_frames: int = int(vehicle_min_stable_frames)
        self.vehicle_overlap_iou: float = float(vehicle_overlap_iou)
        self.on_vehicle_severity: str = str(on_vehicle_severity)
        self.frame_dimensions = frame_dimensions
        self._states: dict[int | str, _TrackIncidentState] = {}
        self._vehicle_states: dict[int, _VehicleState] = {}

    @staticmethod
    def _format_detections(track: Track) -> list[dict[str, Any]]:
        return [
            {
                "bbox": obs.bbox,
                "score": obs.score,
                "timestamp": obs.timestamp,
                "label": track.label,
            }
            for obs in track.history[-20:]
        ]

    @staticmethod
    def _record_pose_outcome(state: _TrackIncidentState, outcome: dict[str, Any]) -> None:
        """Store the terminal pose outcome; only an 'ok' outcome yields keypoint evidence."""
        status = outcome.get("status")
        state.last_pose_outcome = {
            "status": status,
            "reason": outcome.get("reason"),
            "branch": outcome.get("branch"),
            "executed_at": outcome.get("executed_at"),
        }
        if status == "ok":
            state.last_valid_pose = {
                "keypoints": list(outcome.get("keypoints") or []),
                "branch": outcome.get("branch"),
                "executed_at": outcome.get("executed_at"),
                "request_id": outcome.get("request_id"),
                "frame_id": outcome.get("frame_id"),
            }
        # skipped/failed/cancelled carry no pose evidence: the previous valid pose stays
        # untouched and the miss is never read as a negative observation.

    @staticmethod
    def _pose_evidence(state: _TrackIncidentState) -> dict[str, Any]:
        """Describe the pose evidence backing an incident without inventing a negative."""
        if state.last_valid_pose is not None:
            return {
                "status": "ok",
                "reason": None,
                "branch": state.last_valid_pose.get("branch"),
                "keypoints": list(state.last_valid_pose.get("keypoints") or []),
                "executed_at": state.last_valid_pose.get("executed_at"),
                "frame_id": state.last_valid_pose.get("frame_id"),
                "request_id": state.last_valid_pose.get("request_id"),
            }
        latest = state.last_pose_outcome
        status = str(latest.get("status") or "none") if latest else "none"
        return {
            "status": status,
            "reason": latest.get("reason") if latest is not None and status != "ok" else None,
            "branch": latest.get("branch") if latest else None,
            "keypoints": [],
            "executed_at": latest.get("executed_at") if latest else None,
            "frame_id": None,
            "request_id": None,
        }

    def _create_incident(
        self,
        *,
        taxonomy: str,
        severity: str,
        anchor_kind: str,
        anchor_time: float,
        detection_time: float,
        track: Track,
        pose_evidence: dict[str, Any] | None = None,
        vehicle_track_id: int | str | None = None,
        association_uncertainty: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        incident = {
            "taxonomy": taxonomy,
            "severity": severity,
            "anchor_kind": anchor_kind,
            "anchor_time": anchor_time,
            "detection_time": detection_time,
            "track_id": track.track_id,
            "confidence": round(float(track.score), 3),
            "detections": self._format_detections(track),
            "pose_evidence": pose_evidence if pose_evidence is not None else {
                "status": "none",
                "reason": None,
                "branch": None,
                "keypoints": [],
                "executed_at": None,
                "frame_id": None,
                "request_id": None,
            },
        }
        if vehicle_track_id is not None:
            incident["vehicle_track_id"] = vehicle_track_id
        if association_uncertainty is not None:
            incident["association_uncertainty"] = association_uncertainty
        return incident

    def reset(self) -> None:
        self._states.clear()
        self._vehicle_states.clear()

    def observation_gap(self):
        for tid, state in self._states.items():
            self._states[tid] = _TrackIncidentState(
                last_alert_time=state.last_alert_time, triggered=state.triggered)
        # A gap breaks continuous stationarity/uprightness evidence for every vehicle.
        self._vehicle_states.clear()

    @staticmethod
    def _in_bbox(bbox: list[float], x: float, y: float) -> bool:
        return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]

    def _vehicle_is_upright(self, track: Track) -> bool:
        """A two-wheeler is upright while its aspect ratio is below the upright threshold."""
        return float(track.aspect_ratio) < self.vehicle_upright_aspect_ratio

    def _vehicle_is_fallen(self, track: Track) -> bool:
        """Fallen/overturned two-wheeler: flat aspect ratio or rapid tilt."""
        aspect_ratio = float(track.aspect_ratio)
        if aspect_ratio >= self.vehicle_fallen_aspect_ratio:
            return True
        return (
            aspect_ratio >= self.vehicle_upright_aspect_ratio
            and float(track.aspect_ratio_change(window_seconds=1.5)) >= 0.35
        )

    def _update_vehicle_states(self, tracks: list[Track], ts: float) -> None:
        """Refresh per-vehicle stationarity/uprightness history from the current frame."""
        observed_ids: set[int] = set()
        for track in tracks:
            label = getattr(track, "label", None)
            if label not in _VEHICLE_LABELS:
                continue
            tid = track.track_id
            observed_ids.add(tid)
            state = self._vehicle_states.get(tid)
            if state is None:
                state = self._vehicle_states[tid] = _VehicleState(track_id=tid, label=str(label))
            speed = 0.0
            gap_or_clock_jump = (
                state.last_timestamp is not None
                and (ts < state.last_timestamp or ts - state.last_timestamp > self.max_observation_gap)
            )
            if state.last_bbox is not None and state.last_timestamp is not None and not gap_or_clock_jump:
                dt = ts - state.last_timestamp
                if dt > 0.0:
                    prev_cx = (state.last_bbox[0] + state.last_bbox[2]) / 2.0
                    prev_cy = (state.last_bbox[1] + state.last_bbox[3]) / 2.0
                    speed = math.hypot(track.cx - prev_cx, track.cy - prev_cy) / dt
            state.last_timestamp = ts
            state.last_bbox = list(track.bbox)
            state.is_stationary = speed <= self.max_motion_speed
            if not state.is_stationary:
                state.last_high_speed_time = ts
            state.is_upright = self._vehicle_is_upright(track)
            state.is_fallen = self._vehicle_is_fallen(track)
            if gap_or_clock_jump:
                state.stationary_since = ts if (state.is_stationary and state.is_upright) else None
                state.stable_frames = 1 if (state.is_stationary and state.is_upright) else 0
            elif state.is_stationary and state.is_upright:
                if state.stationary_since is None:
                    state.stationary_since = ts
                    state.stable_frames = 1
                else:
                    state.stable_frames += 1
            else:
                state.stationary_since = None
                state.stable_frames = 0
        for stale_id in [key for key in self._vehicle_states if key not in observed_ids]:
            # Association only uses vehicles observed in this frame; a retained stale bbox
            # could otherwise turn a road fall into a low-priority on-vehicle review.
            del self._vehicle_states[stale_id]

    def _associated_vehicles(self, track: Track) -> list[tuple[float, _VehicleState]]:
        """Vehicles whose bbox overlaps the person or contains their center/bottom center."""
        associated: list[tuple[float, _VehicleState]] = []
        for state in self._vehicle_states.values():
            bbox = state.last_bbox
            if bbox is None or len(bbox) < 4:
                continue
            iou = bbox_iou(track.bbox, bbox)
            inside = self._in_bbox(bbox, track.cx, track.cy) or self._in_bbox(bbox, track.cx, track.bbox[3])
            if iou > self.vehicle_overlap_iou or inside:
                associated.append((iou, state))
        associated.sort(key=lambda item: item[0], reverse=True)
        return associated

    def _vehicle_context(
        self, track: Track, before_time: float | None
    ) -> tuple[_VehicleState | None, bool, float | None]:
        """At lying onset: return the qualifying stationary-upright vehicle, danger flag, and overlap IoU.

        The vehicle must have been stationary and upright before this lying bout started,
        with at least a minimal stable duration or minimal stable frames, and without
        a sudden stop from recent high speed.
        """
        qualifying: _VehicleState | None = None
        danger = False
        qualifying_iou: float | None = None
        for iou, vehicle in self._associated_vehicles(track):
            if vehicle.is_fallen:
                danger = True
                continue
            if before_time is not None and vehicle.last_high_speed_time is not None and (
                    before_time - vehicle.last_high_speed_time < 2.0):
                # Vehicle was running fast and stopped suddenly before the incident: danger override
                danger = True
                continue
            if not vehicle.is_upright or not vehicle.is_stationary or vehicle.stationary_since is None:
                continue
            if before_time is None or vehicle.stationary_since >= before_time:
                continue
            stable_duration = before_time - vehicle.stationary_since
            if (stable_duration < self.vehicle_stable_duration
                    and vehicle.stable_frames < self.vehicle_min_stable_frames):
                continue
            if qualifying is None:
                qualifying = vehicle
                qualifying_iou = iou
        return qualifying, danger, qualifying_iou

    def _vehicle_danger_now(self, track: Track, qualifying_id: int | str | None) -> bool:
        """Danger after onset: the associated vehicle is fallen, unstable, or no longer under the person."""
        associated = self._associated_vehicles(track)
        for _, vehicle in associated:
            if vehicle.is_fallen:
                return True
            if vehicle.track_id == qualifying_id and (
                    not vehicle.is_upright or not vehicle.is_stationary):
                return True
        if qualifying_id is not None and qualifying_id in self._vehicle_states:
            # The person is no longer over the vehicle: the on-vehicle association ended.
            return all(vehicle.track_id != qualifying_id for _, vehicle in associated)
        return False

    def _in_roi(self, track: Track, frame_dimensions: tuple[float, float] | None = None) -> bool:
        if self.roi_polygon is None:
            return True
        foot_x = (track.bbox[0] + track.bbox[2]) / 2.0
        foot_y = float(track.bbox[3])
        dims = frame_dimensions or self.frame_dimensions
        if is_normalized_polygon(self.roi_polygon) and dims is not None and dims[0] > 1.0 and dims[1] > 1.0:
            return point_in_polygon(foot_x / float(dims[0]), foot_y / float(dims[1]), self.roi_polygon)
        return point_in_polygon(foot_x, foot_y, self.roi_polygon)

    def process_tracks(
        self,
        tracks: list[Track],
        timestamp: float,
        pose_outcomes: list[Any] | None = None,
        frame_dimensions: tuple[float, float] | None = None,
    ) -> list[dict[str, Any]]:
        dims = frame_dimensions or self.frame_dimensions
        ts = float(timestamp)
        incidents: list[dict[str, Any]] = []
        self._update_vehicle_states(tracks, ts)

        pose_by_track: dict[Any, dict[str, Any]] = {}
        for outcome in pose_outcomes or ():
            normalized = _normalize_pose_outcome(outcome)
            if normalized is not None:
                pose_by_track[normalized["track_id"]] = normalized

        # A track outside the ROI counts as unobserved, so its state is pruned/reset like a missing track
        # instead of going stale and being reused when the person re-enters the ROI.
        observed_ids = {
            track.track_id
            for track in tracks
            if getattr(track, "label", None) == "person" and self._in_roi(track, frame_dimensions=dims)
        }
        for tid, state in list(self._states.items()):
            if tid not in observed_ids:
                if state.last_alert_time is None or ts - state.last_alert_time >= self.cooldown_seconds:
                    del self._states[tid]
                    continue
                self._states[tid] = _TrackIncidentState(
                    last_alert_time=state.last_alert_time, triggered=state.triggered)

        for track in tracks:
            if getattr(track, "label", None) != "person":
                continue
            if not self._in_roi(track, frame_dimensions=dims):
                continue
            tid = track.track_id
            if tid not in self._states:
                self._states[tid] = _TrackIncidentState()
            state = self._states[tid]
            if state.last_timestamp is not None and (
                ts < state.last_timestamp or ts - state.last_timestamp > self.max_observation_gap
            ):
                # Gap or clock jump: drop standing/onset/dwell/motion/pose evidence, keep cooldown.
                state = self._states[tid] = _TrackIncidentState(
                    last_alert_time=state.last_alert_time, triggered=state.triggered)

            pose_outcome = pose_by_track.get(tid)
            if pose_outcome is not None:
                self._record_pose_outcome(state, pose_outcome)

            # Pose assessment
            is_standing = (
                track.aspect_ratio < self.standing_aspect_ratio
                or any(obs.aspect_ratio < self.standing_aspect_ratio for obs in track.history)
            )
            is_lying = track.aspect_ratio >= self.lying_aspect_ratio

            # On-vehicle association is snapshotted when this lying bout starts, so a vehicle
            # that arrives later (or is still moving) can never demote the event to low priority.
            if is_lying:
                if state.lying_onset_time is None:
                    state.lying_onset_time = ts
                    qualifying, danger, iou = self._vehicle_context(track, ts)
                    state.on_vehicle_track_id = qualifying.track_id if qualifying is not None else None
                    state.vehicle_danger = danger
                    state.association_iou = iou
                elif state.on_vehicle_track_id is not None and not state.vehicle_danger:
                    state.vehicle_danger = self._vehicle_danger_now(track, state.on_vehicle_track_id)

            if track.aspect_ratio < self.standing_aspect_ratio:
                state.had_standing = True
                # If person stands back up, reset candidate and triggered state
                state.in_fall_candidate = False
                state.onset_time = None
                state.lying_start_time = None
                _reset_vehicle_association(state)
                state.first_qualifying_time = None
                state.moving_frames = 0
                state.triggered = False
            elif is_standing:
                state.had_standing = True

            # Motion speed check relative to previous observation
            speed = 0.0
            if state.last_cx is not None and state.last_cy is not None and state.last_timestamp is not None:
                dt = ts - state.last_timestamp
                if dt > 0.0:
                    dist = math.hypot(track.cx - state.last_cx, track.cy - state.last_cy)
                    speed = dist / dt

            state.last_cx = track.cx
            state.last_cy = track.cy
            state.last_timestamp = ts

            # If person recovered to semi-upright (not lying), cancel candidate
            if not is_lying and track.aspect_ratio < 1.0:
                state.in_fall_candidate = False
                state.onset_time = None
                state.lying_start_time = None
                _reset_vehicle_association(state)
                state.first_qualifying_time = None
                state.moving_frames = 0
            elif not is_lying:
                _reset_vehicle_association(state)
                state.first_qualifying_time = None
                state.moving_frames = 0

            # Fall onset & persistent lying detection
            if is_lying and not state.triggered:
                if state.had_standing:
                    if not state.in_fall_candidate:
                        # Check if rapid drop or aspect ratio transition occurred
                        v_y = track.vertical_velocity(window_seconds=1.5)
                        ar_change = track.aspect_ratio_change(window_seconds=1.5)
                        if v_y >= self.min_drop_velocity or ar_change >= 0.35:
                            state.in_fall_candidate = True
                            state.onset_time = ts
                            state.lying_start_time = ts

                if state.in_fall_candidate:
                    # Already in candidate
                    if speed > self.max_motion_speed:
                        # Still moving fast (dropping or active movement), update settling time
                        state.lying_start_time = ts
                    elif state.lying_start_time is not None:
                        lying_duration = ts - state.lying_start_time
                        if (lying_duration > self.min_lying_duration
                                and (state.last_alert_time is None
                                     or ts - state.last_alert_time >= self.cooldown_seconds)):
                            # Confirmed fall incident!
                            anchor_time = state.onset_time if state.onset_time is not None else ts
                            incident = self._create_incident(
                                taxonomy="person_fall",
                                severity="critical",
                                anchor_kind="onset",
                                anchor_time=anchor_time,
                                detection_time=ts,
                                track=track,
                                pose_evidence=self._pose_evidence(state),
                            )
                            incidents.append(incident)
                            state.last_alert_time = ts
                            state.triggered = True
                            state.in_fall_candidate = False
                            state.first_qualifying_time = None
                else:
                    # Missing onset / person already lying / slow lying -> persistent lying detection
                    if speed > self.max_motion_speed:
                        state.moving_frames += 1
                        if state.moving_frames >= 2:
                            # Not stationary: restart the window. The anchor becomes the first
                            # stationary observation that follows, not this moving frame.
                            state.first_qualifying_time = None
                    else:
                        state.moving_frames = 0
                        if state.first_qualifying_time is None:
                            state.first_qualifying_time = ts

                        persistent_duration = ts - state.first_qualifying_time
                        if (persistent_duration > self.persistent_lying_duration
                                and (state.last_alert_time is None
                                     or ts - state.last_alert_time >= self.cooldown_seconds)):
                            anchor_time = state.first_qualifying_time
                            on_vehicle = (
                                state.on_vehicle_track_id is not None and not state.vehicle_danger
                            )
                            if on_vehicle:
                                # Stationary, upright vehicle from before the lying bout:
                                # still a review event, but never a low-priority suppression.
                                taxonomy = "person_on_stationary_vehicle"
                                severity = self.on_vehicle_severity
                                vehicle_track_id = state.on_vehicle_track_id
                                association_uncertainty = {
                                    "method": "2d_bbox_overlap",
                                    "overlap_iou": round(float(state.association_iou), 3) if state.association_iou is not None else None,
                                }
                            else:
                                # Missing association, moving/tilted vehicle, or fallen vehicle:
                                # danger override keeps the normal review priority.
                                taxonomy = "person_lying_persistent"
                                severity = self.persistent_lying_severity
                                vehicle_track_id = None
                                association_uncertainty = None
                            incident = self._create_incident(
                                taxonomy=taxonomy,
                                severity=severity,
                                anchor_kind="first_qualifying_observation",
                                anchor_time=anchor_time,
                                detection_time=ts,
                                track=track,
                                pose_evidence=self._pose_evidence(state),
                                vehicle_track_id=vehicle_track_id,
                                association_uncertainty=association_uncertainty,
                            )
                            incidents.append(incident)
                            state.last_alert_time = ts
                            state.triggered = True
                            state.first_qualifying_time = None

        return incidents
