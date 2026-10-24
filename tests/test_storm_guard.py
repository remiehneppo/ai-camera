"""Ticket #41: bounded storm guard for malformed ingest floods."""

import json
import unittest

from domain.storm_guard import (
    BUDGETED_OUTCOMES,
    OUTCOME_ACCEPTED,
    OUTCOME_CONFLICT,
    OUTCOME_DUPLICATE,
    OUTCOME_MALFORMED,
    OUTCOME_RATE_LIMITED,
    OUTCOME_TOO_LARGE,
    OUTCOME_UNAVAILABLE,
    StormGuard,
    StormGuardPolicy,
)

T0 = 1_000.0


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def guard(**policy):
    clock = Clock()
    defaults = {"window_seconds": 60.0, "malformed_budget": 3, "forensic_samples": 2, "sample_text_bytes": 64}
    defaults.update(policy)
    return StormGuard(StormGuardPolicy(**defaults), _now=clock), clock


class BudgetTests(unittest.TestCase):
    def test_budget_is_spent_by_malformed_attempts_and_then_refused(self):
        g, clock = guard()
        self.assertTrue(g.admit())
        for _ in range(3):
            g.record(OUTCOME_MALFORMED, device_id="dev", now=clock.now)
        self.assertFalse(g.admit())
        snapshot = g.snapshot(now=clock.now)
        self.assertEqual((snapshot["budget_spent"], snapshot["budget_remaining"]), (3, 0))
        self.assertTrue(snapshot["degraded"])
        self.assertEqual(snapshot["retry_after_seconds"], 60)

    def test_window_rollover_restores_the_budget(self):
        g, clock = guard()
        for _ in range(3):
            g.record(OUTCOME_MALFORMED, now=clock.now)
        self.assertFalse(g.admit())
        clock.now = T0 + 61
        self.assertTrue(g.admit())
        snapshot = g.snapshot(now=clock.now)
        self.assertEqual((snapshot["budget_spent"], snapshot["total"], snapshot["forensics"]), (0, 0, []))

    def test_duplicates_accepted_and_unavailable_never_spend_the_budget(self):
        g, clock = guard()
        for _ in range(10):
            for outcome in (OUTCOME_DUPLICATE, OUTCOME_ACCEPTED, OUTCOME_UNAVAILABLE):
                g.record(outcome, device_id="dev", detail={"note": "x"}, now=clock.now)
        snapshot = g.snapshot(now=clock.now)
        self.assertEqual(snapshot["budget_spent"], 0)
        self.assertEqual(snapshot["counts"][OUTCOME_DUPLICATE], 10)
        self.assertEqual(snapshot["counts"][OUTCOME_ACCEPTED], 10)
        self.assertEqual(snapshot["forensics"], [], "a duplicate must stay compact: no forensic sample")
        self.assertFalse(snapshot["degraded"])
        self.assertTrue(g.admit())

    def test_conflict_and_oversized_requests_are_budgeted(self):
        self.assertTrue({OUTCOME_MALFORMED, OUTCOME_TOO_LARGE, OUTCOME_CONFLICT, OUTCOME_RATE_LIMITED} <= BUDGETED_OUTCOMES)
        g, clock = guard()
        g.record(OUTCOME_TOO_LARGE, now=clock.now)
        g.record(OUTCOME_CONFLICT, now=clock.now)
        self.assertEqual(g.snapshot(now=clock.now)["budget_spent"], 2)

    def test_rate_limited_attempts_stay_observable_without_growing_the_reserve(self):
        g, clock = guard()
        for _ in range(3):
            g.record(OUTCOME_MALFORMED, now=clock.now)
        for _ in range(50):
            g.record(OUTCOME_RATE_LIMITED, now=clock.now)
        snapshot = g.snapshot(now=clock.now)
        self.assertEqual(snapshot["counts"][OUTCOME_RATE_LIMITED], 50)
        self.assertLessEqual(len(snapshot["forensics"]), 2)
        self.assertTrue(snapshot["truncated"])
        self.assertGreater(snapshot["dropped_samples"], 0)


class ForensicTests(unittest.TestCase):
    def test_forensic_ring_is_bounded_and_reports_truncation(self):
        g, clock = guard(forensic_samples=2, malformed_budget=100)
        for index in range(5):
            g.record(OUTCOME_MALFORMED, device_id=f"dev-{index}", now=clock.now)
        snapshot = g.snapshot(now=clock.now)
        self.assertEqual(len(snapshot["forensics"]), 2)
        self.assertEqual([sample["device_id"] for sample in snapshot["forensics"]], ["dev-3", "dev-4"])
        self.assertEqual((snapshot["truncated"], snapshot["dropped_samples"]), (True, 3))
        self.assertTrue(snapshot["degraded"])

    def test_sample_detail_is_flat_and_length_bounded(self):
        g, clock = guard(forensic_samples=1)
        g.record(
            OUTCOME_MALFORMED,
            device_id="d" * 200,
            detail={"long": "x" * 500, "nested": {"payload": "y" * 500}, "b": 2, "c": 3, "d": 4},
            size_bytes=1234,
            now=clock.now,
        )
        sample = g.snapshot(now=clock.now)["forensics"][0]
        self.assertEqual(len(sample["device_id"]), 64)
        self.assertLessEqual(len(json.dumps(sample["detail"])), 64)
        self.assertNotIn("nested", sample["detail"], "nested structures are never kept")
        self.assertNotIn("long", sample["detail"], "a value above the byte budget is dropped, not truncated mid-key")
        self.assertEqual(sample["detail"], {"b": "2", "c": "3", "d": "4"})
        self.assertEqual(sample["size_bytes"], 1234)

    def test_snapshot_is_json_serialisable_and_deterministic(self):
        g, clock = guard()
        g.record(OUTCOME_ACCEPTED, now=clock.now)
        g.record(OUTCOME_MALFORMED, device_id="dev", detail={"reason": "schema"}, now=clock.now)
        payload = json.loads(g.as_json(now=clock.now))
        self.assertEqual(payload["policy_version"], "storm-guard-v1")
        self.assertEqual(payload["counts"][OUTCOME_MALFORMED], 1)
        self.assertEqual(payload["forensics"][0]["detail"], {"reason": "schema"})

    def test_unknown_outcomes_and_impossible_policies_are_rejected(self):
        g, clock = guard()
        with self.assertRaises(ValueError):
            g.record("exploded", now=clock.now)
        for policy in ({"malformed_budget": 0}, {"window_seconds": 0}, {"forensic_samples": -1},
                       {"sample_text_bytes": 4}, {"malformed_budget": 2.5}):
            with self.assertRaises(ValueError):
                StormGuardPolicy(**policy)


if __name__ == "__main__":
    unittest.main()
