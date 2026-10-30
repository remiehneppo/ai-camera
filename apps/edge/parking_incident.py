"""Edge incident detection engine for illegal parking and dwell time (Task Ticket #62 / US05).

Evaluates vehicle tracks (car, truck, bus, motorcycle) in parking-restricted ROI (point_in_polygon)
and optional restricted schedule (ScheduleWindow).

Dwell time tracking:
- Tracks vehicle position and stationarity.
- If a vehicle stays continuously stationary in the restricted ROI for duration
  T >= max_dwell_seconds (default 30.0s, configurable down to 2.0s for tests),
  triggers a suspected illegal parking event.

Rejects hard negatives:
1) Normal driving / moving through: vehicle passing through ROI without staying stationary
   does NOT trigger.
2) Red-light stop / traffic jam / temporary queue: vehicles that move before max_dwell_seconds
   do NOT trigger.
3) Parking outside restricted schedule / allowed hours: does NOT trigger.
4) Vehicle parked outside restricted ROI: does NOT trigger.
5) Observation gap / track discontinuity: resets dwell timer (does not fabricate long dwell
   duration across gaps).

Generates rule facts dictionaries:
- anchor_kind: "alert_condition"
- payload["taxonomy"]: "illegal_parking"
- payload["severity"]: "low" or "medium" (default "low")
- payload["dwell_seconds"]: measured dwell time
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
import math
from typing import Any, Sequence
from uuid import uuid4

from apps.edge.geometry import is_normalized_polygon, point_in_polygon
from apps.edge.tracker import Track
from domain.alert_module_config import ScheduleWindow, WEEKDAYS


DEFAULT_VEHICLE_LABELS: frozenset[str] = frozenset({"car", "truck", "bus", "motorcycle"})


@dataclass
class _VehicleParkingState:
    """Internal state tracking for one vehicle candidate for illegal parking."""

    track_id: int | str
    label: str
    last_timestamp: float | None = None
    last_bbox: list[float] = field(default_factory=list)
    last_cx: float | None = None
    last_cy: float | None = None
    anchor_cx: float | None = None
    anchor_cy: float | None = None
    is_stationary: bool = False
    stationary_since: float | None = None
    dwell_start_time: float | None = None
    dwell_seconds: float = 0.0
    triggered: bool = False
    last_alert_time: float | None = None
    consecutive_stationary_frames: int = 0
    history_detections: list[dict[str, Any]] = field(default_factory=list)

    def reset_dwell(self) -> None:
        """Reset dwell timing and stationarity state."""
        self.is_stationary = False
        self.stationary_since = None
        self.dwell_start_time = None
        self.dwell_seconds = 0.0
        self.anchor_cx = None
        self.anchor_cy = None
        self.consecutive_stationary_frames = 0
        self.triggered = False


class ParkingIncidentEngine:
    """Independent edge incident detection engine for illegal parking and dwell time (factory: 'illegal_parking')."""

    factory: str = "illegal_parking"

    def __init__(
        self,
        camera_id: str = "camera-001",
        device_id: str = "device-edge-001",
        stream_session_id: str | None = None,
        pipeline_id: str = "parking-incident-pipeline-v1",
        pipeline_version: str = "1",
        config_version: str = "parking-incident-v1",
        origin: str = "live",
        model_artifact_hash: str = "sha256-parking-incident-v1",
        calibration_version: str = "uncalibrated-image-v1",
        quality_state: str = "normal",
        roi_polygon: Sequence[Sequence[float]] | None = None,
        schedule: Sequence[ScheduleWindow] | Sequence[dict[str, Any]] | None = None,
        timezone_info: tzinfo | None = None,
        max_dwell_seconds: float = 30.0,
        stationary_speed_threshold: float = 8.0,
        stationary_displacement_threshold: float = 15.0,
        max_observation_gap: float = 1.0,
        cooldown_seconds: float = 60.0,
        severity: str = "low",
        vehicle_labels: Sequence[str] | frozenset[str] | None = None,
        min_score: float = 0.3,
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
        self.rule_lineage: list[dict[str, str]] = [{"role": "parking_incident", "version": "1.0.0"}]
        self.calibration_version = str(calibration_version)
        self.quality_state = str(quality_state)
        self.roi_polygon = roi_polygon
        self.schedule = schedule
        self.timezone_info = timezone_info or timezone.utc
        self.max_dwell_seconds = float(max_dwell_seconds)
        self.stationary_speed_threshold = float(stationary_speed_threshold)
        self.stationary_displacement_threshold = float(stationary_displacement_threshold)
        self.max_observation_gap = float(max_observation_gap)
        self.cooldown_seconds = float(cooldown_seconds)
        self.severity = str(severity)
        self.vehicle_labels: frozenset[str] = (
            frozenset(vehicle_labels) if vehicle_labels is not None else DEFAULT_VEHICLE_LABELS
        )
        self.min_score = float(min_score)
        self.exceptions = tuple(exceptions or ())
        self.frame_dimensions = frame_dimensions
        self._tracks: dict[int | str, _VehicleParkingState] = {}

    def reset(self) -> None:
        """Clear all internal tracking states and history."""
        self._tracks.clear()

    def observation_gap(self) -> None:
        """Reset dwell timers and continuity across an observation gap for all active tracks."""
        for state in self._tracks.values():
            state.reset_dwell()

    def in_roi(self, track: Track, frame_dimensions: tuple[float, float] | None = None) -> bool:
        """Check if track foot or center is inside the restricted ROI polygon."""
        if self.roi_polygon is None:
            return True
        foot_x = (track.bbox[0] + track.bbox[2]) / 2.0
        foot_y = float(track.bbox[3])
        dims = frame_dimensions or self.frame_dimensions
        if is_normalized_polygon(self.roi_polygon) and dims is not None and dims[0] > 1.0 and dims[1] > 1.0:
            w, h = float(dims[0]), float(dims[1])
            return (
                point_in_polygon(foot_x / w, foot_y / h, self.roi_polygon)
                or point_in_polygon(track.cx / w, track.cy / h, self.roi_polygon)
            )
        return (
            point_in_polygon(foot_x, foot_y, self.roi_polygon)
            or point_in_polygon(track.cx, track.cy, self.roi_polygon)
        )
    def is_in_schedule(self, timestamp: float | datetime) -> bool:
        """Evaluate if timestamp falls within the restricted schedule windows.

        If no schedule is configured, restrictions apply at all times (returns True).
        """
        if not self.schedule:
            return True

        if isinstance(timestamp, datetime):
            dt = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=self.timezone_info)
        else:
            dt = datetime.fromtimestamp(float(timestamp), tz=self.timezone_info)

        day_name = WEEKDAYS[dt.weekday()]
        sec_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1_000_000

        for window in self.schedule:
            if isinstance(window, dict):
                w_days = window.get("days", ())
                w_start = window.get("start_second", 0)
                w_end = window.get("end_second", 86400)
            else:
                w_days = getattr(window, "days", ())
                w_start = getattr(window, "start_second", 0)
                w_end = getattr(window, "end_second", 86400)

            if day_name in w_days and w_start <= sec_of_day <= w_end:
                return True
        return False

    def get_track_state(self, track_id: int | str) -> _VehicleParkingState | None:
        """Retrieve the internal state of a vehicle track for inspection."""
        return self._tracks.get(track_id)

    def _get_or_create_track(self, track: Track) -> _VehicleParkingState:
        tid = track.track_id
        state = self._tracks.get(tid)
        if state is None:
            state = _VehicleParkingState(
                track_id=tid,
                label=track.label,
            )
            self._tracks[tid] = state
        return state

    def _build_facts(
        self,
        track: Track,
        state: _VehicleParkingState,
        anchor_time: float,
        detection_time: float,
    ) -> dict[str, Any]:
        """Return rule facts (anchor kind and scenario payload); snapshot assembly belongs to the caller."""
        detections: list[dict[str, Any]] = list(state.history_detections[-10:])

        return {
            "anchor_kind": "alert_condition",
            "payload": {
                "taxonomy": "illegal_parking",
                "severity": self.severity,
                "confidence": round(float(track.score), 3),
                "track_id": track.track_id,
                "vehicle_label": track.label,
                "dwell_seconds": round(float(state.dwell_seconds), 2),
                "anchor_time": anchor_time,
                "detection_time": detection_time,
                "bbox": [round(float(c), 2) for c in track.bbox],
                "detections": detections,
            },
        }

    def process_tracks(
        self,
        tracks: list[Track],
        timestamp: float | datetime,
        frame_dimensions: tuple[float, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate tracks at timestamp and return validated event snapshots for any triggered illegal parking incidents."""
        dims = frame_dimensions or self.frame_dimensions
        if isinstance(timestamp, datetime):
            ts = float(timestamp.timestamp())
        else:
            ts = float(timestamp)

        events: list[dict[str, Any]] = []
        in_schedule = self.is_in_schedule(timestamp)
        active_track_ids: set[int | str] = set()

        for track in tracks:
            tid = track.track_id
            active_track_ids.add(tid)

            # Filter non-vehicles or low score
            if track.label not in self.vehicle_labels or track.score < self.min_score:
                continue

            # Hard negative 4: Vehicle parked outside restricted ROI does NOT trigger
            if not self.in_roi(track, frame_dimensions=dims):
                # If previously tracked inside ROI, reset its dwell state
                existing = self._tracks.get(tid)
                if existing is not None:
                    existing.reset_dwell()
                    existing.last_timestamp = ts
                    existing.last_bbox = list(track.bbox)
                    existing.last_cx = track.cx
                    existing.last_cy = track.cy
                continue

            state = self._get_or_create_track(track)

            # Check for observation gap or backward clock jump (Hard negative 5)
            gap_or_clock_jump = (
                state.last_timestamp is not None
                and (ts < state.last_timestamp or (ts - state.last_timestamp) > self.max_observation_gap)
            )

            if gap_or_clock_jump:
                state.reset_dwell()

            # Calculate speed and displacement
            inst_speed = 0.0
            if state.last_timestamp is not None and not gap_or_clock_jump:
                dt = ts - state.last_timestamp
                if dt > 0.0 and state.last_cx is not None and state.last_cy is not None:
                    inst_speed = math.hypot(track.cx - state.last_cx, track.cy - state.last_cy) / dt

            # Update history detections
            state.history_detections.append({
                "bbox": list(track.bbox),
                "score": float(track.score),
                "timestamp": ts,
                "label": track.label,
            })
            if len(state.history_detections) > 32:
                state.history_detections[:] = state.history_detections[-20:]

            # Check exceptions: if vehicle matches permitted exception rules, skip dwell accumulation
            is_excepted = False
            if self.exceptions:
                for exc in self.exceptions:
                    code = str(getattr(exc, "code", exc)).lower()
                    if (
                        code in ("all", "permit_all", "all_vehicles")
                        or code in (track.label.lower(), f"permit_{track.label.lower()}")
                        or code == str(track.track_id)
                    ):
                        is_excepted = True
                        break

            # Handle zero-history: first frame of observation cannot establish stationarity alone
            if state.last_timestamp is None or gap_or_clock_jump:
                state.last_cx = track.cx
                state.last_cy = track.cy
                state.last_bbox = list(track.bbox)
                state.last_timestamp = ts
                state.anchor_cx = track.cx
                state.anchor_cy = track.cy
                state.dwell_start_time = None
                state.dwell_seconds = 0.0
                continue

            prev_timestamp = state.last_timestamp

            # Determine stationarity from at least two consecutive observations
            if state.anchor_cx is not None and state.anchor_cy is not None:
                disp_from_anchor = math.hypot(track.cx - state.anchor_cx, track.cy - state.anchor_cy)
                if disp_from_anchor > self.stationary_displacement_threshold:
                    is_stationary = False
                elif inst_speed <= self.stationary_speed_threshold:
                    is_stationary = True
                elif disp_from_anchor <= self.stationary_displacement_threshold * 0.3 and inst_speed <= self.stationary_speed_threshold * 1.5:
                    is_stationary = True
                else:
                    is_stationary = False
            else:
                is_stationary = inst_speed <= self.stationary_speed_threshold

            # State transitions:
            if not is_stationary or is_excepted:
                # Vehicle is moving or excepted: reset dwell timer (Hard negatives 1 & 2)
                state.reset_dwell()
                state.last_cx = track.cx
                state.last_cy = track.cy
                state.last_bbox = list(track.bbox)
                state.last_timestamp = ts
                continue

            # Vehicle is stationary:
            state.is_stationary = True
            if state.anchor_cx is None or state.anchor_cy is None:
                state.anchor_cx = track.cx
                state.anchor_cy = track.cy

            state.last_cx = track.cx
            state.last_cy = track.cy
            state.last_bbox = list(track.bbox)
            state.last_timestamp = ts

            # Hard negative 3: Parking outside restricted schedule / allowed hours does NOT trigger
            if not in_schedule:
                # Outside restricted hours: dwell in restriction does not accumulate
                state.dwell_start_time = None
                state.dwell_seconds = 0.0
                state.triggered = False
                continue

            # In restricted schedule and stationary in restricted ROI
            if state.dwell_start_time is None:
                state.dwell_start_time = prev_timestamp
                state.dwell_seconds = ts - prev_timestamp
            else:
                state.dwell_seconds = ts - state.dwell_start_time

            # Trigger condition: dwell duration exceeds max_dwell_seconds
            if state.dwell_seconds >= self.max_dwell_seconds:
                cooldown_elapsed = (
                    state.last_alert_time is None
                    or (ts - state.last_alert_time) >= self.cooldown_seconds
                )
                if not state.triggered and cooldown_elapsed:
                    event = self._build_facts(
                        track=track,
                        state=state,
                        anchor_time=ts,
                        detection_time=ts,
                    )
                    events.append(event)
                    state.triggered = True
                    state.last_alert_time = ts

        # Clean up stale tracks no longer observed in the frame
        for stale_id in [tid for tid in self._tracks if tid not in active_track_ids]:
            del self._tracks[stale_id]

        return events
