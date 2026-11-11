"""Unified Urban Safety Scenario Engine (US01–US14) for CiviWatch v2.

Covers the 9 extended urban safety scenario groups (US01, US02, US03, US04, US07,
US11, US12, US13, US14) plus the unified `urban_safety_vlm` multi-scenario factory,
complementing the 5 specialized engines (US05, US06, US08, US09, US10).

Strict architectural guarantees:
- Pure temporal evaluation: no network/file I/O inside `process_tracks`.
- Isolated state per scenario (`_env_active_since["US01_fire"]`, `"US01_smoke"`, `"US02"`, `"US13"`)
  so one scenario never clobbers another scenario's timer.
- Independent fire and smoke detection in US01 (smoke does not require concurrent fire).
- ROI polygon clipping for environmental features (US01, US02, US13) and `transition_grace_seconds`
  for US13 streetlight outage.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from apps.edge.geometry import is_normalized_polygon, point_in_polygon
from apps.edge.tracker import Track
from apps.edge.vlm_verifier import VLMVerifier
from domain.alert_module_config import WEEKDAYS
from domain.urban_scenarios import SCENARIO_BY_FACTORY, UrbanScenarioSpec

WASTE_AND_OBJECT_LABELS: frozenset[str] = frozenset({
    "backpack",
    "umbrella",
    "handbag",
    "suitcase",
    "bottle",
    "cup",
    "bowl",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "tv",
    "laptop",
    "obstacle_object",
})

ENCROACHMENT_LABELS: frozenset[str] = frozenset({
    "car",
    "motorcycle",
    "two_wheeler",
    "bicycle",
    "truck",
    "bus",
    "chair",
    "dining table",
    "umbrella",
    "bench",
    "suitcase",
    "backpack",
    "obstacle_object",
})


@dataclass
class _ScenarioTrackState:
    track_id: int | str
    label: str
    first_seen: float
    last_seen: float
    first_bbox: list[float]
    last_bbox: list[float]
    dwell_seconds: float = 0.0
    current_speed: float = 0.0
    max_speed: float = 0.0
    path_distance: float = 0.0
    associated_person_id: int | str | None = None
    unattended_since: float | None = None


@dataclass
class _PairInteractionState:
    proximity_start_time: float
    last_seen_time: float
    motion_window: deque[tuple[float, float]]


def extract_environmental_signals(
    rgb: np.ndarray | None,
    roi_polygon: Sequence[Sequence[float]] | None = None,
    frame_dimensions: tuple[float, float] | None = None,
) -> dict[str, float]:
    """Compute environmental metadata (fire_ratio, smoke_ratio, water_ratio, mean_luma) within rasterized ROI."""
    if rgb is None or not isinstance(rgb, np.ndarray) or rgb.size == 0 or rgb.ndim != 3 or rgb.shape[2] < 3:
        return {}
    h, w = rgb.shape[:2]
    if h <= 0 or w <= 0:
        return {}

    if roi_polygon is not None:
        if len(roi_polygon) < 3:
            return {}
        dims = frame_dimensions or (float(w), float(h))
        if is_normalized_polygon(roi_polygon) and dims[0] > 1.0 and dims[1] > 1.0:
            poly_px = [[float(p[0]) * w, float(p[1]) * h] for p in roi_polygon if len(p) >= 2]
        else:
            poly_px = [[float(p[0]), float(p[1])] for p in roi_polygon if len(p) >= 2]

        n_pts = len(poly_px)
        if n_pts < 3 or not all(math.isfinite(pt[0]) and math.isfinite(pt[1]) for pt in poly_px):
            return {}
        area2 = sum(
            poly_px[i][0] * poly_px[(i + 1) % n_pts][1] - poly_px[(i + 1) % n_pts][0] * poly_px[i][1]
            for i in range(n_pts)
        )
        if abs(area2) <= 1e-6:
            return {}

        clipped_pts = np.clip(np.round(np.asarray(poly_px, dtype=np.float64)), -10_000_000.0, 10_000_000.0).astype(
            np.int32
        )
        mask_u8 = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask_u8, [clipped_pts], (1,))
        poly_mask = mask_u8 > 0
    else:
        poly_mask = np.ones((h, w), dtype=bool)

    poly_area = int(np.count_nonzero(poly_mask))
    if poly_area == 0:
        return {}

    ys_idx, xs_idx = np.nonzero(poly_mask)
    y1, y2 = int(ys_idx.min()), int(ys_idx.max())
    x1, x2 = int(xs_idx.min()), int(xs_idx.max())

    sub_rgb = rgb[y1 : y2 + 1, x1 : x2 + 1]
    sub_mask = poly_mask[y1 : y2 + 1, x1 : x2 + 1]

    r = sub_rgb[:, :, 0].astype(np.float32)
    g = sub_rgb[:, :, 1].astype(np.float32)
    b = sub_rgb[:, :, 2].astype(np.float32)

    fire_mask = (r > 200.0) & (g > 80.0) & (g < 190.0) & (b < 80.0) & ((r - b) > 110.0)
    fire_ratio = float(np.count_nonzero(fire_mask & sub_mask)) / float(poly_area)

    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    smoke_mask = (max_c > 125.0) & (max_c < 215.0) & ((max_c - min_c) < 14.0)
    smoke_ratio = float(np.count_nonzero(smoke_mask & sub_mask)) / float(poly_area)

    rh = sub_rgb.shape[0]
    if rh >= 4:
        lower_sub_mask = sub_mask.copy()
        lower_sub_mask[: rh // 2, :] = False
    else:
        lower_sub_mask = sub_mask
    lower_area = int(np.count_nonzero(lower_sub_mask))
    if lower_area > 0:
        water_mask = (b > 110.0) & (b > r + 25.0) & (g > r + 10.0)
        water_ratio = float(np.count_nonzero(water_mask & lower_sub_mask)) / float(lower_area)
    else:
        water_ratio = 0.0

    mean_luma = float(np.mean(sub_rgb[:, :, :3][sub_mask]))
    return {
        "fire_ratio": fire_ratio,
        "smoke_ratio": smoke_ratio,
        "water_ratio": water_ratio,
        "mean_luma": mean_luma,
    }


class UrbanSafetyScenarioEngine:
    """Configurable engine for US01, US02, US03, US04, US07, US11, US12, US13, US14, and urban_safety_vlm."""

    def __init__(
        self,
        *,
        factory: str = "urban_safety_vlm",
        module_name: str | None = None,
        camera_id: str = "civi-cam-01",
        device_id: str = "civi-edge-01",
        stream_session_id: str | None = None,
        origin: str = "live",
        config_version: str = "civi-v2",
        roi_polygon: list[list[float]] | list[tuple[float, float]] | None = None,
        schedule: Sequence[Any] | None = None,
        exceptions: Sequence[Any] | None = None,
        frame_dimensions: tuple[float, float] | None = None,
        vlm_verifier: VLMVerifier | None = None,
        enable_vlm: bool = True,
        **thresholds: Any,
    ) -> None:
        self.factory = str(factory)
        self.module = str(module_name or factory)
        self.spec: UrbanScenarioSpec | None = SCENARIO_BY_FACTORY.get(self.factory)
        self.scenario_id = self.spec.scenario_id if self.spec is not None else "US00"
        self.pipeline_id = f"civiwatch-{self.factory}-v2"
        self.pipeline_version = "2.0"
        self.config_version = str(config_version or "civi-v2")
        self.camera_id = str(camera_id)
        self.device_id = str(device_id)
        self.stream_session_id = str(stream_session_id or "")
        self.origin = str(origin or "live")
        self.roi_polygon = roi_polygon
        self.schedule = tuple(schedule) if schedule is not None else ()
        self.exceptions = tuple(exceptions) if exceptions is not None else ()
        self.frame_dimensions = frame_dimensions

        # Distinct per-scenario duration thresholds (with fallback to min_persistence_seconds)
        base_persist = float(thresholds.get("min_persistence_seconds", 2.0))
        self.min_persistence_seconds = base_persist
        self.min_dwell_seconds = float(thresholds.get("min_dwell_seconds", base_persist))
        self.min_interaction_seconds = float(thresholds.get("min_interaction_seconds", base_persist))
        self.min_unattended_seconds = float(thresholds.get("min_unattended_seconds", base_persist))
        self.min_dark_duration_seconds = float(thresholds.get("min_dark_duration_seconds", base_persist))
        self.min_impact_duration_seconds = float(thresholds.get("min_impact_duration_seconds", base_persist))
        self.transition_grace_seconds = float(thresholds.get("transition_grace_seconds", 0.0))

        self.max_observation_gap = float(thresholds.get("max_observation_gap", 2.0))
        self.cooldown_seconds = float(thresholds.get("cooldown_seconds", 30.0))
        self.min_score = float(thresholds.get("min_score", 0.25))
        self.fire_ratio_threshold = float(thresholds.get("fire_ratio_threshold", 0.015))
        self.smoke_ratio_threshold = float(thresholds.get("smoke_ratio_threshold", 0.08))
        self.water_coverage_threshold = float(thresholds.get("water_coverage_threshold", 0.12))
        self.luminance_threshold = float(thresholds.get("luminance_threshold", 28.0))
        self.proximity_distance_px = float(thresholds.get("proximity_distance_px", 140.0))
        self.motion_energy_threshold = float(
            thresholds.get("motion_energy_threshold", thresholds.get("motion_spike_threshold", 35.0))
        )
        self.owner_separation_px = float(
            thresholds.get("owner_separation_px", thresholds.get("separation_distance_px", 150.0))
        )
        self.min_object_count = int(thresholds.get("min_object_count", 1))
        self.min_obstruction_area_ratio = float(thresholds.get("min_obstruction_area_ratio", 0.04))

        self.enable_vlm = bool(enable_vlm)
        # Configuration/lineage selection only; pipeline owns VLM execution and storyboard construction.
        self.vlm_verifier = vlm_verifier or (VLMVerifier(endpoint_url="") if self.enable_vlm else None)
        self.rule_lineage = [
            {
                "role": f"{self.factory}_engine",
                "version": f"civiwatch-{self.scenario_id.lower()}-v2",
            }
        ]
        if self.vlm_verifier is not None:
            self.rule_lineage.append(
                {
                    "role": "vlm_verifier",
                    "version": self.vlm_verifier.model_id,
                }
            )

        self._track_states: dict[int | str, _ScenarioTrackState] = {}
        self._pair_states: dict[tuple[int | str, int | str], _PairInteractionState] = {}
        # Isolated timers per environmental condition: never clobber across scenarios!
        self._env_active_since: dict[str, float] = {}
        self._last_timestamp: float | None = None
        self._last_alert_by_taxonomy: dict[str, float] = {}

    def reset(self) -> None:
        self._track_states.clear()
        self._pair_states.clear()
        self._env_active_since.clear()
        self._last_timestamp = None
        self._last_alert_by_taxonomy.clear()

    def reject_candidate(self, facts: Mapping[str, Any]) -> None:
        """Release cooldown written for a rejected candidate when taxonomy and detection_time match."""
        if not isinstance(facts, Mapping):
            return
        raw_payload = facts.get("payload")
        payload = raw_payload if isinstance(raw_payload, Mapping) else facts
        taxonomy = payload.get("taxonomy")
        detection_time = payload.get("detection_time")
        if not isinstance(taxonomy, str) or not taxonomy:
            return
        if isinstance(detection_time, bool) or not isinstance(detection_time, (int, float)):
            return
        det_ts = float(detection_time)
        if not math.isfinite(det_ts):
            return
        recorded_ts = self._last_alert_by_taxonomy.get(taxonomy)
        if recorded_ts is not None and recorded_ts == det_ts:
            self._last_alert_by_taxonomy.pop(taxonomy, None)

    def observation_gap(self) -> None:
        self._track_states.clear()
        self._pair_states.clear()
        self._env_active_since.clear()
        self._last_timestamp = None

    def is_in_schedule(self, timestamp: float, *, grace_seconds: float = 0.0) -> bool:
        if not self.schedule:
            return True
        dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        day_name = WEEKDAYS[dt.weekday()]
        sec = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1_000_000
        for w in self.schedule:
            w_days = getattr(w, "days", ()) if not isinstance(w, dict) else w.get("days", ())
            w_start = getattr(w, "start_second", 0) if not isinstance(w, dict) else w.get("start_second", 0)
            w_end = getattr(w, "end_second", 86400) if not isinstance(w, dict) else w.get("end_second", 86400)
            if day_name in w_days and (w_start + grace_seconds) <= sec <= w_end:
                return True
        return False

    def in_roi(self, track: Track | dict[str, Any], frame_dimensions: tuple[float, float] | None = None) -> bool:
        if self.roi_polygon is None:
            return True
        bbox = track.bbox if isinstance(track, Track) else track.get("bbox", [0.0, 0.0, 0.0, 0.0])
        cx = (float(bbox[0]) + float(bbox[2])) / 2.0
        cy = (float(bbox[1]) + float(bbox[3])) / 2.0
        foot_y = float(bbox[3])
        dims = frame_dimensions or self.frame_dimensions
        if is_normalized_polygon(self.roi_polygon) and dims is not None and dims[0] > 1.0 and dims[1] > 1.0:
            w, h = float(dims[0]), float(dims[1])
            return (
                point_in_polygon(cx / w, foot_y / h, self.roi_polygon)
                or point_in_polygon(cx / w, cy / h, self.roi_polygon)
            )
        return (
            point_in_polygon(cx, foot_y, self.roi_polygon)
            or point_in_polygon(cx, cy, self.roi_polygon)
        )

    def process_tracks(
        self,
        tracks: list[Track],
        timestamp: float,
        pose_outcomes: list[Any] | None = None,
        frame_dimensions: tuple[float, float] | None = None,
        rgb: np.ndarray | None = None,
        environmental_signals: Mapping[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        ts = float(timestamp)
        dims = frame_dimensions or self.frame_dimensions or (
            (float(rgb.shape[1]), float(rgb.shape[0]))
            if isinstance(rgb, np.ndarray) and rgb.ndim >= 2 and rgb.shape[0] > 0 and rgb.shape[1] > 0
            else None
        )

        if self._last_timestamp is not None and (
            ts < self._last_timestamp or ts - self._last_timestamp > self.max_observation_gap
        ):
            self.observation_gap()

        self._last_timestamp = ts
        if not self.is_in_schedule(ts):
            return []

        exception_codes = {
            (getattr(ex, "code", None) if not isinstance(ex, dict) else ex.get("code"))
            for ex in self.exceptions
        }
        if "maintenance_window" in exception_codes:
            return []

        env_sigs = (
            dict(environmental_signals)
            if environmental_signals is not None
            else extract_environmental_signals(rgb, self.roi_polygon, dims)
        )

        candidates: list[dict[str, Any]] = []
        roi_tracks = [t for t in tracks if t.score >= self.min_score and self.in_roi(t, dims)]
        self._update_track_states(roi_tracks, ts)
        self._update_pair_states(roi_tracks, ts)
        if self.factory in {"fire_smoke_suspected", "urban_safety_vlm"}:
            cand = self._eval_us01_fire_smoke(roi_tracks, ts, env_sigs)
            if cand is not None:
                candidates.append(cand)

        if self.factory in {"urban_flooding", "urban_safety_vlm"}:
            cand = self._eval_us02_flooding(roi_tracks, ts, env_sigs)
            if cand is not None:
                candidates.append(cand)

        if self.factory in {"illegal_dumping", "urban_safety_vlm"}:
            cand = self._eval_us03_illegal_dumping(roi_tracks, ts)
            if cand is not None:
                candidates.append(cand)

        if self.factory in {"sidewalk_encroachment", "urban_safety_vlm"}:
            cand = self._eval_us04_sidewalk_encroachment(roi_tracks, ts)
            if cand is not None:
                candidates.append(cand)

        if self.factory in {"violent_altercation", "urban_safety_vlm"}:
            cand = self._eval_us07_violent_altercation(roi_tracks, ts)
            if cand is not None:
                candidates.append(cand)

        if self.factory in {"abandoned_object", "urban_safety_vlm"}:
            cand = self._eval_us11_abandoned_object(roi_tracks, ts)
            if cand is not None:
                candidates.append(cand)

        if self.factory in {"fallen_tree", "urban_safety_vlm"}:
            cand = self._eval_us12_fallen_tree(roi_tracks, ts, dims)
            if cand is not None:
                candidates.append(cand)

        if self.factory in {"streetlight_outage", "urban_safety_vlm"}:
            cand = self._eval_us13_streetlight_outage(ts, env_sigs)
            if cand is not None:
                candidates.append(cand)

        if self.factory in {"property_vandalism", "urban_safety_vlm"}:
            cand = self._eval_us14_property_vandalism(roi_tracks, ts)
            if cand is not None:
                candidates.append(cand)

        emitted_candidates: list[dict[str, Any]] = []
        for facts in candidates:
            tax = str(facts["payload"]["taxonomy"])
            last_alert = self._last_alert_by_taxonomy.get(tax)
            if last_alert is not None and ts - last_alert < self.cooldown_seconds:
                continue

            self._last_alert_by_taxonomy[tax] = ts
            emitted_candidates.append(facts)

        return emitted_candidates

    def _update_track_states(self, roi_tracks: list[Track], ts: float) -> None:
        observed_ids: set[int | str] = set()
        persons = [track for track in roi_tracks if track.label in {"person", "pedestrian"}]

        for track in roi_tracks:
            tid = track.track_id
            observed_ids.add(tid)
            st = self._track_states.get(tid)
            if st is None:
                st = _ScenarioTrackState(
                    track_id=tid,
                    label=track.label,
                    first_seen=ts,
                    last_seen=ts,
                    first_bbox=list(track.bbox),
                    last_bbox=list(track.bbox),
                )
                self._track_states[tid] = st
            else:
                step_dt = ts - st.last_seen
                if step_dt <= 0.0 or step_dt > self.max_observation_gap:
                    st.dwell_seconds = 0.0
                    st.current_speed = 0.0
                    st.max_speed = 0.0
                    st.path_distance = 0.0
                    st.first_seen = ts
                    st.first_bbox = list(track.bbox)
                    st.associated_person_id = None
                    st.unattended_since = None
                else:
                    prev_cx = (st.last_bbox[0] + st.last_bbox[2]) * 0.5
                    prev_cy = (st.last_bbox[1] + st.last_bbox[3]) * 0.5
                    step_dist = math.hypot(track.cx - prev_cx, track.cy - prev_cy)
                    speed = step_dist / step_dt
                    st.current_speed = speed
                    st.path_distance += step_dist
                    st.max_speed = max(st.max_speed, speed)
                    st.dwell_seconds += step_dt
                st.last_seen = ts
                st.last_bbox = list(track.bbox)

            if track.label not in {"person", "pedestrian"}:
                near_person: Track | None = None
                if persons:
                    nearest_p = min(
                        persons,
                        key=lambda p: math.hypot(track.cx - p.cx, track.cy - p.cy),
                    )
                    if math.hypot(track.cx - nearest_p.cx, track.cy - nearest_p.cy) <= self.owner_separation_px:
                        near_person = nearest_p

                if near_person is not None:
                    st.associated_person_id = near_person.track_id
                    st.unattended_since = None
                else:
                    if st.unattended_since is None:
                        st.unattended_since = ts

        for stale_id in [k for k in self._track_states if k not in observed_ids]:
            del self._track_states[stale_id]

    def _update_pair_states(self, roi_tracks: list[Track], ts: float) -> None:
        persons = [t for t in roi_tracks if t.label in {"person", "pedestrian"}]
        active_pairs: set[tuple[int | str, int | str]] = set()

        if len(persons) >= 2:
            for i in range(len(persons)):
                for j in range(i + 1, len(persons)):
                    p1, p2 = persons[i], persons[j]
                    dist = math.hypot(p1.cx - p2.cx, p1.cy - p2.cy)
                    if dist > self.proximity_distance_px:
                        continue
                    st1 = self._track_states.get(p1.track_id)
                    st2 = self._track_states.get(p2.track_id)
                    if st1 is None or st2 is None:
                        continue

                    k1 = (type(p1.track_id).__name__, str(p1.track_id))
                    k2 = (type(p2.track_id).__name__, str(p2.track_id))
                    key = (p1.track_id, p2.track_id) if k1 <= k2 else (p2.track_id, p1.track_id)
                    active_pairs.add(key)

                    current_energy = st1.current_speed + st2.current_speed
                    pair = self._pair_states.get(key)
                    if pair is None:
                        pair = _PairInteractionState(
                            proximity_start_time=ts,
                            last_seen_time=ts,
                            motion_window=deque(),
                        )
                        self._pair_states[key] = pair
                    else:
                        pair.last_seen_time = ts
                        pair.motion_window.append((ts, current_energy))

                    cutoff = ts - max(self.min_interaction_seconds, 1.0)
                    while pair.motion_window and pair.motion_window[0][0] < cutoff:
                        pair.motion_window.popleft()

        for stale_key in [k for k in self._pair_states if k not in active_pairs]:
            del self._pair_states[stale_key]

    def _build_facts(
        self,
        *,
        scenario_id: str,
        taxonomy: str,
        severity: str,
        confidence: float,
        anchor_time: float,
        detection_time: float,
        involved_track_ids: list[int | str],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scenario_id": scenario_id,
            "taxonomy": taxonomy,
            "lifecycle": "candidate",
            "severity": severity,
            "confidence": round(float(confidence), 3),
            "anchor_time": float(anchor_time),
            "detection_time": float(detection_time),
            "involved_track_ids": list(involved_track_ids),
        }
        if extra:
            payload.update(extra)
        return {
            "anchor_kind": "alert_condition",
            "payload": payload,
        }

    def _eval_us01_fire_smoke(
        self,
        tracks: list[Track],
        ts: float,
        env_sigs: Mapping[str, float],
    ) -> dict[str, Any] | None:
        fire_tracks = [t for t in tracks if t.label in {"fire", "smoke", "fire_smoke"}]
        fire_ratio = float(env_sigs.get("fire_ratio", 0.0))
        smoke_ratio = float(env_sigs.get("smoke_ratio", 0.0))

        # Independent fire and smoke triggers (US01 requirement: one sign is sufficient)
        triggered_fire = (
            any(t.label in {"fire", "fire_smoke"} for t in fire_tracks)
            or fire_ratio >= self.fire_ratio_threshold
        )
        # In multi-scenario mode without explicit smoke tracks, require explicit factory or smoke track
        # so neutral gray asphalt does not trigger smoke without an active fire/smoke module
        allow_pixel_smoke = self.factory == "fire_smoke_suspected" or bool(fire_tracks)
        triggered_smoke = (
            any(t.label in {"smoke", "fire_smoke"} for t in fire_tracks)
            or (allow_pixel_smoke and smoke_ratio >= self.smoke_ratio_threshold)
        )

        if triggered_fire:
            self._env_active_since.setdefault("US01_fire", ts)
        else:
            self._env_active_since.pop("US01_fire", None)

        if triggered_smoke:
            self._env_active_since.setdefault("US01_smoke", ts)
        else:
            self._env_active_since.pop("US01_smoke", None)

        fire_dur = (ts - self._env_active_since["US01_fire"]) if "US01_fire" in self._env_active_since else -1.0
        smoke_dur = (ts - self._env_active_since["US01_smoke"]) if "US01_smoke" in self._env_active_since else -1.0

        fire_ready = fire_dur >= self.min_persistence_seconds
        smoke_ready = smoke_dur >= self.min_persistence_seconds
        if not (fire_ready or smoke_ready):
            return None

        sub_tax = (
            "fire_smoke_suspected"
            if (fire_ready and smoke_ready)
            else ("fire_suspected" if fire_ready else "smoke_suspected")
        )
        duration = max(fire_dur, smoke_dur)
        return self._build_facts(
            scenario_id="US01",
            taxonomy=sub_tax,
            severity="critical",
            confidence=max(0.82, min(0.98, 0.75 + max(fire_ratio, smoke_ratio))),
            anchor_time=ts,
            detection_time=ts,
            involved_track_ids=[t.track_id for t in fire_tracks],
            extra={
                "fire_pixel_ratio": round(fire_ratio, 4),
                "smoke_pixel_ratio": round(smoke_ratio, 4),
                "observation_duration_seconds": round(duration, 2),
            },
        )

    def _eval_us02_flooding(
        self,
        tracks: list[Track],
        ts: float,
        env_sigs: Mapping[str, float],
    ) -> dict[str, Any] | None:
        flood_tracks = [t for t in tracks if t.label in {"flood", "water", "urban_flooding"}]
        water_ratio = float(env_sigs.get("water_ratio", 0.0))

        if not flood_tracks and water_ratio < self.water_coverage_threshold:
            self._env_active_since.pop("US02", None)
            return None

        self._env_active_since.setdefault("US02", ts)
        duration = ts - self._env_active_since["US02"]
        if duration < self.min_persistence_seconds:
            return None

        return self._build_facts(
            scenario_id="US02",
            taxonomy="urban_flooding",
            severity="high",
            confidence=0.85,
            anchor_time=ts,
            detection_time=ts,
            involved_track_ids=[t.track_id for t in flood_tracks],
            extra={
                "water_coverage_ratio": round(max(water_ratio, 0.15 if flood_tracks else 0.0), 4),
                "observation_duration_seconds": round(duration, 2),
            },
        )

    def _eval_us03_illegal_dumping(self, tracks: list[Track], ts: float) -> dict[str, Any] | None:
        persons = [t for t in tracks if t.label in {"person", "pedestrian"}]
        for t in tracks:
            if t.label not in WASTE_AND_OBJECT_LABELS and t.label not in {"waste", "trash", "garbage"}:
                continue
            st = self._track_states.get(t.track_id)
            if st is None or st.dwell_seconds < self.min_dwell_seconds:
                continue
            has_actor_departed = False
            if st.associated_person_id is not None:
                actor = next((p for p in persons if p.track_id == st.associated_person_id), None)
                if actor is None or math.hypot(t.cx - actor.cx, t.cy - actor.cy) > self.owner_separation_px:
                    has_actor_departed = True
            taxonomy = "illegal_dumping_action" if has_actor_departed else "unlawful_waste_accumulation"
            return self._build_facts(
                scenario_id="US03",
                taxonomy=taxonomy,
                severity="medium",
                confidence=round(float(t.score), 3),
                anchor_time=ts,
                detection_time=ts,
                involved_track_ids=[t.track_id],
                extra={
                    "dwell_seconds": round(st.dwell_seconds, 2),
                    "object_label": t.label,
                    "has_observed_drop_action": has_actor_departed,
                },
            )
        return None

    def _eval_us04_sidewalk_encroachment(self, tracks: list[Track], ts: float) -> dict[str, Any] | None:
        if self.roi_polygon is None:
            return None
        encroaching = [
            t
            for t in tracks
            if t.label in ENCROACHMENT_LABELS
            and (self._track_states.get(t.track_id) is not None)
            and self._track_states[t.track_id].dwell_seconds >= self.min_dwell_seconds
        ]
        if len(encroaching) < self.min_object_count:
            return None
        max_dwell = max(self._track_states[t.track_id].dwell_seconds for t in encroaching)
        return self._build_facts(
            scenario_id="US04",
            taxonomy="sidewalk_encroachment",
            severity="medium",
            confidence=round(max(float(t.score) for t in encroaching), 3),
            anchor_time=ts,
            detection_time=ts,
            involved_track_ids=[t.track_id for t in encroaching],
            extra={
                "encroaching_object_count": len(encroaching),
                "dwell_seconds": round(max_dwell, 2),
                "object_labels": sorted({t.label for t in encroaching}),
            },
        )

    def _eval_us07_violent_altercation(self, tracks: list[Track], ts: float) -> dict[str, Any] | None:
        persons = [t for t in tracks if t.label in {"person", "pedestrian"}]
        if len(persons) < 2:
            return None
        for i in range(len(persons)):
            for j in range(i + 1, len(persons)):
                p1, p2 = persons[i], persons[j]
                k1 = (type(p1.track_id).__name__, str(p1.track_id))
                k2 = (type(p2.track_id).__name__, str(p2.track_id))
                key = (p1.track_id, p2.track_id) if k1 <= k2 else (p2.track_id, p1.track_id)
                pair = self._pair_states.get(key)
                if pair is None:
                    continue
                duration = ts - pair.proximity_start_time
                if duration < self.min_interaction_seconds:
                    continue
                window_energy = max((s[1] for s in pair.motion_window), default=0.0)
                if window_energy >= self.motion_energy_threshold:
                    dist = math.hypot(p1.cx - p2.cx, p1.cy - p2.cy)
                    return self._build_facts(
                        scenario_id="US07",
                        taxonomy="violent_altercation",
                        severity="critical",
                        confidence=round(min(float(p1.score), float(p2.score)), 3),
                        anchor_time=ts,
                        detection_time=ts,
                        involved_track_ids=[p1.track_id, p2.track_id],
                        extra={
                            "interaction_duration_seconds": round(duration, 2),
                            "pair_distance_px": round(dist, 2),
                            "motion_energy": round(window_energy, 2),
                        },
                    )
        return None

    def _eval_us11_abandoned_object(self, tracks: list[Track], ts: float) -> dict[str, Any] | None:
        for t in tracks:
            if t.label not in WASTE_AND_OBJECT_LABELS:
                continue
            st = self._track_states.get(t.track_id)
            if st is None or st.unattended_since is None:
                continue
            unattended_duration = ts - st.unattended_since
            if unattended_duration < self.min_unattended_seconds:
                continue
            taxonomy = (
                "abandoned_object_dropped"
                if st.associated_person_id is not None
                else "unattended_object_persistent"
            )
            return self._build_facts(
                scenario_id="US11",
                taxonomy=taxonomy,
                severity="high",
                confidence=round(float(t.score), 3),
                anchor_time=ts,
                detection_time=ts,
                involved_track_ids=[t.track_id],
                extra={
                    "unattended_seconds": round(unattended_duration, 2),
                    "object_label": t.label,
                    "observed_placer_departed": st.associated_person_id is not None,
                },
            )
        return None

    def _eval_us12_fallen_tree(
        self,
        tracks: list[Track],
        ts: float,
        dims: tuple[float, float] | None,
    ) -> dict[str, Any] | None:
        frame_area = float(dims[0] * dims[1]) if dims and dims[0] > 0 and dims[1] > 0 else (1920.0 * 1080.0)
        for t in tracks:
            if t.label not in {"potted plant", "fallen_tree", "tree", "branch"}:
                continue
            st = self._track_states.get(t.track_id)
            if st is None or st.dwell_seconds < self.min_persistence_seconds:
                continue
            area_ratio = (t.width * t.height) / max(1.0, frame_area)
            if t.aspect_ratio >= 1.15 and area_ratio >= self.min_obstruction_area_ratio:
                return self._build_facts(
                    scenario_id="US12",
                    taxonomy="fallen_tree",
                    severity="high",
                    confidence=round(float(t.score), 3),
                    anchor_time=ts,
                    detection_time=ts,
                    involved_track_ids=[t.track_id],
                    extra={
                        "obstruction_area_ratio": round(area_ratio, 4),
                        "observation_duration_seconds": round(st.dwell_seconds, 2),
                    },
                )
        return None

    def _eval_us13_streetlight_outage(
        self,
        ts: float,
        env_sigs: Mapping[str, float],
    ) -> dict[str, Any] | None:
        if "mean_luma" not in env_sigs:
            return None
        if not self.is_in_schedule(ts, grace_seconds=self.transition_grace_seconds):
            self._env_active_since.pop("US13", None)
            return None
        mean_luma = float(env_sigs["mean_luma"])
        if mean_luma > self.luminance_threshold:
            self._env_active_since.pop("US13", None)
            return None
        self._env_active_since.setdefault("US13", ts)
        dark_duration = ts - self._env_active_since["US13"]
        if dark_duration < self.min_dark_duration_seconds:
            return None
        return self._build_facts(
            scenario_id="US13",
            taxonomy="streetlight_outage",
            severity="medium",
            confidence=0.88,
            anchor_time=ts,
            detection_time=ts,
            involved_track_ids=[],
            extra={
                "mean_luminance": round(mean_luma, 2),
                "dark_duration_seconds": round(dark_duration, 2),
            },
        )

    def _eval_us14_property_vandalism(self, tracks: list[Track], ts: float) -> dict[str, Any] | None:
        if self.roi_polygon is None:
            return None
        persons = [t for t in tracks if t.label in {"person", "pedestrian"}]
        for p in persons:
            st = self._track_states.get(p.track_id)
            if st is None:
                continue
            first_cx = (st.first_bbox[0] + st.first_bbox[2]) * 0.5
            first_cy = (st.first_bbox[1] + st.first_bbox[3]) * 0.5
            net_disp = math.hypot(p.cx - first_cx, p.cy - first_cy)
            is_linear_walk = st.path_distance > 0 and (net_disp / st.path_distance) > 0.65
            if (
                st.dwell_seconds >= self.min_impact_duration_seconds
                and st.max_speed >= self.motion_energy_threshold
                and not is_linear_walk
            ):
                return self._build_facts(
                    scenario_id="US14",
                    taxonomy="property_vandalism",
                    severity="high",
                    confidence=round(float(p.score), 3),
                    anchor_time=ts,
                    detection_time=ts,
                    involved_track_ids=[p.track_id],
                    extra={
                        "impact_duration_seconds": round(st.dwell_seconds, 2),
                        "peak_motion_speed": round(st.max_speed, 2),
                    },
                )
        return None
