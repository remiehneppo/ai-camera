"""Synthetic probe contract: progress across decode/inference/journal/delivery (Ticket #40).

Pure domain module: no I/O, no framework imports. A probe is an operational health signal,
never a business event: its stages and fault codes are a closed enumeration (so metric label
cardinality is bounded by construction), its report carries a runbook/owner/recovery per
fault, and it has no path to the incident or notification pipeline. A stage that stops
progressing -- or never progresses at all -- is reported as an operational fault with the
observed age and the configured threshold, so "fault route does not rescue" is structural
rather than a policy someone has to remember.
"""

from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Final, FrozenSet, Mapping, Optional

__all__ = [
    "FAULT_CATALOG",
    "FAULT_CODES",
    "FaultSpec",
    "OPERATIONAL_FAULT_TAXONOMY",
    "PIN_GAP_FAULT_CODE",
    "POLICY_VERSION",
    "PinGapDetected",
    "ProbeLedger",
    "ProbePolicy",
    "RUNBOOK_PATH",
    "STAGES",
    "pin_gap_fault_code",
    "stall_fault_code",
]

#: Stages the probe walks in order; a closed set keeps metric labels bounded.
STAGES: Final[tuple[str, ...]] = ("decode", "inference", "journal", "delivery")

#: Probe findings are operational, never a business taxonomy that could open an incident.
OPERATIONAL_FAULT_TAXONOMY: Final[str] = "operational_fault"

POLICY_VERSION: Final[str] = "synthetic-probe-v1"

#: Where an operator finds the runbook for a probe fault; a test keeps this anchor real.
RUNBOOK_PATH: Final[str] = "docs/architecture/contracts.md#synthetic-probe-operational-fault"

_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


@dataclass(frozen=True)
class FaultSpec:
    """Everything an operator needs for one fault without leaving the report."""

    code: str
    stage: str
    metric: str
    window_seconds: float
    threshold_seconds: float
    owner: str
    runbook: str
    recovery: str
    severity: str = "degraded"

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError("fault stage must be a probe stage")
        for name in ("window_seconds", "threshold_seconds"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(name + " must be finite and positive")
        if self.threshold_seconds > self.window_seconds:
            raise ValueError("threshold_seconds must not exceed window_seconds")
        for name in ("code", "metric", "owner", "runbook", "recovery"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(name + " must be a non-empty string")


def stall_fault_code(stage: str) -> str:
    return "probe_" + stage + "_stalled"


PIN_GAP_FAULT_CODE: Final[str] = "probe_journal_pin_gap"


def pin_gap_fault_code(stage: str = "journal") -> str:
    return "probe_" + stage + "_pin_gap"


class PinGapDetected(RuntimeError):
    """Raised when journal or delivery detects missing or incomplete pin coverage."""

    def __init__(self, message: str = "pin gap detected", *, gap_seconds: float = 0.0) -> None:
        super().__init__(message)
        self.gap_seconds = max(0.0, float(gap_seconds))


#: One documented fault per stage: metric, window, threshold, owner, runbook and recovery.
FAULT_CATALOG: Final[dict[str, FaultSpec]] = {
    **{
        stall_fault_code(stage): FaultSpec(
            code=stall_fault_code(stage),
            stage=stage,
            metric="probe_" + stage + "_age_seconds",
            window_seconds=300.0,
            threshold_seconds=120.0,
            owner="edge-ops",
            runbook=RUNBOOK_PATH,
            recovery="restart the " + stage + " stage, then re-run the synthetic probe",
        )
        for stage in STAGES
    },
    PIN_GAP_FAULT_CODE: FaultSpec(
        code=PIN_GAP_FAULT_CODE,
        stage="journal",
        metric="probe_journal_pin_gap_seconds",
        window_seconds=300.0,
        threshold_seconds=120.0,
        owner="edge-ops",
        runbook=RUNBOOK_PATH,
        recovery="verify recorder ring coverage and outbox before restarting journal stage",
        severity="degraded",
    ),
    pin_gap_fault_code("delivery"): FaultSpec(
        code=pin_gap_fault_code("delivery"),
        stage="delivery",
        metric="probe_delivery_pin_gap_seconds",
        window_seconds=300.0,
        threshold_seconds=120.0,
        owner="edge-ops",
        runbook=RUNBOOK_PATH,
        recovery="verify recorder ring coverage and outbox before restarting delivery stage",
        severity="degraded",
    ),
}

FAULT_CODES: Final[FrozenSet[str]] = frozenset(FAULT_CATALOG)

DEFAULT_STAGE_BUDGET_SECONDS: Final[float] = 120.0


@dataclass(frozen=True)
class ProbePolicy:
    """Per-stage stall threshold; the lab default is 120s, not a signed SLA."""

    stage_budgets: Mapping[str, float] = field(default_factory=dict)
    window_seconds: float = 300.0
    sample_correlations: int = 8

    def __post_init__(self) -> None:
        unknown = set(self.stage_budgets) - set(STAGES)
        if unknown:
            raise ValueError("stage_budgets may only name probe stages")
        for stage, budget in self.stage_budgets.items():
            if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0:
                raise ValueError("stage budget must be finite and positive: " + stage)
        if type(self.window_seconds) not in (int, float) or not math.isfinite(self.window_seconds) or self.window_seconds <= 0:
            raise ValueError("window_seconds must be finite and positive")
        if type(self.sample_correlations) is not int or self.sample_correlations < 0:
            raise ValueError("sample_correlations must be a non-negative integer")
        # Copy the caller's mapping: a frozen policy must not change when they reuse the dict.
        object.__setattr__(self, "stage_budgets", MappingProxyType(dict(self.stage_budgets)))

    def budget_for(self, stage: str) -> float:
        return float(self.stage_budgets.get(stage, DEFAULT_STAGE_BUDGET_SECONDS))


class ProbeLedger:
    """Bounded per-stage progress tracking for one device/process."""

    def __init__(self, policy: Optional[ProbePolicy] = None, *, now: Callable[[], float] = time.time) -> None:
        self.policy = policy or ProbePolicy()
        self._now = now
        self._lock = threading.RLock()
        self._last_progress: dict[str, float] = {}
        self._checkpoints: dict[str, int] = {stage: 0 for stage in STAGES}
        self._correlations: list[str] = []
        self._pin_gaps: dict[str, dict[str, Any]] = {}
        self._started_at = float(self._now())

    def _clock(self, now: Optional[float]) -> float:
        return float(self._now()) if now is None else float(now)

    def checkpoint(self, correlation_id: str, stage: str, *, at: Optional[float] = None) -> float:
        """Record that one stage did progress; returns the timestamp used."""
        if stage not in STAGES:
            raise ValueError("stage is not a probe stage")
        if not isinstance(correlation_id, str) or not _IDENTIFIER.match(correlation_id):
            raise ValueError("correlation_id must be a safe identifier")
        with self._lock:
            stamp = self._clock(at)
            self._last_progress[stage] = stamp
            self._checkpoints[stage] += 1
            if self.policy.sample_correlations:
                self._correlations.append(correlation_id)
                if len(self._correlations) > self.policy.sample_correlations:
                    del self._correlations[0]
            return stamp

    def last_progress(self, stage: str) -> Optional[float]:
        with self._lock:
            return self._last_progress.get(stage)

    def record_pin_gap(
        self,
        stage: str = "journal",
        *,
        gap_seconds: float = 0.0,
        at: Optional[float] = None,
    ) -> None:
        """Record that a stage observed missing or incomplete pin coverage."""
        if pin_gap_fault_code(stage) not in FAULT_CATALOG:
            raise ValueError(f"pin gap fault not supported for stage '{stage}'; only stages with cataloged pin gap faults are allowed")
        with self._lock:
            self._pin_gaps[stage] = {
                "detected_at": self._clock(at),
                "gap_seconds": max(0.0, float(gap_seconds)),
            }

    def clear_pin_gap(self, stage: str = "journal") -> None:
        """Clear recorded pin gap for a stage after healthy progress."""
        with self._lock:
            self._pin_gaps.pop(stage, None)

    def pin_gaps(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._pin_gaps)

    def evaluate(self, *, now: Optional[float] = None) -> list[dict[str, Any]]:
        """Faults for stages that never progressed or stopped progressing past their budget, plus pin gaps."""
        stamp = self._clock(now)
        faults: list[dict[str, Any]] = []
        with self._lock:
            for stage in STAGES:
                spec = FAULT_CATALOG[stall_fault_code(stage)]
                last = self._last_progress.get(stage)
                budget = self.policy.budget_for(stage)
                # A clock that jumped backwards cannot measure staleness; report 0, never a negative age.
                age = None if last is None else max(0.0, stamp - last)
                if last is not None and age is not None and age <= budget:
                    continue
                faults.append(
                    {
                        "code": spec.code,
                        "taxonomy": OPERATIONAL_FAULT_TAXONOMY,
                        "stage": stage,
                        "metric": spec.metric,
                        "window_seconds": spec.window_seconds,
                        "threshold_seconds": spec.threshold_seconds,
                        "budget_seconds": budget,
                        "observed": {
                            "last_progress_at": last,
                            "age_seconds": age,
                            "checkpoints": self._checkpoints.get(stage, 0),
                        },
                        "owner": spec.owner,
                        "runbook": spec.runbook,
                        "recovery": spec.recovery,
                        "severity": spec.severity,
                    }
                )
            for stage, gap_info in self._pin_gaps.items():
                code = pin_gap_fault_code(stage)
                if code in FAULT_CATALOG:
                    spec = FAULT_CATALOG[code]
                    faults.append(
                        {
                            "code": spec.code,
                            "taxonomy": OPERATIONAL_FAULT_TAXONOMY,
                            "stage": stage,
                            "metric": spec.metric,
                            "window_seconds": spec.window_seconds,
                            "threshold_seconds": spec.threshold_seconds,
                            "budget_seconds": self.policy.budget_for(stage),
                            "observed": {
                                "last_progress_at": self._last_progress.get(stage),
                                "gap_seconds": gap_info["gap_seconds"],
                                "detected_at": gap_info["detected_at"],
                                "checkpoints": self._checkpoints.get(stage, 0),
                            },
                            "owner": spec.owner,
                            "runbook": spec.runbook,
                            "recovery": spec.recovery,
                            "severity": spec.severity,
                        }
                    )
        return faults

    def snapshot(self, *, now: Optional[float] = None) -> dict[str, Any]:
        stamp = self._clock(now)
        faults = self.evaluate(now=stamp)
        with self._lock:
            stages = {
                stage: {
                    "last_progress_at": self._last_progress.get(stage),
                    "age_seconds": None if self._last_progress.get(stage) is None
                    else max(0.0, stamp - float(self._last_progress[stage])),
                    "budget_seconds": self.policy.budget_for(stage),
                    "checkpoints": self._checkpoints.get(stage, 0),
                }
                for stage in STAGES
            }
            correlations = list(self._correlations)
            pin_gaps = dict(self._pin_gaps)
        return {
            "policy_version": POLICY_VERSION,
            "taxonomy": OPERATIONAL_FAULT_TAXONOMY,
            "started_at": self._started_at,
            "evaluated_at": stamp,
            "stages": stages,
            "faults": faults,
            "fault_count": len(faults),
            "degraded": bool(faults),
            "correlations": correlations,
            "pin_gaps": pin_gaps,
        }

    def reset(self) -> None:
        """Clear progress after a recovery step, so the next probe starts from a clean window."""
        with self._lock:
            self._last_progress.clear()
            self._checkpoints = {stage: 0 for stage in STAGES}
            self._correlations.clear()
            self._pin_gaps.clear()
            self._started_at = float(self._now())