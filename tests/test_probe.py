"""Ticket #40: synthetic probe contract, runner and edge-health surfacing."""

import ast
import inspect
import json
import time
import unittest

from apps.edge import probe as probe_module
from apps.edge.health import EdgeHealthMonitor
from apps.edge.probe import (
    PinGapDetected,
    ProbeScheduler,
    SyntheticProbe,
    make_journal_pin_stage,
)
from domain.probe_contract import (
    FAULT_CODES,
    FAULT_CATALOG,
    OPERATIONAL_FAULT_TAXONOMY,
    PIN_GAP_FAULT_CODE,
    RUNBOOK_PATH,
    STAGES,
    ProbeLedger,
    ProbePolicy,
    pin_gap_fault_code,
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
        self.assertIn(PIN_GAP_FAULT_CODE, FAULT_CODES)
        pin_spec = FAULT_CATALOG[PIN_GAP_FAULT_CODE]
        self.assertEqual(pin_spec.stage, "journal")
        self.assertEqual(pin_spec.metric, "probe_journal_pin_gap_seconds")
        self.assertTrue(pin_spec.owner and pin_spec.runbook and pin_spec.recovery)
        self.assertLessEqual(pin_spec.threshold_seconds, pin_spec.window_seconds)
        self.assertEqual(len(FAULT_CODES), len(STAGES) + 2, "label cardinality is bounded by the stage enum and pin gaps")

    def test_pin_gap_ledger_record_and_reset(self):
        l, clock = ledger()
        for stage in STAGES:
            l.checkpoint("probe-1", stage, at=clock.now)
        self.assertEqual(l.evaluate(now=clock.now), [])

        # Record a pin gap for journal
        l.record_pin_gap("journal", gap_seconds=15.0, at=clock.now)
        faults = l.evaluate(now=clock.now)
        self.assertEqual([f["code"] for f in faults], [PIN_GAP_FAULT_CODE])
        fault = faults[0]
        self.assertEqual(fault["stage"], "journal")
        self.assertEqual(fault["metric"], "probe_journal_pin_gap_seconds")
        self.assertEqual(fault["observed"]["gap_seconds"], 15.0)
        self.assertEqual(fault["severity"], "degraded")
        self.assertEqual(fault["owner"], "edge-ops")
        self.assertEqual(fault["runbook"], RUNBOOK_PATH)

        snapshot = l.snapshot(now=clock.now)
        self.assertEqual(snapshot["fault_count"], 1)
        self.assertTrue(snapshot["degraded"])
        self.assertIn("journal", snapshot["pin_gaps"])

        # Clearing pin gap restores healthy state
        l.clear_pin_gap("journal")
        self.assertEqual(l.evaluate(now=clock.now), [])

        # Test reset clears pin gaps
        l.record_pin_gap("journal", gap_seconds=10.0, at=clock.now)
        self.assertEqual(len(l.evaluate(now=clock.now)), 1)
        l.reset()
        self.assertEqual(l.pin_gaps(), {})
        self.assertEqual(len(l.evaluate(now=clock.now)), len(STAGES))

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
            imported, {"__future__", "time", "typing", "uuid", "domain.probe_contract", "threading"},
            "the probe must not gain an outbox/incident/transport import",
        )

    def test_pin_gap_injection_stops_probe_and_records_typed_reason(self):
        executed = []
        journal_stage = make_journal_pin_stage(inject_gap=True, gap_seconds=8.0)
        calls = {
            "decode": lambda: executed.append("decode"),
            "inference": lambda: executed.append("inference"),
            "journal": journal_stage,
            "delivery": lambda: executed.append("delivery"),
        }
        probe, clock, l = self.probe(calls)
        report = probe.run("probe-pin-gap")
        self.assertEqual(executed, ["decode", "inference"])
        self.assertEqual(report["stopped_at"], "journal")
        self.assertFalse(report["ok"])
        self.assertTrue(report["degraded"])
        self.assertEqual(report["stages"][-1]["reason"], "PinGapDetected")
        fault_codes = [f["code"] for f in report["faults"]]
        self.assertIn(PIN_GAP_FAULT_CODE, fault_codes)

    def test_pin_gap_verifier_detects_missing_coverage_and_redacts_secrets(self):
        def secret_pin_check():
            raise PinGapDetected("secret /etc/shadow token=supersecret", gap_seconds=12.0)

        calls = {
            "decode": lambda: None,
            "inference": lambda: None,
            "journal": secret_pin_check,
            "delivery": lambda: None,
        }
        probe, clock, _ = self.probe(calls)
        report = probe.run("probe-secret")
        self.assertEqual(report["stages"][-1]["reason"], "PinGapDetected")
        report_json = json.dumps(report)
        self.assertNotIn("/etc/shadow", report_json)
        self.assertNotIn("supersecret", report_json)

    def test_pin_gap_recovery_clears_fault_on_next_probe_run(self):
        gap_active = True

        def journal_stage():
            if gap_active:
                raise PinGapDetected("gap", gap_seconds=5.0)

        calls = {
            "decode": lambda: None,
            "inference": lambda: None,
            "journal": journal_stage,
            "delivery": lambda: None,
        }
        probe, clock, ledger_obj = self.probe(calls)
        report1 = probe.run("p1")
        self.assertFalse(report1["ok"])
        self.assertIn(PIN_GAP_FAULT_CODE, [f["code"] for f in report1["faults"]])

        # Recovery: gap is fixed
        gap_active = False
        report2 = probe.run("p2")
        self.assertTrue(report2["ok"])
        self.assertNotIn(PIN_GAP_FAULT_CODE, [f["code"] for f in report2["faults"]])
        self.assertEqual(report2["fault_count"], 0)

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

    def test_pin_gap_fault_degrades_health_without_incident(self):
        monitor = self.healthy()
        self.assertEqual(monitor.get_health_snapshot()["status"], "healthy")
        clock = Clock()
        calls = {
            "decode": lambda: None,
            "inference": lambda: None,
            "journal": make_journal_pin_stage(inject_gap=True, gap_seconds=15.0),
            "delivery": lambda: None,
        }
        l = ProbeLedger(ProbePolicy(), now=clock)
        probe = SyntheticProbe(l, calls, now=clock)
        report = probe.run("probe-pg")
        self.assertEqual(report["stopped_at"], "journal")
        monitor.record_probe_faults(report["faults"])
        snapshot = monitor.get_health_snapshot()
        self.assertEqual(snapshot["status"], "degraded")
        self.assertIn(PIN_GAP_FAULT_CODE, snapshot["all_reasons"])
        self.assertIn(PIN_GAP_FAULT_CODE, snapshot["metrics"]["operational_faults"])
        self.assertGreaterEqual(snapshot["metrics"]["probe_fault_count"], 1)

        from domain.event_contract import EventValidationError, validate_event
        with self.assertRaises(EventValidationError):
            validate_event(report)


class SchedulerTests(unittest.TestCase):
    def test_probe_scheduler_deterministic_ticks_and_reporter(self):
        clock = Clock(T0)
        calls = {stage: (lambda: None) for stage in STAGES}
        l = ProbeLedger(ProbePolicy(), now=clock)
        probe = SyntheticProbe(l, calls, now=clock)
        reports = []
        scheduler = ProbeScheduler(probe, interval_seconds=10.0, now=clock, reporter=reports.append)

        # First tick runs immediately
        r1 = scheduler.tick()
        self.assertIsNotNone(r1)
        self.assertEqual(scheduler.run_count, 1)
        self.assertEqual(scheduler.last_run_at, T0)
        self.assertEqual(len(reports), 1)

        # Advance clock by 5s (< 10s interval): should not run
        clock.now = T0 + 5.0
        r2 = scheduler.tick()
        self.assertIsNone(r2)
        self.assertEqual(scheduler.run_count, 1)
        self.assertEqual(len(reports), 1)

        # Advance clock to T0 + 10s (>= 10s interval): should run
        clock.now = T0 + 10.0
        r3 = scheduler.tick()
        self.assertIsNotNone(r3)
        self.assertEqual(scheduler.run_count, 2)
        self.assertEqual(scheduler.last_run_at, T0 + 10.0)
        self.assertEqual(len(reports), 2)

    def test_probe_scheduler_background_thread_lifecycle(self):
        clock = time.time
        calls = {stage: (lambda: None) for stage in STAGES}
        l = ProbeLedger(ProbePolicy(), now=clock)
        probe = SyntheticProbe(l, calls, now=clock)
        scheduler = ProbeScheduler(probe, interval_seconds=0.05, now=clock)
        self.assertFalse(scheduler.is_alive())

        scheduler.start()
        self.assertTrue(scheduler.is_alive())

        deadline = time.time() + 1.0
        while scheduler.run_count < 2 and time.time() < deadline:
            time.sleep(0.01)

        self.assertGreaterEqual(scheduler.run_count, 2)
        scheduler.stop(timeout_seconds=2.0)
        self.assertFalse(scheduler.is_alive())


class RuntimeIntegrationTests(unittest.TestCase):
    def test_edge_runtime_probe_scheduler_hook_and_status(self):
        import shutil
        import subprocess
        import tempfile
        from apps.edge.runtime import EdgeRuntime

        if not (shutil.which('ffmpeg') and shutil.which('ffprobe')):
            self.skipTest("FFmpeg required")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=blue:s=32x24:r=4', '-t', '0.5', '-c:v', 'ffv1', '-g', '1',
                            str(source)], check=True, capture_output=True)

            clock = Clock(T0)
            journal_active = [lambda: None]
            calls = {
                "decode": lambda: None,
                "inference": lambda: None,
                "journal": lambda: journal_active[0](),
                "delivery": lambda: None,
            }
            l = ProbeLedger(ProbePolicy(), now=clock)
            probe = SyntheticProbe(l, calls, now=clock)
            scheduler = ProbeScheduler(probe, interval_seconds=10.0, now=clock)

            runtime = EdgeRuntime(
                source=source,
                output_dir=Path(directory) / 'ring',
                analytics_enabled=False,
                disabled_reason='test',
                segment_seconds=0.5,
                probe_scheduler=scheduler,
            )
            self.assertIs(runtime.probe_scheduler, scheduler)

            runtime.start()
            status = runtime.status()
            self.assertIn('probe', status)
            self.assertIsNotNone(status['probe'])
            self.assertFalse(status['probe']['degraded'])

            # Inject a pin gap into probe
            journal_active[0] = make_journal_pin_stage(inject_gap=True, gap_seconds=20.0)
            clock.now = T0 + 15.0
            report = runtime.tick_probe()
            self.assertIsNotNone(report)
            status = runtime.status()
            self.assertTrue(status['probe']['degraded'])
            self.assertTrue(status['probe']['degraded'])
            self.assertTrue(status['degraded'])
            self.assertIn(PIN_GAP_FAULT_CODE, [f['code'] for f in status['probe']['faults']])

            runtime.stop()
            self.assertFalse(scheduler.is_alive())


if __name__ == "__main__":
    unittest.main()