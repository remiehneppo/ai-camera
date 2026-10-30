"""Danger zone intrusion detection engine (US10 carrier vertical; factory: 'danger_zone')."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from typing import Any, Sequence
from uuid import uuid4

from apps.edge.geometry import is_normalized_polygon, point_in_polygon, scale_roi_to_pixels
from apps.edge.tracker import Track
from domain.alert_module_config import ScheduleWindow, WEEKDAYS


__all__ = ["DangerZoneIncidentEngine", "DEFAULT_PERSON_LABELS"]

DEFAULT_PERSON_LABELS: frozenset[str] = frozenset({"person", "pedestrian"})


@dataclass
class _DangerZoneTrackState:
    """Internal state tracking for one pedestrian candidate inside a restricted/danger ROI."""

    track_id: int | str
    label: str
    first_entered_time: float | None = None
    last_seen_time: float = 0.0
    consecutive_frames: int = 1
    triggered: bool = False
    last_alert_time: float | None = None
    history_detections: list[dict[str, Any]] = field(default_factory=list)

    def reset_dwell(self) -> None:
        """Reset dwell timing and observation continuity across an observation gap or exit."""
        self.consecutive_frames = 0
        self.first_entered_time = None
        self.triggered = False


class DangerZoneIncidentEngine:
    """Independent edge incident detection engine for dangerous zone intrusion (factory: 'danger_zone')."""

    factory: str = "danger_zone"

    def __init__(
        self,
        camera_id: str = "camera-001",
        device_id: str = "device-edge-001",
        stream_session_id: str | None = None,
        pipeline_id: str = "danger-zone-pipeline-v1",
        pipeline_version: str = "1",
        config_version: str = "danger-zone-v1",
        origin: str = "live",
        model_artifact_hash: str = "sha256-danger-zone-v1",
        calibration_version: str = "uncalibrated-image-v1",
        quality_state: str = "normal",
        roi_polygon: Sequence[Sequence[float]] | None = None,
        schedule: Sequence[ScheduleWindow] | Sequence[dict[str, Any]] | None = None,
        timezone_info: tzinfo | None = None,
        min_dwell_seconds: float = 0.0,
        consecutive_hits: int = 2,
        max_observation_gap: float = 1.0,
        cooldown_seconds: float = 30.0,
        severity: str = "critical",
        target_labels: Sequence[str] | frozenset[str] | None = None,
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
        self.rule_lineage: list[dict[str, str]] = [{"role": "danger_zone_incident", "version": "1.0.0"}]
        self.calibration_version = str(calibration_version)
        self.quality_state = str(quality_state)
        self.roi_polygon = roi_polygon
        self.schedule = schedule
        self.timezone_info = timezone_info or timezone.utc
        self.min_dwell_seconds = max(0.0, float(min_dwell_seconds))
        self.consecutive_hits = max(1, int(consecutive_hits))
        self.max_observation_gap = float(max_observation_gap)
        self.cooldown_seconds = float(cooldown_seconds)
        self.severity = str(severity)
        self.target_labels: frozenset[str] = (
            frozenset(target_labels) if target_labels is not None else DEFAULT_PERSON_LABELS
        )
        self.min_score = float(min_score)
        self.exceptions = tuple(exceptions or ())
        self.frame_dimensions = frame_dimensions
        self._tracks: dict[int | str, _DangerZoneTrackState] = {}
        self._last_timestamp: float | None = None

    def reset(self) -> None:
        """Clear all internal tracking states and history."""
        self._tracks.clear()
        self._last_timestamp = None

    def observation_gap(self) -> None:
        """Reset continuous dwell timers and consecutive hits across an observation gap."""
        for state in self._tracks.values():
            state.reset_dwell()
        self._last_timestamp = None

    def in_roi(self, track: Track | dict[str, Any], frame_dimensions: tuple[float, float] | None = None) -> bool:
        """Check if person foot point or center is inside the restricted ROI polygon."""
        if self.roi_polygon is None:
            return True
        bbox = track.bbox if isinstance(track, Track) else track.get("bbox", [0.0, 0.0, 0.0, 0.0])
        cx = track.cx if isinstance(track, Track) else (bbox[0] + bbox[2]) / 2.0
        cy = track.cy if isinstance(track, Track) else (bbox[1] + bbox[3]) / 2.0
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

    def _build_facts(
        self,
        track: Track | dict[str, Any],
        state: _DangerZoneTrackState,
        anchor_time: float,
        detection_time: float,
    ) -> dict[str, Any]:
        """Return rule facts (anchor kind and scenario payload); snapshot assembly belongs to the caller."""
        bbox = track.bbox if isinstance(track, Track) else track.get("bbox", [0.0, 0.0, 0.0, 0.0])
        score = float(track.score) if isinstance(track, Track) else float(track.get("score", 0.0))
        label = str(track.label) if isinstance(track, Track) else str(track.get("label", "person"))
        tid = track.track_id if isinstance(track, Track) else track.get("track_id", state.track_id)

        detections: list[dict[str, Any]] = list(state.history_detections[-10:])
        first_time = state.first_entered_time if state.first_entered_time is not None else detection_time
        dwell_seconds = max(0.0, detection_time - first_time)

        return {
            "anchor_kind": "alert_condition",
            "payload": {
                "module": self.module,
                "factory": self.factory,
                "taxonomy": "danger_zone_intrusion",
                "severity": self.severity,
                "confidence": round(score, 3),
                "track_id": tid,
                "person_label": label,
                "dwell_seconds": round(dwell_seconds, 2),
                "anchor_time": anchor_time,
                "detection_time": detection_time,
                "bbox": [round(float(c), 2) for c in bbox],
                "detections": detections,
            },
        }

    def process_tracks(
        self,
        tracks: Sequence[Track] | Sequence[dict[str, Any]],
        timestamp: float,
        frame_dimensions: tuple[float, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate pedestrian tracks at timestamp and return validated event snapshots for danger zone entries."""
        ts = float(timestamp)
        dims = frame_dimensions or self.frame_dimensions
        if frame_dimensions is not None:
            self.frame_dimensions = frame_dimensions

        # 0. Check observation gap / clock jump backwards
        if self._last_timestamp is not None:
            if ts < self._last_timestamp or (ts - self._last_timestamp) > self.max_observation_gap:
                self.observation_gap()

        self._last_timestamp = ts

        # 1. Check schedule filter
        if not self.is_in_schedule(ts):
            for s in self._tracks.values():
                s.reset_dwell()
            return []

        events: list[dict[str, Any]] = []
        observed_ids: set[int | str] = set()

        for track in tracks:
            bbox = track.bbox if isinstance(track, Track) else track.get("bbox", [])
            score = float(track.score) if isinstance(track, Track) else float(track.get("score", 0.0))
            label = str(track.label) if isinstance(track, Track) else str(track.get("label", "person"))
            tid = track.track_id if isinstance(track, Track) else track.get("track_id")

            if tid is None or label not in self.target_labels or score < self.min_score:
                continue

            observed_ids.add(tid)
            inside = self.in_roi(track, frame_dimensions=dims)

            state = self._tracks.get(tid)
            if not inside:
                if state is not None:
                    state.reset_dwell()
                continue

            # Track is inside ROI
            if state is None:
                state = _DangerZoneTrackState(
                    track_id=tid,
                    label=label,
                    first_entered_time=ts,
                    last_seen_time=ts,
                    consecutive_frames=1,
                    history_detections=[{
                        "bbox": list(bbox),
                        "score": score,
                        "timestamp": ts,
                        "label": label,
                    }],
                )
                self._tracks[tid] = state
            else:
                state.label = label
                if state.first_entered_time is None:
                    state.first_entered_time = ts
                    state.consecutive_frames = 1
                else:
                    state.consecutive_frames += 1
                state.last_seen_time = ts
                state.history_detections.append({
                    "bbox": list(bbox),
                    "score": score,
                    "timestamp": ts,
                    "label": label,
                })
                if len(state.history_detections) > 20:
                    state.history_detections[:] = state.history_detections[-15:]

            first_time = state.first_entered_time if state.first_entered_time is not None else ts
            dwell_seconds = ts - first_time
            if state.consecutive_frames >= self.consecutive_hits and dwell_seconds >= self.min_dwell_seconds:
                # Check cooldown to prevent duplicate alert spam for the same track
                if state.last_alert_time is None or (ts - state.last_alert_time) >= self.cooldown_seconds:
                    event = self._build_facts(
                        track=track,
                        state=state,
                        anchor_time=ts,
                        detection_time=ts,
                    )
                    state.triggered = True
                    state.last_alert_time = ts
                    events.append(event)

        # Tracks absent from the currently observed qualifying tracks inside ROI:
        # must break observation continuity / reset dwell (retaining cooldown).
        for tid, s in list(self._tracks.items()):
            if tid not in observed_ids:
                s.reset_dwell()
                if (ts - s.last_seen_time) > 10.0:
                    del self._tracks[tid]

        return events
