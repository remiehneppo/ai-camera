"""Synthetic probe runner: walk decode -> inference -> journal -> delivery (Ticket #40).

The probe is a health signal, not an event producer. It walks the four stages the pipeline
must keep progressing through, checkpoints each one in the domain ledger, and returns an
operational report whose faults carry their own metric/window/threshold/owner/runbook/
recovery. It holds no outbox, incident engine, or transport reference, so a failing probe
can only surface a fault: there is no code path here that could turn a probe into an
incident or a notification.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping, Optional
from uuid import uuid4

from domain.probe_contract import (
    OPERATIONAL_FAULT_TAXONOMY,
    POLICY_VERSION,
    STAGES,
    PinGapDetected,
    ProbeLedger,
    pin_gap_fault_code,
)

__all__ = ["PinGapDetected", "ProbeScheduler", "SyntheticProbe", "make_journal_pin_stage"]


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
            except PinGapDetected as error:
                stopped_at = stage
                self.ledger.record_pin_gap(
                    stage=stage,
                    gap_seconds=error.gap_seconds,
                    at=stage_started,
                )
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
            self.ledger.clear_pin_gap(stage)
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


def make_journal_pin_stage(
    pin_verifier: Optional[Callable[[], Any]] = None,
    *,
    inject_gap: bool = False,
    gap_seconds: float = 0.0,
) -> Callable[[], None]:
    """Helper/stage factory to detect or inject a pin-gap fault in journal or delivery stage."""
    def stage_fn() -> None:
        if inject_gap:
            raise PinGapDetected("injected pin gap fault", gap_seconds=gap_seconds)
        if pin_verifier is not None:
            res = pin_verifier()
            if res is False:
                raise PinGapDetected("pin verifier returned False", gap_seconds=gap_seconds)
            if isinstance(res, dict):
                comp = res.get("completeness")
                if comp in ("missing", "partial"):
                    detected_gap = float(res.get("gap_seconds", gap_seconds))
                    raise PinGapDetected(f"pin coverage {comp}", gap_seconds=detected_gap)
    return stage_fn


class ProbeScheduler:
    """Bounded, periodic or tick-driven runner for SyntheticProbe."""

    def __init__(
        self,
        probe: SyntheticProbe,
        *,
        interval_seconds: float = 30.0,
        now: Callable[[], float] = time.time,
        reporter: Optional[Callable[[dict[str, Any]], None]] = None,
        run_immediately: bool = True,
    ) -> None:
        if type(interval_seconds) not in (int, float) or not (interval_seconds > 0):
            raise ValueError("interval_seconds must be positive and finite")
        self.probe = probe
        self.interval_seconds = float(interval_seconds)
        self._now = now
        self.reporter = reporter
        self._run_immediately = run_immediately
        self._lock = threading.RLock()
        self._last_run_at: Optional[float] = None
        self._last_report: Optional[dict[str, Any]] = None
        self._run_count: int = 0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def last_report(self) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._last_report

    @property
    def last_run_at(self) -> Optional[float]:
        with self._lock:
            return self._last_run_at

    @property
    def run_count(self) -> int:
        with self._lock:
            return self._run_count

    def is_alive(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def tick(self, now: Optional[float] = None, *, correlation_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Run the probe if the interval has elapsed since last run, or if never run."""
        current = float(self._now()) if now is None else float(now)
        with self._lock:
            if self._last_run_at is not None:
                elapsed = current - self._last_run_at
                if elapsed < self.interval_seconds:
                    return None
            elif not self._run_immediately:
                self._last_run_at = current
                return None

            report = self.probe.run(correlation_id=correlation_id)
            self._last_run_at = current
            self._last_report = report
            self._run_count += 1
            if self.reporter is not None:
                self.reporter(report)
            return report

    def start(self) -> "ProbeScheduler":
        """Start the background runner thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="probe-scheduler",
            )
            self._thread.start()
            return self

    def _run_loop(self) -> None:
        self.tick()
        while not self._stop_event.is_set():
            sleep_step = min(0.2, self.interval_seconds)
            if self._stop_event.wait(timeout=sleep_step):
                break
            self.tick()

    def stop(self, timeout_seconds: float = 3.0) -> None:
        """Stop background runner thread and wait for it to join."""
        self._stop_event.set()
        thread: Optional[threading.Thread] = None
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout_seconds)))
        with self._lock:
            self._thread = None
