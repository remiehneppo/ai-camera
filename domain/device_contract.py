"""Device lifecycle and site-access enforcement contract (Ticket #33).

Pure domain module: no I/O, no framework or infrastructure imports. Records are
immutable, validate themselves on construction, and normalise their inputs.
Enforcement helpers return ``(allowed, reason_code)`` rather than raising;
lifecycle helpers raise ``DeviceLifecycleError`` for illegal input or illegal
state transitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Dict, Final, FrozenSet, List, Optional, Pattern, Tuple

from domain.evidence_contract import validate_storage_id

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ALL_DEVICE_STATUSES",
    "DeviceLifecycleError",
    "DeviceRecord",
    "ENROLLED_STATUSES",
    "REASON_CAMERA_NOT_ALLOWED",
    "REASON_DEVICE_CREDENTIAL_REVOKED",
    "REASON_DEVICE_QUARANTINED",
    "REASON_DEVICE_STATUS_UNKNOWN",
    "ReviewerAccessRecord",
    "STATUS_ACTIVE",
    "STATUS_ENROLLED",
    "STATUS_QUARANTINED",
    "STATUS_REVOKED",
    "can_transition",
    "check_device_access",
    "check_reviewer_site_access",
    "quarantine_device",
    "reactivate_device",
    "revoke_device",
    "transition_device",
    "validate_device_status",
    "validate_iso8601_timestamp",
]

# --- Device lifecycle states -------------------------------------------------

STATUS_ACTIVE: Final[str] = "active"
STATUS_ENROLLED: Final[str] = "enrolled"
STATUS_QUARANTINED: Final[str] = "quarantined"
STATUS_REVOKED: Final[str] = "revoked"

#: States in which a device is considered live and serving.
ENROLLED_STATUSES: Final[FrozenSet[str]] = frozenset({STATUS_ACTIVE, STATUS_ENROLLED})

ALL_DEVICE_STATUSES: Final[FrozenSet[str]] = frozenset(
    {STATUS_ACTIVE, STATUS_ENROLLED, STATUS_QUARANTINED, STATUS_REVOKED}
)

#: Terminal state: ``revoked`` maps to the empty set on purpose.
ALLOWED_TRANSITIONS: Final[Dict[str, FrozenSet[str]]] = {
    STATUS_ACTIVE: frozenset({STATUS_QUARANTINED, STATUS_REVOKED}),
    STATUS_ENROLLED: frozenset({STATUS_QUARANTINED, STATUS_REVOKED}),
    STATUS_QUARANTINED: frozenset({STATUS_ACTIVE, STATUS_ENROLLED, STATUS_REVOKED}),
    STATUS_REVOKED: frozenset(),
}

# --- Enforcement reason codes -----------------------------------------------

REASON_DEVICE_CREDENTIAL_REVOKED: Final[str] = "device_credential_revoked"
REASON_DEVICE_QUARANTINED: Final[str] = "device_quarantined"
REASON_CAMERA_NOT_ALLOWED: Final[str] = "camera_not_allowed_for_device"
REASON_DEVICE_STATUS_UNKNOWN: Final[str] = "device_status_unknown"

# --- Error codes ------------------------------------------------------------

ERROR_INVALID_STORAGE_ID: Final[str] = "invalid_storage_id"
ERROR_INVALID_DEVICE_STATUS: Final[str] = "invalid_device_status"
ERROR_INVALID_TIMESTAMP: Final[str] = "invalid_timestamp"
ERROR_INVALID_REASON: Final[str] = "invalid_reason"
ERROR_INVALID_ACCESS_LIST: Final[str] = "invalid_access_list"
ERROR_INVALID_REVIEWER_ID: Final[str] = "invalid_reviewer_id"
ERROR_INVALID_REVIEWER_FLAG: Final[str] = "invalid_reviewer_flag"
ERROR_INVALID_DEVICE_RECORD: Final[str] = "invalid_device_record"
ERROR_INVALID_REVIEWER_RECORD: Final[str] = "invalid_reviewer_record"
ERROR_INVALID_TRANSITION: Final[str] = "invalid_device_status_transition"
ERROR_REVOKED_TERMINAL: Final[str] = "revoked_device_is_terminal"


class DeviceLifecycleError(ValueError):
    """Typed failure for device lifecycle / access contract violations."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code: str = code
        self.message: str = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


_ISO8601_PATTERN: Final[Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})?$"
)


def validate_iso8601_timestamp(value: object, field_name: str = "timestamp") -> str:
    """Validate a timestamp string as ISO-8601 and return it unchanged."""
    if not isinstance(value, str) or not value:
        raise DeviceLifecycleError(
            ERROR_INVALID_TIMESTAMP,
            f"{field_name} must be a non-empty ISO-8601 string",
        )
    if not _ISO8601_PATTERN.match(value):
        raise DeviceLifecycleError(
            ERROR_INVALID_TIMESTAMP, f"{field_name} {value!r} is not an ISO-8601 timestamp"
        )
    parseable = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(parseable)
    except ValueError as exc:
        raise DeviceLifecycleError(
            ERROR_INVALID_TIMESTAMP, f"{field_name} {value!r} is not parseable: {exc}"
        ) from exc
    return value


def validate_device_status(value: object) -> str:
    """Validate a device status and return its canonical (lowercase) form."""
    if not isinstance(value, str):
        raise DeviceLifecycleError(
            ERROR_INVALID_DEVICE_STATUS,
            f"device status must be a string, got {type(value).__name__}",
        )
    normalised = value.strip().lower()
    if normalised not in ALL_DEVICE_STATUSES:
        raise DeviceLifecycleError(
            ERROR_INVALID_DEVICE_STATUS,
            f"device status {value!r} is not one of {sorted(ALL_DEVICE_STATUSES)}",
        )
    return normalised


def _normalize_reason(value: object, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DeviceLifecycleError(
            ERROR_INVALID_REASON, f"{field_name} must be a string, got {type(value).__name__}"
        )
    cleaned = value.strip()
    if not cleaned:
        raise DeviceLifecycleError(
            ERROR_INVALID_REASON, f"{field_name} must not be blank when provided"
        )
    return cleaned


def _normalize_str_tuple(value: object, field_name: str) -> Tuple[str, ...]:
    """Coerce a sequence of non-empty strings into a de-duplicated tuple."""
    if value is None:
        return ()
    if isinstance(value, str):
        raise DeviceLifecycleError(
            ERROR_INVALID_ACCESS_LIST,
            f"{field_name} must be a sequence of strings, not a bare string",
        )
    if not isinstance(value, (tuple, list)):
        raise DeviceLifecycleError(
            ERROR_INVALID_ACCESS_LIST,
            f"{field_name} must be a tuple or list, got {type(value).__name__}",
        )
    collected: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise DeviceLifecycleError(
                ERROR_INVALID_ACCESS_LIST,
                f"{field_name} entries must be non-empty strings, got {item!r}",
            )
        cleaned = item.strip()
        if cleaned not in collected:
            collected.append(cleaned)
    return tuple(collected)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Records ----------------------------------------------------------------


@dataclass(frozen=True)
class DeviceRecord:
    """One enrolled camera device bound to a site."""

    device_id: str
    site_id: str
    status: str
    enrolled_at: str
    updated_at: str
    revocation_reason: Optional[str] = None
    quarantine_reason: Optional[str] = None
    #: Empty tuple means every camera on this device/site is allowed.
    allowed_cameras: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            validate_storage_id(self.device_id)
            validate_storage_id(self.site_id)
        except ValueError as exc:
            raise DeviceLifecycleError(ERROR_INVALID_STORAGE_ID, str(exc)) from exc
        object.__setattr__(self, "status", validate_device_status(self.status))
        validate_iso8601_timestamp(self.enrolled_at, "enrolled_at")
        validate_iso8601_timestamp(self.updated_at, "updated_at")
        object.__setattr__(
            self, "revocation_reason", _normalize_reason(self.revocation_reason, "revocation_reason")
        )
        object.__setattr__(
            self, "quarantine_reason", _normalize_reason(self.quarantine_reason, "quarantine_reason")
        )
        object.__setattr__(
            self, "allowed_cameras", _normalize_str_tuple(self.allowed_cameras, "allowed_cameras")
        )

    @property
    def is_revoked(self) -> bool:
        return self.status == STATUS_REVOKED

    @property
    def is_quarantined(self) -> bool:
        return self.status == STATUS_QUARANTINED

    @property
    def is_serving(self) -> bool:
        return self.status in ENROLLED_STATUSES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "site_id": self.site_id,
            "status": self.status,
            "enrolled_at": self.enrolled_at,
            "updated_at": self.updated_at,
            "revocation_reason": self.revocation_reason,
            "quarantine_reason": self.quarantine_reason,
            "allowed_cameras": list(self.allowed_cameras),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DeviceRecord:
        return cls(
            device_id=data["device_id"],
            site_id=data.get("site_id", "default_site"),
            status=data.get("status", STATUS_ACTIVE),
            enrolled_at=data.get("enrolled_at", _utc_now()),
            updated_at=data.get("updated_at", _utc_now()),
            revocation_reason=data.get("revocation_reason"),
            quarantine_reason=data.get("quarantine_reason"),
            allowed_cameras=tuple(data.get("allowed_cameras", ())),
        )


@dataclass(frozen=True)
class ReviewerAccessRecord:
    """A reviewer's site scope and export capability."""

    reviewer_id: str
    #: Empty tuple means all sites (global viewer).
    allowed_sites: Tuple[str, ...] = ()
    can_review: bool = True
    can_export: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.reviewer_id, str) or not self.reviewer_id.strip():
            raise DeviceLifecycleError(
                ERROR_INVALID_REVIEWER_ID, "reviewer_id must be a non-empty string"
            )
        object.__setattr__(self, "reviewer_id", self.reviewer_id.strip())
        object.__setattr__(
            self, "allowed_sites", _normalize_str_tuple(self.allowed_sites, "allowed_sites")
        )
        for name, flag in (("can_review", self.can_review), ("can_export", self.can_export)):
            if not isinstance(flag, bool):
                raise DeviceLifecycleError(
                    ERROR_INVALID_REVIEWER_FLAG,
                    f"{name} must be a bool, got {type(flag).__name__}",
                )

    @property
    def is_global_viewer(self) -> bool:
        return not self.allowed_sites


# --- Enforcement ------------------------------------------------------------


def check_device_access(
    device: DeviceRecord, camera_id: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """Decide whether a device (and optionally one camera) may be accessed.

    Returns ``(allowed, reason_code)``. Precedence is revoked > quarantined >
    camera allowlist, so a revoked credential is never reported as a camera
    problem.
    """
    if not isinstance(device, DeviceRecord):
        raise DeviceLifecycleError(
            ERROR_INVALID_DEVICE_RECORD,
            f"device must be a DeviceRecord, got {type(device).__name__}",
        )
    if device.status == STATUS_REVOKED:
        return False, REASON_DEVICE_CREDENTIAL_REVOKED
    if device.status == STATUS_QUARANTINED:
        return False, REASON_DEVICE_QUARANTINED
    if device.status not in ENROLLED_STATUSES:
        return False, REASON_DEVICE_STATUS_UNKNOWN
    if camera_id is not None:
        try:
            validate_storage_id(camera_id)
        except ValueError as exc:
            raise DeviceLifecycleError(ERROR_INVALID_STORAGE_ID, str(exc)) from exc
        if device.allowed_cameras and camera_id not in device.allowed_cameras:
            return False, REASON_CAMERA_NOT_ALLOWED
    return True, None


def check_reviewer_site_access(
    reviewer: ReviewerAccessRecord, event_site_id: Optional[str]
) -> bool:
    """Decide whether a reviewer may see events from ``event_site_id``.

    An empty ``allowed_sites`` grants global access. A site-scoped reviewer is
    denied when the event carries no site id, since the site cannot be proven
    to be in scope.
    """
    if not isinstance(reviewer, ReviewerAccessRecord):
        raise DeviceLifecycleError(
            ERROR_INVALID_REVIEWER_RECORD,
            f"reviewer must be a ReviewerAccessRecord, got {type(reviewer).__name__}",
        )
    if not reviewer.allowed_sites:
        return True
    if event_site_id is None:
        return False
    if not isinstance(event_site_id, str):
        raise DeviceLifecycleError(
            ERROR_INVALID_STORAGE_ID,
            f"event_site_id must be a string, got {type(event_site_id).__name__}",
        )
    return event_site_id.strip() in reviewer.allowed_sites


# --- Lifecycle transitions --------------------------------------------------


def can_transition(current_status: str, new_status: str) -> bool:
    """Return whether ``current_status`` may become ``new_status``."""
    current = validate_device_status(current_status)
    target = validate_device_status(new_status)
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def transition_device(
    device: DeviceRecord,
    new_status: str,
    *,
    reason: Optional[str] = None,
    now: Optional[str] = None,
) -> DeviceRecord:
    """Return a new record moved to ``new_status``, or raise."""
    if not isinstance(device, DeviceRecord):
        raise DeviceLifecycleError(
            ERROR_INVALID_DEVICE_RECORD,
            f"device must be a DeviceRecord, got {type(device).__name__}",
        )
    target = validate_device_status(new_status)
    clean_reason = _normalize_reason(reason, "reason")

    if target == device.status:
        raise DeviceLifecycleError(
            ERROR_INVALID_TRANSITION,
            f"device {device.device_id!r} is already {target!r}",
        )
    if target not in ALLOWED_TRANSITIONS.get(device.status, frozenset()):
        if device.status == STATUS_REVOKED:
            raise DeviceLifecycleError(
                ERROR_REVOKED_TERMINAL,
                f"device {device.device_id!r} is revoked and cannot become {target!r}",
            )
        raise DeviceLifecycleError(
            ERROR_INVALID_TRANSITION,
            f"device {device.device_id!r} cannot go from {device.status!r} to {target!r}",
        )

    changes: Dict[str, Any] = {
        "status": target,
        "updated_at": validate_iso8601_timestamp(now, "now") if now is not None else _utc_now(),
    }
    if target == STATUS_QUARANTINED:
        changes["quarantine_reason"] = clean_reason
    elif target == STATUS_REVOKED:
        changes["revocation_reason"] = clean_reason
    else:
        changes["quarantine_reason"] = None
        changes["revocation_reason"] = None
    return replace(device, **changes)


def quarantine_device(
    device: DeviceRecord, *, reason: Optional[str] = None, now: Optional[str] = None
) -> DeviceRecord:
    """Move a serving device to ``quarantined``."""
    return transition_device(device, STATUS_QUARANTINED, reason=reason, now=now)


def reactivate_device(
    device: DeviceRecord, *, reason: Optional[str] = None, now: Optional[str] = None
) -> DeviceRecord:
    """Return a quarantined device to ``active`` service after inspection."""
    return transition_device(device, STATUS_ACTIVE, reason=reason, now=now)


def revoke_device(
    device: DeviceRecord, *, reason: Optional[str] = None, now: Optional[str] = None
) -> DeviceRecord:
    """Permanently decommission a device (terminal state)."""
    return transition_device(device, STATUS_REVOKED, reason=reason, now=now)
