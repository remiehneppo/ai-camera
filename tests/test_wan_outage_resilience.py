"""Comprehensive test suite for WAN Outage 24h Autonomy, Metadata Priority, and Backlog Drain (Ticket #36)."""

from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock
from urllib.error import URLError
import uuid

from apps.edge.health import EdgeHealthMonitor, HealthStatus
from apps.edge.outbox import EventOutbox
from apps.edge.quota import StorageBreakdown, StorageQuotaManager
from apps.edge.wan_resilience import WanOutageCoordinator
from domain.event_contract import canonical_event_hash, validate_event
from domain.evidence_contract import make_evidence_request
from domain.wan_outage import (
    DEFAULT_AUTONOMY_BUDGET_SECONDS,
    DEFAULT_MIN_STATE_RESERVE_BYTES,
    DISK_LOSS_DISCLAIMER,
    ITEM_TYPE_EVIDENCE_CLIP,
    ITEM_TYPE_METADATA,
    POLICY_VERSION,
    PRIORITY_EVIDENCE_CLIP,
    PRIORITY_METADATA,
    REASON_AGE_BELOW_TTL,
    REASON_OUTAGE_BUDGET_EXCEEDED,
    REASON_PINNED_PROTECTED,
    REASON_RECOVERY_IMPOSSIBLE_RATE,
    REASON_STORAGE_EXHAUSTED,
    REASON_UNACKED_PROTECTED_AGAINST_TTL,
    STATUS_DEGRADED,
    STATUS_HEALTHY,
    STATUS_RECOVERY_IMPOSSIBLE,
    STATUS_TOLERANCE_EXCEEDED,
    STATUS_UNAVAILABLE,
    STATUS_VERIFIED,
    AutonomySizingModel,
    BacklogDrainModel,
    DrainVerificationResult,
    EvidenceTTLEvaluation,
    MetadataPriorityPolicy,
    OutageAssessment,
    RpoRtoAssessment,
    evaluate_evidence_ttl_eligibility,
    filter_unexpired_unacked_evidence,
)


def make_test_event(
    *,
    event_id: str | None = None,
    message_id: str | None = None,
    revision: int = 1,
    evidence_requests: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    now = "2026-10-12T00:00:00.000000Z"
    payload: dict[str, object] = {
        "taxonomy": "synthetic_demo",
        "lifecycle": "candidate",
        "severity": "low",
        "score": 0.0,
    }
    if evidence_requests:
        payload["evidence_requests"] = evidence_requests

    return {
        "schema_version": 1,
        "message_id": message_id or f"msg-{uuid.uuid4()}",
        "event_id": event_id or str(uuid.uuid4()),
        "revision": revision,
        "device_id": "lab-edge-01",
        "camera_id": "lab-camera-01",
        "stream_session_id": "00000000-0000-4000-8000-000000000002",
        "pipeline_id": "synthetic-fixture",
        "pipeline_version": "1",
        "origin": "synthetic",
        "event_time": now,
        "produced_at": now,
        "config_version": "synthetic-fixture-v1",
        "model_lineage": [{"role": "fixture", "version": "1"}],
        "model_artifact_hash": "unknown_artifact",
        "calibration_version": "uncalibrated",
        "quality_state": "unknown",
        "payload": payload,
    }


def make_valid_receipt(item: dict[str, object]) -> dict[str, object]:
    event = item["event"]
    assert isinstance(event, dict)
    return {
        "device_id": event["device_id"],
        "event_id": event["event_id"],
        "revision": event["revision"],
        "message_id": item["message_id"],
        "event_hash": item["event_hash"],
        "accepted": True,
        "canonicalization": "canonical-json-python-v1",
        "accepted_at": "2026-10-12T00:00:01.000000Z",
    }


class AutonomySizingModelTests(unittest.TestCase):
    """Tests for 24h autonomy sizing, consumption, and time-to-full calculations."""

    def test_default_values_and_validation(self) -> None:
        model = AutonomySizingModel()
        self.assertEqual(model.autonomy_budget_seconds, 86400.0)
        self.assertEqual(model.min_state_reserve_bytes, DEFAULT_MIN_STATE_RESERVE_BYTES)
        self.assertEqual(model.total_generation_rate_bytes_per_second, 0.0)

        with self.assertRaises(ValueError):
            AutonomySizingModel(autonomy_budget_seconds=-10.0)
        with self.assertRaises(ValueError):
            AutonomySizingModel(event_rate_per_second=-1.0)
        with self.assertRaises(ValueError):
            AutonomySizingModel(avg_event_bytes=-1)
        with self.assertRaises(ValueError):
            AutonomySizingModel(min_state_reserve_bytes=-100)

    def test_generation_rate_and_consumption_estimates(self) -> None:
        # 2 events/sec @ 1000B = 2000 B/s
        # 0.01 clips/sec (36 clips/h) @ 5,000,000B = 50,000 B/s
        # Total rate = 52,000 B/s
        model = AutonomySizingModel(
            autonomy_budget_seconds=86400.0,
            event_rate_per_second=2.0,
            avg_event_bytes=1000,
            evidence_rate_per_second=0.01,
            avg_clip_bytes=5_000_000,
        )
        self.assertEqual(model.event_generation_rate_bytes_per_second, 2000.0)
        self.assertEqual(model.evidence_generation_rate_bytes_per_second, 50000.0)
        self.assertEqual(model.total_generation_rate_bytes_per_second, 52000.0)

        # Estimate 1 hour (3600s)
        meta_b, clip_b, total_b = model.estimate_backlog_consumption(3600.0)
        self.assertEqual(meta_b, 7_200_000)
        self.assertEqual(clip_b, 180_000_000)
        self.assertEqual(total_b, 187_200_000)

        # Estimate 24 hours (86400s)
        meta_24h, clip_24h, total_24h = model.estimate_backlog_consumption(86400.0)
        self.assertEqual(meta_24h, 172_800_000)
        self.assertEqual(clip_24h, 4_320_000_000)
        self.assertEqual(total_24h, 4_492_800_000)

    def test_calculate_time_to_full(self) -> None:
        model = AutonomySizingModel(
            event_rate_per_second=1.0,
            avg_event_bytes=1000,
            evidence_rate_per_second=0.0,
            min_state_reserve_bytes=50_000_000,
        )
        # Total rate = 1000 B/s
        # Available 150MB -> Usable = 150MB - 50MB reserve = 100MB = 100,000,000 bytes
        # Time to full = 100,000,000 / 1000 = 100,000 seconds
        time_to_full = model.calculate_time_to_full(150_000_000, preserve_reserve=True)
        self.assertEqual(time_to_full, 100_000.0)

        # Without preserving reserve
        time_to_full_raw = model.calculate_time_to_full(150_000_000, preserve_reserve=False)
        self.assertEqual(time_to_full_raw, 150_000.0)

        # Available less than reserve -> 0.0s
        self.assertEqual(model.calculate_time_to_full(40_000_000, preserve_reserve=True), 0.0)

        # Rate == 0 -> infinite
        idle_model = AutonomySizingModel(event_rate_per_second=0.0, evidence_rate_per_second=0.0)
        self.assertEqual(idle_model.calculate_time_to_full(100_000_000), float("inf"))

    def test_can_sustain_autonomy(self) -> None:
        # Rate: 10,000 B/s. 24h = 864,000,000 bytes. Reserve = 50,000,000.
        # Total required = 914,000,000 bytes.
        model = AutonomySizingModel(
            event_rate_per_second=10.0,
            avg_event_bytes=1000,
            min_state_reserve_bytes=50_000_000,
        )
        self.assertTrue(model.can_sustain_autonomy(1_000_000_000))
        self.assertFalse(model.can_sustain_autonomy(900_000_000))

    def test_evaluate_outage_state_healthy_and_degraded(self) -> None:
        model = AutonomySizingModel(autonomy_budget_seconds=86400.0)

        # Within budget -> healthy
        assessment_ok = model.evaluate_outage(3600.0, available_bytes=500_000_000)
        self.assertFalse(assessment_ok.is_budget_exceeded)
        self.assertEqual(assessment_ok.status, STATUS_HEALTHY)
        self.assertIsNone(assessment_ok.reason)

        # Exceeded budget -> degraded
        assessment_degraded = model.evaluate_outage(86401.0, available_bytes=500_000_000)
        self.assertTrue(assessment_degraded.is_budget_exceeded)
        self.assertEqual(assessment_degraded.status, STATUS_DEGRADED)
        self.assertEqual(assessment_degraded.reason, REASON_OUTAGE_BUDGET_EXCEEDED)

        # Storage below reserve -> unavailable
        assessment_exhausted = model.evaluate_outage(
            100.0,
            available_bytes=DEFAULT_MIN_STATE_RESERVE_BYTES - 1000,
        )
        self.assertEqual(assessment_exhausted.status, STATUS_UNAVAILABLE)
        self.assertEqual(assessment_exhausted.reason, REASON_STORAGE_EXHAUSTED)


class NoTTLOnUnackedEvidenceTests(unittest.TestCase):
    """Enforce that unACKed evidence and pending events are NEVER expired by a TTL clock."""

    def test_unacked_evidence_never_expires_regardless_of_age(self) -> None:
        # Ages: 1 hour, 24 hours, 7 days, 1 year
        test_ages = [3600.0, 86400.0, 7 * 86400.0, 365 * 86400.0]
        for age in test_ages:
            eval_res = evaluate_evidence_ttl_eligibility(
                request_id="req-unacked-1",
                is_acked=False,
                is_pinned=False,
                age_seconds=age,
                ttl_seconds=86400.0,
            )
            self.assertFalse(eval_res.eligible_for_expiry)
            self.assertEqual(eval_res.rejection_reason, REASON_UNACKED_PROTECTED_AGAINST_TTL)

    def test_pinned_evidence_never_expires_even_if_acked(self) -> None:
        eval_res = evaluate_evidence_ttl_eligibility(
            request_id="req-pinned-1",
            is_acked=True,
            is_pinned=True,
            age_seconds=100_000.0,
            ttl_seconds=86400.0,
        )
        self.assertFalse(eval_res.eligible_for_expiry)
        self.assertEqual(eval_res.rejection_reason, REASON_PINNED_PROTECTED)

    def test_acked_unpinned_evidence_expires_only_after_ttl(self) -> None:
        # Below TTL
        young_res = evaluate_evidence_ttl_eligibility(
            request_id="req-young",
            is_acked=True,
            is_pinned=False,
            age_seconds=10_000.0,
            ttl_seconds=86400.0,
        )
        self.assertFalse(young_res.eligible_for_expiry)
        self.assertEqual(young_res.rejection_reason, REASON_AGE_BELOW_TTL)

        # Above TTL
        old_res = evaluate_evidence_ttl_eligibility(
            request_id="req-old",
            is_acked=True,
            is_pinned=False,
            age_seconds=90_000.0,
            ttl_seconds=86400.0,
        )
        self.assertTrue(old_res.eligible_for_expiry)
        self.assertIsNone(old_res.rejection_reason)

    def test_filter_unexpired_unacked_evidence_partitions_correctly(self) -> None:
        current_time = 1_000_000.0
        items = [
            # 1. Unacked, old (10 days old) -> MUST BE PROTECTED
            {"request_id": "r1", "state": "requested", "created_at_epoch": current_time - 10 * 86400.0},
            # 2. Unacked fulfilled, old -> MUST BE PROTECTED
            {"request_id": "r2", "state": "fulfilled", "created_at_epoch": current_time - 3 * 86400.0},
            # 3. Pinned, acked, old -> MUST BE PROTECTED
            {"request_id": "r3", "state": "acknowledged", "is_pinned": True, "created_at_epoch": current_time - 5 * 86400.0},
            # 4. Acked, young (< 24h) -> PROTECTED (age below TTL)
            {"request_id": "r4", "state": "acknowledged", "is_pinned": False, "created_at_epoch": current_time - 3600.0},
            # 5. Acked, old (> 24h) -> ELIGIBLE FOR EXPIRY
            {"request_id": "r5", "state": "acknowledged", "is_pinned": False, "created_at_epoch": current_time - 100_000.0},
        ]

        protected, eligible = filter_unexpired_unacked_evidence(
            items,
            current_time=current_time,
            ttl_seconds=86400.0,
        )
        protected_ids = {p["request_id"] for p in protected}
        eligible_ids = {e["request_id"] for e in eligible}

        self.assertEqual(protected_ids, {"r1", "r2", "r3", "r4"})
        self.assertEqual(eligible_ids, {"r5"})
        self.assertEqual(
            next(p for p in protected if p["request_id"] == "r1")["ttl_protection_reason"],
            REASON_UNACKED_PROTECTED_AGAINST_TTL,
        )


class MetadataPriorityPolicyTests(unittest.TestCase):
    """Enforce metadata prioritization over video clips during outage and drain recovery."""

    def test_select_next_transfer_type(self) -> None:
        policy = MetadataPriorityPolicy()
        # Both pending -> metadata first
        self.assertEqual(policy.select_next_transfer_type(10, 5), ITEM_TYPE_METADATA)
        # Only metadata pending
        self.assertEqual(policy.select_next_transfer_type(3, 0), ITEM_TYPE_METADATA)
        # Only clips pending
        self.assertEqual(policy.select_next_transfer_type(0, 4), ITEM_TYPE_EVIDENCE_CLIP)
        # Neither pending
        self.assertIsNone(policy.select_next_transfer_type(0, 0))

    def test_should_defer_clip_upload(self) -> None:
        policy = MetadataPriorityPolicy()
        self.assertTrue(policy.should_defer_clip_upload(1))
        self.assertTrue(policy.should_defer_clip_upload(100))
        self.assertFalse(policy.should_defer_clip_upload(0))

    def test_prioritize_queue_order(self) -> None:
        metadata_items = ["meta_1", "meta_2"]
        clip_items = ["clip_1", "clip_2"]
        ordered = MetadataPriorityPolicy.prioritize_queue(metadata_items, clip_items)
        self.assertEqual(
            ordered,
            [
                (ITEM_TYPE_METADATA, "meta_1"),
                (ITEM_TYPE_METADATA, "meta_2"),
                (ITEM_TYPE_EVIDENCE_CLIP, "clip_1"),
                (ITEM_TYPE_EVIDENCE_CLIP, "clip_2"),
            ],
        )


class BacklogDrainModelTests(unittest.TestCase):
    """Mathematical validation of the B / (U - G) drain rate model."""

    def test_recovery_impossible_when_u_le_g(self) -> None:
        # U < G: Upload 500 B/s, Generation 1000 B/s
        model_less = BacklogDrainModel(
            backlog_bytes=100_000,
            upload_rate_bytes_per_second=500.0,
            generation_rate_bytes_per_second=1000.0,
        )
        self.assertFalse(model_less.is_recovery_possible)
        self.assertEqual(model_less.net_drain_rate_bytes_per_second, -500.0)
        with self.assertRaises(ValueError) as ctx:
            model_less.calculate_expected_drain_time()
        self.assertIn(REASON_RECOVERY_IMPOSSIBLE_RATE, str(ctx.exception))

        # U == G: Upload 1000 B/s, Generation 1000 B/s
        model_equal = BacklogDrainModel(
            backlog_bytes=100_000,
            upload_rate_bytes_per_second=1000.0,
            generation_rate_bytes_per_second=1000.0,
        )
        self.assertFalse(model_equal.is_recovery_possible)
        self.assertEqual(model_equal.net_drain_rate_bytes_per_second, 0.0)
        with self.assertRaises(ValueError):
            model_equal.calculate_expected_drain_time()

        # Verification result reports recovery impossible
        res = model_less.verify_drain(10.0)
        self.assertFalse(res.is_recovery_possible)
        self.assertEqual(res.status, STATUS_RECOVERY_IMPOSSIBLE)
        self.assertFalse(res.within_tolerance)

    def test_recovery_possible_and_exact_drain_calculation(self) -> None:
        # B = 10,000,000 bytes (10MB)
        # U = 3,000,000 B/s, G = 1,000,000 B/s -> net = 2,000,000 B/s
        # T = 10,000,000 / 2,000,000 = 5.0 seconds
        model = BacklogDrainModel(
            backlog_bytes=10_000_000,
            upload_rate_bytes_per_second=3_000_000.0,
            generation_rate_bytes_per_second=1_000_000.0,
        )
        self.assertTrue(model.is_recovery_possible)
        self.assertEqual(model.calculate_expected_drain_time(), 5.0)

        # Predict backlog trajectory
        self.assertEqual(model.predict_backlog(0.0), 10_000_000.0)
        self.assertEqual(model.predict_backlog(2.5), 5_000_000.0)
        self.assertEqual(model.predict_backlog(5.0), 0.0)
        self.assertEqual(model.predict_backlog(10.0), 0.0)

    def test_verify_drain_trajectory_tolerances(self) -> None:
        model = BacklogDrainModel(
            backlog_bytes=10_000_000,
            upload_rate_bytes_per_second=2_000_000.0,
            generation_rate_bytes_per_second=0.0,
        )
        # Expected T = 10,000,000 / 2,000,000 = 5.0s
        # Tolerance 15% of 5s = 0.75s, but min_tolerance_seconds = 1.0s -> allowed [4.0, 6.0]
        verified = model.verify_drain(5.2, tolerance_fraction=0.15)
        self.assertTrue(verified.within_tolerance)
        self.assertEqual(verified.status, STATUS_VERIFIED)

        too_slow = model.verify_drain(8.5, tolerance_fraction=0.15)
        self.assertFalse(too_slow.within_tolerance)
        self.assertEqual(too_slow.status, STATUS_TOLERANCE_EXCEEDED)

    def test_assess_rpo_rto_scope(self) -> None:
        model = BacklogDrainModel(
            backlog_bytes=20_000_000,
            upload_rate_bytes_per_second=4_000_000.0,
            generation_rate_bytes_per_second=0.0,
        )
        assessment = model.assess_rpo_rto()
        self.assertEqual(assessment.rpo_seconds, 0.0)
        self.assertEqual(assessment.rto_seconds, 5.0)
        self.assertEqual(assessment.disclaimer, DISK_LOSS_DISCLAIMER)


class WanOutageCoordinatorTests(unittest.TestCase):
    """Integration test suite for WanOutageCoordinator across outages, priorities, and recovery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "outbox.sqlite3"
        self.outbox = EventOutbox(self.db_path)
        self.current_time = 1000.0

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _clock(self) -> float:
        return self.current_time

    def _advance_clock(self, seconds: float) -> None:
        self.current_time += seconds

    def test_connectivity_state_tracking(self) -> None:
        coordinator = WanOutageCoordinator(
            outbox=self.outbox,
            clock_fn=self._clock,
            autonomy_budget_seconds=86400.0,
        )
        self.assertTrue(coordinator.is_online)
        self.assertEqual(coordinator.outage_duration(), 0.0)

        # Transition offline
        self.current_time = 1000.0
        coordinator.record_connectivity(False)
        self.assertFalse(coordinator.is_online)
        self.assertEqual(coordinator.outage_count, 1)

        # Advance 3600 seconds
        self._advance_clock(3600.0)
        self.assertEqual(coordinator.outage_duration(), 3600.0)
        self.assertFalse(coordinator.is_outage_budget_exceeded())

        # Advance past 24h budget (86400s)
        self._advance_clock(83000.0)  # total 86600s
        self.assertEqual(coordinator.outage_duration(), 86600.0)
        self.assertTrue(coordinator.is_outage_budget_exceeded())

        # Restore online
        coordinator.record_connectivity(True)
        self.assertTrue(coordinator.is_online)
        self.assertEqual(coordinator.outage_duration(), 0.0)
        self.assertEqual(coordinator.total_outage_seconds, 86600.0)

    def test_health_monitor_and_quota_degraded_when_budget_exceeded(self) -> None:
        health_monitor = EdgeHealthMonitor(outbox=self.outbox)
        quota_manager = StorageQuotaManager(outbox=self.outbox)

        coordinator = WanOutageCoordinator(
            outbox=self.outbox,
            quota_manager=quota_manager,
            health_monitor=health_monitor,
            autonomy_budget_seconds=86400.0,
            clock_fn=self._clock,
        )

        # Mark started
        health_monitor.mark_started()
        health_monitor.record_frame_received(receive_time=self.current_time)

        # Go offline
        coordinator.record_connectivity(False)
        self.assertFalse(quota_manager.degraded)

        # Advance past budget
        self._advance_clock(90000.0)
        coordinator.sync_health_and_quota()

        # StorageQuotaManager must be degraded
        self.assertTrue(quota_manager.degraded)
        self.assertEqual(quota_manager.degraded_reason, REASON_OUTAGE_BUDGET_EXCEEDED)

        # EdgeHealthMonitor snapshot must report DEGRADED with wan_outage_degraded
        snapshot = health_monitor.get_health_snapshot(now=self.current_time)
        self.assertEqual(snapshot["status"], HealthStatus.DEGRADED.value)
        self.assertIn("wan_outage_degraded", snapshot["metrics"]["operational_faults"])
        self.assertIn("wan_outage_degraded", snapshot["all_reasons"])

        # Restore online
        coordinator.record_connectivity(True)
        self.assertFalse(quota_manager.degraded)
        self.assertIsNone(quota_manager.degraded_reason)

        snapshot_recovered = health_monitor.get_health_snapshot(now=self.current_time)
        self.assertNotIn("wan_outage_degraded", snapshot_recovered["metrics"]["operational_faults"])
        self.assertNotIn("wan_outage_degraded", snapshot_recovered["all_reasons"])

    def test_metadata_prioritization_over_clips(self) -> None:
        # Enqueue 2 metadata events
        ev1 = make_test_event()
        stream_session_id = str(ev1["stream_session_id"])
        ev1_payload = ev1["payload"]
        assert isinstance(ev1_payload, dict)
        ev1_payload["evidence_requests"] = [
            make_evidence_request("clip-req-1", stream_session_id, "synthetic", 10.0)
        ]
        ev2 = make_test_event()
        self.outbox.enqueue(ev1)
        self.outbox.enqueue(ev2)

        # Mock uploader
        mock_uploader = MagicMock()
        mock_uploader.upload_pending.return_value = 1

        sent_events: list[str] = []

        def mock_sender(item: dict[str, object]) -> dict[str, object]:
            sent_events.append(str(item["message_id"]))
            return make_valid_receipt(item)

        coordinator = WanOutageCoordinator(
            outbox=self.outbox,
            uploader=mock_uploader,
            event_sender=mock_sender,
            clock_fn=self._clock,
        )

        self.assertEqual(len(self.outbox.pending()), 2)

        # In step 1: flush 1 metadata event
        step1 = coordinator.drain_step(metadata_batch=1, clip_batch=1)
        self.assertEqual(step1["metadata_delivered"], 1)
        # Clip upload MUST be deferred because metadata is still pending!
        self.assertEqual(step1["clips_uploaded"], 0)
        mock_uploader.upload_pending.assert_not_called()
        self.assertEqual(len(self.outbox.pending()), 1)

        # In step 2: flush remaining metadata event
        step2 = coordinator.drain_step(metadata_batch=10, clip_batch=1)
        self.assertEqual(step2["metadata_delivered"], 1)
        # All metadata delivered in step 2! Now clips are allowed to upload
        self.assertEqual(step2["clips_uploaded"], 1)
        mock_uploader.upload_pending.assert_called_once()
        self.assertEqual(len(self.outbox.pending()), 0)

    def test_network_failure_backoff_and_zero_data_loss(self) -> None:
        ev = make_test_event()
        msg_id = self.outbox.enqueue(ev)

        attempts_made = 0
        delays_slept: list[float] = []

        def failing_sender(item: dict[str, object]) -> dict[str, object]:
            nonlocal attempts_made
            attempts_made += 1
            raise URLError("Connection refused: WAN network down")

        def mock_sleep(d: float) -> None:
            delays_slept.append(d)

        coordinator = WanOutageCoordinator(
            outbox=self.outbox,
            event_sender=failing_sender,
            clock_fn=self._clock,
            sleep_fn=mock_sleep,
            max_retries=2,
            backoff_base=1.0,
            max_backoff=4.0,
            jitter=False,
        )

        # Flush metadata
        delivered = coordinator.flush_pending_metadata()
        self.assertEqual(delivered, 0)

        # Retries made: initial + 2 retries = 3 attempts
        self.assertEqual(attempts_made, 3)
        self.assertEqual(delays_slept, [1.0, 2.0])

        # Coordinator transitioned to offline upon network failure
        self.assertFalse(coordinator.is_online)

        # CRITICAL ACCEPTANCE: Event must NOT be dropped or deleted!
        pending = self.outbox.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["message_id"], msg_id)
        self.assertEqual(pending[0]["attempts"], 3)

    def test_resume_and_drain_all_with_verification(self) -> None:
        # Enqueue 3 events
        evs = [make_test_event() for _ in range(3)]
        for ev in evs:
            self.outbox.enqueue(ev)

        self.assertEqual(len(self.outbox.pending()), 3)

        sent_messages: list[str] = []

        def mock_sender(item: dict[str, object]) -> dict[str, object]:
            sent_messages.append(str(item["message_id"]))
            return make_valid_receipt(item)

        coordinator = WanOutageCoordinator(
            outbox=self.outbox,
            event_sender=mock_sender,
            clock_fn=self._clock,
        )

        # Simulate network restored, drain all
        drain_stats = coordinator.drain_all()
        self.assertTrue(drain_stats["online"])
        self.assertEqual(drain_stats["total_metadata_delivered"], 3)
        self.assertEqual(len(self.outbox.pending()), 0)
        self.assertEqual(drain_stats["final_backlog_bytes"], 0)

        # Mathematical verification of drain trajectory
        verification = coordinator.verify_drain_trajectory(
            upload_rate=50_000.0,
            generation_rate=10_000.0,
            start_backlog_bytes=drain_stats["initial_backlog_bytes"],
            measured_drain_time=0.1,
            tolerance_fraction=0.5,
        )
        self.assertTrue(verification.within_tolerance)
        self.assertEqual(verification.status, STATUS_VERIFIED)


if __name__ == "__main__":
    unittest.main()
