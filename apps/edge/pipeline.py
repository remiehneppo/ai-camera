"""End-to-end Edge Perception Pipeline composing detector, tracker, incident engine, recorder, outbox, and uploader."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import inspect
import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import numpy as np

from apps.edge.crowd_incident import CrowdIncidentEngine
from apps.edge.danger_zone import DangerZoneIncidentEngine
from apps.edge.evidence import EvidenceLifecycle
from apps.edge.geometry import is_normalized_polygon, scale_roi_to_pixels
from apps.edge.health import EdgeHealthMonitor
from apps.edge.incident import IncidentEngine, point_in_polygon
from apps.edge.oracle_detector import OnnxDetector
from apps.edge.parking_incident import ParkingIncidentEngine
from apps.edge.vehicle_incident import VehicleIncidentEngine
from domain.alert_module_config import (
    ALLOWLISTED_FACTORIES,
    AlertModuleDefinition,
    AlertModuleRegistry,
    CameraModuleConfig,
    ConfigError,
    ERROR_FACTORY_NOT_ALLOWED,
    WEEKDAYS,
)
from apps.edge.perception import PerceptionExecution
from apps.edge.outbox import EventOutbox
from apps.edge.pose import PoseManager, PoseOutcome, PoseRequest, PoseScheduler
from apps.edge.quota import StorageQuotaManager
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import ByteTracker
from apps.edge.uploader import EdgeUploader
from apps.edge.snapshot import build_incident_snapshot

logger = logging.getLogger(__name__)


DEFAULT_ODD_POLICY: dict[str, Any] = {
    "version": "default-v1", "low_light_mean": 15.0, "glare_mean": 240.0,
    "low_contrast_std": 5.0, "blur_laplacian_var": None, "freeze_frames": None,
}


def _signature(rgb: np.ndarray) -> bytes:
    return hashlib.sha256(np.ascontiguousarray(rgb)).digest()


def assess_quality(rgb: Any, policy: dict[str, Any] | None = None, *, reason: str | None = None) -> dict[str, Any]:
    """Versioned image-quality assessment. odd_supported is True only for a measured normal frame,
    False for measured degradation, None when quality could not be measured (never inferred as OK)."""
    pol = {**DEFAULT_ODD_POLICY, **(policy or {})}
    base = {"policy_version": pol["version"], "reason": reason}
    if rgb is None or not isinstance(rgb, np.ndarray) or rgb.size == 0 or rgb.ndim < 2:
        return {**base, "state": "unknown", "odd_supported": None, "reason": reason or "invalid_frame"}
    mean_val, std_val = float(np.mean(rgb)), float(np.std(rgb))
    state = "normal"
    if mean_val < pol["low_light_mean"]:
        state = "low_light"
    elif mean_val > pol["glare_mean"]:
        state = "glare"
    elif std_val < pol["low_contrast_std"]:
        state = "low_contrast"
    elif pol["blur_laplacian_var"] is not None and rgb.shape[0] > 2 and rgb.shape[1] > 2:
        g = rgb.reshape(rgb.shape[0], rgb.shape[1], -1).mean(axis=2)
        lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1]
        if float(lap.var()) < pol["blur_laplacian_var"]:
            state = "blur"
    return {**base, "state": state, "odd_supported": state == "normal"}


#: Thresholds a capability policy must declare itself; they are never inherited.
_CAPABILITY_REQUIRED_THRESHOLDS: tuple[str, ...] = ("low_light_mean", "glare_mean", "low_contrast_std")
#: Optional threshold that disables the corresponding check when undeclared or None.
#: Freeze detection is deliberately absent: it needs frame-to-frame state, which stays on
#: PerceptionPipeline, so a stateless helper must not imply that freeze was assessed.
_CAPABILITY_OPTIONAL_THRESHOLDS: tuple[str, ...] = ("blur_laplacian_var",)


def _validated_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate a capability policy and return only the keys it declares itself.

    A capability must not inherit DEFAULT_ODD_POLICY thresholds: a version alone would
    otherwise report ODD support measured with numbers the capability never supplied.
    """
    version = policy.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("quality policy requires a non-empty version")
    missing = [name for name in _CAPABILITY_REQUIRED_THRESHOLDS if name not in policy]
    if missing:
        raise ValueError("quality policy must declare thresholds explicitly: " + ", ".join(missing))
    effective: dict[str, Any] = {"version": version}
    for name in _CAPABILITY_REQUIRED_THRESHOLDS:
        value = policy[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"quality policy threshold {name} must be a finite number")
        effective[name] = float(value)
    for name in _CAPABILITY_OPTIONAL_THRESHOLDS:
        value = policy.get(name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
        ):
            raise ValueError(f"quality policy threshold {name} must be a finite number or None")
        effective[name] = float(value) if value is not None else None
    return effective


def assess_capability_quality(
    rgb: Any,
    *,
    capability: str,
    camera_id: str,
    site_id: str | None = None,
    policy: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Assess one alert capability's quality within its own camera/site ODD scope.

    The result is {"scope": {capability, camera_id, site_id}, "quality": quality}. Scope
    identity is echoed, never inferred: a missing site_id stays None rather than being
    derived from the camera or device name.

    A capability is only assessed against a policy it supplies itself. With no policy the
    result is unknown / odd_supported=None / reason "policy_unconfigured", so quality that
    was never measured cannot be mistaken for supported ODD or for an observation gap.
    A supplied policy must carry "version" plus the thresholds it is measured with, or a
    ValueError is raised instead of silently inheriting global defaults.
    """
    for name, value in (("capability", capability), ("camera_id", camera_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if site_id is not None and (not isinstance(site_id, str) or not site_id.strip()):
        raise ValueError("site_id must be a non-empty string when provided")

    scope = {"capability": capability, "camera_id": camera_id, "site_id": site_id}
    if policy is None:
        # odd_supported stays None: nothing was measured, so it is not "supported" or "degraded".
        # The caller's observation reason is preserved rather than dropped, so a configuration
        # gap and a lost observation stay distinguishable instead of overwriting each other.
        quality: dict[str, Any] = {"state": "unknown", "odd_supported": None,
                                   "reason": "policy_unconfigured", "policy_version": None}
        if reason is not None:
            quality["observation_reason"] = reason
        return {"scope": scope, "quality": quality}
    quality = assess_quality(rgb, _validated_policy(policy), reason=reason)
    return {"scope": scope, "quality": quality}


def evaluate_odd(rgb: np.ndarray) -> str:
    """Backward-compatible state string; invalid frames keep the legacy label."""
    q = assess_quality(rgb)
    return "invalid_frame" if q["state"] == "unknown" else q["state"]


def create_incident_engine(
    factory: str | None = None,
    *,
    camera_id: str,
    device_id: str = "lab-edge-01",
    stream_session_id: str | None = None,
    config: CameraModuleConfig | None = None,
    definition: AlertModuleDefinition | None = None,
    module_name: str | None = None,
    config_version: str | None = None,
    frame_dimensions: tuple[int, int] | tuple[float, float] | None = None,
    **kwargs: Any,
) -> Any:
    """Instantiate an incident engine from an allowlisted factory, definition, and module config."""
    actual_factory = (
        definition.factory
        if definition is not None
        else (factory or (config.module if config is not None and config.module in ALLOWLISTED_FACTORIES else None))
    )
    if not actual_factory or actual_factory not in ALLOWLISTED_FACTORIES:
        raise ConfigError(
            ERROR_FACTORY_NOT_ALLOWED,
            f"module factory '{actual_factory}' is not in the registered allowlist",
            field="factory",
        )
    mod_name = module_name or (definition.module if definition is not None else (config.module if config is not None else actual_factory))
    cfg_version = config_version or (definition.config_version if definition is not None else kwargs.pop("config_version", None))

    roi_poly = config.roi_polygon() if config is not None else kwargs.pop("roi_polygon", None)
    if frame_dimensions is not None and roi_poly is not None:
        roi_poly = scale_roi_to_pixels(roi_poly, frame_dimensions[0], frame_dimensions[1])
    schedule = config.schedule if config is not None else kwargs.pop("schedule", None)
    exceptions = config.exceptions if config is not None else kwargs.pop("exceptions", None)

    thresholds: dict[str, Any] = dict(config.thresholds) if config is not None else {}
    params = {**thresholds, **kwargs}
    if cfg_version is not None:
        params["config_version"] = cfg_version

    if actual_factory == "person_down":
        return IncidentEngine(
            camera_id=camera_id,
            device_id=device_id,
            stream_session_id=stream_session_id,
            module_name=mod_name,
            roi_polygon=roi_poly,
            frame_dimensions=frame_dimensions,
            **params,
        )
    elif actual_factory == "danger_zone":
        return DangerZoneIncidentEngine(
            camera_id=camera_id,
            device_id=device_id,
            stream_session_id=stream_session_id,
            module_name=mod_name,
            roi_polygon=roi_poly,
            schedule=schedule,
            exceptions=exceptions,
            **params,
        )
    elif actual_factory == "illegal_parking":
        return ParkingIncidentEngine(
            camera_id=camera_id,
            device_id=device_id,
            stream_session_id=stream_session_id,
            module_name=mod_name,
            roi_polygon=roi_poly,
            schedule=schedule,
            exceptions=exceptions,
            **params,
        )
    elif actual_factory == "crowd_incident":
        raw_schedule = schedule if schedule is not None else params.pop("schedule_filter", None)
        schedule_filter: Any = None
        if callable(raw_schedule) or isinstance(raw_schedule, dict):
            schedule_filter = raw_schedule
        elif raw_schedule is not None:
            windows = tuple(raw_schedule)
            def _filter(ts: float) -> bool:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                day_name = WEEKDAYS[dt.weekday()]
                sec = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1_000_000
                for w in windows:
                    w_days = getattr(w, "days", ()) if not isinstance(w, dict) else w.get("days", ())
                    w_start = getattr(w, "start_second", 0) if not isinstance(w, dict) else w.get("start_second", 0)
                    w_end = getattr(w, "end_second", 86400) if not isinstance(w, dict) else w.get("end_second", 86400)
                    if day_name in w_days and w_start <= sec <= w_end:
                        return True
                return False
            schedule_filter = _filter
        return CrowdIncidentEngine(
            camera_id=camera_id,
            device_id=device_id,
            stream_session_id=stream_session_id,
            module_name=mod_name,
            roi_polygon=roi_poly,
            schedule_filter=schedule_filter,
            exceptions=exceptions,
            **params,
        )
    elif actual_factory == "vehicle_incident":
        return VehicleIncidentEngine(
            camera_id=camera_id,
            device_id=device_id,
            stream_session_id=stream_session_id,
            module_name=mod_name,
            roi_polygon=roi_poly,
            **params,
        )
    raise ConfigError(ERROR_FACTORY_NOT_ALLOWED, f"unsupported factory '{actual_factory}'", field="factory")

class PerceptionPipeline:
    """Perception pipeline composing detection, ByteTrack, fall incident engine, and evidence upload."""

    def __init__(
        self,
        *,
        recorder: FileRecorder,
        outbox: EventOutbox,
        detector: OnnxDetector | None = None,
        tracker: ByteTracker | None = None,
        incident_engine: IncidentEngine | None = None,
        uploader: EdgeUploader | None = None,
        manifest_path: str | Path | None = None,
        model_path: str | Path | None = None,
        camera_id: str = "lab-camera-01",
        device_id: str = "lab-edge-01",
        stream_session_id: str | None = None,
        pipeline_id: str = "perception-pipeline-v1",
        pipeline_version: str = "1",
        config_version: str = "pipeline-v1",
        calibration_version: str = "uncalibrated",
        quality_state: str = "unknown",
        odd_policy: dict[str, Any] | None = None,
        roi_polygon: list[list[float]] | list[tuple[float, float]] | None = None,
        origin: str = "live",
        execution: PerceptionExecution | None = None,
        pose_manager: PoseManager | None = None,
        pose_scheduler: PoseScheduler | None = None,
        health: EdgeHealthMonitor | None = None,
        quota_manager: StorageQuotaManager | None = None,
        site_id: str | None = None,
        incident_engines: Sequence[Any] | Mapping[str, Any] | None = None,
        module_configs: Sequence[CameraModuleConfig] | None = None,
        alert_registry: AlertModuleRegistry | None = None,
        capability_policies: Mapping[str, dict[str, Any]] | None = None,
    ) -> None:
        self.alert_registry = alert_registry
        self.recorder = recorder
        self.outbox = outbox
        self.uploader = uploader
        self.quota_manager = quota_manager or getattr(health, "quota_manager", None) or StorageQuotaManager(
            recorder=recorder, outbox=outbox,
        )
        self.evidence = EvidenceLifecycle(outbox, recorder, uploader, quota_manager=self.quota_manager)
        self.camera_id = camera_id
        self.device_id = device_id
        self.stream_session_id = stream_session_id or str(uuid4())
        self.pipeline_id = pipeline_id
        self.pipeline_version = pipeline_version
        self.config_version = config_version
        self.calibration_version = calibration_version
        self._configured_quality_state = quality_state
        self.quality_state = quality_state
        self.odd_policy = {**DEFAULT_ODD_POLICY, **(odd_policy or {})}
        self.quality: dict[str, Any] = {"state": quality_state, "odd_supported": None,
                                        "policy_version": self.odd_policy["version"], "reason": None}
        self._prev_signature: bytes | None = None
        self._same_frames = 0
        self.roi_polygon = roi_polygon
        self.origin = origin

        if execution is not None and (detector is not None or manifest_path or model_path):
            raise ValueError("provide execution or detector configuration, not both")
        self.execution = execution or PerceptionExecution(detector, manifest_path=manifest_path,
                                                         model_path=model_path, origin=origin)
        self.detector = self.execution.detector
        self.pose_manager = pose_manager
        self.pose_scheduler: PoseScheduler | None
        if pose_scheduler is not None:
            self.pose_scheduler = pose_scheduler
            if pose_manager is not None:
                pose_manager.scheduler = pose_scheduler
        elif pose_manager is not None:
            self.pose_scheduler = getattr(pose_manager, "scheduler", None)
        else:
            self.pose_scheduler = None
        self.core_epoch = 1
        self._last_frame_id = -1
        self._last_timestamp: float | None = None
        self.last_observation: dict[str, Any] | None = None
        self._processing_lock = threading.RLock()
        self._lineage = (self.camera_id, self.stream_session_id, self.core_epoch, self.origin, self.config_version)

        # Tracking and incident engines
        self.site_id = site_id
        self.capability_policies = dict(capability_policies or {})
        self.tracker = tracker or ByteTracker(
            high_threshold=0.5,
            low_threshold=0.1,
            match_threshold=0.2,
        )

        engines_list: list[Any] = []
        if incident_engines is not None:
            if isinstance(incident_engines, Mapping):
                engines_list.extend(incident_engines.values())
            else:
                engines_list.extend(incident_engines)

        if module_configs is not None:
            for mod_cfg in module_configs:
                if not mod_cfg.enabled or mod_cfg.camera_id != self.camera_id:
                    continue
                defn: AlertModuleDefinition | None = None
                if alert_registry is not None:
                    try:
                        defn = alert_registry.definition(mod_cfg.module)
                    except Exception:
                        defn = None
                factory_name = defn.factory if defn is not None else (mod_cfg.module if mod_cfg.module in ALLOWLISTED_FACTORIES else None)
                if not factory_name or factory_name not in ALLOWLISTED_FACTORIES:
                    raise ConfigError(
                        ERROR_FACTORY_NOT_ALLOWED,
                        f"module '{mod_cfg.module}' has no allowlisted factory",
                        field="factory",
                    )
                eng = create_incident_engine(
                    factory=factory_name,
                    camera_id=self.camera_id,
                    device_id=self.device_id,
                    stream_session_id=self.stream_session_id,
                    config=mod_cfg,
                    definition=defn,
                    module_name=mod_cfg.module,
                    origin=self.origin,
                )
                engines_list.append(eng)
        no_selection = (incident_engines is None and module_configs is None and incident_engine is None)
        if incident_engine is not None:
            if incident_engine not in engines_list:
                engines_list.insert(0, incident_engine)
        elif no_selection:
            engines_list.append(
                IncidentEngine(
                    standing_aspect_ratio=0.85,
                    lying_aspect_ratio=1.2,
                    min_drop_velocity=15.0,
                    min_lying_duration=3.0,
                    cooldown_seconds=30.0,
                    roi_polygon=self.roi_polygon,
                )
            )

        self.incident_engines: list[Any] = engines_list
        self.incident_engine: IncidentEngine | None = self.incident_engines[0] if self.incident_engines else None
        if self.incident_engine is not None and getattr(self.incident_engine, "roi_polygon", None) is None:
            self.incident_engine.roi_polygon = self.roi_polygon

        provenance = self.execution.provenance
        self.model_lineage = [{"role": "detector", "version": provenance.get("model_id", "unknown")}]
        self.model_artifact_hash = provenance.get("model_sha256", "unknown_artifact")

        self.health = health or EdgeHealthMonitor(
            recorder=self.recorder,
            recorder_session_id=self.stream_session_id,
            outbox=self.outbox,
            backend_checker=uploader,
            quota_manager=self.quota_manager,
        )
        self.health.quota_manager = self.quota_manager
        self._cached_roi_key: tuple[Any, int, int] | None = None
        self._cached_pixel_roi: list[list[float]] | None = None
        self._engine_param_cache: dict[int, tuple[bool, bool]] = {}
    def _get_pixel_roi(self, width: int, height: int) -> list[list[float]] | None:
        """Retrieve or compute cached pixel-scaled ROI polygon for current frame dimensions."""
        if self.roi_polygon is None:
            return None
        cache_key = (id(self.roi_polygon), int(width), int(height))
        if self._cached_roi_key == cache_key and self._cached_pixel_roi is not None:
            return self._cached_pixel_roi
        scaled = scale_roi_to_pixels(self.roi_polygon, float(width), float(height))
        self._cached_pixel_roi = scaled or [[float(p[0]), float(p[1])] for p in self.roi_polygon if len(p) >= 2]
        self._cached_roi_key = cache_key
        return self._cached_pixel_roi

    def _dispatch_engine_process_tracks(
        self,
        engine: Any,
        tracks: list[Any],
        timestamp: float,
        pose_outcomes: list[Any],
        frame_dimensions: tuple[float, float],
    ) -> list[dict[str, Any]]:
        """Dispatch track evaluation to an incident engine matching its supported signature."""
        engine_id = id(engine)
        params_info = self._engine_param_cache.get(engine_id)
        if params_info is None:
            try:
                sig = inspect.signature(engine.process_tracks)
                params = sig.parameters
                has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
                has_pose = has_varkw or ("pose_outcomes" in params)
                has_dims = has_varkw or ("frame_dimensions" in params)
                params_info = (has_pose, has_dims)
            except Exception:
                params_info = (True, True)
            self._engine_param_cache[engine_id] = params_info

        has_pose, has_dims = params_info
        kwargs: dict[str, Any] = {}
        if has_pose:
            kwargs["pose_outcomes"] = pose_outcomes
        if has_dims:
            kwargs["frame_dimensions"] = frame_dimensions

        return engine.process_tracks(tracks, timestamp=timestamp, **kwargs)
    def get_engine(self, name_or_factory: str) -> Any | None:
        """Find an active incident engine by module name or factory."""
        for engine in self.incident_engines:
            if getattr(engine, "factory", None) == name_or_factory or getattr(engine, "module", None) == name_or_factory:
                return engine
        return None


    def process_frame(self, rgb, timestamp, frame_id, *, detections=None, observation_status=None):
        with self._processing_lock:
            return self._process_frame(rgb, timestamp, frame_id, detections=detections,
                                       observation_status=observation_status)

    def _process_frame(
        self,
        rgb: np.ndarray,
        timestamp: float,
        frame_id: int,
        *,
        detections: list[dict[str, Any]] | None = None,
        observation_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Process one video frame: detection -> tracking -> incident engine -> event/pin/outbox."""
        ts = float(timestamp)
        fid = int(frame_id)

        lineage = (self.camera_id, self.stream_session_id, self.core_epoch, self.origin, self.config_version)
        if lineage != self._lineage:
            self.tracker.reset()
            for engine in self.incident_engines:
                engine.reset()
            if self.pose_manager is not None:
                self.pose_manager.set_epoch(self.core_epoch)
            self._last_frame_id = -1
            self._last_timestamp = None
            self._lineage = lineage
            self._set_unknown_quality("session_reset")
        if fid <= self._last_frame_id:
            frame = self.execution.frame(self.camera_id, self.stream_session_id, self.core_epoch,
                                         self.origin, fid, ts)
            self._set_unknown_quality("detection_stale")
            self.last_observation = {
                **frame,
                "detection_status": "stale",
                "detections": [],
                "quality": dict(self.quality),
                "quality_state": self.quality_state,
            }
            self._observation_gap()
            return []
        if self._last_timestamp is not None and ts <= self._last_timestamp:
            ts = self._last_timestamp + 1e-6
        frame = self.execution.frame(self.camera_id, self.stream_session_id, self.core_epoch,
                                     self.origin, fid, ts)
        if self.pose_manager is not None:
            self.pose_manager.cache_frame(self.camera_id, self.stream_session_id, self.core_epoch, fid, rgb)
        self._last_frame_id = fid
        self._last_timestamp = ts
        self.health.mark_started()
        self.health.record_frame_received(receive_time=time.time())
        self.health.set_component_capability("analytics", "active")
        try:
            observation = self.execution.execute(rgb, frame, detections=detections, status=observation_status)
        except Exception:
            self.health.set_component_capability("analytics", "failed")
            raise
        self.last_observation = observation
        if observation["detection_status"] not in {"ok", "ok_empty"}:
            self._set_unknown_quality(f"detection_{observation['detection_status']}")
            observation["quality"] = dict(self.quality)
            observation["quality_state"] = self.quality_state
            self.health.set_component_capability("analytics", "failed")
            self._observation_gap()
            return []
        formatted_dets = observation["detections"]
        self._update_quality(rgb)
        observation["quality_state"] = self.quality_state
        observation["quality"] = dict(self.quality)

        if self.roi_polygon is not None:
            roi_to_check = self._get_pixel_roi(rgb.shape[1], rgb.shape[0]) or self.roi_polygon
            formatted_dets = [
                d for d in formatted_dets
                if len(d.get("bbox", [])) >= 4 and point_in_polygon(
                    (d["bbox"][0] + d["bbox"][2]) / 2.0,
                    float(d["bbox"][3]),
                    roi_to_check,
                )
            ]

        provenance = observation.get("provenance") or {}
        if provenance:
            self.model_lineage = [{"role": "detector", "version": provenance.get("model_id", "unknown")}]
            self.model_artifact_hash = provenance.get("model_sha256", "unknown_artifact")

        # 2. Update multi-object tracker
        tracks = self.tracker.update(formatted_dets, timestamp=ts)

        for track in self.tracker.get_all_tracks():
            if track.state == "removed":
                track.history.clear()

        # Pose candidate scheduling across branches
        pose_outcomes: list[PoseOutcome] = []
        if self.pose_scheduler is not None:
            active_tracks = [t for t in tracks if t.state == "active"]
            candidates = self.pose_scheduler.schedule_tracks(
                tracks=active_tracks,
                current_time=ts,
                frame_id=fid,
                camera_id=self.camera_id,
                stream_session_id=self.stream_session_id,
                core_epoch=self.core_epoch,
            )
            if self.pose_manager is not None:
                for cand in candidates:
                    self.pose_manager.submit_request(cand)
                pose_outcomes = self.pose_manager.process_pending(current_time=ts)

        observation["pose_capability"] = self.get_pose_capability()
        observation["pose_metrics"] = self.get_pose_metrics()
        if pose_outcomes:
            observation["pose_outcomes"] = [o.to_dict() for o in pose_outcomes]
            observation["pose_status"] = "ok" if any(o.status == "ok" for o in pose_outcomes) else pose_outcomes[0].status
            observation["pose_reason"] = None if any(o.status == "ok" for o in pose_outcomes) else pose_outcomes[0].reason

        # 3. Assess incident engines
        emitted_events: list[dict[str, Any]] = []
        frame_dims = (float(rgb.shape[1]), float(rgb.shape[0]))
        for engine in self.incident_engines:
            incidents = self._dispatch_engine_process_tracks(
                engine,
                tracks=tracks,
                timestamp=ts,
                pose_outcomes=pose_outcomes,
                frame_dimensions=frame_dims,
            )
            if not incidents:
                continue
            cap_name = str(getattr(engine, "factory", getattr(engine, "module", "person_down")))
            quality = self.quality
            scope = None
            if cap_name in self.capability_policies:
                scoped = assess_capability_quality(
                    rgb,
                    capability=cap_name,
                    camera_id=self.camera_id,
                    site_id=self.site_id,
                    policy=self.capability_policies[cap_name],
                )
                quality = scoped["quality"]
                scope = scoped["scope"]
            feature = {
                "pipeline_id": (
                    self.pipeline_id
                    if cap_name == "person_down"
                    else getattr(engine, "pipeline_id", self.pipeline_id)
                ),
                "pipeline_version": (
                    self.pipeline_version
                    if cap_name == "person_down"
                    else getattr(engine, "pipeline_version", self.pipeline_version)
                ),
                "config_version": getattr(engine, "config_version", None) or self.config_version,
                "rule_lineage": getattr(engine, "rule_lineage", []),
            }
            for facts in incidents:
                context = {
                    "camera_id": self.camera_id,
                    "device_id": self.device_id,
                    "stream_session_id": self.stream_session_id,
                    "origin": self.origin,
                    "model_lineage": self._event_model_lineage(),
                    "model_artifact_hash": self.model_artifact_hash,
                    "calibration_version": self.calibration_version,
                    "quality": quality,
                    "capability_scope": scope,
                }
                snapshot = build_incident_snapshot(facts, context=context, feature=feature)
                self.evidence.persist(snapshot)
                emitted_events.append(snapshot)
        return emitted_events

    def _set_unknown_quality(self, reason: str) -> None:
        self._prev_signature = None
        self._same_frames = 0
        if self._configured_quality_state != "unknown":
            return
        self.quality = assess_quality(None, self.odd_policy, reason=reason)
        self.quality_state = "unknown"

    def _update_quality(self, rgb: Any) -> None:
        if self._configured_quality_state != "unknown":
            return  # externally configured state: supported-ODD is not claimed
        prev = self.quality["state"]
        q = assess_quality(rgb, self.odd_policy)
        n = self.odd_policy["freeze_frames"]
        if q["state"] != "unknown" and n:
            sig = _signature(rgb)
            same = self._prev_signature is not None and sig == self._prev_signature
            self._same_frames = self._same_frames + 1 if same else 0
            self._prev_signature = sig
            if self._same_frames >= n:
                q.update(state="frozen", odd_supported=False, reason="identical_frames")
        if q["state"] == "normal" and prev != "normal" and (prev != "unknown" or self.quality.get("reason")):
            q["recovery_reason"] = f"recovered_from_{self.quality['reason'] if prev == 'unknown' else prev}"
        self.quality = q
        self.quality_state = q["state"]

    def observation_gap(self) -> None:
        """Mark observation gap on frame drop, network hiccup, or stream loss."""
        with self._processing_lock:
            self._observation_gap()

    def _observation_gap(self):
        for engine in self.incident_engines:
            engine.observation_gap()
        # Retain track IDs/cooldown, discard pre-gap motion and standing evidence.
        for track in self.tracker.get_all_tracks():
            track.history.clear()
        self._set_unknown_quality("observation_gap")

    def _event_model_lineage(self) -> list[dict[str, Any]]:
        """Model lineage for one event, extended with the pose estimator when one is loaded."""
        lineage = list(self.model_lineage)
        estimator = getattr(self.pose_manager, "estimator", None) if self.pose_manager is not None else None
        manifest = getattr(estimator, "manifest", None)
        model_id = manifest.get("model_id") if isinstance(manifest, dict) else None
        if model_id and not any(entry.get("role") == "pose_estimator" for entry in lineage):
            lineage.append({
                "role": "pose_estimator",
                "version": str(model_id),
            })
        return lineage

    def request_pose(
        self,
        request: dict[str, Any] | PoseRequest,
        rgb: np.ndarray | None = None,
        current_time: float | None = None,
    ) -> PoseOutcome:
        """Submit and synchronously evaluate a pose request."""
        req = PoseRequest.from_dict(request) if isinstance(request, dict) else request
        if self.pose_manager is None:
            return PoseOutcome(
                request_id=req.request_id,
                camera_id=req.camera_id,
                stream_session_id=req.stream_session_id,
                core_epoch=req.core_epoch,
                frame_id=req.frame_id,
                track_id=req.track_id,
                status="failed",
                reason="pose_manager_unavailable",
                executed_at=datetime.now(timezone.utc).timestamp(),
            )
        eval_time = current_time if current_time is not None else self._last_timestamp
        return self.pose_manager.request_pose(req, rgb=rgb, current_time=eval_time)

    def set_core_epoch(self, epoch: int) -> None:
        """Update core epoch and notify pose manager of invalidation."""
        self.core_epoch = epoch
        if self.pose_manager is not None:
            self.pose_manager.set_epoch(epoch)
        if self.pose_scheduler is not None and (
            self.pose_manager is None or self.pose_scheduler is not getattr(self.pose_manager, "scheduler", None)
        ):
            self.pose_scheduler.set_epoch(epoch)

    def status(self) -> dict[str, Any]:
        """Report pipeline operational status, quality state, and capability."""
        with self._processing_lock:
            return {
                "camera_id": self.camera_id,
                "device_id": self.device_id,
                "stream_session_id": self.stream_session_id,
                "core_epoch": self.core_epoch,
                "quality_state": self.quality_state,
                "pose_capability": self.get_pose_capability(),
                "pose_metrics": self.get_pose_metrics(),
            }

    def get_pose_metrics(self) -> dict[str, Any]:
        """Retrieve branch coverage and scheduling metrics."""
        if self.pose_manager is not None and hasattr(self.pose_manager, "get_metrics"):
            return self.pose_manager.get_metrics()
        if self.pose_scheduler is not None:
            return self.pose_scheduler.get_metrics()
        return {}

    def get_pose_capability(self) -> dict[str, Any]:
        """Retrieve current pose estimation capability and degradation reason."""
        if self.pose_manager is not None and hasattr(self.pose_manager, "get_capability_status"):
            return {
                "status": self.pose_manager.get_capability_status(),
                "reason": self.pose_manager.get_degraded_reason(),
            }
        if self.pose_scheduler is not None:
            return {
                "status": self.pose_scheduler.capability_status,
                "reason": self.pose_scheduler.degraded_reason,
            }
        return {
            "status": "unsupported",
            "reason": "pose_manager_unavailable",
        }

    def trigger_upload(self, *, reconcile: bool = True, finish_sessions=()) -> int:
        """Trigger reconciliation and upload of pending events and evidence clips to server."""
        if self.uploader is None:
            return 0

        if reconcile:
            self.evidence.reconcile(finish_sessions=finish_sessions)

        # Deliver pending event metadata to server /v1/events
        try:
            from apps.edge.send_synthetic import deliver_pending

            deliver_pending(
                self.outbox,
                self.uploader.server_url,
                self.uploader.device_token,
            )
        except Exception as exc:
            logger.warning("Event metadata delivery failed: %s", exc)

        # Upload pending evidence clips to /v1/evidence
        return self.evidence.upload_pending()
