"""Behavioral Incident Engine for edge fall detection."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from apps.edge.tracker import Track


@dataclass
class _TrackIncidentState:
    had_standing: bool = False
    in_fall_candidate: bool = False
    onset_time: float | None = None
    lying_start_time: float | None = None
    last_cx: float | None = None
    last_cy: float | None = None
    last_timestamp: float | None = None
    last_alert_time: float | None = None
    triggered: bool = False


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
    ) -> None:
        self.standing_aspect_ratio: float = float(standing_aspect_ratio)
        self.lying_aspect_ratio: float = float(lying_aspect_ratio)
        self.min_drop_velocity: float = float(min_drop_velocity)
        self.min_lying_duration: float = float(min_lying_duration)
        self.cooldown_seconds: float = float(cooldown_seconds)
        self.max_motion_speed: float = float(max_motion_speed)
        self._states: dict[int | str, _TrackIncidentState] = {}

    def reset(self) -> None:
        self._states.clear()

    def process_tracks(self, tracks: list[Track], timestamp: float) -> list[dict[str, Any]]:
        ts = float(timestamp)
        incidents: list[dict[str, Any]] = []

        for track in tracks:
            tid = track.track_id
            if tid not in self._states:
                self._states[tid] = _TrackIncidentState()
            state = self._states[tid]

            # Cooldown check
            if state.last_alert_time is not None:
                if (ts - state.last_alert_time) < self.cooldown_seconds:
                    continue

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

            # Fall onset & persistent lying detection
            if is_lying and state.had_standing and not state.triggered:
                if not state.in_fall_candidate:
                    # Check if rapid drop or aspect ratio transition occurred
                    v_y = track.vertical_velocity(window_seconds=1.5)
                    ar_change = track.aspect_ratio_change(window_seconds=1.5)
                    if v_y >= self.min_drop_velocity or ar_change >= 0.35:
                        state.in_fall_candidate = True
                        state.onset_time = ts
                        state.lying_start_time = ts
                else:
                    # Already in candidate
                    if speed > self.max_motion_speed:
                        # Still moving fast (dropping or active movement), update settling time
                        state.lying_start_time = ts
                        state.onset_time = ts
                    elif state.lying_start_time is not None:
                        lying_duration = ts - state.lying_start_time
                        if lying_duration > self.min_lying_duration:
                            # Confirmed fall incident!
                            anchor_time = state.onset_time if state.onset_time is not None else ts
                            recent_dets = [
                                {
                                    "bbox": obs.bbox,
                                    "score": obs.score,
                                    "timestamp": obs.timestamp,
                                    "label": track.label,
                                }
                                for obs in track.history[-20:]
                            ]
                            conf = round(float(track.score), 3)
                            incident: dict[str, Any] = {
                                "taxonomy": "person_fall",
                                "severity": "critical",
                                "anchor_kind": "onset",
                                "anchor_time": anchor_time,
                                "detection_time": ts,
                                "track_id": tid,
                                "confidence": conf,
                                "detections": recent_dets,
                            }
                            incidents.append(incident)
                            state.last_alert_time = ts
                            state.triggered = True
                            state.in_fall_candidate = False

        return incidents
