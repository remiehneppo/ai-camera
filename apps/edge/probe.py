"""Synthetic probe runner: walk decode -> inference -> journal -> delivery (Ticket #40).

The probe is a health signal, not an event producer. It walks the four stages the pipeline
must keep progressing through, checkpoints each one in the domain ledger, and returns an
operational report whose faults carry their own metric/window/threshold/owner/runbook/
recovery. It holds no outbox, incident engine, or transport reference, so a failing probe
can only surface a fault: there is no code path here that could turn a probe into an
incident or a notification.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Optional
from uuid import uuid4

from domain.probe_contract import OPERATIONAL_FAULT_TAXONOMY, POLICY_VERSION, STAGES, ProbeLedger

__all__ = ["SyntheticProbe"]


class SyntheticProbe:
    """One probe run over injected stage callables."""

    def __init__(
        self,
        ledger: ProbeLedger,
        stages: Mapping[str, Callable[[], Any]],
        *,
        now: Callable[[], float] = time.time,
        reporter: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        missing = [stage for stage in STAGES if stage not in stages]
        if missing:
            raise ValueError("probe requires every stage: " + ", ".join(missing))
        unknown = [stage for stage in stages if stage not in STAGES]
        if unknown:
            raise ValueError("probe stage is not on the allowlist: " + ", ".join(sorted(unknown)))
        for stage in STAGES:
            if not callable(stages[stage]):
                raise ValueError("probe stage must be callable: " + stage)
        self.ledger = ledger
        self.stages = dict(stages)
        self._now = now
        self.reporter = reporter

    def run(self, correlation_id: Optional[str] = None) -> dict[str, Any]:
        """Walk every stage once; stop at the first stage that fails."""
        correlation = correlation_id or uuid4().hex
        results: list[dict[str, Any]] = []
        stopped_at: Optional[str] = None
        started = float(self._now())
        for stage in STAGES:
            stage_started = float(self._now())
            try:
                self.stages[stage]()
            except Exception as error:
                stopped_at = stage
                results.append(
                    {
                        "stage": stage,
                        "outcome": "failed",
                        "duration_ms": round((float(self._now()) - stage_started) * 1000, 3),
                        # Reason is typed, never the message: a probe report must not leak payload.
                        "reason": type(error).__name__,
                    }
                )
                break
            self.ledger.checkpoint(correlation, stage, at=stage_started)
            results.append(
                {
                    "stage": stage,
                    "outcome": "progressed",
                    "duration_ms": round((float(self._now()) - stage_started) * 1000, 3),
                }
            )
        faults = self.ledger.evaluate(now=float(self._now()))
        report: dict[str, Any] = {
            "policy_version": POLICY_VERSION,
            "taxonomy": OPERATIONAL_FAULT_TAXONOMY,
            "correlation_id": correlation,
            "ok": stopped_at is None and not faults,
            "stopped_at": stopped_at,
            "duration_ms": round((float(self._now()) - started) * 1000, 3),
            "stages": results,
            "faults": faults,
            "fault_count": len(faults),
            "degraded": bool(faults),
        }
        if self.reporter is not None:
            self.reporter(report)
        return report
