"""Ticket #40: synthetic probe contract, runner and edge-health surfacing."""

import ast
import inspect
import json
import time
import unittest

from apps.edge import probe as probe_module
from apps.edge.health import EdgeHealthMonitor
from apps.edge.probe import SyntheticProbe
from domain.probe_contract import (
    FAULT_CODES,
    FAULT_CATALOG,
    OPERATIONAL_FAULT_TAXONOMY,
    RUNBOOK_PATH,
    STAGES,
    ProbeLedger,
    ProbePolicy,
    stall_fault_code,
)
from pathlib import Path
import re

T0 = 1_000.0


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def ledger(**policy):
    clock = Clock()
    return ProbeLedger(ProbePolicy(**policy), now=clock), clock


class ContractTests(unittest.TestCase):
    def test_every_stage_has_a_documented_fault_with_runbook_and_owner(self):
        self.assertEqual(set(FAULT_CATALOG), FAULT_CODES)
        for stage in STAGES:
            code = stall_fault_code(stage)
            spec = FAULT_CATALOG[code]
            self.assertEqual(spec.stage, stage)
            self.assertEqual(spec.metric, "probe_" + stage + "_age_seconds")
            self.assertTrue(spec.owner and spec.runbook and spec.recovery)
            self.assertLessEqual(spec.threshold_seconds, spec.window_seconds)
        self.assertEqual(len(FAULT_CODES), len(STAGES), "label cardinality is bounded by the stage enum")

    def test_fresh_ledger_reports_every_stage_as_never_progressed(self):
        l, clock = ledger()
        faults = l.evaluate(now=clock.now)
        self.assertEqual([fault["stage"] for fault in faults], list(STAGES))
        first = faults[0]
        self.assertEqual(first["taxonomy"], OPERATIONAL_FAULT_TAXONOMY)
        self.assertIsNone(first["observed"]["last_progress_at"])
        self.assertEqual(first["observed"]["checkpoints"], 0)
        for key in ("code", "metric", "window_seconds", "threshold_seconds", "owner", "runbook", "recovery"):
            self.assertIn(key, first)

    def test_progress_clears_the_fault_for_that_stage_only(self):
        l, clock = ledger()
        for stage in STAGES:
            l.checkpoint("probe-1", stage, at=clock.now)
        self.assertEqual(l.evaluate(now=clock.now), [])
        snapshot = l.snapshot(now=clock.now)
        self.assertEqual((snapshot["fault_count"], snapshot["degraded"]), (0, False))
        self.assertEqual(snapshot["stages"]["decode"]["checkpoints"], 1)
        self.assertGreaterEqual(snapshot["stages"]["decode"]["age_seconds"], 0.0)

    def test_stale_stage_faults_after_its_budget(self):
        l, clock = ledger(stage_budgets={"delivery": 10.0, "decode": 300.0, "inference": 300.0, "journal": 300.0})
        for stage in STAGES:
            l.checkpoint("probe-1", stage, at=clock.now)
        clock.now = T0 + 50
        faults = l.evaluate(now=clock.now)
        self.assertEqual([fault["stage"] for fault in faults], ["delivery"])
        self.assertEqual(faults[0]["budget_seconds"], 10.0)
        self.assertAlmostEqual(faults[0]["observed"]["age_seconds"], 50.0)

    def test_correlations_are_bounded_and_reset_clears_progress(self):
        l, clock = ledger(sample_correlations=2)
        for correlation in ("p1", "p2", "p3"):
            l.checkpoint(correlation, "decode", at=clock.now)
        self.assertEqual(l.snapshot(now=clock.now)["correlations"], ["p2", "p3"])
        l.reset()
        self.assertEqual(l.snapshot(now=clock.now)["correlations"], [])
        self.assertEqual(len(l.evaluate(now=clock.now)), len(STAGES))

    def test_invalid_inputs_are_refused(self):
        l, clock = ledger()
        with self.assertRaises(ValueError):
            l.checkpoint("p1", "transcode", at=clock.now)
        with self.assertRaises(ValueError):
            l.checkpoint("../etc/passwd", "decode", at=clock.now)
        for policy in ({"stage_budgets": {"transcode": 5}}, {"stage_budgets": {"decode": -1}},
                       {"window_seconds": 0}, {"sample_correlations": -1}):
            with self.assertRaises(ValueError):
                ProbePolicy(**policy)
        with self.assertRaises(ValueError):
            from domain.probe_contract import FaultSpec
            FaultSpec(code="x", stage="decode", metric="m", window_seconds=10, threshold_seconds=20,
                      owner="o", runbook="r", recovery="c")

    def test_backwards_clock_never_reports_a_negative_age(self):
        l, clock = ledger()
        for stage in STAGES:
            l.checkpoint("p1", stage, at=clock.now)
        snapshot = l.snapshot(now=clock.now - 1_000)
        self.assertEqual(snapshot["stages"]["decode"]["age_seconds"], 0.0)
        self.assertEqual(snapshot["fault_count"], 0, "a backwards clock must not invent a stall")
        self.assertNotIn("-1000", json.dumps(snapshot))

    def test_policy_mapping_is_frozen_against_later_caller_mutation(self):
        budgets = {"decode": 1.0}
        policy = ProbePolicy(stage_budgets=budgets)
        budgets["decode"] = 999.0
        self.assertEqual(policy.budget_for("decode"), 1.0)
        with self.assertRaises(TypeError):
            policy.stage_budgets["decode"] = 5.0  # type: ignore[index]

    def test_every_fault_runbook_anchor_exists_in_the_repo(self):
        path, _, anchor = RUNBOOK_PATH.partition("#")
        self.assertTrue(Path(path).is_file(), RUNBOOK_PATH)
        headings = [
            line.lstrip("#").strip() for line in Path(path).read_text().splitlines() if line.startswith("#")
        ]
        slugs = {
            re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-") for heading in headings
        }
        self.assertIn(anchor, slugs, "the runbook anchor must resolve to a real heading")
        for spec in FAULT_CATALOG.values():
            self.assertEqual(spec.runbook, RUNBOOK_PATH)

    def test_snapshot_is_json_serialisable(self):
        l, clock = ledger()
        payload = json.loads(json.dumps(l.snapshot(now=clock.now)))
        self.assertEqual(payload["policy_version"], "synthetic-probe-v1")
        self.assertEqual(payload["taxonomy"], OPERATIONAL_FAULT_TAXONOMY)


class RunnerTests(unittest.TestCase):
    def probe(self, calls, ledger_obj=None):
        clock = Clock()
        l = ledger_obj or ProbeLedger(ProbePolicy(), now=clock)
        return SyntheticProbe(l, calls, now=clock), clock, l

    def test_successful_run_progresses_every_stage(self):
        executed = []
        probe, clock, _ = self.probe({stage: (lambda s=stage: executed.append(s)) for stage in STAGES})
        report = probe.run("probe-1")
        self.assertEqual(executed, list(STAGES))
        self.assertTrue(report["ok"])
        self.assertIsNone(report["stopped_at"])
        self.assertEqual([stage["outcome"] for stage in report["stages"]], ["progressed"] * 4)
        self.assertEqual(report["fault_count"], 0)
        self.assertEqual(report["taxonomy"], OPERATIONAL_FAULT_TAXONOMY)

    def test_failing_stage_stops_the_probe_and_reports_only_the_type(self):
        executed = []

        def boom():
            raise RuntimeError("secret payload /etc/shadow")

        calls = {
            "decode": lambda: executed.append("decode"),
            "inference": boom,
            "journal": lambda: executed.append("journal"),
            "delivery": lambda: executed.append("delivery"),
        }
        probe, clock, _ = self.probe(calls)
        report = probe.run("probe-2")
        self.assertEqual(executed, ["decode"])
        self.assertEqual(report["stopped_at"], "inference")
        self.assertFalse(report["ok"])
        self.assertTrue(report["degraded"])
        self.assertEqual(report["stages"][-1]["reason"], "RuntimeError")
        self.assertIn(stall_fault_code("inference"), [fault["code"] for fault in report["faults"]])
        self.assertNotIn("secret payload", json.dumps(report))
        self.assertNotIn("/etc/shadow", json.dumps(report))

    def test_probe_requires_exactly_the_allowlisted_stages(self):
        clock = Clock()
        l = ProbeLedger(ProbePolicy(), now=clock)
        with self.assertRaises(ValueError):
            SyntheticProbe(l, {"decode": lambda: None}, now=clock)
        with self.assertRaises(ValueError):
            SyntheticProbe(l, {**{stage: (lambda: None) for stage in STAGES}, "transcode": lambda: None}, now=clock)
        with self.assertRaises(ValueError):
            SyntheticProbe(l, {**{stage: (lambda: None) for stage in STAGES}, "decode": "not-callable"}, now=clock)

    def test_report_is_operational_and_never_an_event(self):
        probe, clock, _ = self.probe({stage: (lambda: None) for stage in STAGES})
        report = probe.run("probe-3")
        for forbidden in ("payload", "event_id", "revision", "message_id", "taxonomy_business"):
            self.assertNotIn(forbidden, report)
        self.assertEqual(report["taxonomy"], OPERATIONAL_FAULT_TAXONOMY)
        imported: set[str] = set()
        for node in ast.walk(ast.parse(inspect.getsource(probe_module))):
            if isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").lower())
            elif isinstance(node, ast.Import):
                imported.update(alias.name.lower() for alias in node.names)
        self.assertEqual(
            imported, {"__future__", "time", "typing", "uuid", "domain.probe_contract"},
            "the probe must not gain an outbox/incident/transport import",
        )

    def test_reporter_receives_the_report_for_health_surfacing(self):
        seen = []
        clock = Clock()
        l = ProbeLedger(ProbePolicy(), now=clock)
        probe = SyntheticProbe(l, {stage: (lambda: None) for stage in STAGES}, now=clock, reporter=seen.append)
        report = probe.run("probe-4")
        self.assertEqual(seen, [report])


class HealthSurfacingTests(unittest.TestCase):
    def healthy(self):
        monitor = EdgeHealthMonitor()
        monitor.mark_started()
        monitor.record_frame_received(receive_time=time.time(), capture_time=time.time(), clock_mapping_valid=True)
        return monitor

    def test_probe_faults_degrade_health_without_an_incident(self):
        monitor = self.healthy()
        self.assertEqual(monitor.get_health_snapshot()["status"], "healthy")
        clock = Clock()

        def stalled_journal():
            raise TimeoutError("journal writer deadlocked")

        calls = {stage: (lambda: None) for stage in STAGES}
        calls["journal"] = stalled_journal
        report = SyntheticProbe(ProbeLedger(ProbePolicy(), now=clock), calls, now=clock).run("p")
        self.assertEqual(report["stopped_at"], "journal")
        monitor.record_probe_faults(report["faults"])
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["metrics"]["probe_fault_count"], len(report["faults"]))
        self.assertIn(stall_fault_code("journal"), snapshot["all_reasons"])
        self.assertIn(stall_fault_code("journal"), snapshot["metrics"]["operational_faults"])
        self.assertIn(snapshot["status"], ("degraded", "unavailable"))

    def test_absent_probe_faults_leave_health_unchanged(self):
        monitor = self.healthy()
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "healthy")
        self.assertEqual(snapshot["metrics"]["probe_fault_count"], 0)
        self.assertEqual(snapshot["metrics"]["probe_faults"], [])


if __name__ == "__main__":
    unittest.main()
