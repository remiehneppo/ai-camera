"""WAN outage autonomy, metadata priority, and backlog drain rate contract (Ticket #36).

Pure domain module: no I/O, no filesystem, network, or framework imports. Defines:
1. 24h Autonomy & Sizing Model (Q6, contracts §3):
   Evaluates autonomy duration (target 24h = 86,400s), time-to-full, and backlog storage
   consumption for events and evidence clips under configured generation rates and disk capacity.
   Surfaces degraded / wan_outage_budget_exceeded when outage exceeds the autonomy budget without network.
2. Strict unACKed Evidence Persistence Policy (Q6/Q12):
   Explicitly enforces that unACKed evidence clips and pending outbox events are NEVER expired or
   deleted by a TTL clock during WAN outages, protecting event and evidence persistence.
3. Metadata Priority Policy (contracts §3):
   Enforces strict priority of lightweight metadata outbox events over large evidence video clips,
   preventing video upload from starving event delivery during outage and recovery.
4. Backlog Drain Rate Model B / (U - G):
   Formalizes backlog drain dynamics where B is backlog size (bytes or items), U is upload bandwidth/rate,
   and G is ongoing generation rate.
   Declares recovery impossible when U <= G (backlog cannot be cleared).
   Calculates expected drain time T = B / (U - G) when U > G, and provides trajectory verification.
5. RPO/RTO Reporting Scope (contracts §3):
   Reports RPO (0s under persistent journal/recorder without disk loss) and RTO (drain time B/(U-G)),
   with explicit disclaimer that disk loss is not protected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Final, FrozenSet, Mapping, Sequence

__all__ = [
    "DEFAULT_AUTONOMY_BUDGET_SECONDS",
    "DEFAULT_EVENT_RING_MINUTES",
    "DEFAULT_MIN_STATE_RESERVE_BYTES",
    "DEFAULT_POST_ROLL_SECONDS",
    "DEFAULT_PRE_ROLL_SECONDS",
    "DEFAULT_SERVER_RETENTION_DAYS",
    "DISK_LOSS_DISCLAIMER",
    "ITEM_TYPE_EVIDENCE_CLIP",
    "ITEM_TYPE_METADATA",
    "POLICY_VERSION",
    "PRIORITY_EVIDENCE_CLIP",
    "PRIORITY_METADATA",
    "REASON_AGE_BELOW_TTL",
    "REASON_OUTAGE_BUDGET_EXCEEDED",
    "REASON_PINNED_PROTECTED",
    "REASON_RECOVERY_IMPOSSIBLE_RATE",
    "REASON_STORAGE_EXHAUSTED",
    "REASON_UNACKED_PROTECTED_AGAINST_TTL",
    "STATUS_DEGRADED",
    "STATUS_HEALTHY",
    "STATUS_RECOVERY_IMPOSSIBLE",
    "STATUS_TOLERANCE_EXCEEDED",
    "STATUS_UNAVAILABLE",
    "STATUS_VERIFIED",
    "AutonomySizingModel",
    "BacklogDrainModel",
    "DrainVerificationResult",
    "EvidenceTTLEvaluation",
    "MetadataPriorityPolicy",
    "OutageAssessment",
    "RpoRtoAssessment",
    "evaluate_evidence_ttl_eligibility",
    "filter_unexpired_unacked_evidence",
]

POLICY_VERSION: Final[str] = "wan-outage-v1"

#: Standard 24-hour target autonomy budget in seconds (Q6 / contracts §3).
DEFAULT_AUTONOMY_BUDGET_SECONDS: Final[float] = 24.0 * 3600.0  # 86,400.0s

#: Edge pre-roll buffer window in seconds (Q6).
DEFAULT_PRE_ROLL_SECONDS: Final[float] = 10.0

#: Edge post-roll recording window in seconds (Q6).
DEFAULT_POST_ROLL_SECONDS: Final[float] = 20.0

#: Edge rolling event ring duration in minutes (Q6).
DEFAULT_EVENT_RING_MINUTES: Final[float] = 10.0

#: Central server clip retention window in days (Q6).
DEFAULT_SERVER_RETENTION_DAYS: Final[float] = 7.0

#: Minimum state reserve protection threshold (50MB) per Q12 / contracts §3.
DEFAULT_MIN_STATE_RESERVE_BYTES: Final[int] = 50 * 1024 * 1024

#: Explicit disclaimer that edge autonomy does not guarantee endurance against hardware disk destruction.
DISK_LOSS_DISCLAIMER: Final[str] = "zero_rpo_assumes_local_disk_integrity_no_disk_loss_guarantee"

REASON_OUTAGE_BUDGET_EXCEEDED: Final[str] = "wan_outage_budget_exceeded"
REASON_STORAGE_EXHAUSTED: Final[str] = "storage_exhausted"
REASON_UNACKED_PROTECTED_AGAINST_TTL: Final[str] = "unacked_protected_against_ttl"
REASON_PINNED_PROTECTED: Final[str] = "pinned_protected"
REASON_AGE_BELOW_TTL: Final[str] = "age_below_ttl"
REASON_RECOVERY_IMPOSSIBLE_RATE: Final[str] = "drain_rate_insufficient_recovery_impossible"

STATUS_HEALTHY: Final[str] = "healthy"
STATUS_DEGRADED: Final[str] = "degraded"
STATUS_UNAVAILABLE: Final[str] = "unavailable"
STATUS_VERIFIED: Final[str] = "verified"
STATUS_RECOVERY_IMPOSSIBLE: Final[str] = "recovery_impossible"
STATUS_TOLERANCE_EXCEEDED: Final[str] = "tolerance_exceeded"

PRIORITY_METADATA: Final[int] = 0
PRIORITY_EVIDENCE_CLIP: Final[int] = 1

ITEM_TYPE_METADATA: Final[str] = "metadata_event"
ITEM_TYPE_EVIDENCE_CLIP: Final[str] = "evidence_clip"


@dataclass(frozen=True)
class OutageAssessment:
    """Truthful evaluation of edge autonomy and WAN outage health."""

    outage_duration_seconds: float
    autonomy_budget_seconds: float
    is_budget_exceeded: bool
    status: str
    reason: str | None
    estimated_backlog_bytes: int
    time_to_full_seconds: float | None = None
    state_reserve_bytes: int = DEFAULT_MIN_STATE_RESERVE_BYTES

    def to_dict(self) -> dict[str, Any]:
        return {
            "outage_duration_seconds": self.outage_duration_seconds,
            "autonomy_budget_seconds": self.autonomy_budget_seconds,
            "is_budget_exceeded": self.is_budget_exceeded,
            "status": self.status,
            "reason": self.reason,
            "estimated_backlog_bytes": self.estimated_backlog_bytes,
            "time_to_full_seconds": self.time_to_full_seconds,
            "state_reserve_bytes": self.state_reserve_bytes,
        }


@dataclass(frozen=True)
class AutonomySizingModel:
    """Sizing and storage consumption model for 24h edge autonomy under WAN outage."""

    autonomy_budget_seconds: float = DEFAULT_AUTONOMY_BUDGET_SECONDS
    event_rate_per_second: float = 0.0
    avg_event_bytes: int = 1024
    evidence_rate_per_second: float = 0.0
    avg_clip_bytes: int = 5 * 1024 * 1024  # 5 MB typical 30s 1080p clip
    min_state_reserve_bytes: int = DEFAULT_MIN_STATE_RESERVE_BYTES

    def __post_init__(self) -> None:
        if not math.isfinite(self.autonomy_budget_seconds) or self.autonomy_budget_seconds <= 0:
            raise ValueError("autonomy_budget_seconds must be finite and positive")
        if not math.isfinite(self.event_rate_per_second) or self.event_rate_per_second < 0:
            raise ValueError("event_rate_per_second must be finite and non-negative")
        if self.avg_event_bytes < 0:
            raise ValueError("avg_event_bytes must be non-negative")
        if not math.isfinite(self.evidence_rate_per_second) or self.evidence_rate_per_second < 0:
            raise ValueError("evidence_rate_per_second must be finite and non-negative")
        if self.avg_clip_bytes < 0:
            raise ValueError("avg_clip_bytes must be non-negative")
        if self.min_state_reserve_bytes < 0:
            raise ValueError("min_state_reserve_bytes must be non-negative")

    @property
    def event_generation_rate_bytes_per_second(self) -> float:
        return self.event_rate_per_second * float(self.avg_event_bytes)

    @property
    def evidence_generation_rate_bytes_per_second(self) -> float:
        return self.evidence_rate_per_second * float(self.avg_clip_bytes)

    @property
    def total_generation_rate_bytes_per_second(self) -> float:
        return self.event_generation_rate_bytes_per_second + self.evidence_generation_rate_bytes_per_second

    def estimate_backlog_consumption(self, duration_seconds: float) -> tuple[int, int, int]:
        """Estimate storage consumed during outage duration.

        Returns:
            (metadata_bytes, clip_bytes, total_bytes)
        """
        if duration_seconds < 0:
            raise ValueError("duration_seconds cannot be negative")
        meta_bytes = int(math.ceil(self.event_generation_rate_bytes_per_second * duration_seconds))
        clip_bytes = int(math.ceil(self.evidence_generation_rate_bytes_per_second * duration_seconds))
        return meta_bytes, clip_bytes, meta_bytes + clip_bytes

    def calculate_time_to_full(self, available_bytes: int, *, preserve_reserve: bool = True) -> float:
        """Calculate seconds until storage reaches capacity or the state reserve boundary."""
        if available_bytes < 0:
            raise ValueError("available_bytes cannot be negative")
        reserve = self.min_state_reserve_bytes if preserve_reserve else 0
        usable_bytes = max(0, available_bytes - reserve)
        rate = self.total_generation_rate_bytes_per_second
        if rate <= 0.0:
            return float("inf")
        return float(usable_bytes) / rate

    def can_sustain_autonomy(self, available_bytes: int, duration_seconds: float | None = None) -> bool:
        """Check whether available storage satisfies the 24h autonomy target with state reserve."""
        target = self.autonomy_budget_seconds if duration_seconds is None else float(duration_seconds)
        _, _, required_bytes = self.estimate_backlog_consumption(target)
        total_needed = required_bytes + self.min_state_reserve_bytes
        return available_bytes >= total_needed

    def evaluate_outage(
        self,
        outage_duration_seconds: float,
        *,
        available_bytes: int | None = None,
    ) -> OutageAssessment:
        """Evaluate an in-progress or historical WAN outage against autonomy budgets."""
        if outage_duration_seconds < 0:
            raise ValueError("outage_duration_seconds cannot be negative")

        _, _, est_backlog = self.estimate_backlog_consumption(outage_duration_seconds)
        is_exceeded = outage_duration_seconds > self.autonomy_budget_seconds

        time_to_full = None
        status = STATUS_HEALTHY
        reason = None

        if available_bytes is not None:
            time_to_full = self.calculate_time_to_full(available_bytes, preserve_reserve=True)
            if available_bytes <= self.min_state_reserve_bytes:
                status = STATUS_UNAVAILABLE
                reason = REASON_STORAGE_EXHAUSTED

        if status != STATUS_UNAVAILABLE:
            if is_exceeded:
                status = STATUS_DEGRADED
                reason = REASON_OUTAGE_BUDGET_EXCEEDED

        return OutageAssessment(
            outage_duration_seconds=outage_duration_seconds,
            autonomy_budget_seconds=self.autonomy_budget_seconds,
            is_budget_exceeded=is_exceeded,
            status=status,
            reason=reason,
            estimated_backlog_bytes=est_backlog,
            time_to_full_seconds=time_to_full,
            state_reserve_bytes=self.min_state_reserve_bytes,
        )


@dataclass(frozen=True)
class EvidenceTTLEvaluation:
    """Result of evaluating an evidence item for TTL cleanup eligibility."""

    request_id: str
    is_acked: bool
    is_pinned: bool
    age_seconds: float
    eligible_for_expiry: bool
    rejection_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "is_acked": self.is_acked,
            "is_pinned": self.is_pinned,
            "age_seconds": self.age_seconds,
            "eligible_for_expiry": self.eligible_for_expiry,
            "rejection_reason": self.rejection_reason,
        }


def evaluate_evidence_ttl_eligibility(
    *,
    request_id: str,
    is_acked: bool,
    is_pinned: bool = False,
    age_seconds: float = 0.0,
    ttl_seconds: float = DEFAULT_AUTONOMY_BUDGET_SECONDS,
) -> EvidenceTTLEvaluation:
    """Enforce strict NO-TTL on unACKed evidence during WAN outage.

    STRICT UNACK PRESERVATION (Q6, Q12, contracts §3):
    - UnACKed evidence and pending outbox events are NEVER expired or deleted by a TTL clock.
    - Outage exceeding 24h does NOT act as a TTL to delete unACK evidence.
    - Pinned segments are protected until explicitly released.
    - Only ACKed and unpinned items whose age exceeds ttl_seconds may be expired.
    """
    if not is_acked:
        return EvidenceTTLEvaluation(
            request_id=request_id,
            is_acked=False,
            is_pinned=is_pinned,
            age_seconds=age_seconds,
            eligible_for_expiry=False,
            rejection_reason=REASON_UNACKED_PROTECTED_AGAINST_TTL,
        )
    if is_pinned:
        return EvidenceTTLEvaluation(
            request_id=request_id,
            is_acked=True,
            is_pinned=True,
            age_seconds=age_seconds,
            eligible_for_expiry=False,
            rejection_reason=REASON_PINNED_PROTECTED,
        )
    if age_seconds < ttl_seconds:
        return EvidenceTTLEvaluation(
            request_id=request_id,
            is_acked=True,
            is_pinned=False,
            age_seconds=age_seconds,
            eligible_for_expiry=False,
            rejection_reason=REASON_AGE_BELOW_TTL,
        )
    return EvidenceTTLEvaluation(
        request_id=request_id,
        is_acked=True,
        is_pinned=False,
        age_seconds=age_seconds,
        eligible_for_expiry=True,
        rejection_reason=None,
    )


def filter_unexpired_unacked_evidence(
    items: Sequence[Mapping[str, Any]],
    *,
    current_time: float,
    ttl_seconds: float = DEFAULT_AUTONOMY_BUDGET_SECONDS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partitions evidence records into (protected_items, eligible_for_expiry_items).

    Guarantees 100% of unACKed items are placed in protected_items, regardless of age.
    """
    protected: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []

    for item in items:
        req_id = str(item.get("request_id") or "")
        state = item.get("state")
        is_acked = bool(
            state == "acknowledged"
            or (item.get("receipt") and item.get("receipt", {}).get("transfer_state") == "acknowledged")
            or item.get("is_acked") is True
        )
        is_pinned = bool(item.get("is_pinned", False) or item.get("released") == 0)
        created_time = float(item.get("created_at_epoch") or item.get("start") or current_time)
        age = max(0.0, current_time - created_time)

        eval_res = evaluate_evidence_ttl_eligibility(
            request_id=req_id,
            is_acked=is_acked,
            is_pinned=is_pinned,
            age_seconds=age,
            ttl_seconds=ttl_seconds,
        )
        dict_item = dict(item)
        if eval_res.eligible_for_expiry:
            eligible.append(dict_item)
        else:
            dict_item["ttl_protection_reason"] = eval_res.rejection_reason
            protected.append(dict_item)

    return protected, eligible


class MetadataPriorityPolicy:
    """Enforces strict priority of metadata outbox events over raw video clips."""

    @staticmethod
    def select_next_transfer_type(
        pending_metadata_count: int,
        pending_clip_count: int,
    ) -> str | None:
        """Select next transfer type, strictly prioritizing metadata."""
        if pending_metadata_count > 0:
            return ITEM_TYPE_METADATA
        if pending_clip_count > 0:
            return ITEM_TYPE_EVIDENCE_CLIP
        return None

    @staticmethod
    def should_defer_clip_upload(pending_metadata_count: int) -> bool:
        """Returns True if clip uploads must be deferred because metadata events are pending."""
        return pending_metadata_count > 0

    @staticmethod
    def prioritize_queue(
        metadata_items: Sequence[Any],
        clip_items: Sequence[Any],
    ) -> list[tuple[str, Any]]:
        """Order backlog items strictly prioritizing metadata first, then clips."""
        ordered: list[tuple[str, Any]] = []
        for m in metadata_items:
            ordered.append((ITEM_TYPE_METADATA, m))
        for c in clip_items:
            ordered.append((ITEM_TYPE_EVIDENCE_CLIP, c))
        return ordered


@dataclass(frozen=True)
class DrainVerificationResult:
    """Outcome of verifying actual drain measurements against theoretical B / (U - G)."""

    backlog_bytes: int
    upload_rate: float
    generation_rate: float
    net_drain_rate: float
    is_recovery_possible: bool
    expected_drain_time_seconds: float | None
    measured_drain_time_seconds: float | None
    discrepancy_seconds: float | None
    within_tolerance: bool
    status: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "backlog_bytes": self.backlog_bytes,
            "upload_rate": self.upload_rate,
            "generation_rate": self.generation_rate,
            "net_drain_rate": self.net_drain_rate,
            "is_recovery_possible": self.is_recovery_possible,
            "expected_drain_time_seconds": self.expected_drain_time_seconds,
            "measured_drain_time_seconds": self.measured_drain_time_seconds,
            "discrepancy_seconds": self.discrepancy_seconds,
            "within_tolerance": self.within_tolerance,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True)
class RpoRtoAssessment:
    """Scope of RPO and RTO guarantees during WAN outage and recovery."""

    rpo_seconds: float
    rto_seconds: float | None
    backlog_bytes: int
    net_drain_rate: float
    is_recovery_possible: bool
    disclaimer: str = DISK_LOSS_DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "rpo_seconds": self.rpo_seconds,
            "rto_seconds": self.rto_seconds,
            "backlog_bytes": self.backlog_bytes,
            "net_drain_rate": self.net_drain_rate,
            "is_recovery_possible": self.is_recovery_possible,
            "disclaimer": self.disclaimer,
        }


@dataclass(frozen=True)
class BacklogDrainModel:
    """Mathematical backlog drain model B / (U - G) (Ticket #36).

    Parameters:
        backlog_bytes: Initial backlog byte size B.
        upload_rate_bytes_per_second: Upload bandwidth / transfer rate U.
        generation_rate_bytes_per_second: Ongoing generation rate G during recovery.
    """

    backlog_bytes: int
    upload_rate_bytes_per_second: float
    generation_rate_bytes_per_second: float = 0.0

    def __post_init__(self) -> None:
        if self.backlog_bytes < 0:
            raise ValueError("backlog_bytes cannot be negative")
        if not math.isfinite(self.upload_rate_bytes_per_second) or self.upload_rate_bytes_per_second < 0:
            raise ValueError("upload_rate_bytes_per_second must be finite and non-negative")
        if not math.isfinite(self.generation_rate_bytes_per_second) or self.generation_rate_bytes_per_second < 0:
            raise ValueError("generation_rate_bytes_per_second must be finite and non-negative")

    @property
    def net_drain_rate_bytes_per_second(self) -> float:
        return self.upload_rate_bytes_per_second - self.generation_rate_bytes_per_second

    @property
    def is_recovery_possible(self) -> bool:
        """True only if upload rate U is strictly greater than generation rate G."""
        return self.upload_rate_bytes_per_second > self.generation_rate_bytes_per_second

    def calculate_expected_drain_time(self) -> float:
        """Calculate theoretical drain time T = B / (U - G).

        Raises ValueError if U <= G (recovery impossible).
        Returns 0.0 if B == 0.
        """
        if self.backlog_bytes == 0:
            return 0.0
        if not self.is_recovery_possible:
            raise ValueError(
                f"{REASON_RECOVERY_IMPOSSIBLE_RATE}: upload rate ({self.upload_rate_bytes_per_second:.2f} B/s) "
                f"<= generation rate ({self.generation_rate_bytes_per_second:.2f} B/s); backlog cannot be cleared"
            )
        return float(self.backlog_bytes) / self.net_drain_rate_bytes_per_second

    def predict_backlog(self, elapsed_seconds: float) -> float:
        """Calculate predicted remaining backlog at time t."""
        if elapsed_seconds < 0:
            raise ValueError("elapsed_seconds cannot be negative")
        if self.is_recovery_possible:
            return max(0.0, float(self.backlog_bytes) - self.net_drain_rate_bytes_per_second * elapsed_seconds)
        else:
            return float(self.backlog_bytes) + (self.generation_rate_bytes_per_second - self.upload_rate_bytes_per_second) * elapsed_seconds

    def assess_rpo_rto(self) -> RpoRtoAssessment:
        """Assess RPO and RTO within scope.

        RPO is 0s under durable local storage: no unACKed events or evidence clips are lost.
        RTO is expected drain time T = B / (U - G) when recovery is possible.
        """
        rto = self.calculate_expected_drain_time() if self.is_recovery_possible else None
        return RpoRtoAssessment(
            rpo_seconds=0.0,
            rto_seconds=rto,
            backlog_bytes=self.backlog_bytes,
            net_drain_rate=self.net_drain_rate_bytes_per_second,
            is_recovery_possible=self.is_recovery_possible,
        )

    def verify_drain(
        self,
        measured_drain_time_seconds: float,
        *,
        tolerance_fraction: float = 0.15,
        min_tolerance_seconds: float = 1.0,
    ) -> DrainVerificationResult:
        """Verify measured drain time against the theoretical B / (U - G) model."""
        if measured_drain_time_seconds < 0:
            raise ValueError("measured_drain_time_seconds cannot be negative")

        if not self.is_recovery_possible:
            return DrainVerificationResult(
                backlog_bytes=self.backlog_bytes,
                upload_rate=self.upload_rate_bytes_per_second,
                generation_rate=self.generation_rate_bytes_per_second,
                net_drain_rate=self.net_drain_rate_bytes_per_second,
                is_recovery_possible=False,
                expected_drain_time_seconds=None,
                measured_drain_time_seconds=measured_drain_time_seconds,
                discrepancy_seconds=None,
                within_tolerance=False,
                status=STATUS_RECOVERY_IMPOSSIBLE,
                message=(
                    f"Recovery impossible: upload rate U ({self.upload_rate_bytes_per_second:.2f} B/s) "
                    f"<= generation rate G ({self.generation_rate_bytes_per_second:.2f} B/s)"
                ),
            )

        expected_t = self.calculate_expected_drain_time()
        discrepancy = abs(measured_drain_time_seconds - expected_t)
        allowed_discrepancy = max(min_tolerance_seconds, expected_t * tolerance_fraction)
        within_tolerance = discrepancy <= allowed_discrepancy

        status = STATUS_VERIFIED if within_tolerance else STATUS_TOLERANCE_EXCEEDED
        message = (
            f"Measured drain time {measured_drain_time_seconds:.2f}s vs expected {expected_t:.2f}s "
            f"(discrepancy {discrepancy:.2f}s, tolerance ±{allowed_discrepancy:.2f}s): {status}"
        )
        return DrainVerificationResult(
            backlog_bytes=self.backlog_bytes,
            upload_rate=self.upload_rate_bytes_per_second,
            generation_rate=self.generation_rate_bytes_per_second,
            net_drain_rate=self.net_drain_rate_bytes_per_second,
            is_recovery_possible=True,
            expected_drain_time_seconds=expected_t,
            measured_drain_time_seconds=measured_drain_time_seconds,
            discrepancy_seconds=discrepancy,
            within_tolerance=within_tolerance,
            status=status,
            message=message,
        )
