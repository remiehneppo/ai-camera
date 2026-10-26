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

    def test_zero_sample_policy_counts_drops_instead_of_crashing(self):
        g, clock = guard(forensic_samples=0)
        for _ in range(2):
            g.record(OUTCOME_MALFORMED, device_id="dev", now=clock.now)
        snapshot = g.snapshot(now=clock.now)
        self.assertEqual(snapshot["forensics"], [])
        self.assertEqual(snapshot["dropped_samples"], 2)
        self.assertTrue(snapshot["truncated"])
        self.assertTrue(snapshot["degraded"])

    def test_snapshot_cannot_be_used_to_mutate_the_guard_window(self):
        g, clock = guard(forensic_samples=2)
        g.record(OUTCOME_MALFORMED, device_id="dev", detail={"reason": "schema"}, now=clock.now)
        report = g.snapshot(now=clock.now)
        report["forensics"][0]["detail"]["reason"] = "tampered"
        report["counts"][OUTCOME_MALFORMED] = 999
        fresh = g.snapshot(now=clock.now)
        self.assertEqual(fresh["forensics"][0]["detail"], {"reason": "schema"})
        self.assertEqual(fresh["counts"][OUTCOME_MALFORMED], 1)

    def test_concurrent_recording_keeps_exact_counts(self):
        import threading

        g, clock = guard(malformed_budget=10 ** 6, forensic_samples=1)

        def hammer():
            for _ in range(5_000):
                g.record(OUTCOME_ACCEPTED, now=clock.now)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(g.snapshot(now=clock.now)["counts"][OUTCOME_ACCEPTED], 20_000)

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


class MediaFailureAndSinkTests(unittest.TestCase):
    def test_forensic_sink_receives_sample_and_bounds_retention(self):
        sink_samples = []
        clock = Clock()
        g = StormGuard(
            StormGuardPolicy(malformed_budget=5, forensic_samples=2),
            _now=clock,
            forensic_sink=lambda s: sink_samples.append(s),
        )
        # Duplicate and accepted outcomes must NOT trigger forensic sink
        g.record(OUTCOME_ACCEPTED, now=clock.now)
        g.record(OUTCOME_DUPLICATE, now=clock.now)
        self.assertEqual(len(sink_samples), 0)

        # Malformed triggers sink
        g.record(OUTCOME_MALFORMED, device_id="dev-1", detail={"reason": "schema"}, now=clock.now)
        self.assertEqual(len(sink_samples), 1)
        self.assertEqual(sink_samples[0]["outcome"], OUTCOME_MALFORMED)
        self.assertEqual(sink_samples[0]["device_id"], "dev-1")

        snap = g.snapshot(now=clock.now)
        self.assertFalse(snap["forensic_storage_degraded"])
        self.assertEqual(snap["sink_failures"], 0)
        self.assertEqual(snap["media_write_failures"], 0)

    def test_forensic_sink_oserror_drops_sample_and_sets_degraded(self):
        def failing_sink(sample):
            raise OSError(28, "No space left on device")

        clock = Clock()
        g = StormGuard(
            StormGuardPolicy(malformed_budget=10, forensic_samples=3),
            _now=clock,
            forensic_sink=failing_sink,
        )
        # Must not raise to caller on OSError
        g.record(OUTCOME_MALFORMED, device_id="dev-fail", detail={"err": "bad"}, now=clock.now)

        snap = g.snapshot(now=clock.now)
        self.assertEqual(snap["dropped_samples"], 1)
        self.assertEqual(snap["sink_failures"], 1)
        self.assertEqual(snap["media_write_failures"], 1)
        self.assertTrue(snap["forensic_storage_degraded"])
        self.assertTrue(snap["degraded"])
        self.assertTrue(snap["truncated"])
        self.assertEqual(snap["forensics"], [], "failed sample is dropped and not retained")

    def test_storage_unavailable_drops_sample_and_sets_degraded(self):
        storage_ok = True
        clock = Clock()
        g = StormGuard(
            StormGuardPolicy(malformed_budget=10, forensic_samples=3),
            _now=clock,
            storage_available=lambda: storage_ok,
        )
        g.record(OUTCOME_MALFORMED, device_id="dev-1", now=clock.now)
        self.assertFalse(g.snapshot(now=clock.now)["forensic_storage_degraded"])
        self.assertEqual(len(g.snapshot(now=clock.now)["forensics"]), 1)

        # Simulate storage becoming unavailable (disk full / reserve reached)
        storage_ok = False
        snap_before = g.snapshot(now=clock.now)
        self.assertTrue(snap_before["forensic_storage_degraded"])
        self.assertTrue(snap_before["degraded"])

        # Recording malformed payload drops sample and increments failures
        g.record(OUTCOME_MALFORMED, device_id="dev-2", now=clock.now)
        snap_after = g.snapshot(now=clock.now)
        self.assertEqual(snap_after["dropped_samples"], 1)
        self.assertEqual(snap_after["sink_failures"], 1)
        self.assertEqual(snap_after["media_write_failures"], 1)
        # In-memory forensics was not grown with the dropped sample
        self.assertEqual(len(snap_after["forensics"]), 1)

    def test_media_write_hook_compat_and_record_failure_direct(self):
        hook_called = []
        clock = Clock()
        g = StormGuard(
            StormGuardPolicy(malformed_budget=5, forensic_samples=2),
            _now=clock,
            media_write_hook=lambda s: hook_called.append(s),
        )
        g.record(OUTCOME_MALFORMED, device_id="dev-hook", now=clock.now)
        self.assertEqual(len(hook_called), 1)

        # Direct recording of media write failure
        g.record_media_failure(count=2)
        snap = g.snapshot(now=clock.now)
        self.assertEqual(snap["media_write_failures"], 2)
        self.assertEqual(snap["sink_failures"], 2)
        self.assertEqual(snap["dropped_samples"], 2)
        self.assertTrue(snap["forensic_storage_degraded"])

    def test_sample_detail_redacts_secrets(self):
        clock = Clock()
        g = StormGuard(_now=clock)
        g.record(
            OUTCOME_MALFORMED,
            device_id="dev-secret",
            detail={
                "auth_token": "Bearer super-secret-token",
                "api_key": "xyz-12345",
                "user_password": "mypassword",
                "safe_param": "hello",
            },
            now=clock.now,
        )
        sample = g.snapshot(now=clock.now)["forensics"][0]
        self.assertEqual(sample["detail"]["auth_token"], "<redacted>")
        self.assertEqual(sample["detail"]["api_key"], "<redacted>")
        self.assertEqual(sample["detail"]["user_password"], "<redacted>")
        self.assertEqual(sample["detail"]["safe_param"], "hello")


if __name__ == "__main__":
    unittest.main()
