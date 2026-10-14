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
    first_qualifying_time: float | None = None
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
        persistent_lying_duration: float | None = None,
        persistent_lying_severity: str = "high",
    ) -> None:
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

    def _create_incident(
        self,
        *,
        taxonomy: str,
        severity: str,
        anchor_kind: str,
        anchor_time: float,
        detection_time: float,
        track: Track,
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
        }

    def reset(self) -> None:
        self._states.clear()

    def observation_gap(self):
        for tid, state in self._states.items():
            self._states[tid] = _TrackIncidentState(
                last_alert_time=state.last_alert_time, triggered=state.triggered)

    def process_tracks(self, tracks: list[Track], timestamp: float) -> list[dict[str, Any]]:
        ts = float(timestamp)
        incidents: list[dict[str, Any]] = []

        observed_ids = {track.track_id for track in tracks}
        for tid, state in list(self._states.items()):
            if tid not in observed_ids:
                if state.last_alert_time is None or ts - state.last_alert_time >= self.cooldown_seconds:
                    del self._states[tid]
                    continue
                self._states[tid] = _TrackIncidentState(
                    last_alert_time=state.last_alert_time, triggered=state.triggered)

        for track in tracks:
            tid = track.track_id
            if tid not in self._states:
                self._states[tid] = _TrackIncidentState()
            state = self._states[tid]

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
            elif not is_lying:
                state.first_qualifying_time = None

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
                        state.onset_time = ts
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
                            )
                            incidents.append(incident)
                            state.last_alert_time = ts
                            state.triggered = True
                            state.in_fall_candidate = False
                            state.first_qualifying_time = None
                else:
                    # Missing onset / person already lying / slow lying -> persistent lying detection
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
                        )
                        incidents.append(incident)
                        state.last_alert_time = ts
                        state.triggered = True
                        state.first_qualifying_time = None

        return incidents
