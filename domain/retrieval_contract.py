"""Retained-evidence retrieval command contract (Ticket #32).

Pure domain module: no I/O, no framework imports. A retrieval command asks one device to
keep a clip that an authorized reviewer requested, and it is the only thing a device may
receive from the server: the wire payload is validated against a closed field set, the
target/action vocabulary is an allowlist, and any shell/executable/URL shaped field is
refused, so the channel can never become a remote shell.

The state machine is a set of pure transitions over an immutable `RetrievalState`:
`issue_command` -> `claim` (lease, replay-safe) -> `acknowledge` (metadata | artifact |
failure). A metadata acknowledgement records receipt and never terminalises a command: it
does not release, delete or expire the clip. Only an artifact acknowledgement completes
it, and a repeated acknowledgement of the same artifact is idempotent while a different
artifact is a conflict.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Any, Final, FrozenSet, Mapping, Optional, Pattern
from uuid import uuid4

__all__ = [
    "ACK_ARTIFACT",
    "ACK_FAILURE",
    "ACK_METADATA",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_OFFLINE_AFTER_SECONDS",
    "ERROR_ARTIFACT_CONFLICT",
    "ERROR_COMMAND_TERMINAL",
    "ERROR_FORBIDDEN_FIELD",
    "ERROR_INVALID_ACK",
    "ERROR_INVALID_COMMAND",
    "ERROR_STALE_LEASE",
    "ERROR_TARGET_NOT_ALLOWED",
    "ERROR_TTL_EXCEEDED",
    "ERROR_UNKNOWN_ACK_KIND",
    "EvidenceRef",
    "FAILURE_REASONS",
    "MAX_TTL_SECONDS",
    "RETENTION_SCOPES",
    "RetrievalCommand",
    "RetrievalError",
    "RetrievalState",
    "STATUS_CLAIMED",
    "STATUS_COMPLETED",
    "STATUS_EXPIRED",
    "STATUS_FAILED",
    "STATUS_OFFLINE",
    "STATUS_PENDING",
    "TARGETS",
    "acknowledge",
    "claim",
    "issue_command",
    "requester_status",
    "settle_target",
    "validate_command_payload",
    "wire_payload",
]

TARGETS: Final[FrozenSet[str]] = frozenset({"edge", "server"})
RETENTION_SCOPES: Final[FrozenSet[str]] = frozenset({"clip", "metadata"})

TODO_ACTION_RETAIN_CLIP: Final[str] = "retain_clip"
ACTION_ALLOWLIST: Final[FrozenSet[str]] = frozenset({TODO_ACTION_RETAIN_CLIP})

ACK_METADATA: Final[str] = "metadata"
ACK_ARTIFACT: Final[str] = "artifact"
ACK_FAILURE: Final[str] = "failure"
ACK_KINDS: Final[FrozenSet[str]] = frozenset({ACK_METADATA, ACK_ARTIFACT, ACK_FAILURE})

#: Closed field set per acknowledgement kind; the device cannot send free-form data back.
ACK_FIELDS: Final[dict[str, FrozenSet[str]]] = {
    ACK_METADATA: frozenset({"kind"}),
    ACK_ARTIFACT: frozenset({"kind", "sha256", "size_bytes", "actual_ranges"}),
    ACK_FAILURE: frozenset({"kind", "reason"}),
}

FAILURE_REASONS: Final[FrozenSet[str]] = frozenset(
    {"evidence_unavailable", "recorder_unavailable", "unsupported_target", "storage_insufficient"}
)

STATUS_PENDING: Final[str] = "pending"
STATUS_CLAIMED: Final[str] = "claimed"
STATUS_COMPLETED: Final[str] = "completed"
STATUS_FAILED: Final[str] = "failed"
STATUS_EXPIRED: Final[str] = "expired"
STATUS_OFFLINE: Final[str] = "offline"

TERMINAL_STATUSES: Final[FrozenSet[str]] = frozenset({STATUS_COMPLETED, STATUS_FAILED, STATUS_EXPIRED})

MAX_TTL_SECONDS: Final[float] = 3600.0
DEFAULT_LEASE_SECONDS: Final[float] = 30.0
DEFAULT_OFFLINE_AFTER_SECONDS: Final[float] = 90.0

ERROR_INVALID_COMMAND: Final[str] = "invalid_retrieval_command"
ERROR_TARGET_NOT_ALLOWED: Final[str] = "target_not_allowed"
ERROR_FORBIDDEN_FIELD: Final[str] = "forbidden_command_field"
ERROR_TTL_EXCEEDED: Final[str] = "ttl_exceeded"
ERROR_COMMAND_TERMINAL: Final[str] = "command_already_terminal"
ERROR_STALE_LEASE: Final[str] = "stale_lease"
ERROR_UNKNOWN_ACK_KIND: Final[str] = "unknown_ack_kind"
ERROR_INVALID_ACK: Final[str] = "invalid_ack"
ERROR_ARTIFACT_CONFLICT: Final[str] = "artifact_conflict"

_IDENTIFIER: Final[Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_FORBIDDEN_FIELD: Final[Pattern[str]] = re.compile(
    r"shell|exec|argv|command line|script|url|endpoint|callback|spawn|pipe|stdin|binary", re.IGNORECASE
)

#: Closed field set of the device-facing payload; nothing else may travel on this channel.
WIRE_FIELDS: Final[FrozenSet[str]] = frozenset(
    {
        "command_id",
        "device_id",
        "target",
        "action",
        "evidence",
        "issued_at",
        "expires_at",
        "retention_scope",
        "status",
        "lease_id",
        "expires_in_seconds",
    }
)
WIRE_EVIDENCE_FIELDS: Final[FrozenSet[str]] = frozenset({"device_id", "event_id", "request_id"})

#: The wire payload names no issuer: a device does not need to know which reviewer asked.
WIRE_ISSUER: Final[str] = "wire"


class RetrievalError(ValueError):
    """Typed failure for an illegal retrieval command, transition or acknowledgement."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code + ": " + message)


def _fail(code: str, message: str) -> RetrievalError:
    return RetrievalError(code, message)


def _require_identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.match(value):
        raise _fail(ERROR_INVALID_COMMAND, name + " must be a safe identifier")
    return value


def _require_time(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise _fail(ERROR_INVALID_COMMAND, name + " must be a finite epoch timestamp")
    return float(value)


@dataclass(frozen=True)
class EvidenceRef:
    """Which event evidence a retrieval command is about."""

    device_id: str
    event_id: str
    request_id: str

    def __post_init__(self) -> None:
        for name in ("device_id", "event_id", "request_id"):
            _require_identifier(getattr(self, name), name)

    def as_dict(self) -> dict[str, str]:
        return {"device_id": self.device_id, "event_id": self.event_id, "request_id": self.request_id}


@dataclass(frozen=True)
class RetrievalCommand:
    """An authorized request to retain one clip; immutable and validated on construction."""

    command_id: str
    device_id: str
    target: str
    action: str
    evidence: EvidenceRef
    issued_by: str
    issued_at: float
    expires_at: float
    retention_scope: str = "clip"

    def __post_init__(self) -> None:
        _require_identifier(self.command_id, "command_id")
        _require_identifier(self.device_id, "device_id")
        _require_identifier(self.issued_by, "issued_by")
        if self.target not in TARGETS:
            raise _fail(ERROR_TARGET_NOT_ALLOWED, "target is not an allowlisted retrieval target")
        if self.action not in ACTION_ALLOWLIST:
            raise _fail(ERROR_INVALID_COMMAND, "action is not in the allowlist")
        if not isinstance(self.evidence, EvidenceRef):
            raise _fail(ERROR_INVALID_COMMAND, "evidence must be an EvidenceRef")
        if self.evidence.device_id != self.device_id:
            raise _fail(ERROR_INVALID_COMMAND, "evidence device does not match command device")
        issued = _require_time(self.issued_at, "issued_at")
        expires = _require_time(self.expires_at, "expires_at")
        if expires <= issued:
            raise _fail(ERROR_INVALID_COMMAND, "expires_at must be after issued_at")
        if expires - issued > MAX_TTL_SECONDS:
            raise _fail(ERROR_TTL_EXCEEDED, "command ttl exceeds the allowed bound")
        if self.retention_scope not in RETENTION_SCOPES:
            raise _fail(ERROR_INVALID_COMMAND, "retention_scope must be clip or metadata")

    def as_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "device_id": self.device_id,
            "target": self.target,
            "action": self.action,
            "evidence": self.evidence.as_dict(),
            "issued_by": self.issued_by,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "retention_scope": self.retention_scope,
        }


@dataclass(frozen=True)
class RetrievalState:
    """Command plus its durable progress; every transition returns a new state."""

    command: RetrievalCommand
    status: str = STATUS_PENDING
    lease_id: Optional[str] = None
    claimed_at: Optional[float] = None
    attempts: int = 0
    metadata_acknowledged: bool = False
    artifact: Optional[Mapping[str, Any]] = None
    reason: Optional[str] = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def issue_command(
    *,
    command_id: str,
    device_id: str,
    target: str,
    evidence: EvidenceRef,
    issued_by: str,
    issued_at: float,
    ttl_seconds: float = 300.0,
    retention_scope: str = "clip",
    action: str = TODO_ACTION_RETAIN_CLIP,
) -> RetrievalState:
    """Create a pending command with a bounded expiry."""
    if type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
        raise _fail(ERROR_INVALID_COMMAND, "ttl_seconds must be finite and positive")
    command = RetrievalCommand(
        command_id=command_id,
        device_id=device_id,
        target=target,
        action=action,
        evidence=evidence,
        issued_by=issued_by,
        issued_at=float(issued_at),
        expires_at=float(issued_at) + float(ttl_seconds),
        retention_scope=retention_scope,
    )
    return RetrievalState(command=command)


def claim(state: RetrievalState, *, now: float, lease_seconds: float = DEFAULT_LEASE_SECONDS) -> RetrievalState:
    """Lease the command to the polling device.

    Idempotent while the lease is alive (the same lease is returned, so a duplicate poll
    cannot cause a second execution) and replay-safe once terminal (a completed command is
    returned unchanged, never re-issued).
    """
    now = _require_time(now, "now")
    if type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds) or lease_seconds <= 0:
        raise _fail(ERROR_INVALID_COMMAND, "lease_seconds must be finite and positive")
    if state.terminal:
        return state
    if now >= state.command.expires_at:
        return replace(state, status=STATUS_EXPIRED, lease_id=None, reason="expired", artifact=None)
    if state.status == STATUS_CLAIMED and state.claimed_at is not None and now < state.claimed_at + float(lease_seconds):
        return state
    return replace(
        state,
        status=STATUS_CLAIMED,
        lease_id=uuid4().hex,
        claimed_at=now,
        attempts=state.attempts + 1,
        reason=None,
    )


def _ack_artifact(ack: Mapping[str, Any]) -> dict[str, Any]:
    sha256 = ack.get("sha256")
    size = ack.get("size_bytes")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise _fail(ERROR_INVALID_ACK, "artifact acknowledgement needs a lowercase sha256")
    if type(size) is not int or size < 0:
        raise _fail(ERROR_INVALID_ACK, "artifact acknowledgement needs a non-negative size_bytes")
    artifact: dict[str, Any] = {"sha256": sha256, "size_bytes": size}
    ranges = ack.get("actual_ranges")
    if ranges is not None:
        if not isinstance(ranges, list):
            raise _fail(ERROR_INVALID_ACK, "actual_ranges must be a list")
        artifact["actual_ranges"] = ranges
    return artifact


def acknowledge(
    state: RetrievalState,
    *,
    now: float,
    lease_id: Optional[str],
    ack: Mapping[str, Any],
) -> RetrievalState:
    """Apply a device acknowledgement.

    `metadata` only records receipt: the command stays open and the clip stays retained.
    `artifact` completes it and is idempotent for the same bytes. `failure` ends it with an
    allowlisted reason.
    """
    now = _require_time(now, "now")
    if not isinstance(ack, Mapping):
        raise _fail(ERROR_INVALID_ACK, "acknowledgement must be an object")
    kind = ack.get("kind")
    if kind not in ACK_KINDS:
        raise _fail(ERROR_UNKNOWN_ACK_KIND, "acknowledgement kind is not allowed")
    if set(ack) - ACK_FIELDS[kind]:
        raise _fail(ERROR_INVALID_ACK, "acknowledgement carries a field its kind does not define")
    if state.terminal:
        if kind == ACK_ARTIFACT and state.status == STATUS_COMPLETED and state.artifact is not None:
            if dict(state.artifact) == _ack_artifact(ack):
                return state
            raise _fail(ERROR_ARTIFACT_CONFLICT, "finalized artifact bytes are immutable")
        raise _fail(ERROR_COMMAND_TERMINAL, "command is already terminal")
    if state.status != STATUS_CLAIMED or state.lease_id is None:
        raise _fail(ERROR_STALE_LEASE, "command is not leased to a device")
    if not isinstance(lease_id, str) or lease_id != state.lease_id:
        raise _fail(ERROR_STALE_LEASE, "acknowledgement lease does not match the live lease")
    if now >= state.command.expires_at:
        # A late acknowledgement may not complete a command whose window has closed.
        return replace(state, status=STATUS_EXPIRED, reason="expired", lease_id=None, claimed_at=None)

    if kind == ACK_METADATA:
        if state.metadata_acknowledged:
            return state
        return replace(state, metadata_acknowledged=True)
    if kind == ACK_FAILURE:
        reason = ack.get("reason")
        if reason not in FAILURE_REASONS:
            raise _fail(ERROR_INVALID_ACK, "failure reason is not allowlisted")
        return replace(state, status=STATUS_FAILED, reason=str(reason), lease_id=None)
    artifact = _ack_artifact(ack)
    return replace(state, status=STATUS_COMPLETED, artifact=artifact, reason=None, lease_id=None, claimed_at=None)


def settle_target(
    state: RetrievalState,
    *,
    now: float,
    available: bool,
    artifact: Optional[Mapping[str, Any]] = None,
) -> RetrievalState:
    """Close a command the target itself fulfils (a `server` target needs no device).

    Availability is probed at read time, so a cleanup that removed the artifact after the
    request was issued ends as `failed: evidence_unavailable` instead of a silent completion.
    """
    now = _require_time(now, "now")
    if state.terminal:
        return state
    if now >= state.command.expires_at:
        return replace(state, status=STATUS_EXPIRED, reason="expired", lease_id=None)
    if not available:
        return replace(state, status=STATUS_FAILED, reason="evidence_unavailable", lease_id=None, claimed_at=None)
    if artifact is None:
        raise _fail(ERROR_INVALID_ACK, "available target needs an artifact receipt")
    return replace(
        state,
        status=STATUS_COMPLETED,
        artifact=_ack_artifact({"kind": ACK_ARTIFACT, **artifact}),
        reason=None,
        lease_id=None,
        claimed_at=None,
    )


def requester_status(
    state: RetrievalState,
    *,
    now: float,
    device_last_seen: Optional[float],
    offline_after: float = DEFAULT_OFFLINE_AFTER_SECONDS,
) -> str:
    """What the requesting reviewer sees: pending/offline/expired/completed/failed.

    `offline` is a delivery problem, not a retention decision: the command is still open and
    will be delivered when the device polls again.
    """
    now = _require_time(now, "now")
    if state.status in TERMINAL_STATUSES:
        return state.status
    if now >= state.command.expires_at:
        return STATUS_EXPIRED
    if device_last_seen is None or now - device_last_seen > float(offline_after):
        return STATUS_OFFLINE
    return STATUS_PENDING


def wire_payload(state: RetrievalState, *, now: Optional[float] = None) -> dict[str, Any]:
    """Exactly what the device receives: a closed field set, no free-form field."""
    payload: dict[str, Any] = {
        "command_id": state.command.command_id,
        "device_id": state.command.device_id,
        "target": state.command.target,
        "action": state.command.action,
        "evidence": state.command.evidence.as_dict(),
        "issued_at": state.command.issued_at,
        "expires_at": state.command.expires_at,
        "retention_scope": state.command.retention_scope,
        "status": state.status,
        "lease_id": state.lease_id,
    }
    if now is not None:
        payload["expires_in_seconds"] = max(0.0, state.command.expires_at - float(now))
    return payload


def validate_command_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a device-facing command before executing it; unknown or shell-shaped fields fail."""
    if not isinstance(payload, Mapping):
        raise _fail(ERROR_INVALID_COMMAND, "command payload must be an object")
    forbidden = sorted(key for key in payload if _FORBIDDEN_FIELD.search(str(key)))
    if forbidden:
        raise _fail(ERROR_FORBIDDEN_FIELD, "command payload carries a field the channel never allows")
    unknown = sorted(set(payload) - WIRE_FIELDS)
    if unknown:
        raise _fail(ERROR_INVALID_COMMAND, "command payload carries an unknown field")
    missing = sorted({"command_id", "device_id", "target", "action", "evidence", "issued_at", "expires_at"} - set(payload))
    if missing:
        raise _fail(ERROR_INVALID_COMMAND, "command payload is missing a required field")
    evidence = payload["evidence"]
    if not isinstance(evidence, Mapping) or set(evidence) != WIRE_EVIDENCE_FIELDS:
        raise _fail(ERROR_INVALID_COMMAND, "evidence must carry exactly device/event/request ids")
    command = RetrievalCommand(
        command_id=payload["command_id"],
        device_id=payload["device_id"],
        target=payload["target"],
        action=payload["action"],
        evidence=EvidenceRef(
            device_id=evidence["device_id"],
            event_id=evidence["event_id"],
            request_id=evidence["request_id"],
        ),
        issued_by=WIRE_ISSUER,
        issued_at=payload["issued_at"],
        expires_at=payload["expires_at"],
        retention_scope=payload.get("retention_scope", "clip"),
    )
    status = payload.get("status", STATUS_PENDING)
    if status not in {STATUS_PENDING, STATUS_CLAIMED, STATUS_COMPLETED, STATUS_FAILED, STATUS_EXPIRED}:
        raise _fail(ERROR_INVALID_COMMAND, "status is not a retrieval status")
    lease_id = payload.get("lease_id")
    if lease_id is not None and not isinstance(lease_id, str):
        raise _fail(ERROR_INVALID_COMMAND, "lease_id must be a string")
    return {**command.as_dict(), "status": status, "lease_id": lease_id}
