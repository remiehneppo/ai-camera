"""Comprehensive unit and scenario tests for Ticket #47: Vehicle Motion & Suspected-Incident Flow.

Covers:
- Domain Vehicle Motion (Tasks M01 & M02):
  * Kinematics & trajectory smoothing (cx, cy, vx, vy, speed, acceleration, heading).
  * Robust time handling (variable dt, timestamp jitter, track gaps, predictions, epoch/session resets).
  * Pairwise interaction & TTC risk in image space (closing speed, IoU, expansion rate, risk levels,
    enforcing that TTC/overlap alone does NOT prove collision).
- Edge Vehicle Incident Engine (Task I06 / US08):
  * 3 US08 Branches:
    1) vehicle_vehicle: converging vehicles with sudden deceleration / post-collision halt / deflection.
    2) vehicle_pedestrian: vehicle & pedestrian convergence, rapid deceleration or person down.
    3) vehicle_rollover_or_barrier: two-wheeler/car rollover or barrier crash with abrupt stop.
  * 4 Hard Negatives Rejections:
    - Red-light stop / traffic jam.
    - Near-miss.
    - Perspective overlap.
    - Stationary vehicle without prior motion.
  * Full snapshot validation against domain.event_contract.validate_event:
    - pipeline_id: "vehicle-incident-pipeline-v1"
    - pipeline_version: "1"
    - payload["taxonomy"]: "vehicle_incident"
    - payload["interaction_type"]: vehicle_vehicle | vehicle_pedestrian | vehicle_rollover_or_barrier
    - payload["severity"]: critical | high
    - evidence_requests with Q36 anchor: evidence_anchor_kind="alert_condition", [-10s, +20s].
"""

from __future__ import annotations

import math
import unittest
from uuid import uuid4

from apps.edge.tracker import Track
from apps.edge.vehicle_incident import (
    PEDESTRIAN_LABELS,
    TWO_WHEELER_LABELS,
    VEHICLE_LABELS,
    VehicleIncidentEngine,
    point_in_polygon,
)
from domain.event_contract import validate_event
from domain.evidence_contract import make_evidence_request, validate_evidence_request
from domain.vehicle_motion import (
    KinematicsTracker,
    KinematicState,
    PairwiseInteractionRisk,
    bbox_iou,
    check_collision_evidence,
    compute_pairwise_risk,
)


def _make_track(
    track_id: int,
    bbox: list[float],
    timestamp: float,
    label: str = "car",
    score: float = 0.95,
) -> Track:
    return Track(
        track_id=track_id,
        bbox=bbox,
        score=score,
        label=label,
        timestamp=timestamp,
    )


class TestEvidenceContractAlertCondition(unittest.TestCase):
    """Test Q36 alert_condition anchor kind in domain/evidence_contract.py."""

    def test_alert_condition_anchor_kind_is_accepted(self) -> None:
        session_id = str(uuid4())
        req = make_evidence_request(
            request_id="req-alert-001",
            session_id=session_id,
            anchor_kind="alert_condition",
            anchor_time=100.0,
        )
        self.assertEqual(req["evidence_anchor_kind"], "alert_condition")
        self.assertEqual(req["evidence_anchor_time"], 100.0)
        self.assertEqual(req["requested_start"], 90.0)
        self.assertEqual(req["requested_end"], 120.0)
        self.assertEqual(req["policy_version"], "lab-pre10-post20-v1")

    def test_invalid_anchor_kind_still_rejected(self) -> None:
        session_id = str(uuid4())
        with self.assertRaises(ValueError):
            make_evidence_request(
                request_id="req-alert-002",
                session_id=session_id,
                anchor_kind="invalid_kind",
                anchor_time=100.0,
            )


class TestVehicleMotionKinematics(unittest.TestCase):
    """M01: Kinematics and trajectory smoothing."""

    def test_straight_line_motion(self) -> None:
        tracker = KinematicsTracker()
        # Object moves horizontally at constant 100 px/s: x = 100 * t, y = 50.0
        state = KinematicState(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, True)
        for i in range(15):
            t = round(i * 0.1, 2)
            cx = 100.0 * t
            cy = 50.0
            state = tracker.update(timestamp=t, cx=cx, cy=cy)

        # After smoothing converges, speed should be ~100 px/s, heading ~ 0.0 rad
        self.assertAlmostEqual(state.vx, 100.0, delta=10.0)
        self.assertAlmostEqual(state.vy, 0.0, delta=5.0)
        self.assertAlmostEqual(state.speed, 100.0, delta=10.0)
        self.assertAlmostEqual(state.heading, 0.0, delta=0.1)
        self.assertFalse(state.is_stationary)
        # Constant velocity -> acceleration near 0
        self.assertAlmostEqual(state.acceleration, 0.0, delta=15.0)

    def test_variable_dt_does_not_spike_acceleration(self) -> None:
        tracker = KinematicsTracker()
        # Variable intervals: 0.05s, 0.12s, 0.08s, 0.15s, etc.
        intervals = [0.05, 0.12, 0.08, 0.15, 0.06, 0.14, 0.09, 0.11]
        t = 0.0
        x = 0.0
        v_const = 80.0
        tracker.update(timestamp=0.0, cx=0.0, cy=0.0)

        max_scalar_acc = 0.0
        for dt in intervals * 3:
            t = round(t + dt, 4)
            x += v_const * dt
            state = tracker.update(timestamp=t, cx=x, cy=0.0)
            if t > 0.4:  # allow initial warmup
                max_scalar_acc = max(max_scalar_acc, state.scalar_acceleration)

        # Variable dt must NOT create artificial acceleration spikes (> 30 px/s^2)
        self.assertLess(max_scalar_acc, 30.0)

    def test_timestamp_jitter_does_not_create_false_acceleration_spike(self) -> None:
        tracker = KinematicsTracker()
        # Normal frames at ~10 FPS with occasional millisecond jitter frames (dt = 0.002s)
        timestamps = [0.0, 0.10, 0.20, 0.202, 0.30, 0.40, 0.403, 0.50, 0.60]
        max_acc = 0.0
        for t in timestamps:
            x = 100.0 * t
            state = tracker.update(timestamp=t, cx=x, cy=100.0)
            if t > 0.25:
                max_acc = max(max_acc, abs(state.acceleration))

        # A naive (v2-v1)/0.002 would spike to thousands of px/s^2.
        # Robust filter must keep acceleration bounded (< 40 px/s^2).
        self.assertLess(max_acc, 40.0)

    def test_track_gap_resets_history_without_spike(self) -> None:
        tracker = KinematicsTracker(max_observation_gap=1.0)
        # Normal motion at 100 px/s up to t=0.5
        for i in range(6):
            t = i * 0.1
            tracker.update(timestamp=t, cx=100.0 * t, cy=0.0)

        # Large gap: 2.0s gap (t jumps to 2.5s)
        state_after_gap = tracker.update(timestamp=2.5, cx=500.0, cy=0.0)
        # Must reset: velocity and acceleration set to 0, no enormous spike from (500 - 50)/2.0
        self.assertEqual(state_after_gap.acceleration, 0.0)
        self.assertEqual(state_after_gap.speed, 0.0)
        self.assertTrue(state_after_gap.is_stationary)

    def test_epoch_change_resets_history(self) -> None:
        tracker = KinematicsTracker()
        tracker.update(timestamp=1.0, cx=100.0, cy=0.0, epoch=1)
        tracker.update(timestamp=1.1, cx=110.0, cy=0.0, epoch=1)
        # Epoch increments -> discontinuity
        state = tracker.update(timestamp=1.2, cx=200.0, cy=0.0, epoch=2)
        self.assertEqual(state.acceleration, 0.0)
        self.assertEqual(state.speed, 0.0)

    def test_session_discontinuity_resets_history(self) -> None:
        tracker = KinematicsTracker()
        tracker.update(timestamp=1.0, cx=100.0, cy=0.0, session_id="sess-A")
        tracker.update(timestamp=1.1, cx=110.0, cy=0.0, session_id="sess-A")
        # Session changes -> discontinuity
        state = tracker.update(timestamp=1.2, cx=200.0, cy=0.0, session_id="sess-B")
        self.assertEqual(state.acceleration, 0.0)
        self.assertEqual(state.speed, 0.0)

    def test_predicted_observation_does_not_create_acceleration_spike(self) -> None:
        tracker = KinematicsTracker()
        for i in range(5):
            t = i * 0.1
            tracker.update(timestamp=t, cx=80.0 * t, cy=0.0)

        # Predicted update (e.g. lost detector measurement)
        state_pred = tracker.update(timestamp=0.5, cx=40.0, cy=0.0, is_predicted=True)
        self.assertTrue(state_pred.is_predicted)
        self.assertEqual(state_pred.acceleration, 0.0)
        self.assertEqual(state_pred.scalar_acceleration, 0.0)


class TestPairwiseInteractionAndTTC(unittest.TestCase):
    """M02: Pairwise interaction & TTC risk in image space."""

    def test_converging_vehicles_escalate_risk_level(self) -> None:
        # Car 1 at x=100 moving right at 50 px/s
        k1 = KinematicState(
            timestamp=1.0, cx=100.0, cy=200.0, vx=50.0, vy=0.0,
            speed=50.0, ax=0.0, ay=0.0, acceleration=0.0, scalar_acceleration=0.0,
            heading=0.0, is_stationary=False,
        )
        box1 = [70.0, 180.0, 130.0, 220.0]

        # Car 2 at x=300 moving left at 50 px/s (head-on convergence)
        k2 = KinematicState(
            timestamp=1.0, cx=300.0, cy=200.0, vx=-50.0, vy=0.0,
            speed=50.0, ax=0.0, ay=0.0, acceleration=0.0, scalar_acceleration=0.0,
            heading=math.pi, is_stationary=False,
        )
        box2 = [270.0, 180.0, 330.0, 220.0]

        risk = compute_pairwise_risk(1, k1, box1, 2, k2, box2)
        self.assertAlmostEqual(risk.distance, 200.0)
        self.assertAlmostEqual(risk.closing_speed, 100.0)
        self.assertAlmostEqual(risk.ttc, 2.0)
        self.assertEqual(risk.risk_level, "high")
        # Critical rule: TTC/overlap alone does NOT prove collision!
        self.assertFalse(risk.is_collision_proven)

    def test_diverging_vehicles_produce_none_risk(self) -> None:
        # Car 1 moving left, Car 2 moving right (diverging)
        k1 = KinematicState(
            timestamp=1.0, cx=100.0, cy=200.0, vx=-50.0, vy=0.0,
            speed=50.0, ax=0.0, ay=0.0, acceleration=0.0, scalar_acceleration=0.0,
            heading=math.pi, is_stationary=False,
        )
        k2 = KinematicState(
            timestamp=1.0, cx=300.0, cy=200.0, vx=50.0, vy=0.0,
            speed=50.0, ax=0.0, ay=0.0, acceleration=0.0, scalar_acceleration=0.0,
            heading=0.0, is_stationary=False,
        )
        risk = compute_pairwise_risk(
            1, k1, [70.0, 180.0, 130.0, 220.0],
            2, k2, [270.0, 180.0, 330.0, 220.0],
        )
        self.assertLessEqual(risk.closing_speed, 0.0)
        self.assertEqual(risk.ttc, float("inf"))
        self.assertEqual(risk.risk_level, "none")
        self.assertFalse(risk.is_collision_proven)

    def test_expansion_rate_computed_from_iou_delta(self) -> None:
        box1 = [100.0, 100.0, 200.0, 200.0]
        box2 = [150.0, 100.0, 250.0, 200.0]
        k1 = KinematicState(0, 150, 150, 0, 0, 0, 0, 0, 0, 0, 0, True)
        k2 = KinematicState(0, 200, 150, 0, 0, 0, 0, 0, 0, 0, 0, True)

        curr_iou = bbox_iou(box1, box2)
        risk = compute_pairwise_risk(
            1, k1, box1, 2, k2, box2,
            prev_iou=0.0, dt=0.1,
        )
        self.assertAlmostEqual(risk.expansion_rate, curr_iou / 0.1, delta=0.05)


class TestVehicleIncidentEngineBranches(unittest.TestCase):
    """I06: 3 US08 Branches + Event Contract Conformance."""

    def setUp(self) -> None:
        self.engine = VehicleIncidentEngine(
            camera_id="cam-urban-01",
            device_id="edge-dev-01",
            cooldown_seconds=5.0,
        )

    def test_branch_1_vehicle_vehicle_collision(self) -> None:
        """Two moving vehicles converge with sudden deceleration and post-collision halt."""
        t1 = _make_track(1, [100.0, 200.0, 160.0, 260.0], 0.0, label="car")
        t2 = _make_track(2, [400.0, 200.0, 460.0, 260.0], 0.0, label="car")

        events = []
        # Phase 1: Moving towards each other at 100 px/s (t=0.0 to 1.0)
        for i in range(1, 11):
            t = round(i * 0.1, 2)
            # t1 moves right: cx goes from 130 to 230
            # t2 moves left: cx goes from 430 to 330
            b1 = [100.0 + i * 10.0, 200.0, 160.0 + i * 10.0, 260.0]
            b2 = [400.0 - i * 10.0, 200.0, 460.0 - i * 10.0, 260.0]
            t1.update(b1, score=0.92, timestamp=t)
            t2.update(b2, score=0.91, timestamp=t)
            evs = self.engine.process_tracks([t1, t2], timestamp=t)
            events.extend(evs)

        self.assertEqual(len(events), 0, "No event during initial normal convergence")

        # Phase 2: Collision impact at t=1.1 (overlap, sudden deceleration spike, followed by halt)
        impact_b1 = [210.0, 200.0, 270.0, 260.0]
        impact_b2 = [240.0, 200.0, 300.0, 260.0]  # overlap with b1
        t1.update(impact_b1, score=0.90, timestamp=1.1)
        t2.update(impact_b2, score=0.90, timestamp=1.1)
        evs = self.engine.process_tracks([t1, t2], timestamp=1.1)
        events.extend(evs)

        # Halt phase: vehicles stop at impact position
        for step in range(2, 6):
            t = round(1.0 + step * 0.1, 2)
            t1.update(impact_b1, score=0.90, timestamp=t)
            t2.update(impact_b2, score=0.90, timestamp=t)
            evs = self.engine.process_tracks([t1, t2], timestamp=t)
            events.extend(evs)

        self.assertGreaterEqual(len(events), 1, "Vehicle-vehicle crash must trigger an event")
        ev = events[0]
        # Conformance check with domain.event_contract.validate_event
        validate_event(ev)

        self.assertEqual(ev["pipeline_id"], "vehicle-incident-pipeline-v1")
        self.assertEqual(ev["pipeline_version"], "1")
        self.assertEqual(ev["payload"]["taxonomy"], "vehicle_incident")
        self.assertEqual(ev["payload"]["interaction_type"], "vehicle_vehicle")
        self.assertIn(ev["payload"]["severity"], ("critical", "high"))
        self.assertIn(1, ev["payload"]["track_ids"])
        self.assertIn(2, ev["payload"]["track_ids"])

        # Q36 Evidence request anchor check
        req = ev["payload"]["evidence_requests"][0]
        self.assertEqual(req["evidence_anchor_kind"], "alert_condition")
        anchor = req["evidence_anchor_time"]
        self.assertEqual(req["requested_start"], anchor - 10)
        self.assertEqual(req["requested_end"], anchor + 20)

    def test_branch_2_vehicle_pedestrian_incident(self) -> None:
        """Vehicle and pedestrian converge, followed by pedestrian impact / person down."""
        v_track = _make_track(10, [100.0, 200.0, 180.0, 260.0], 0.0, label="car")
        p_track = _make_track(20, [260.0, 200.0, 300.0, 280.0], 0.0, label="person")  # AR = 40/80 = 0.5 (standing)

        events = []
        # Car approaches pedestrian
        for i in range(1, 10):
            t = round(i * 0.1, 2)
            v_bbox = [100.0 + i * 15.0, 200.0, 180.0 + i * 15.0, 260.0]
            v_track.update(v_bbox, score=0.95, timestamp=t)
            p_track.update([260.0, 200.0, 300.0, 280.0], score=0.92, timestamp=t)
            evs = self.engine.process_tracks([v_track, p_track], timestamp=t)
            events.extend(evs)

        # Impact at t=1.0: pedestrian knocked down (lying aspect ratio 120 wide x 40 tall: AR = 3.0 >= 1.2)
        v_track.update([240.0, 200.0, 320.0, 260.0], score=0.90, timestamp=1.0)
        p_track.update([250.0, 240.0, 370.0, 280.0], score=0.88, timestamp=1.0)
        evs = self.engine.process_tracks([v_track, p_track], timestamp=1.0)
        events.extend(evs)

        self.assertGreaterEqual(len(events), 1, "Vehicle-pedestrian impact must trigger an event")
        ev = events[0]
        validate_event(ev)

        self.assertEqual(ev["payload"]["taxonomy"], "vehicle_incident")
        self.assertEqual(ev["payload"]["interaction_type"], "vehicle_pedestrian")
        self.assertEqual(ev["payload"]["severity"], "critical")
        self.assertEqual(ev["payload"]["evidence_requests"][0]["evidence_anchor_kind"], "alert_condition")

    def test_branch_3a_two_wheeler_rollover(self) -> None:
        """Two-wheeler moving and then experiencing sudden aspect ratio inversion (fallen over)."""
        moto = _make_track(30, [100.0, 200.0, 150.0, 300.0], 0.0, label="motorcycle")  # w=50, h=100 -> AR=0.5 (upright)

        events = []
        # Moving upright for 10 frames
        for i in range(1, 11):
            t = round(i * 0.1, 2)
            moto.update([100.0 + i * 10.0, 200.0, 150.0 + i * 10.0, 300.0], score=0.94, timestamp=t)
            evs = self.engine.process_tracks([moto], timestamp=t)
            events.extend(evs)

        # Falls over at t=1.1: w=120, h=50 -> AR=2.4 >= 1.2
        fallen_bbox = [210.0, 260.0, 330.0, 310.0]
        moto.update(fallen_bbox, score=0.91, timestamp=1.1)
        evs = self.engine.process_tracks([moto], timestamp=1.1)
        events.extend(evs)

        self.assertGreaterEqual(len(events), 1, "Two-wheeler rollover must trigger an incident")
        ev = events[0]
        validate_event(ev)

        self.assertEqual(ev["payload"]["taxonomy"], "vehicle_incident")
        self.assertEqual(ev["payload"]["interaction_type"], "vehicle_rollover_or_barrier")
        self.assertEqual(ev["payload"]["severity"], "critical")
        self.assertEqual(ev["payload"]["evidence_requests"][0]["evidence_anchor_kind"], "alert_condition")

    def test_branch_3b_vehicle_barrier_crash(self) -> None:
        """Vehicle moving at high speed crashes into barrier/curb and stops abruptly."""
        car = _make_track(40, [100.0, 200.0, 180.0, 260.0], 0.0, label="car")

        events = []
        # High speed approach: 150 px/s (15 px per 0.1s)
        for i in range(1, 11):
            t = round(i * 0.1, 2)
            car.update([100.0 + i * 15.0, 200.0, 180.0 + i * 15.0, 260.0], score=0.95, timestamp=t)
            evs = self.engine.process_tracks([car], timestamp=t)
            events.extend(evs)

        # Abrupt impact stop at t=1.1 against barrier
        barrier_bbox = [250.0, 200.0, 330.0, 260.0]
        for step in range(1, 6):
            t = round(1.0 + step * 0.1, 2)
            car.update(barrier_bbox, score=0.92, timestamp=t)
            evs = self.engine.process_tracks([car], timestamp=t)
            events.extend(evs)

        self.assertGreaterEqual(len(events), 1, "Barrier crash with sudden deceleration into stationary state must trigger")
        ev = events[0]
        validate_event(ev)
        self.assertEqual(ev["payload"]["interaction_type"], "vehicle_rollover_or_barrier")


class TestVehicleIncidentHardNegatives(unittest.TestCase):
    """Hard Negatives Rejection (Ticket #47 / US08)."""

    def setUp(self) -> None:
        self.engine = VehicleIncidentEngine(
            camera_id="cam-urban-01",
            device_id="edge-dev-01",
        )

    def test_negative_1_red_light_stop_and_traffic_jam(self) -> None:
        """Smooth deceleration into upright stationary state without deceleration spike must NOT trigger."""
        car = _make_track(100, [100.0, 200.0, 180.0, 260.0], 0.0, label="car")

        events = []
        # Car smoothly decelerates from 60 px/s to 0 over 2.5 seconds (acceleration ~ -24 px/s^2, well above -120)
        t = 0.0
        x = 100.0
        speed = 60.0
        for i in range(1, 26):
            t = round(i * 0.1, 2)
            speed = max(0.0, 60.0 - (i * 2.4))  # smooth deceleration
            x += speed * 0.1
            car.update([x, 200.0, x + 80.0, 260.0], score=0.95, timestamp=t)
            evs = self.engine.process_tracks([car], timestamp=t)
            events.extend(evs)

        # Vehicle is now stationary at red light for another 2 seconds
        for i in range(26, 46):
            t = round(i * 0.1, 2)
            car.update([x, 200.0, x + 80.0, 260.0], score=0.95, timestamp=t)
            evs = self.engine.process_tracks([car], timestamp=t)
            events.extend(evs)

        self.assertEqual(len(events), 0, "Red light stop must NOT trigger any incident event")

    def test_negative_2_near_miss_smooth_pass(self) -> None:
        """Vehicles converge with high closing speed (low TTC) but pass smoothly without collision."""
        # Car 1 moves from left to right at y=200
        # Car 2 moves from right to left at y=280 (adjacent lane)
        c1 = _make_track(201, [50.0, 180.0, 130.0, 240.0], 0.0, label="car")
        c2 = _make_track(202, [450.0, 260.0, 530.0, 320.0], 0.0, label="car")

        events = []
        # 20 frames of smooth passing
        for i in range(1, 21):
            t = round(i * 0.1, 2)
            b1 = [50.0 + i * 20.0, 180.0, 130.0 + i * 20.0, 240.0]
            b2 = [450.0 - i * 20.0, 260.0, 530.0 - i * 20.0, 320.0]
            c1.update(b1, score=0.95, timestamp=t)
            c2.update(b2, score=0.95, timestamp=t)
            evs = self.engine.process_tracks([c1, c2], timestamp=t)
            events.extend(evs)

        self.assertEqual(len(events), 0, "Near-miss passing smoothly without stoppage or impact must NOT trigger")

    def test_negative_3_perspective_overlap(self) -> None:
        """Distant/background 2D overlap without convergence velocity or abrupt motion change."""
        # Car 1 driving steadily at y=100 (distant lane)
        # Car 2 driving steadily at y=120 (same general area in 2D image, overlapping bounding boxes)
        c1 = _make_track(301, [200.0, 100.0, 280.0, 150.0], 0.0, label="car")
        c2 = _make_track(302, [220.0, 110.0, 300.0, 160.0], 0.0, label="car")  # IoU > 0.4

        events = []
        for i in range(1, 16):
            t = round(i * 0.1, 2)
            b1 = [200.0 + i * 5.0, 100.0, 280.0 + i * 5.0, 150.0]
            b2 = [220.0 + i * 5.0, 110.0, 300.0 + i * 5.0, 160.0]  # moving in parallel
            c1.update(b1, score=0.95, timestamp=t)
            c2.update(b2, score=0.95, timestamp=t)
            evs = self.engine.process_tracks([c1, c2], timestamp=t)
            events.extend(evs)

        self.assertEqual(len(events), 0, "Perspective overlap without convergence or deceleration must NOT trigger")

    def test_negative_4_stationary_vehicle_without_prior_motion(self) -> None:
        """Stationary vehicle from frame 0 is NOT treated as a crash confirmation."""
        # A parked car sitting still
        parked_car = _make_track(401, [150.0, 150.0, 230.0, 210.0], 0.0, label="car")

        events = []
        for i in range(1, 25):
            t = round(i * 0.1, 2)
            parked_car.update([150.0, 150.0, 230.0, 210.0], score=0.94, timestamp=t)
            evs = self.engine.process_tracks([parked_car], timestamp=t)
            events.extend(evs)

        self.assertEqual(len(events), 0, "Parked vehicle without prior motion must NOT trigger crash")


class TestVehicleIncidentROIAndLifecycle(unittest.TestCase):
    """ROI filtering, cooldown, and lifecycle operations."""

    def test_tracks_outside_roi_are_ignored(self) -> None:
        # Define a roadway polygon around [200..600, 200..600]
        roi = [[200.0, 200.0], [600.0, 200.0], [600.0, 600.0], [200.0, 600.0]]
        engine = VehicleIncidentEngine(roi_polygon=roi)

        # Motorcycle falls outside ROI at [50, 50]
        moto = _make_track(501, [20.0, 20.0, 70.0, 120.0], 0.0, label="motorcycle")
        for i in range(1, 10):
            t = round(i * 0.1, 2)
            moto.update([20.0 + i * 5.0, 20.0, 70.0 + i * 5.0, 120.0], score=0.92, timestamp=t)
            evs = engine.process_tracks([moto], timestamp=t)
            self.assertEqual(len(evs), 0)

        # Fall over outside ROI
        moto.update([65.0, 50.0, 165.0, 90.0], score=0.90, timestamp=1.0)
        evs = engine.process_tracks([moto], timestamp=1.0)
        self.assertEqual(len(evs), 0, "Rollover outside roadway ROI must be ignored")

    def test_observation_gap_resets_engine(self) -> None:
        engine = VehicleIncidentEngine()
        car = _make_track(601, [100.0, 100.0, 180.0, 160.0], 0.0, label="car")
        for i in range(1, 10):
            t = round(i * 0.1, 2)
            car.update([100.0 + i * 10.0, 100.0, 180.0 + i * 10.0, 160.0], score=0.9, timestamp=t)
            engine.process_tracks([car], timestamp=t)

        engine.observation_gap()
        # After gap, kinematics is reset
        state = engine._tracks.get(601)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertIsNone(state.last_kinematics)

    def test_reset_clears_all_tracks_and_pairs(self) -> None:
        engine = VehicleIncidentEngine()
        car = _make_track(701, [100.0, 100.0, 180.0, 160.0], 0.0, label="car")
        engine.process_tracks([car], timestamp=0.1)
        self.assertEqual(len(engine._tracks), 1)

        engine.reset()
        self.assertEqual(len(engine._tracks), 0)
        self.assertEqual(len(engine._pairs), 0)


if __name__ == "__main__":
    unittest.main()
