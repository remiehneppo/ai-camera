"""Independent alert-module x camera configuration contract (Ticket #03 delta slice).

Pure domain module: no I/O, no framework or infrastructure imports. A configuration is
canonical and immutable; parsing is fail-fast, reports module/camera/field context, and
never echoes the offending value, so a rejected configuration cannot leak a secret into a
log or an error response.

The registry keeps one activation state per (module, camera) pair, so registering a new
module never inherits another module's state, and a camera session change re-binds the
activation instead of silently carrying observations across sessions. Registration is not a
capacity claim: it records configuration, not concurrent runtime load.

ADR-0001 requires an allowlisted factory per registered module and sharing of
source/detector/tracker/pose when compatible: a definition names the factory that will run
it, `register` rejects any factory outside the allowlist, and modules that declare the same
perception profile on the same camera are reported as one perception group instead of two.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Final, FrozenSet, Iterable, Mapping, NamedTuple, Optional, Pattern, Tuple

__all__ = [
    "ALLOWLISTED_FACTORIES",
    "ActivationState",
    "AlertModuleDefinition",
    "AlertModuleRegistry",
    "CONFIG_FIELDS",
    "CameraModuleConfig",
    "ConfigError",
    "ExceptionRule",
    "RegionOfInterest",
    "SCHEMA_VERSION",
    "STATUS_ACTIVE",
    "STATUS_DISABLED",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "ScheduleWindow",
    "WEEKDAYS",
    "parse_camera_module_config",
]

SCHEMA_VERSION: Final[str] = "module-camera-config-v1"

#: Factories this codebase ships; a module whose factory is outside this set is refused.
ALLOWLISTED_FACTORIES: Final[FrozenSet[str]] = frozenset(
    {"person_down", "vehicle_incident", "danger_zone", "illegal_parking", "crowd_incident"}
)

#: Configuration keys an operator may set for one module on one camera.
CONFIG_FIELDS: Final[FrozenSet[str]] = frozenset(
    {"version", "enabled", "disabled_reason", "roi", "schedule", "thresholds", "exceptions"}
)

#: Fields a module definition may declare as required when the module is enabled.
REQUIRABLE_FIELDS: Final[FrozenSet[str]] = frozenset({"roi", "schedule", "thresholds", "exceptions"})

WEEKDAYS: Final[Tuple[str, ...]] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

STATUS_PENDING: Final[str] = "pending"
STATUS_ACTIVE: Final[str] = "active"
STATUS_DISABLED: Final[str] = "disabled"
STATUS_REJECTED: Final[str] = "rejected"

#: Operator-facing capability per activation status; "not_activated" is not "disabled".
_CAPABILITY_BY_STATUS: Final[dict[str, str]] = {
    STATUS_ACTIVE: "enabled",
    STATUS_DISABLED: "disabled",
    STATUS_PENDING: "not_activated",
    STATUS_REJECTED: "rejected",
}

ERROR_INVALID_MODULE_ID: Final[str] = "invalid_module_id"
ERROR_INVALID_CAMERA_ID: Final[str] = "invalid_camera_id"
ERROR_INVALID_DEFINITION: Final[str] = "invalid_module_definition"
ERROR_DUPLICATE_MODULE: Final[str] = "duplicate_module"
ERROR_UNKNOWN_MODULE: Final[str] = "unknown_module"
ERROR_FACTORY_NOT_ALLOWED: Final[str] = "factory_not_allowlisted"
ERROR_SECRET_FIELD: Final[str] = "secret_field_not_allowed"
ERROR_UNKNOWN_FIELD: Final[str] = "unknown_config_field"
ERROR_MISSING_REQUIRED_FIELD: Final[str] = "missing_required_field"
ERROR_MISSING_DISABLED_REASON: Final[str] = "missing_disabled_reason"
ERROR_INVALID_FIELD_TYPE: Final[str] = "invalid_field_type"
ERROR_INVALID_CONFIG_VERSION: Final[str] = "invalid_config_version"
ERROR_INVALID_SESSION_ID: Final[str] = "invalid_session_id"
ERROR_INVALID_ROI: Final[str] = "invalid_region_of_interest"
ERROR_INVALID_SCHEDULE: Final[str] = "invalid_schedule_window"
ERROR_UNKNOWN_THRESHOLD: Final[str] = "unknown_threshold"
ERROR_INVALID_THRESHOLD: Final[str] = "invalid_threshold_value"
ERROR_INVALID_EXCEPTION: Final[str] = "invalid_exception"
ERROR_STALE_CONFIG_VERSION: Final[str] = "stale_config_version"

_IDENTIFIER: Final[Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_SECRET_KEY: Final[Pattern[str]] = re.compile(
    r"secret|token|passw|credential|api[_-]?key|private[_-]?key|bearer|signature", re.IGNORECASE
)


class ConfigError(ValueError):
    """Typed fail-fast error carrying module/camera/field context.

    Messages name fields, never values: a rejected configuration must not echo a secret.
    `message` keeps the un-prefixed text so a caller can re-raise the same failure with
    added context without duplicating the code prefix.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        module: Optional[str] = None,
        camera_id: Optional[str] = None,
        field: Optional[str] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.module = module
        self.camera_id = camera_id
        self.field = field
        context = ", ".join(
            name + "=" + value
            for name, value in (("module", module), ("camera", camera_id), ("field", field))
            if value
        )
        super().__init__(code + ": " + message + (" [" + context + "]" if context else ""))

    def describe(self) -> dict[str, Optional[str]]:
        return {"code": self.code, "module": self.module, "camera_id": self.camera_id, "field": self.field}


class _Place(NamedTuple):
    """Which module x camera a failure belongs to; keeps error context out of every signature."""

    module: Optional[str] = None
    camera_id: Optional[str] = None

    def fail(self, code: str, message: str, field: Optional[str] = None) -> ConfigError:
        return ConfigError(code, message, module=self.module, camera_id=self.camera_id, field=field)


def _require_identifier(value: Any, code: str, name: str, place: Optional[_Place] = None) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.match(value):
        if place is None:
            raise ConfigError(code, name + " must be a safe identifier")
        raise place.fail(code, name + " must be a safe identifier")
    return value


def _is_empty(value: Any) -> bool:
    try:
        return not len(value)
    except TypeError:
        return False


def _secret_keys(payload: Mapping[str, Any]) -> Tuple[str, ...]:
    found: list[str] = []
    for key, value in payload.items():
        if _SECRET_KEY.search(str(key)):
            found.append(str(key))
        elif isinstance(value, Mapping):
            found.extend(_secret_keys(value))
    return tuple(sorted(found))


@dataclass(frozen=True)
class RegionOfInterest:
    """Normalised polygon (coordinates in [0, 1]) in source frame space."""

    points: Tuple[Tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ConfigError(ERROR_INVALID_ROI, "a region of interest needs at least three points")
        for point in self.points:
            if not isinstance(point, tuple) or len(point) != 2:
                raise ConfigError(ERROR_INVALID_ROI, "region of interest points must be (x, y) pairs")
            for value in point:
                if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
                    raise ConfigError(ERROR_INVALID_ROI, "region of interest coordinates must be normalised to [0, 1]")

    def as_polygon(self) -> list[list[float]]:
        """Shape accepted by `apps.edge.pipeline.Pipeline(roi_polygon=...)`."""
        return [[float(x), float(y)] for x, y in self.points]


@dataclass(frozen=True)
class ScheduleWindow:
    """Inclusive local-time window; start/end are seconds of day."""

    days: Tuple[str, ...]
    start_second: int
    end_second: int

    def __post_init__(self) -> None:
        if not self.days or len(set(self.days)) != len(self.days) or set(self.days) - set(WEEKDAYS):
            raise ConfigError(ERROR_INVALID_SCHEDULE, "schedule days must be unique weekday names")
        for value in (self.start_second, self.end_second):
            if type(value) is not int:
                raise ConfigError(ERROR_INVALID_SCHEDULE, "schedule bounds must be integer seconds of day")
        if not 0 <= self.start_second < self.end_second <= 86400:
            raise ConfigError(ERROR_INVALID_SCHEDULE, "schedule window must satisfy 0 <= start < end <= 86400")


@dataclass(frozen=True)
class ExceptionRule:
    """A named, reviewed exception (for example a permitted parking interval)."""

    code: str
    reason: str

    def __post_init__(self) -> None:
        _require_identifier(self.code, ERROR_INVALID_EXCEPTION, "exception code")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ConfigError(ERROR_INVALID_EXCEPTION, "exception requires a reason")


@dataclass(frozen=True)
class AlertModuleDefinition:
    """What one alert module needs before it may be enabled on a camera.

    `factory` names the allowlisted pipeline factory that will run the module; two modules
    that declare the same `perception_profile` on one camera share source/detector/tracker/
    pose rather than decoding and inferring twice.
    """

    module: str
    config_version: str
    factory: str
    required_fields: FrozenSet[str] = frozenset()
    thresholds: FrozenSet[str] = frozenset()
    perception_profile: Optional[str] = None

    def __post_init__(self) -> None:
        place = _Place(self.module if isinstance(self.module, str) else None)
        _require_identifier(self.module, ERROR_INVALID_MODULE_ID, "module")
        if not isinstance(self.config_version, str) or not self.config_version.strip():
            raise place.fail(ERROR_INVALID_DEFINITION, "config_version must be a non-empty string")
        _require_identifier(self.factory, ERROR_FACTORY_NOT_ALLOWED, "factory", place)
        if not isinstance(self.required_fields, (frozenset, set)):
            raise place.fail(ERROR_INVALID_DEFINITION, "required_fields must be a set of field names")
        if set(self.required_fields) - REQUIRABLE_FIELDS:
            raise place.fail(ERROR_INVALID_DEFINITION, "required_fields may only name roi/schedule/thresholds/exceptions")
        if not isinstance(self.thresholds, (frozenset, set)):
            raise place.fail(ERROR_INVALID_DEFINITION, "thresholds must be a set of threshold names")
        for name in self.thresholds:
            _require_identifier(name, ERROR_INVALID_DEFINITION, "threshold name", place)
        if self.perception_profile is None:
            object.__setattr__(self, "perception_profile", self.factory)
        else:
            _require_identifier(self.perception_profile, ERROR_INVALID_DEFINITION, "perception_profile", place)


@dataclass(frozen=True)
class CameraModuleConfig:
    """Canonical configuration for one module on one camera."""

    module: str
    camera_id: str
    version: int
    enabled: bool
    disabled_reason: Optional[str] = None
    roi: Tuple[RegionOfInterest, ...] = ()
    schedule: Tuple[ScheduleWindow, ...] = ()
    thresholds: Tuple[Tuple[str, float], ...] = ()
    exceptions: Tuple[ExceptionRule, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.module, ERROR_INVALID_MODULE_ID, "module")
        _require_identifier(self.camera_id, ERROR_INVALID_CAMERA_ID, "camera_id", _Place(self.module if isinstance(self.module, str) else None))
        place = _Place(self.module, self.camera_id)
        if type(self.version) is not int or self.version <= 0:
            raise place.fail(ERROR_INVALID_CONFIG_VERSION, "version must be a positive integer", "version")
        if type(self.enabled) is not bool:
            raise place.fail(ERROR_INVALID_FIELD_TYPE, "enabled must be boolean", "enabled")
        if not self.enabled:
            if not isinstance(self.disabled_reason, str) or not self.disabled_reason.strip():
                raise place.fail(ERROR_MISSING_DISABLED_REASON, "a disabled module needs a reason", "disabled_reason")
            object.__setattr__(self, "disabled_reason", self.disabled_reason.strip())
        elif self.disabled_reason is not None:
            raise place.fail(ERROR_INVALID_FIELD_TYPE, "an enabled module cannot carry a disabled reason", "disabled_reason")
        names = [name for name, _ in self.thresholds]
        if len(set(names)) != len(names) or names != sorted(names):
            raise place.fail(ERROR_INVALID_THRESHOLD, "thresholds must be unique and ordered by name", "thresholds")

    def threshold(self, name: str) -> Optional[float]:
        return dict(self.thresholds).get(name)

    def roi_polygon(self) -> Optional[list[list[float]]]:
        return self.roi[0].as_polygon() if self.roi else None

    def describe(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "camera_id": self.camera_id,
            "version": self.version,
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
            "roi": [[list(point) for point in region.points] for region in self.roi],
            "schedule": [
                {"days": list(window.days), "start_second": window.start_second, "end_second": window.end_second}
                for window in self.schedule
            ],
            "thresholds": {name: value for name, value in self.thresholds},
            "exceptions": [{"code": rule.code, "reason": rule.reason} for rule in self.exceptions],
        }

    @property
    def config_hash(self) -> str:
        canonical = json.dumps(self.describe(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_roi(raw: Any, place: _Place) -> Tuple[RegionOfInterest, ...]:
    if not isinstance(raw, (list, tuple)):
        raise place.fail(ERROR_INVALID_FIELD_TYPE, "roi must be a list", "roi")
    regions: list[RegionOfInterest] = []
    for item in raw:
        if not isinstance(item, (list, tuple)):
            raise place.fail(ERROR_INVALID_ROI, "each region must be a list of points", "roi")
        points = tuple(
            (point[0], point[1]) for point in item if isinstance(point, (list, tuple)) and len(point) == 2
        )
        if len(points) != len(item):
            raise place.fail(ERROR_INVALID_ROI, "each point must be an (x, y) pair", "roi")
        try:
            regions.append(RegionOfInterest(points=points))
        except ConfigError as error:
            raise place.fail(error.code, error.message, "roi") from None
    return tuple(regions)


def _parse_schedule(raw: Any, place: _Place) -> Tuple[ScheduleWindow, ...]:
    if not isinstance(raw, (list, tuple)):
        raise place.fail(ERROR_INVALID_FIELD_TYPE, "schedule must be a list", "schedule")
    windows: list[ScheduleWindow] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"days", "start_second", "end_second"}:
            raise place.fail(ERROR_INVALID_SCHEDULE, "each window needs exactly days/start_second/end_second", "schedule")
        days = item["days"]
        if not isinstance(days, (list, tuple)):
            raise place.fail(ERROR_INVALID_SCHEDULE, "days must be a list", "schedule")
        try:
            windows.append(
                ScheduleWindow(days=tuple(days), start_second=item["start_second"], end_second=item["end_second"])
            )
        except ConfigError as error:
            raise place.fail(error.code, error.message, "schedule") from None
    return tuple(windows)


def _parse_thresholds(raw: Any, definition: AlertModuleDefinition, place: _Place) -> Tuple[Tuple[str, float], ...]:
    if not isinstance(raw, Mapping):
        raise place.fail(ERROR_INVALID_FIELD_TYPE, "thresholds must be an object", "thresholds")
    parsed: dict[str, float] = {}
    for name, value in raw.items():
        if name not in definition.thresholds:
            raise place.fail(
                ERROR_UNKNOWN_THRESHOLD, "threshold is not declared by the module definition", "thresholds." + str(name)
            )
        if type(value) not in (int, float) or not math.isfinite(value):
            raise place.fail(ERROR_INVALID_THRESHOLD, "threshold value must be a finite number", "thresholds." + str(name))
        parsed[name] = float(value)
    return tuple(sorted(parsed.items()))


def _parse_exceptions(raw: Any, place: _Place) -> Tuple[ExceptionRule, ...]:
    if not isinstance(raw, (list, tuple)):
        raise place.fail(ERROR_INVALID_FIELD_TYPE, "exceptions must be a list", "exceptions")
    rules: list[ExceptionRule] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"code", "reason"}:
            raise place.fail(ERROR_INVALID_EXCEPTION, "each exception needs exactly code and reason", "exceptions")
        try:
            rules.append(ExceptionRule(code=item["code"], reason=item["reason"]))
        except ConfigError as error:
            raise place.fail(error.code, error.message, "exceptions") from None
    return tuple(rules)


def parse_camera_module_config(
    definition: AlertModuleDefinition, camera_id: str, payload: Mapping[str, Any]
) -> CameraModuleConfig:
    """Validate one module x camera configuration, failing fast with field context."""
    _require_identifier(camera_id, ERROR_INVALID_CAMERA_ID, "camera_id", _Place(definition.module))
    place = _Place(definition.module, camera_id)
    if not isinstance(payload, Mapping):
        raise place.fail(ERROR_INVALID_FIELD_TYPE, "configuration must be an object")

    secrets = _secret_keys(payload)
    if secrets:
        raise place.fail(ERROR_SECRET_FIELD, "configuration must not carry secret material", secrets[0])

    unknown = sorted(set(payload) - CONFIG_FIELDS)
    if unknown:
        raise place.fail(ERROR_UNKNOWN_FIELD, "configuration carries a field the schema does not define", unknown[0])

    for required in ("version", "enabled"):
        if required not in payload:
            raise place.fail(ERROR_MISSING_REQUIRED_FIELD, required + " is required", required)

    enabled = payload["enabled"]
    disabled_reason = payload.get("disabled_reason")

    if enabled is True:
        if disabled_reason is not None:
            raise place.fail(ERROR_INVALID_FIELD_TYPE, "an enabled module cannot carry a disabled reason", "disabled_reason")
        for name in sorted(definition.required_fields):
            if name not in payload or _is_empty(payload[name]):
                raise place.fail(ERROR_MISSING_REQUIRED_FIELD, "enabled module is missing a required field", name)
    elif enabled is False:
        if not isinstance(disabled_reason, str) or not disabled_reason.strip():
            raise place.fail(ERROR_MISSING_DISABLED_REASON, "disabled module needs a reason", "disabled_reason")

    return CameraModuleConfig(
        module=definition.module,
        camera_id=camera_id,
        version=payload["version"],
        enabled=enabled,
        disabled_reason=disabled_reason,
        roi=_parse_roi(payload.get("roi") or (), place),
        schedule=_parse_schedule(payload.get("schedule") or (), place),
        thresholds=_parse_thresholds(payload.get("thresholds") or {}, definition, place),
        exceptions=_parse_exceptions(payload.get("exceptions") or (), place),
    )


@dataclass(frozen=True)
class ActivationState:
    """Desired vs observed state for one module x camera pair."""

    module: str
    camera_id: str
    session_id: Optional[str]
    desired_version: int
    observed_version: Optional[int]
    status: str
    reason: Optional[str] = None


class AlertModuleRegistry:
    """Independent per module x camera configuration and activation state.

    stage records the desired configuration only; activate is the boundary that makes a
    version observed. An activation older than the observed version is rejected and the last
    known good version is kept, so a bad local configuration cannot roll observation
    backwards. Whatever is currently observed keeps being reported until that boundary.
    """

    def __init__(self, allowlisted_factories: Iterable[str] = ALLOWLISTED_FACTORIES) -> None:
        self._allowlisted_factories: FrozenSet[str] = frozenset(allowlisted_factories)
        self._definitions: dict[str, AlertModuleDefinition] = {}
        self._configs: dict[tuple[str, str], CameraModuleConfig] = {}
        self._states: dict[tuple[str, str], ActivationState] = {}

    def register(self, definition: AlertModuleDefinition) -> None:
        if definition.module in self._definitions:
            raise ConfigError(ERROR_DUPLICATE_MODULE, "module is already registered", module=definition.module)
        if definition.factory not in self._allowlisted_factories:
            raise ConfigError(
                ERROR_FACTORY_NOT_ALLOWED,
                "module factory is not in the registered allowlist",
                module=definition.module,
                field="factory",
            )
        self._definitions[definition.module] = definition

    def definition(self, module: str) -> AlertModuleDefinition:
        try:
            return self._definitions[module]
        except KeyError:
            raise ConfigError(ERROR_UNKNOWN_MODULE, "module is not registered", module=module) from None

    def modules(self) -> Tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def parse(self, module: str, camera_id: str, payload: Mapping[str, Any]) -> CameraModuleConfig:
        return parse_camera_module_config(self.definition(module), camera_id, payload)

    def config(self, module: str, camera_id: str) -> Optional[CameraModuleConfig]:
        return self._configs.get((module, camera_id))

    def stage(self, config: CameraModuleConfig) -> ActivationState:
        """Record the desired configuration; an already observed state is left untouched."""
        self.definition(config.module)
        key = (config.module, config.camera_id)
        previous = self._states.get(key)
        if previous is not None and previous.observed_version is not None:
            status, reason, observed = previous.status, previous.reason, previous.observed_version
        elif config.enabled:
            status, reason, observed = STATUS_PENDING, None, None
        else:
            status, reason, observed = STATUS_DISABLED, config.disabled_reason, None
        session_id = previous.session_id if previous else None
        state = ActivationState(
            module=config.module,
            camera_id=config.camera_id,
            session_id=session_id,
            desired_version=config.version,
            observed_version=observed,
            status=status,
            reason=reason,
        )
        self._configs[key] = config
        self._states[key] = state
        return state

    def activate(self, config: CameraModuleConfig, *, session_id: str) -> ActivationState:
        self.definition(config.module)
        _require_identifier(session_id, ERROR_INVALID_SESSION_ID, "session_id", _Place(None, config.camera_id))
        key = (config.module, config.camera_id)
        previous = self._states.get(key)
        same_session = previous is not None and previous.session_id == session_id
        observed = previous.observed_version if (same_session and previous is not None) else None

        if observed is not None and config.version < observed:
            rejected = ActivationState(
                module=config.module,
                camera_id=config.camera_id,
                session_id=session_id,
                desired_version=config.version,
                observed_version=observed,
                status=STATUS_REJECTED,
                reason=ERROR_STALE_CONFIG_VERSION,
            )
            self._states[key] = rejected
            return rejected

        state = ActivationState(
            module=config.module,
            camera_id=config.camera_id,
            session_id=session_id,
            desired_version=config.version,
            observed_version=config.version,
            status=STATUS_ACTIVE if config.enabled else STATUS_DISABLED,
            reason=None if config.enabled else config.disabled_reason,
        )
        self._configs[key] = config
        self._states[key] = state
        return state

    def state(self, module: str, camera_id: str) -> Optional[ActivationState]:
        return self._states.get((module, camera_id))

    def reset_session(self, camera_id: str, session_id: str) -> Tuple[str, ...]:
        """Re-bind a camera session, dropping observed state for that camera only."""
        _require_identifier(camera_id, ERROR_INVALID_CAMERA_ID, "camera_id")
        _require_identifier(session_id, ERROR_INVALID_SESSION_ID, "session_id", _Place(None, camera_id))
        reset: list[str] = []
        for key, state in self._states.items():
            if key[1] != camera_id:
                continue
            config = self._configs.get(key)
            if config is not None and not config.enabled:
                status, reason = STATUS_DISABLED, config.disabled_reason
            else:
                status, reason = STATUS_PENDING, None
            self._states[key] = ActivationState(
                module=state.module,
                camera_id=camera_id,
                session_id=session_id,
                desired_version=state.desired_version,
                observed_version=None,
                status=status,
                reason=reason,
            )
            reset.append(state.module)
        return tuple(sorted(reset))

    def capabilities(self) -> dict[str, Any]:
        """Operator/doctor report: real per-camera status and the reason a module is disabled."""
        modules = []
        for module in self.modules():
            definition = self.definition(module)
            cameras = []
            for (name, camera_id), config in sorted(self._configs.items()):
                if name != module:
                    continue
                state = self._states[(module, camera_id)]
                cameras.append(
                    {
                        "camera_id": camera_id,
                        "capability": _CAPABILITY_BY_STATUS[state.status],
                        "status": state.status,
                        "reason": state.reason,
                        "config_version": config.version,
                        "config_hash": config.config_hash,
                    }
                )
            modules.append(
                {
                    "module": module,
                    "config_version": definition.config_version,
                    "factory": definition.factory,
                    "perception_profile": definition.perception_profile,
                    "cameras": cameras,
                }
            )
        return {"schema_version": SCHEMA_VERSION, "modules": modules}

    def active_modules(self, camera_id: str) -> Tuple[str, ...]:
        return tuple(
            sorted(
                module
                for (module, camera), state in self._states.items()
                if camera == camera_id and state.status == STATUS_ACTIVE
            )
        )

    def activation_for_camera(self, camera_id: str, session_id: str) -> dict[str, Any]:
        """The single seam a runtime consumes for one camera at one session boundary.

        `analytics_enabled`/`disabled_reason` are what `EdgeRuntime` needs to decide whether
        to start analytics; `roi_polygon` is the shape `Pipeline(roi_polygon=...)` accepts.
        """
        _require_identifier(camera_id, ERROR_INVALID_CAMERA_ID, "camera_id")
        _require_identifier(session_id, ERROR_INVALID_SESSION_ID, "session_id", _Place(None, camera_id))
        active: list[dict[str, Any]] = []
        disabled: list[dict[str, Any]] = []
        for (module, camera), state in sorted(self._states.items()):
            if camera != camera_id:
                continue
            definition = self.definition(module)
            if state.status == STATUS_ACTIVE:
                active.append(
                    {"module": module, "factory": definition.factory,
                     "perception_profile": definition.perception_profile}
                )
            elif state.status == STATUS_DISABLED:
                disabled.append({"module": module, "reason": state.reason})
        roi_polygon: Optional[list[list[float]]] = None
        for entry in active:
            config = self._configs.get((str(entry["module"]), camera_id))
            if config is not None and config.roi_polygon() is not None:
                roi_polygon = config.roi_polygon()
                break
        reasons = [str(entry["module"]) + ": " + str(entry["reason"]) for entry in disabled]
        return {
            "camera_id": camera_id,
            "session_id": session_id,
            "analytics_enabled": bool(active),
            "disabled_reason": None if active else ("no module enabled for camera" + (" (" + "; ".join(reasons) + ")" if reasons else "")),
            "roi_polygon": roi_polygon,
            "modules": active,
            "disabled_modules": disabled,
        }

    def perception_groups(self) -> list[dict[str, Any]]:
        """Group active modules that may share one decode/inference execution (ADR-0001)."""
        grouped: dict[tuple[str, str], list[str]] = {}
        for (module, camera), state in sorted(self._states.items()):
            if state.status != STATUS_ACTIVE:
                continue
            profile = str(self.definition(module).perception_profile)
            grouped.setdefault((camera, profile), []).append(module)
        return [
            {
                "camera_id": camera,
                "perception_profile": profile,
                "modules": sorted(modules),
                "shared": len(modules) > 1,
            }
            for (camera, profile), modules in sorted(grouped.items())
        ]
