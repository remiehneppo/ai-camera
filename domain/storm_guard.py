"""Inbound storm guard: bounded counters and forensics for a malformed flood (Ticket #41).

Pure domain module: no I/O, no framework imports. A flood of malformed payloads must not be
able to consume the state reserve, and it must not be silent either: the guard keeps a
rolling window of outcome counters, refuses further malformed attempts once the budget is
spent (so the caller answers 429 instead of persisting anything), and retains a *bounded*
ring of forensic samples with an explicit truncation flag.

Duplicate deliveries stay compact on purpose: a duplicate revision of an already persisted
event is counted but never sampled and never touches the malformed budget, so a retrying
edge cannot starve legitimate traffic. Valid unique events are always counted, never
sampled, and never refused by this guard -- a unique storm shows up as truncation/degraded,
not as silent data loss.
"""

from __future__ import annotations

import json
import math
import time
from threading import RLock
from dataclasses import dataclass, field
from typing import Any, Callable, Final, FrozenSet, Mapping, Optional

__all__ = [
    "BUDGETED_OUTCOMES",
    "OUTCOMES",
    "OUTCOME_ACCEPTED",
    "OUTCOME_CONFLICT",
    "OUTCOME_DUPLICATE",
    "OUTCOME_MALFORMED",
    "OUTCOME_RATE_LIMITED",
    "OUTCOME_TOO_LARGE",
    "OUTCOME_UNAVAILABLE",
    "POLICY_VERSION",
    "StormGuard",
    "StormGuardPolicy",
]

OUTCOME_ACCEPTED: Final[str] = "accepted"
OUTCOME_DUPLICATE: Final[str] = "duplicate"
OUTCOME_CONFLICT: Final[str] = "conflict"
OUTCOME_MALFORMED: Final[str] = "malformed"
OUTCOME_TOO_LARGE: Final[str] = "too_large"
OUTCOME_UNAVAILABLE: Final[str] = "unavailable"
OUTCOME_RATE_LIMITED: Final[str] = "rate_limited"

OUTCOMES: Final[FrozenSet[str]] = frozenset(
    {
        OUTCOME_ACCEPTED,
        OUTCOME_DUPLICATE,
        OUTCOME_CONFLICT,
        OUTCOME_MALFORMED,
        OUTCOME_TOO_LARGE,
        OUTCOME_UNAVAILABLE,
        OUTCOME_RATE_LIMITED,
    }
)

#: Outcomes that spend the malformed budget and earn a forensic sample.
BUDGETED_OUTCOMES: Final[FrozenSet[str]] = frozenset(
    {OUTCOME_MALFORMED, OUTCOME_TOO_LARGE, OUTCOME_RATE_LIMITED, OUTCOME_CONFLICT}
)

POLICY_VERSION: Final[str] = "storm-guard-v1"


@dataclass(frozen=True)
class StormGuardPolicy:
    """Lab budget for one rolling window; not a signed production SLA."""

    window_seconds: float = 60.0
    malformed_budget: int = 50
    forensic_samples: int = 8
    sample_text_bytes: int = 240

    def __post_init__(self) -> None:
        if type(self.window_seconds) not in (int, float) or not math.isfinite(self.window_seconds) or self.window_seconds <= 0:
            raise ValueError("window_seconds must be finite and positive")
        for name in ("malformed_budget", "forensic_samples"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(name + " must be a non-negative integer")
        if self.malformed_budget == 0:
            raise ValueError("malformed_budget must allow at least one malformed attempt")
        if type(self.sample_text_bytes) is not int or self.sample_text_bytes < 32:
            raise ValueError("sample_text_bytes must be an integer >= 32")


def _bounded_detail(detail: Optional[Mapping[str, Any]], limit: int) -> dict[str, str]:
    """Keep a small, flat, bounded summary: never a payload dump, never a secret value."""
    if not detail:
        return {}
    kept: dict[str, str] = {}
    budget = limit
    for key in sorted(detail, key=str)[:4]:
        value = detail[key]
        if isinstance(value, (Mapping, list, tuple, set)):
            continue
        text = str(value)[:64]
        cost = len(str(key)) + len(text) + 4
        if cost > budget:
            break
        kept[str(key)[:32]] = text
        budget -= cost
    return kept


@dataclass
class StormGuard:
    """Rolling-window counters plus a bounded forensic ring."""

    policy: StormGuardPolicy = field(default_factory=StormGuardPolicy)
    _now: Callable[[], float] = time.time
    # FastAPI serves sync endpoints from a worker thread while the event loop records
    # ingest outcomes, so the window is shared mutable state across threads.
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _window_started_at: float = field(default=0.0, init=False)
    _counts: dict[str, int] = field(default_factory=dict, init=False)
    _samples: list[dict[str, Any]] = field(default_factory=list, init=False)
    _dropped_samples: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._window_started_at = float(self._now())

    # -- window ----------------------------------------------------------

    def _roll(self, now: float) -> None:
        if now - self._window_started_at < self.policy.window_seconds:
            return
        self._window_started_at = now
        self._counts = {}
        self._samples = []
        self._dropped_samples = 0

    def _clock(self, now: Optional[float]) -> float:
        return float(self._now()) if now is None else float(now)

    # -- admission -------------------------------------------------------

    def spent(self, *, now: Optional[float] = None) -> int:
        """How much of the malformed budget this window has consumed."""
        with self._lock:
            now = self._clock(now)
            self._roll(now)
            return sum(self._counts.get(outcome, 0) for outcome in BUDGETED_OUTCOMES)

    def admit(self, *, now: Optional[float] = None) -> bool:
        """False once the malformed budget is spent: the caller answers 429 and persists nothing."""
        return self.spent(now=now) < self.policy.malformed_budget

    def retry_after_seconds(self, *, now: Optional[float] = None) -> int:
        with self._lock:
            now = self._clock(now)
            remaining = self.policy.window_seconds - (now - self._window_started_at)
            return max(1, int(math.ceil(remaining)))

    # -- recording -------------------------------------------------------

    def record(
        self,
        outcome: str,
        *,
        device_id: str = "",
        detail: Optional[Mapping[str, Any]] = None,
        size_bytes: Optional[int] = None,
        now: Optional[float] = None,
    ) -> None:
        if outcome not in OUTCOMES:
            raise ValueError("unknown ingest outcome")
        with self._lock:
            self._record_locked(outcome, device_id=device_id, detail=detail, size_bytes=size_bytes, now=now)

    def _record_locked(
        self,
        outcome: str,
        *,
        device_id: str,
        detail: Optional[Mapping[str, Any]],
        size_bytes: Optional[int],
        now: Optional[float],
    ) -> None:
        now = self._clock(now)
        self._roll(now)
        self._counts[outcome] = self._counts.get(outcome, 0) + 1
        if outcome not in BUDGETED_OUTCOMES:
            # Accepted, duplicate and unavailable outcomes stay compact: no sample, no budget.
            return
        sample = {
            "at": now,
            "outcome": outcome,
            "device_id": str(device_id)[:64],
            "size_bytes": int(size_bytes) if isinstance(size_bytes, int) else None,
            "detail": _bounded_detail(detail, self.policy.sample_text_bytes),
        }
        if len(self._samples) >= self.policy.forensic_samples:
            self._samples.pop(0)
            self._dropped_samples += 1
        self._samples.append(sample)

    # -- reporting -------------------------------------------------------

    def snapshot(self, *, now: Optional[float] = None) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_locked(now=now)

    def _snapshot_locked(self, *, now: Optional[float]) -> dict[str, Any]:
        now = self._clock(now)
        self._roll(now)
        budgeted = sum(self._counts.get(outcome, 0) for outcome in BUDGETED_OUTCOMES)
        degraded = budgeted >= self.policy.malformed_budget or self._dropped_samples > 0
        return {
            "policy_version": POLICY_VERSION,
            "window_seconds": self.policy.window_seconds,
            "window_started_at": self._window_started_at,
            "malformed_budget": self.policy.malformed_budget,
            "budget_spent": budgeted,
            "budget_remaining": max(0, self.policy.malformed_budget - budgeted),
            "counts": {outcome: self._counts.get(outcome, 0) for outcome in sorted(OUTCOMES)},
            "total": sum(self._counts.values()),
            "degraded": degraded,
            "truncated": self._dropped_samples > 0,
            "dropped_samples": self._dropped_samples,
            # Deep enough that a caller cannot mutate the guard's own window through a report.
            "forensics": [{**sample, "detail": dict(sample["detail"])} for sample in self._samples],
            "retry_after_seconds": self.retry_after_seconds(now=now) if budgeted >= self.policy.malformed_budget else 0,
        }

    def as_json(self, *, now: Optional[float] = None) -> str:
        return json.dumps(self.snapshot(now=now), sort_keys=True, allow_nan=False)
