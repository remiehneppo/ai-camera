"""Central retention, deletion, export, and backup/restore reconciliation contract (Ticket #43).

Pure domain module: no I/O, no filesystem or MongoDB imports. Defines:
1. Central clip retention policy (default 7 days = 604,800s per Q6 / contracts §3) and
   deletion eligibility rules (protects unexpired clips, open retrieval commands, pinned
   or legal-hold records, and unreviewed high/critical events unless explicitly permitted).
2. Immutable manifest receipt preservation on retention expiry: expiring a clip transitions
   server availability to "expired" while preserving "sha256", "size_bytes",
   "request_id", "event_id", "device_id", and requested/actual ranges (contracts §4).
3. RBAC and immutable audit records for central delete and export actions.
4. Reconciliation classification across MongoDB manifests and stored media files without
   assuming a cross-system atomic transaction: "verified", "pending", "missing",
   "corrupt", and "orphan", plus RPO/RTO and lab HA disclaimer reporting (M12-ERR03).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
import re
from typing import Any, Final, FrozenSet, Iterable, Mapping, Optional

__all__ = [
    "ACTION_CENTRAL_DELETE",
    "ACTION_CENTRAL_EXPORT",
    "ACTION_RETENTION_EXPIRE",
    "AVAILABILITY_AVAILABLE",
    "AVAILABILITY_EXPIRED",
    "AVAILABILITY_MISSING",
    "AVAILABILITY_PENDING",
    "AVAILABILITY_QUARANTINED",
    "DEFAULT_CENTRAL_RETENTION_SECONDS",
    "HA_DISCLAIMER",
    "IMMUTABLE_RECEIPT_FIELDS",
    "INTEGRITY_CORRUPT",
    "INTEGRITY_UNVERIFIED",
    "INTEGRITY_VERIFIED",
    "POLICY_VERSION",
    "RECONCILE_CORRUPT",
    "RECONCILE_MISSING",
    "RECONCILE_ORPHAN",
    "RECONCILE_PENDING",
    "RECONCILE_STATES",
    "RECONCILE_VERIFIED",
    "ROLE_ADMIN",
    "ROLE_OPERATOR",
    "ROLE_REVIEWER",
    "RetentionActionAudit",
    "RetentionDecision",
    "RetentionError",
    "RetentionPolicy",
    "apply_reconcile_outcome_to_manifest",
    "apply_retention_expiry_to_manifest",
    "authorize_retention_action",
    "build_reconciliation_report",
    "classify_manifest_and_file",
    "evaluate_retention_candidate",
]

POLICY_VERSION: Final[str] = "central-retention-v1"

#: Default server clip retention window: 7 days (Q6 / contracts §3).
DEFAULT_CENTRAL_RETENTION_SECONDS: Final[float] = 7 * 24 * 3600.0  # 604,800.0

#: Explicit lab topology disclaimer (M12-ERR03): single-member replica set is not HA.
HA_DISCLAIMER: Final[str] = "lab_single_replica_not_production_ha"

AVAILABILITY_PENDING: Final[str] = "pending"
AVAILABILITY_AVAILABLE: Final[str] = "available"
AVAILABILITY_MISSING: Final[str] = "missing"
AVAILABILITY_EXPIRED: Final[str] = "expired"
AVAILABILITY_QUARANTINED: Final[str] = "quarantined"

INTEGRITY_UNVERIFIED: Final[str] = "unverified"
INTEGRITY_VERIFIED: Final[str] = "verified"
INTEGRITY_CORRUPT: Final[str] = "corrupt"

RECONCILE_VERIFIED: Final[str] = "verified"
RECONCILE_PENDING: Final[str] = "pending"
RECONCILE_MISSING: Final[str] = "missing"
RECONCILE_CORRUPT: Final[str] = "corrupt"
RECONCILE_ORPHAN: Final[str] = "orphan"

RECONCILE_STATES: Final[FrozenSet[str]] = frozenset(
    {
        RECONCILE_VERIFIED,
        RECONCILE_PENDING,
        RECONCILE_MISSING,
        RECONCILE_CORRUPT,
        RECONCILE_ORPHAN,
    }
)

ACTION_RETENTION_EXPIRE: Final[str] = "retention_expire"
ACTION_CENTRAL_DELETE: Final[str] = "central_delete"
ACTION_CENTRAL_EXPORT: Final[str] = "central_export"

ROLE_REVIEWER: Final[str] = "reviewer"
ROLE_OPERATOR: Final[str] = "operator"
ROLE_ADMIN: Final[str] = "admin"

_ALLOWED_ROLES_BY_ACTION: Final[dict[str, FrozenSet[str]]] = {
    ACTION_RETENTION_EXPIRE: frozenset({ROLE_OPERATOR, ROLE_ADMIN}),
    ACTION_CENTRAL_DELETE: frozenset({ROLE_ADMIN}),
    ACTION_CENTRAL_EXPORT: frozenset({ROLE_REVIEWER, ROLE_OPERATOR, ROLE_ADMIN}),
}

#: Immutable receipt fields on an evidence manifest that retention/reconcile must never erase.
IMMUTABLE_RECEIPT_FIELDS: Final[tuple[str, ...]] = (
    "device_id",
    "event_id",
    "request_id",
    "sha256",
    "size_bytes",
    "requested_start",
    "requested_end",
    "actual_start",
    "actual_end",
)

_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class RetentionError(ValueError):
    """Typed error for unauthorized or invalid retention/export/restore operations."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class RetentionPolicy:
    """Central retention policy rules (Ticket #43 / Task E03)."""

    retention_seconds: float = DEFAULT_CENTRAL_RETENTION_SECONDS
    protect_open_retrievals: bool = True
    protect_pinned_or_legal_hold: bool = True
    protect_unreviewed_high_severity: bool = True
    protected_severities: FrozenSet[str] = field(
        default_factory=lambda: frozenset({"high", "critical"})
    )

    def __post_init__(self) -> None:
        if (
            type(self.retention_seconds) not in (int, float)
            or not math.isfinite(self.retention_seconds)
            or self.retention_seconds <= 0
        ):
            raise RetentionError("invalid_retention_policy", "retention_seconds must be finite and positive")


@dataclass(frozen=True)
class RetentionDecision:
    """Result of evaluating whether one stored clip may be expired and removed from disk."""

    device_id: str
    event_id: str
    request_id: str
    eligible_for_delete: bool
    reason: str
    age_seconds: Optional[float]
    retention_seconds: float


@dataclass(frozen=True)
class RetentionActionAudit:
    """Immutable audit record for a central retention, delete, or export action."""

    audit_id: str
    action: str
    actor: str
    role: str
    reason: str
    timestamp: float
    device_id: str
    event_id: str
    request_id: Optional[str] = None
    site_id: Optional[str] = None
    policy_version: str = POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "action": self.action,
            "actor": self.actor,
            "role": self.role,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "device_id": self.device_id,
            "event_id": self.event_id,
            "request_id": self.request_id,
            "site_id": self.site_id,
            "policy_version": self.policy_version,
        }


def authorize_retention_action(
    *,
    action: str,
    actor: str,
    role: str,
    reason: str,
    timestamp: float,
    device_id: str,
    event_id: str,
    request_id: Optional[str] = None,
    site_id: Optional[str] = None,
    allowed_sites: Optional[Iterable[str]] = None,
    audit_id: str = "audit-1",
) -> RetentionActionAudit:
    """Verify RBAC role, site scope, and non-empty reason before executing delete/export."""
    if action not in _ALLOWED_ROLES_BY_ACTION:
        raise RetentionError("unknown_retention_action", f"unsupported action: {action}")
    if not isinstance(actor, str) or not _IDENTIFIER.match(actor):
        raise RetentionError("invalid_actor", "actor must be a non-empty safe identifier")
    if not isinstance(role, str) or role not in _ALLOWED_ROLES_BY_ACTION[action]:
        raise RetentionError("unauthorized_role", f"role '{role}' is not authorized for {action}")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 512:
        raise RetentionError("invalid_reason", "action requires a non-empty audit reason (<= 512 chars)")
    if not isinstance(device_id, str) or not device_id.strip():
        raise RetentionError("invalid_target", "device_id is required")
    if not isinstance(event_id, str) or not event_id.strip():
        raise RetentionError("invalid_target", "event_id is required")
    if allowed_sites is not None:
        allowed_set = set(allowed_sites)
        if allowed_set and (site_id is None or site_id not in allowed_set):
            raise RetentionError("site_access_denied", f"actor '{actor}' is not authorized for site '{site_id}'")
    if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
        raise RetentionError("invalid_timestamp", "timestamp must be finite")

    return RetentionActionAudit(
        audit_id=audit_id,
        action=action,
        actor=actor,
        role=role,
        reason=reason.strip(),
        timestamp=float(timestamp),
        device_id=device_id,
        event_id=event_id,
        request_id=request_id,
        site_id=site_id,
    )


def evaluate_retention_candidate(
    record: Mapping[str, Any],
    *,
    now: float,
    policy: Optional[RetentionPolicy] = None,
    has_open_retrieval: bool = False,
    review_decision: Optional[str] = None,
    event_severity: Optional[str] = None,
) -> RetentionDecision:
    """Pure decision: can this server evidence clip be removed under the retention policy?"""
    active_policy = policy or RetentionPolicy()
    device_id = str(record.get("device_id", ""))
    event_id = str(record.get("event_id", ""))
    request_id = str(record.get("request_id", ""))
    raw_manifest = record.get("manifest")
    manifest: Mapping[str, Any] = raw_manifest if isinstance(raw_manifest, Mapping) else {}

    raw_locations = manifest.get("locations")
    locations: Mapping[str, Any] = raw_locations if isinstance(raw_locations, Mapping) else {}
    raw_server_loc = locations.get("server")
    server_loc: Mapping[str, Any] = raw_server_loc if isinstance(raw_server_loc, Mapping) else {}
    server_avail = server_loc.get("availability")

    if manifest.get("file_status") == AVAILABILITY_EXPIRED or server_avail == AVAILABILITY_EXPIRED:
        return RetentionDecision(
            device_id=device_id,
            event_id=event_id,
            request_id=request_id,
            eligible_for_delete=False,
            reason="already_expired",
            age_seconds=None,
            retention_seconds=active_policy.retention_seconds,
        )

    if active_policy.protect_pinned_or_legal_hold and (
        bool(record.get("legal_hold"))
        or bool(record.get("pinned"))
        or bool(manifest.get("legal_hold"))
        or bool(manifest.get("pinned"))
    ):
        return RetentionDecision(
            device_id=device_id,
            event_id=event_id,
            request_id=request_id,
            eligible_for_delete=False,
            reason="protected_legal_hold_or_pinned",
            age_seconds=None,
            retention_seconds=active_policy.retention_seconds,
        )

    if active_policy.protect_open_retrievals and has_open_retrieval:
        return RetentionDecision(
            device_id=device_id,
            event_id=event_id,
            request_id=request_id,
            eligible_for_delete=False,
            reason="protected_open_retrieval_command",
            age_seconds=None,
            retention_seconds=active_policy.retention_seconds,
        )

    if (
        active_policy.protect_unreviewed_high_severity
        and event_severity in active_policy.protected_severities
        and (review_decision is None or review_decision == "unreviewed")
    ):
        return RetentionDecision(
            device_id=device_id,
            event_id=event_id,
            request_id=request_id,
            eligible_for_delete=False,
            reason="protected_unreviewed_high_severity",
            age_seconds=None,
            retention_seconds=active_policy.retention_seconds,
        )

    uploaded_at = record.get("uploaded_at")
    if not isinstance(uploaded_at, (int, float)) or not math.isfinite(float(uploaded_at)):
        return RetentionDecision(
            device_id=device_id,
            event_id=event_id,
            request_id=request_id,
            eligible_for_delete=False,
            reason="missing_uploaded_timestamp",
            age_seconds=None,
            retention_seconds=active_policy.retention_seconds,
        )

    age = max(0.0, float(now) - float(uploaded_at))
    if age < active_policy.retention_seconds:
        return RetentionDecision(
            device_id=device_id,
            event_id=event_id,
            request_id=request_id,
            eligible_for_delete=False,
            reason="within_retention_window",
            age_seconds=age,
            retention_seconds=active_policy.retention_seconds,
        )

    return RetentionDecision(
        device_id=device_id,
        event_id=event_id,
        request_id=request_id,
        eligible_for_delete=True,
        reason="retention_expired",
        age_seconds=age,
        retention_seconds=active_policy.retention_seconds,
    )


def apply_retention_expiry_to_manifest(
    manifest: Mapping[str, Any],
    *,
    expired_at: float,
    reason: str = "central_retention_expired",
) -> dict[str, Any]:
    """Transition a manifest to server-expired while preserving every immutable receipt field."""
    updated = deepcopy(dict(manifest))
    for field_name in IMMUTABLE_RECEIPT_FIELDS:
        if field_name in manifest:
            updated[field_name] = deepcopy(manifest[field_name])

    updated["file_status"] = AVAILABILITY_EXPIRED
    updated["expired_at"] = float(expired_at)
    updated["expiry_reason"] = reason
    updated["manifest_version"] = int(updated.get("manifest_version", 1)) + 1

    locations = dict(updated.get("locations") or {})
    server_loc = dict(locations.get("server") or {})
    server_loc["availability"] = AVAILABILITY_EXPIRED
    locations["server"] = server_loc
    updated["locations"] = locations
    return updated


def classify_manifest_and_file(
    manifest_record: Mapping[str, Any],
    *,
    file_exists: bool,
    actual_size_bytes: Optional[int],
    actual_sha256: Optional[str],
) -> str:
    """Classify one manifest record against observed disk state during restore/reconcile."""
    raw_inner = manifest_record.get("manifest")
    manifest: Mapping[str, Any] = raw_inner if isinstance(raw_inner, Mapping) else manifest_record
    build_state = manifest.get("build_state") or manifest_record.get("status")
    transfer_state = manifest.get("transfer_state")

    expected_sha = manifest.get("sha256")
    expected_size = manifest.get("size_bytes")
    if (
        build_state in {"pending", "collecting"}
        or transfer_state in {"not_started", "uploading"}
        or not isinstance(expected_sha, str)
        or not expected_sha
        or type(expected_size) is not int
    ):
        return RECONCILE_PENDING

    if not file_exists:
        return RECONCILE_MISSING

    if actual_size_bytes != expected_size or (actual_sha256 or "").lower() != expected_sha.lower():
        return RECONCILE_CORRUPT

    return RECONCILE_VERIFIED


def apply_reconcile_outcome_to_manifest(
    manifest: Mapping[str, Any],
    outcome: str,
    *,
    reconciled_at: float,
) -> dict[str, Any]:
    """Update availability/integrity metadata on a manifest from reconciliation without mutating receipts."""
    if outcome not in {RECONCILE_VERIFIED, RECONCILE_PENDING, RECONCILE_MISSING, RECONCILE_CORRUPT}:
        raise RetentionError("invalid_reconcile_outcome", f"cannot apply outcome {outcome} to manifest")

    updated = deepcopy(dict(manifest))
    for field_name in IMMUTABLE_RECEIPT_FIELDS:
        if field_name in manifest:
            updated[field_name] = deepcopy(manifest[field_name])

    locations = dict(updated.get("locations") or {})
    server_loc = dict(locations.get("server") or {})

    if outcome == RECONCILE_VERIFIED:
        updated["file_status"] = AVAILABILITY_AVAILABLE
        server_loc["availability"] = AVAILABILITY_AVAILABLE
        server_loc["integrity"] = INTEGRITY_VERIFIED
    elif outcome == RECONCILE_PENDING:
        updated["file_status"] = AVAILABILITY_PENDING
        server_loc["availability"] = AVAILABILITY_PENDING
        server_loc["integrity"] = INTEGRITY_UNVERIFIED
    elif outcome == RECONCILE_MISSING:
        updated["file_status"] = AVAILABILITY_MISSING
        server_loc["availability"] = AVAILABILITY_MISSING
        server_loc["integrity"] = INTEGRITY_UNVERIFIED
    elif outcome == RECONCILE_CORRUPT:
        updated["file_status"] = INTEGRITY_CORRUPT
        server_loc["availability"] = AVAILABILITY_QUARANTINED
        server_loc["integrity"] = INTEGRITY_CORRUPT

    locations["server"] = server_loc
    updated["locations"] = locations
    updated["reconciled_at"] = float(reconciled_at)
    return updated


def build_reconciliation_report(
    *,
    items: Iterable[Mapping[str, Any]],
    orphan_files: Iterable[str],
    backup_created_at: float,
    latest_data_timestamp: float,
    restore_started_at: float,
    restore_completed_at: float,
    collections_restored: Mapping[str, int],
) -> dict[str, Any]:
    """Build a structured backup/restore & reconciliation proof report with RPO/RTO and HA disclaimer."""
    counts: dict[str, int] = {
        RECONCILE_VERIFIED: 0,
        RECONCILE_PENDING: 0,
        RECONCILE_MISSING: 0,
        RECONCILE_CORRUPT: 0,
        RECONCILE_ORPHAN: 0,
    }
    item_list: list[dict[str, Any]] = []
    for item in items:
        state = str(item.get("state", ""))
        if state not in counts:
            raise RetentionError("invalid_reconcile_state", f"unknown state {state}")
        counts[state] += 1
        item_list.append(dict(item))

    orphans = sorted(str(p) for p in orphan_files)
    counts[RECONCILE_ORPHAN] = len(orphans)

    rpo_seconds = max(0.0, round(float(backup_created_at) - float(latest_data_timestamp), 6))
    rto_seconds = max(0.0, round(float(restore_completed_at) - float(restore_started_at), 6))

    return {
        "policy_version": POLICY_VERSION,
        "ha_disclaimer": HA_DISCLAIMER,
        "production_ha_signed_off": False,
        "rpo_seconds": rpo_seconds,
        "rto_seconds": rto_seconds,
        "backup_created_at": float(backup_created_at),
        "latest_data_timestamp": float(latest_data_timestamp),
        "restore_started_at": float(restore_started_at),
        "restore_completed_at": float(restore_completed_at),
        "collections_restored": dict(collections_restored),
        "counts": counts,
        "items": item_list,
        "orphan_files": orphans,
        "clean": counts[RECONCILE_MISSING] == 0 and counts[RECONCILE_CORRUPT] == 0 and counts[RECONCILE_ORPHAN] == 0,
    }
