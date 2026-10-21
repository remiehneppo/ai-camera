"""Behavioral Incident Engine for edge fall detection."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from apps.edge.tracker import Track


def point_in_polygon(x: float, y: float, polygon: list[list[float]] | list[tuple[float, float]]) -> bool:
    """Ray casting algorithm for testing if a 2D point is inside a polygon."""
    if not polygon or len(polygon) < 3:
        return True
    n = len(polygon)
    inside = False
    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


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
    first_qualifying_time: float | None = None
    moving_frames: int = 0
    last_cx: float | None = None
    last_cy: float | None = None
    last_timestamp: float | None = None
    last_alert_time: float | None = None
    triggered: bool = False
    last_valid_pose: dict[str, Any] | None = None
    last_pose_outcome: dict[str, Any] | None = None


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
        self._states: dict[int | str, _TrackIncidentState] = {}

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
    ) -> dict[str, Any]:
        return {
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

    def reset(self) -> None:
        self._states.clear()

    def observation_gap(self):
        for tid, state in self._states.items():
            self._states[tid] = _TrackIncidentState(
                last_alert_time=state.last_alert_time, triggered=state.triggered)

    def _in_roi(self, track: Track) -> bool:
        if self.roi_polygon is None:
            return True
        foot_x = (track.bbox[0] + track.bbox[2]) / 2.0
        return point_in_polygon(foot_x, float(track.bbox[3]), self.roi_polygon)

    def process_tracks(
        self,
        tracks: list[Track],
        timestamp: float,
        pose_outcomes: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        ts = float(timestamp)
        incidents: list[dict[str, Any]] = []

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
            if getattr(track, "label", None) == "person" and self._in_roi(track)
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
            if not self._in_roi(track):
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

            if track.aspect_ratio < self.standing_aspect_ratio:
                state.had_standing = True
                # If person stands back up, reset candidate and triggered state
                state.in_fall_candidate = False
                state.onset_time = None
                state.lying_start_time = None
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
                state.first_qualifying_time = None
                state.moving_frames = 0
            elif not is_lying:
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
                            incident = self._create_incident(
                                taxonomy="person_lying_persistent",
                                severity=self.persistent_lying_severity,
                                anchor_kind="first_qualifying_observation",
                                anchor_time=anchor_time,
                                detection_time=ts,
                                track=track,
                                pose_evidence=self._pose_evidence(state),
                            )
                            incidents.append(incident)
                            state.last_alert_time = ts
                            state.triggered = True
                            state.first_qualifying_time = None

        return incidents
