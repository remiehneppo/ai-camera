"""Ticket #28: negative audit and G2 quality regression acceptance flow.

Locks the G2 contract end to end:

- alerts-only may never be accepted as recall evidence;
- recall is a Horvitz-Thompson ratio over strata weights ``1 / p_h``, never a
  raw-count pool across strata with different inclusion probabilities;
- uncertainty is a 95% Wilson interval on the Kish effective sample size and
  small samples are flagged as insufficient;
- metrics break down per person-down branch;
- the edge negative-audit sampler is deterministic, writes a reviewable
  manifest, and never samples alert windows;
- the CLI report emits JSON/Markdown with targets, verdict and owner sign-off.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.negative_audit_report as negative_audit_report
from apps.edge.audit_sampler import AuditSamplingError, NegativeAuditSampler
from domain.quality_eval import (
    BRANCHES,
    QualityEvalError,
    SamplingPlan,
    Stratum,
    evaluate_quality_metrics,
    wilson_interval,
)

MATCHING_WINDOW = 60.0


def two_stratum_plan(min_samples: int = 30) -> SamplingPlan:
    """Day camera sampled at p=0.5 and night camera at p=0.1."""
    return SamplingPlan(
        plan_version="g2-person-down-v1",
        capability="person_down",
        site="site-a",
        min_samples=min_samples,
        strata=(
            Stratum("day", 0.5, camera_id="cam-day", time_band="day"),
            Stratum("night", 0.1, camera_id="cam-night", time_band="night"),
        ),
    )


def single_stratum_plan(probability: float = 0.5, min_samples: int = 30) -> SamplingPlan:
    return SamplingPlan(
        plan_version="g2-person-down-v1",
        capability="person_down",
        min_samples=min_samples,
        strata=(Stratum("all", probability, camera_id="cam-1"),),
    )


def sampling_plan_with_small_minimum() -> SamplingPlan:
    """Single-stratum plan whose pinned minimum sits below the default 30."""
    return SamplingPlan(
        plan_version="small-v1",
        capability="person_down",
        min_samples=5,
        strata=(Stratum("all", 0.5, camera_id="cam-1"),),
    )


def alert(camera_id="cam-day", decision="confirmed", branch="person_fall", **extra):
    record = {
        "capability": "person_down",
        "camera_id": camera_id,
        "reviewed_decision": decision,
        "branch": branch,
    }
    record.update(extra)
    return record


def negative(camera_id="cam-day", missed=0, duration=3600.0, branch="person_fall", **extra):
    record = {
        "camera_id": camera_id,
        "duration_seconds": duration,
        "missed_instances": missed,
        "branch": branch,
    }
    record.update(extra)
    return record


def g2_pass_fixture():
    """80 reviewed negatives over two strata and 60 confirmed alerts: verdict PASS."""
    alerts = [alert(camera_id="cam-day") for _ in range(60)]
    alerts.append(alert(camera_id="cam-night", decision="false_positive", branch="person_lying_persistent"))
    negatives = [negative(camera_id="cam-day") for _ in range(40)]
    negatives += [negative(camera_id="cam-night") for _ in range(40)]
    return alerts, negatives


def g2_fail_fixture():
    """Weighted recall 10/60 < 0.90 with sufficient coverage: verdict FAIL."""
    alerts = [alert(camera_id="cam-day") for _ in range(10)]
    negatives = [negative(camera_id="cam-day") for _ in range(40)]
    negatives += [negative(camera_id="cam-night", missed=1 if index < 5 else 0) for index in range(40)]
    return alerts, negatives


def run_cli(argv):
    """Run ``main()`` in-process and return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = negative_audit_report.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestAlertsOnlyForbidsRecall(unittest.TestCase):
    """G2 must never report recall from alerts alone."""

    def test_alerts_only_without_negatives_is_blocked(self):
        alerts = [alert() for _ in range(12)]
        for negatives in (None, []):
            with self.subTest(negatives=negatives):
                metrics = evaluate_quality_metrics(
                    alerts, negatives, plan=two_stratum_plan(), matching_window_seconds=MATCHING_WINDOW
                )
                self.assertEqual(metrics["verdict"], "BLOCKED")
                self.assertIn("alerts_only", metrics["blocking_gaps"])
                self.assertIn("alerts_only", metrics["verdict_reasons"])
                self.assertEqual(metrics["counts"]["negative_samples_total"], 0)
                self.assertEqual(metrics["counts"]["negative_samples_reviewed"], 0)
                # Recall is explicitly not accepted: sufficiency is refused and no
                # missed-incident denominator exists for the interval to rest on.
                self.assertFalse(metrics["sample_sufficiency"]["sufficient"])
                self.assertIn("no_reviewed_negative_samples", metrics["sample_sufficiency"]["reasons"])
                self.assertEqual(metrics["recall"]["weighted_missed_units"], 0.0)

    def test_alerts_only_recall_estimate_is_never_accepted(self):
        metrics = evaluate_quality_metrics(
            [alert() for _ in range(12)], None, plan=two_stratum_plan(), matching_window_seconds=MATCHING_WINDOW
        )
        # Any numeric estimate present is unusable evidence: the gate blocks the
        # verdict and the sufficiency block records the missing denominator.
        self.assertNotEqual(metrics["verdict"], "PASS")
        self.assertFalse(metrics["sample_sufficiency"]["sufficient"])
        self.assertEqual(metrics["sample_sufficiency"]["reviewed_negatives"], 0)
        self.assertIn("alerts_only", metrics["verdict_reasons"])

    def test_empty_review_is_blocked_with_no_recall(self):
        metrics = evaluate_quality_metrics([], None)
        self.assertEqual(metrics["verdict"], "BLOCKED")
        self.assertIsNone(metrics["recall"]["estimate"])
        self.assertIsNone(metrics["recall"]["ci_low"])
        self.assertIn("no_reviewed_data", metrics["verdict_reasons"])

    def test_pending_negative_samples_still_count_as_alerts_only(self):
        # Sampled but unreviewed windows are not a denominator.
        pending = [{"camera_id": "cam-day", "duration_seconds": 3600, "status": "pending_review"} for _ in range(10)]
        metrics = evaluate_quality_metrics(
            [alert() for _ in range(5)], pending, plan=two_stratum_plan(), matching_window_seconds=MATCHING_WINDOW
        )
        self.assertEqual(metrics["counts"]["negative_samples_pending_review"], 10)
        self.assertEqual(metrics["counts"]["negative_samples_reviewed"], 0)
        self.assertIn("alerts_only", metrics["blocking_gaps"])
        self.assertEqual(metrics["verdict"], "BLOCKED")

    def test_reviewed_negative_sample_unblocks_alerts_only(self):
        alerts, negatives = g2_pass_fixture()
        metrics = evaluate_quality_metrics(
            alerts, negatives, plan=two_stratum_plan(), matching_window_seconds=MATCHING_WINDOW
        )
        self.assertNotIn("alerts_only", metrics["blocking_gaps"])
        self.assertEqual(metrics["verdict"], "PASS")


class TestWeightedSamplingDisparity(unittest.TestCase):
    """Stratified weights ``1 / p_h`` replace raw counts across strata."""

    def setUp(self):
        self.plan = two_stratum_plan(min_samples=10)
        self.alerts = [alert(camera_id="cam-day") for _ in range(10)]
        # 10 day samples (p=0.5) and 10 night samples (p=0.1), one miss each.
        self.negatives = [negative(camera_id="cam-day") for _ in range(9)]
        self.negatives.append(negative(camera_id="cam-day", missed=1))
        self.negatives += [negative(camera_id="cam-night") for _ in range(9)]
        self.negatives.append(negative(camera_id="cam-night", missed=1))

    def test_horvitz_thompson_weights_missed_incidents(self):
        metrics = evaluate_quality_metrics(
            self.alerts, self.negatives, plan=self.plan, min_samples=10, matching_window_seconds=MATCHING_WINDOW
        )
        recall = metrics["recall"]
        self.assertAlmostEqual(recall["weighted_missed_units"], 12.0, places=9)
        self.assertAlmostEqual(recall["weighted_detected_units"], 10.0, places=9)
        self.assertAlmostEqual(recall["weighted_total_units"], 22.0, places=9)
        self.assertAlmostEqual(recall["estimate"], 10.0 / 22.0, places=9)
        # Raw bookkeeping still exposes the 2 observed misses, but they are not the estimator.
        self.assertEqual(recall["missed_units"], 2)
        self.assertEqual(metrics["counts"]["negative_positives_found"], 2)

    def test_weighted_recall_differs_from_naive_raw_count_recall(self):
        metrics = evaluate_quality_metrics(
            self.alerts, self.negatives, plan=self.plan, min_samples=10, matching_window_seconds=MATCHING_WINDOW
        )
        naive = 10.0 / (10.0 + 2.0)
        self.assertAlmostEqual(naive, 5.0 / 6.0, places=9)
        # Pooling raw counts would report 83% instead of the honest 45%.
        self.assertLess(metrics["recall"]["estimate"], naive - 0.3)
        self.assertNotAlmostEqual(metrics["recall"]["estimate"], naive, places=3)

    def test_error_probability_weights_per_stratum_hours(self):
        metrics = evaluate_quality_metrics(
            self.alerts, self.negatives, plan=self.plan, min_samples=10, matching_window_seconds=MATCHING_WINDOW
        )
        strata = {entry["stratum_id"]: entry for entry in metrics["coverage"]["strata"]}
        # 10 sampled hours at p=0.5 -> 20 hours; at p=0.1 -> 100 hours.
        self.assertAlmostEqual(strata["day"]["raw_hours"], 10.0, places=9)
        self.assertAlmostEqual(strata["day"]["estimated_hours"], 20.0, places=9)
        self.assertAlmostEqual(strata["night"]["raw_hours"], 10.0, places=9)
        self.assertAlmostEqual(strata["night"]["estimated_hours"], 100.0, places=9)
        self.assertAlmostEqual(metrics["false_positives"]["camera_hours_estimated"], 120.0, places=9)
        self.assertAlmostEqual(metrics["false_positives"]["camera_hours_raw"], 20.0, places=9)

    def test_equal_probability_units_match_raw_counts(self):
        plan = SamplingPlan(
            plan_version="equal-v1",
            capability="person_down",
            min_samples=10,
            strata=(Stratum("a", 0.5, camera_id="cam-a"), Stratum("b", 0.5, camera_id="cam-b")),
        )
        # Same p_h for alerts and negatives: every unit carries weight 2.
        alerts = [alert(camera_id="cam-a", inclusion_probability=0.5) for _ in range(10)]
        negatives = [negative(camera_id="cam-a") for _ in range(5)]
        negatives += [negative(camera_id="cam-b", missed=1) for _ in range(2)]
        negatives += [negative(camera_id="cam-b") for _ in range(3)]
        metrics = evaluate_quality_metrics(
            alerts, negatives, plan=plan, min_samples=10, matching_window_seconds=MATCHING_WINDOW
        )
        # With identical weights the HT ratio collapses onto the raw counting ratio.
        self.assertAlmostEqual(metrics["recall"]["weighted_missed_units"], 4.0, places=9)
        self.assertAlmostEqual(metrics["recall"]["weighted_detected_units"], 20.0, places=9)
        self.assertAlmostEqual(metrics["recall"]["estimate"], 10.0 / 12.0, places=9)


class TestConfidenceIntervalsAndSampleSufficiency(unittest.TestCase):
    def test_wilson_interval_brackets_estimate(self):
        for estimate, size in ((0.95, 100), (0.5, 30), (0.75, 40), (0.9, 200)):
            with self.subTest(estimate=estimate, size=size):
                lower, upper = wilson_interval(estimate, size)
                self.assertGreaterEqual(lower, 0.0)
                self.assertLessEqual(upper, 1.0)
                self.assertLess(lower, estimate)
                self.assertGreater(upper, estimate)

    def test_wilson_interval_clamps_at_one(self):
        lower, upper = wilson_interval(1.0, 60)
        self.assertLess(lower, 1.0)
        self.assertAlmostEqual(upper, 1.0, places=12)

    def test_wilson_interval_narrows_with_sample_size(self):
        wide = wilson_interval(0.95, 40)
        narrow = wilson_interval(0.95, 400)
        self.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])
        self.assertGreater(narrow[0], wide[0])

    def test_larger_confidence_interval_is_required_for_invalid_levels(self):
        with self.assertRaises(QualityEvalError):
            wilson_interval(0.9, 10, confidence=1.0)
        with self.assertRaises(QualityEvalError):
            wilson_interval(0.9, 0)

    def test_metrics_interval_brackets_recall_estimate(self):
        alerts, negatives = g2_fail_fixture()
        metrics = evaluate_quality_metrics(
            alerts, negatives, plan=two_stratum_plan(), matching_window_seconds=MATCHING_WINDOW
        )
        recall = metrics["recall"]
        self.assertAlmostEqual(recall["estimate"], 10.0 / 60.0, places=9)
        self.assertLess(recall["ci_low"], recall["estimate"])
        self.assertGreater(recall["ci_high"], recall["estimate"])
        self.assertEqual(metrics["verdict"], "FAIL")

    def test_small_sample_is_flagged_insufficient(self):
        alerts = [alert() for _ in range(40)]
        negatives = [negative(camera_id="cam-day") for _ in range(2)]
        metrics = evaluate_quality_metrics(
            alerts, [*negatives, negative(camera_id="cam-night")],
            plan=two_stratum_plan(),
            matching_window_seconds=MATCHING_WINDOW,
        )
        sufficiency = metrics["sample_sufficiency"]
        self.assertFalse(sufficiency["sufficient"])
        self.assertEqual(sufficiency["min_samples"], 30)
        self.assertLess(sufficiency["effective_negative_samples"], 30)
        self.assertTrue(
            any(reason.startswith("effective_negative_samples=") for reason in sufficiency["reasons"]),
            sufficiency["reasons"],
        )
        self.assertEqual(metrics["verdict"], "BLOCKED")
        self.assertIn("insufficient_sample", metrics["verdict_reasons"])

    def test_perfect_recall_still_blocked_when_sample_too_small(self):
        # 40 confirmed alerts but only 2 reviewed negatives: not enough evidence.
        alerts = [alert(camera_id="cam-day", branch="person_fall") for _ in range(40)]
        negatives = [negative(camera_id="cam-day"), negative(camera_id="cam-night")]
        metrics = evaluate_quality_metrics(
            alerts, negatives, plan=two_stratum_plan(), matching_window_seconds=MATCHING_WINDOW
        )
        self.assertAlmostEqual(metrics["recall"]["estimate"], 1.0, places=9)
        self.assertEqual(metrics["verdict"], "BLOCKED")
        self.assertIn("insufficient_sample", metrics["verdict_reasons"])

    def test_min_samples_is_pinned_from_the_plan(self):
        plan = sampling_plan_with_small_minimum()
        alerts = [alert(camera_id="cam-1") for _ in range(5)]
        negatives = [negative(camera_id="cam-1") for _ in range(6)]
        metrics = evaluate_quality_metrics(
            alerts, negatives, plan=plan, matching_window_seconds=MATCHING_WINDOW
        )
        self.assertEqual(metrics["protocol"]["min_samples"], 5)
        self.assertTrue(metrics["sample_sufficiency"]["sufficient"])
        self.assertNotIn("insufficient_sample", metrics["verdict_reasons"])

    def test_protocol_pins_estimator_and_uncertainty(self):
        alerts, negatives = g2_pass_fixture()
        metrics = evaluate_quality_metrics(
            alerts, negatives, plan=two_stratum_plan(), matching_window_seconds=MATCHING_WINDOW
        )
        self.assertEqual(metrics["protocol"]["recall_estimator"], "horvitz_thompson_ratio")
        self.assertEqual(metrics["protocol"]["interval_method"], "wilson_on_kish_effective_n")
        self.assertEqual(metrics["protocol"]["denominator_unit"], "estimated_camera_hours")
        self.assertEqual(metrics["protocol"]["confidence_level"], 0.95)
        self.assertEqual(metrics["protocol"]["plan_sha256"], two_stratum_plan().content_hash())


class TestPerBranchPersonDownMetrics(unittest.TestCase):
    def setUp(self):
        self.plan = single_stratum_plan(probability=0.5, min_samples=10)
        self.alerts = (
            [alert(camera_id="cam-1", branch="person_fall") for _ in range(10)]
            + [alert(camera_id="cam-1", branch="person_lying_persistent") for _ in range(10)]
            + [alert(camera_id="cam-1", branch="person_on_stationary_vehicle") for _ in range(5)]
            + [alert(camera_id="cam-1", decision="false_positive", branch="person_lying_persistent")]
        )
        self.negatives = (
            [negative(camera_id="cam-1", missed=1, branch="person_fall") for _ in range(2)]
            + [negative(camera_id="cam-1", missed=1, branch="person_on_stationary_vehicle")]
            + [negative(camera_id="cam-1", branch="person_fall") for _ in range(9)]
        )

    def metrics(self):
        return evaluate_quality_metrics(
            self.alerts,
            self.negatives,
            plan=self.plan,
            min_samples=10,
            matching_window_seconds=MATCHING_WINDOW,
        )

    def test_all_person_down_branches_are_reported(self):
        self.assertEqual(
            BRANCHES,
            ("person_fall", "person_lying_persistent", "person_on_stationary_vehicle"),
        )
        branches = self.metrics()["branches"]
        for name in BRANCHES:
            self.assertIn(name, branches)
            self.assertIn("ci_low", branches[name])
            self.assertIn("ci_high", branches[name])
            self.assertIn("effective_sample_size", branches[name])
            self.assertIn("false_positives", branches[name])

    def test_branch_recall_uses_its_own_units(self):
        branches = self.metrics()["branches"]
        # weight 2 per negative: 2 missed (4) + 10 detected -> 10/14.
        self.assertAlmostEqual(branches["person_fall"]["estimate"], 10.0 / 14.0, places=9)
        self.assertAlmostEqual(branches["person_fall"]["weighted_missed_units"], 4.0, places=9)
        # no missed incidents, perfect branch recall.
        self.assertAlmostEqual(branches["person_lying_persistent"]["estimate"], 1.0, places=9)
        # 1 missed sample (weight 2) + 5 detected -> 5/7.
        self.assertAlmostEqual(branches["person_on_stationary_vehicle"]["estimate"], 5.0 / 7.0, places=9)

    def test_false_positives_are_attributed_per_branch(self):
        branches = self.metrics()["branches"]
        self.assertEqual(branches["person_lying_persistent"]["false_positives"], 1)
        self.assertEqual(branches["person_fall"]["false_positives"], 0)
        self.assertEqual(branches["person_on_stationary_vehicle"]["false_positives"], 0)

    def test_branch_units_reconcile_with_overall_recall(self):
        metrics = self.metrics()
        detected = sum(block["weighted_detected_units"] for block in metrics["branches"].values())
        missed = sum(block["weighted_missed_units"] for block in metrics["branches"].values())
        self.assertAlmostEqual(detected, metrics["recall"]["weighted_detected_units"], places=9)
        self.assertAlmostEqual(missed, metrics["recall"]["weighted_missed_units"], places=9)
        self.assertAlmostEqual(metrics["recall"]["estimate"], 25.0 / 31.0, places=9)
        self.assertEqual(metrics["verdict"], "FAIL")


class TestEdgeAuditSampler(unittest.TestCase):
    DIRNAME = "audit_samples"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.plan = two_stratum_plan()
        self.sampler = NegativeAuditSampler(self.root, self.plan)

    def tearDown(self):
        self._tmp.cleanup()

    def test_noise_is_deterministic_across_instances(self):
        other = NegativeAuditSampler(self.root, self.plan)
        for offset in range(25):
            start, end = offset * 60.0, offset * 60.0 + 60.0
            self.assertEqual(
                self.sampler.noise("cam-day", start, end),
                other.noise("cam-day", start, end),
            )
        # A different salt deliberately re-draws the sample.
        salted = NegativeAuditSampler(self.root, self.plan, salt="other-salt")
        self.assertNotEqual(
            self.sampler.noise("cam-day", 0.0, 60.0),
            salted.noise("cam-day", 0.0, 60.0),
        )

    def test_noise_is_uniform_in_unit_interval(self):
        for offset in range(100):
            value = self.sampler.noise("cam-day", offset * 60.0, offset * 60.0 + 30.0)
            self.assertGreaterEqual(value, 0.0)
            self.assertLess(value, 1.0)

    def test_selection_rate_tracks_inclusion_probability(self):
        windows = 400
        day = sum(
            self.sampler.should_sample("cam-day", index * 60.0, index * 60.0 + 60.0) for index in range(windows)
        )
        night = sum(
            self.sampler.should_sample("cam-night", index * 60.0, index * 60.0 + 60.0) for index in range(windows)
        )
        day_rate = day / windows
        night_rate = night / windows
        self.assertAlmostEqual(day_rate, 0.5, delta=0.06)
        self.assertAlmostEqual(night_rate, 0.1, delta=0.06)
        # The p=0.1 stratum is sampled far less than the p=0.5 stratum.
        self.assertLess(night_rate, day_rate / 2)

    def test_full_inclusion_stratum_is_always_sampled(self):
        sampler = NegativeAuditSampler(
            self.root, SamplingPlan("census-v1", "person_down", (Stratum("all", 1.0),))
        )
        for offset in range(5):
            self.assertTrue(sampler.should_sample("any-camera", offset * 10.0, offset * 10.0 + 10.0))

    def test_sample_manifest_records_the_audit_contract(self):
        record = self._first_sample("cam-night")
        self.assertIsNotNone(record)
        for field in (
            "sample_id",
            "stratum_id",
            "inclusion_probability",
            "camera_id",
            "start_time",
            "end_time",
            "duration_seconds",
            "rights_cleared",
            "status",
            "capability",
            "plan_version",
            "manifest_version",
            "sampler_version",
        ):
            self.assertIn(field, record)
        self.assertEqual(record["stratum_id"], "night")
        self.assertAlmostEqual(record["inclusion_probability"], 0.1, places=9)
        self.assertTrue(record["rights_cleared"])
        self.assertEqual(record["status"], "pending_review")
        self.assertEqual(record["plan_version"], self.plan.plan_version)
        self.assertEqual(record["capability"], self.plan.capability)
        self.assertAlmostEqual(record["duration_seconds"], 60.0, places=9)
        self.assertGreater(len(record["sample_id"]), 8)

    def test_manifest_is_persisted_as_jsonl_with_summary(self):
        record = self._first_sample("cam-day")
        path = self.root / self.DIRNAME / "samples.jsonl"
        self.assertTrue(path.is_file())
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["sample_id"], record["sample_id"])
        summary = self.sampler.summary()
        self.assertEqual(summary["samples"], 1)
        self.assertEqual(summary["pending_review"], 1)
        self.assertEqual(summary["by_stratum"], {"day": 1})
        self.assertAlmostEqual(summary["sampled_seconds"], 60.0, places=9)

    def test_plan_snapshot_pins_the_plan_hash(self):
        self._first_sample("cam-day")
        snapshot = json.loads((self.root / self.DIRNAME / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["plan_sha256"], self.plan.content_hash())
        self.assertEqual(snapshot["plan"]["plan_version"], self.plan.plan_version)
        self.assertEqual(snapshot["sampler_version"], "negative-audit-sampler-v1")

    def test_alert_windows_are_never_negative_audit_samples(self):
        for offset in range(200):
            start, end = offset * 60.0, offset * 60.0 + 60.0
            self.assertIsNone(
                self.sampler.sample_window(
                    camera_id="cam-day", start_time=start, end_time=end, alert_count=1
                )
            )
        self.assertEqual(self.sampler.samples(), [])
        self.assertFalse((self.root / self.DIRNAME / "samples.jsonl").exists())

    def test_negative_alert_count_is_rejected(self):
        with self.assertRaises(AuditSamplingError):
            self.sampler.sample_window(camera_id="cam-day", start_time=0.0, end_time=60.0, alert_count=-1)

    def test_non_rights_cleared_sample_is_flagged_and_blocks_the_report(self):
        window = self._first_sampled_window("cam-day")
        record = self.sampler.sample_window(
            camera_id="cam-day",
            start_time=window[0],
            end_time=window[1],
            rights_cleared=False,
        )
        self.assertIsNotNone(record)
        self.assertFalse(record["rights_cleared"])
        metrics = evaluate_quality_metrics(
            [alert(camera_id="cam-day") for _ in range(5)],
            self.sampler.samples(),
            plan=self.plan,
            matching_window_seconds=MATCHING_WINDOW,
        )
        self.assertIn("rights_not_cleared:1", metrics["blocking_gaps"])
        self.assertEqual(metrics["coverage"]["rights_not_cleared"], 1)
        self.assertEqual(metrics["verdict"], "BLOCKED")

    def test_pending_samples_do_not_supply_a_denominator(self):
        for camera in ("cam-day", "cam-night"):
            self._first_sample(camera)
        metrics = evaluate_quality_metrics(
            [alert(camera_id="cam-day") for _ in range(5)],
            self.sampler.samples(),
            plan=self.plan,
            matching_window_seconds=MATCHING_WINDOW,
        )
        self.assertEqual(metrics["counts"]["negative_samples_total"], 2)
        self.assertEqual(metrics["counts"]["negative_samples_reviewed"], 0)
        self.assertEqual(metrics["counts"]["negative_samples_pending_review"], 2)
        self.assertEqual(metrics["verdict"], "BLOCKED")
        self.assertIn("alerts_only", metrics["blocking_gaps"])

    def test_reviewed_sampler_manifest_feeds_the_metrics(self):
        window = self._first_sampled_window("cam-night")
        record = self.sampler.sample_window(
            camera_id="cam-night", start_time=window[0], end_time=window[1]
        )
        reviewed = dict(record)
        reviewed.update({"status": "reviewed", "missed_instances": 1, "review_minutes": 4.0})
        metrics = evaluate_quality_metrics(
            [alert(camera_id="cam-night") for _ in range(8)],
            [reviewed],
            plan=self.plan,
            min_samples=1,
            matching_window_seconds=MATCHING_WINDOW,
        )
        # The manifest's own p_h (0.1) drives the HT weight -> 10 missed incidents.
        self.assertAlmostEqual(metrics["recall"]["weighted_missed_units"], 10.0, places=9)
        self.assertEqual(metrics["counts"]["negative_samples_reviewed"], 1)
        self.assertAlmostEqual(metrics["review_load"]["review_minutes_per_negative"], 4.0, places=9)

    def test_segment_sampling_reads_recorder_window(self):
        start, end = self._first_sampled_window("cam-night")

        class Segment:
            camera_id = "cam-night"
            start_seconds = start
            end_seconds = end

        record = self.sampler.sample_segment(Segment())
        self.assertIsNotNone(record)
        self.assertEqual(record["camera_id"], "cam-night")
        self.assertAlmostEqual(record["start_time"], start, places=9)
        self.assertAlmostEqual(record["end_time"], end, places=9)
        self.assertAlmostEqual(record["inclusion_probability"], 0.1, places=9)

    def test_invalid_windows_and_cameras_are_rejected(self):
        with self.assertRaises(AuditSamplingError):
            self.sampler.sample_window(camera_id="cam-day", start_time=60.0, end_time=60.0)
        with self.assertRaises(AuditSamplingError):
            self.sampler.sample_window(camera_id="", start_time=0.0, end_time=60.0)
        with self.assertRaises(AuditSamplingError):
            self.sampler.sample_window(camera_id="cam-day", start_time=0.0, end_time=float("nan"))
        with self.assertRaises(AuditSamplingError):
            NegativeAuditSampler(self.root, self.plan, salt="")

    # ---- helpers -----------------------------------------------------------

    def _first_sampled_window(self, camera_id):
        for offset in range(2000):
            start, end = 1_000.0 + offset * 60.0, 1_000.0 + offset * 60.0 + 60.0
            if self.sampler.should_sample(camera_id, start, end):
                return start, end
        self.fail(f"no sampled window found for {camera_id}")

    def _first_sample(self, camera_id):
        start, end = self._first_sampled_window(camera_id)
        return self.sampler.sample_window(camera_id=camera_id, start_time=start, end_time=end)


class TestCliReportGeneration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.alerts_pass, self.negatives_pass = g2_pass_fixture()
        self.alerts_fail, self.negatives_fail = g2_fail_fixture()
        self.alerts_path = self._write("alerts.json", self.alerts_pass)
        self.negatives_path = self._write("negatives.json", self.negatives_pass)
        self.fail_alerts_path = self._write("alerts_fail.json", self.alerts_fail)
        self.fail_negatives_path = self._write("negatives_fail.json", self.negatives_fail)
        self.plan_path = self._write("plan.json", two_stratum_plan().to_dict())

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _base_argv(self, alerts, negatives=None, rest=()):
        argv = ["--alerts", str(alerts)]
        if negatives is not None:
            argv += ["--negatives", str(negatives)]
        argv += ["--plan", str(self.plan_path), "--site", "site-a", "--matching-window-seconds", "60"]
        return argv + list(rest)

    def _pass_argv(self, rest=()):
        return self._base_argv(
            self.alerts_path,
            self.negatives_path,
            rest=["--generated-at", "2026-01-01T00:00:00+00:00", *rest],
        )

    def test_json_report_contains_verdict_protocol_and_signoff(self):
        output = self.root / "report.json"
        code, _, _ = run_cli(self._pass_argv(rest=["--output", str(output)]))
        self.assertEqual(code, 0)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["report_version"], "g2-negative-audit-report-v1")
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["verdict_reasons"], [])
        protocol = report["protocol"]
        self.assertAlmostEqual(protocol["min_recall"], 0.90, places=9)
        self.assertAlmostEqual(protocol["max_fp_per_day"], 2.0, places=9)
        self.assertEqual(protocol["min_samples"], 30)
        self.assertEqual(protocol["plan_version"], "g2-person-down-v1")
        self.assertEqual(protocol["plan_sha256"], two_stratum_plan().content_hash())
        self.assertEqual(protocol["confidence_level"], 0.95)
        self.assertEqual(protocol["matching_window_seconds"], 60.0)
        self.assertEqual(report["site"], "site-a")
        signoff = report["owner_signoff"]
        self.assertEqual(signoff["status"], "pending")
        self.assertIn("owner", signoff["required_fields"])
        self.assertIn("residual_risk", signoff["required_fields"])
        self.assertEqual(signoff["template"]["verdict"], "PASS")
        self.assertEqual(signoff["template"]["thresholds"]["min_recall"], 0.90)
        self.assertEqual(signoff["template"]["plan_version"], "g2-person-down-v1")

    def test_markdown_report_contains_thresholds_and_signoff_block(self):
        output = self.root / "report.md"
        code, _, _ = run_cli(self._pass_argv(rest=["--output", str(output)]))
        self.assertEqual(code, 0)
        text = output.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# G2 quality report — person_down"))
        self.assertIn("Verdict: **PASS**", text)
        self.assertIn("| Recall target | 90.00% |", text)
        self.assertIn("| Max FP / camera-day | 2.00 |", text)
        self.assertIn("| Min samples | 30 |", text)
        self.assertIn("| Plan version | `g2-person-down-v1` |", text)
        self.assertIn("| `person_fall` |", text)
        self.assertIn("| `person_lying_persistent` |", text)
        self.assertIn("| `person_on_stationary_vehicle` |", text)
        self.assertIn("## Owner sign-off", text)
        self.assertIn("Status: **pending**", text)
        self.assertIn("- [ ] Owner named and accountable for these thresholds", text)

    def test_markdown_is_inferred_from_output_suffix(self):
        output = self.root / "nested" / "report.md"
        code, _, _ = run_cli(self._pass_argv(rest=["--output", str(output)]))
        self.assertEqual(code, 0)
        self.assertTrue(output.read_text(encoding="utf-8").startswith("# G2 quality report"))

    def test_explicit_markdown_format_on_stdout(self):
        code, stdout, _ = run_cli(self._pass_argv(rest=["--format", "markdown"]))
        self.assertEqual(code, 0)
        self.assertIn("# G2 quality report — person_down", stdout)
        self.assertIn("## Owner sign-off", stdout)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout)

    def test_strict_mode_exit_codes_for_pass_fail_and_blocked(self):
        pass_code, _, _ = run_cli(
            self._base_argv(
                self.alerts_path,
                self.negatives_path,
                rest=["--strict", "--format", "json"],
            )
        )
        self.assertEqual(pass_code, 0)

        fail_code, _, _ = run_cli(
            [
                "--alerts",
                str(self.fail_alerts_path),
                "--negatives",
                str(self.fail_negatives_path),
                "--plan",
                str(self.plan_path),
                "--matching-window-seconds",
                "60",
                "--strict",
            ]
        )
        self.assertEqual(fail_code, 1)

        blocked_code, _, _ = run_cli(
            [
                "--alerts",
                str(self.alerts_path),
                "--plan",
                str(self.plan_path),
                "--matching-window-seconds",
                "60",
                "--strict",
            ]
        )
        self.assertEqual(blocked_code, 2)

    def test_non_strict_mode_still_exits_zero(self):
        for alerts, negatives in (
            (self.fail_alerts_path, self.fail_negatives_path),
            (self.alerts_path, None),
        ):
            with self.subTest(alerts=alerts.name, negatives=negatives):
                argv = ["--alerts", str(alerts)]
                if negatives is not None:
                    argv += ["--negatives", str(negatives)]
                argv += ["--plan", str(self.plan_path), "--matching-window-seconds", "60"]
                code, _, _ = run_cli(argv)
                self.assertEqual(code, 0)

    def test_alerts_only_cli_report_blocks_recall(self):
        output = self.root / "blocked.json"
        code, _, _ = run_cli(
            [
                "--alerts",
                str(self.alerts_path),
                "--plan",
                str(self.plan_path),
                "--matching-window-seconds",
                "60",
                "--output",
                str(output),
            ]
        )
        self.assertEqual(code, 0)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["verdict"], "BLOCKED")
        self.assertIn("alerts_only", report["verdict_reasons"])
        self.assertIn("alerts_only", report["blocking_gaps"])
        self.assertFalse(report["sample_sufficiency"]["sufficient"])
        self.assertEqual(report["counts"]["negative_samples_reviewed"], 0)
        self.assertEqual(report["owner_signoff"]["template"]["verdict"], "BLOCKED")

    def test_fail_verdict_reports_recall_below_target(self):
        code, stdout, _ = run_cli(
            [
                "--alerts",
                str(self.fail_alerts_path),
                "--negatives",
                str(self.fail_negatives_path),
                "--plan",
                str(self.plan_path),
                "--matching-window-seconds",
                "60",
                "--format",
                "json",
            ]
        )
        self.assertEqual(code, 0)
        report = json.loads(stdout)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(report["verdict_reasons"][0].startswith("recall_below_target"))
        self.assertAlmostEqual(report["recall"]["estimate"], 10.0 / 60.0, places=9)

    def test_cli_runs_as_a_subprocess_entry_point(self):
        output = self.root / "subprocess-report.json"
        process = subprocess.run(
            [
                sys.executable,
                "tools/negative_audit_report.py",
                "--alerts",
                str(self.alerts_path),
                "--negatives",
                str(self.negatives_path),
                "--plan",
                str(self.plan_path),
                "--matching-window-seconds",
                "60",
                "--output",
                str(output),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("wrote", process.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["counts"]["negative_samples_reviewed"], 80)

    def test_missing_input_exits_two_with_error_message(self):
        code, _, stderr = run_cli(["--alerts", str(self.root / "absent.json")])
        self.assertEqual(code, 2)
        self.assertIn("error:", stderr)
        self.assertIn("input not found", stderr)

    def test_jsonl_and_directory_inputs_are_accepted(self):
        alert_dir = self.root / "alerts-jsonl"
        negative_dir = self.root / "negatives-jsonl"
        alert_dir.mkdir()
        negative_dir.mkdir()
        (alert_dir / "alerts.jsonl").write_text(
            "\n".join(json.dumps(record) for record in self.alerts_pass) + "\n", encoding="utf-8"
        )
        (negative_dir / "a.jsonl").write_text(
            "\n".join(json.dumps(record) for record in self.negatives_pass[:40]) + "\n", encoding="utf-8"
        )
        (negative_dir / "b.jsonl").write_text(
            "\n".join(json.dumps(record) for record in self.negatives_pass[40:]) + "\n", encoding="utf-8"
        )
        code, stdout, _ = run_cli(
            [
                "--alerts",
                str(alert_dir),
                "--negatives",
                str(negative_dir),
                "--plan",
                str(self.plan_path),
                "--matching-window-seconds",
                "60",
                "--format",
                "json",
            ]
        )
        self.assertEqual(code, 0)
        report = json.loads(stdout)
        self.assertEqual(report["inputs"]["alerts"]["records"], 61)
        self.assertEqual(report["inputs"]["negatives"]["records"], 80)
        self.assertEqual(len(report["inputs"]["negatives"]["files"]), 2)
        self.assertEqual(report["counts"]["negative_samples_reviewed"], 80)
        self.assertEqual(report["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
