"""Comprehensive unit and scenario tests for Ticket #62: Illegal Parking & Dwell Time (US05).

Covers:
- Edge Parking Incident Engine (Task Ticket #62 / US05):
  * ParkingIncidentEngine: independent state/config module per camera (factory: "illegal_parking").
  * Evaluates vehicle tracks (car, truck, bus, motorcycle) in parking-restricted ROI (point_in_polygon)
    and optional restricted schedule (ScheduleWindow).
  * Dwell time tracking: track vehicle position and stationarity. If a vehicle stays continuously
    stationary in the restricted ROI for duration T >= max_dwell_seconds, trigger a suspected event.
  * Rejects hard negatives:
    1) Normal driving / moving through: vehicle passing through ROI without staying stationary
       does NOT trigger.
    2) Red-light stop / traffic jam / temporary queue: vehicles that move before max_dwell_seconds
       do NOT trigger.
    3) Parking outside restricted schedule / allowed hours: does NOT trigger.
    4) Vehicle parked outside restricted ROI: does NOT trigger.
    5) Observation gap / track discontinuity: resets dwell timer (does not fabricate long dwell
       duration across gaps).
  * Generates valid full-snapshot event contracts passing domain.event_contract.validate_event:
    - pipeline_id: "parking-incident-pipeline-v1"
    - pipeline_version: "1"
    - payload["taxonomy"]: "illegal_parking"
    - payload["severity"]: "low" or "medium"
    - payload["dwell_seconds"]: measured dwell time
    - evidence_requests with Q36 anchor: evidence_anchor_kind="alert_condition",
      requested_start = anchor - 10, requested_end = anchor + 20.
  * Lifecycle operations: reset, observation_gap, per-camera state isolation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
from uuid import uuid4

from apps.edge.parking_incident import (
    DEFAULT_VEHICLE_LABELS,
    ParkingIncidentEngine,
    point_in_polygon,
)
from apps.edge.tracker import Track
from domain.alert_module_config import ScheduleWindow
from domain.event_contract import validate_event


def _make_track(
    track_id: int | str,
    bbox: list[float],
    timestamp: float,
    label: str = "car",
    score: float = 0.95,
) -> Track:
    return Track(
        track_id=int(track_id) if isinstance(track_id, int) else 1,
        bbox=bbox,
        score=score,
        label=label,
        timestamp=timestamp,
    )


class TestPointInPolygon(unittest.TestCase):
    """Test point_in_polygon ray casting helper."""

    def test_empty_or_small_polygon_returns_true(self) -> None:
        self.assertTrue(point_in_polygon(10.0, 10.0, None))
        self.assertTrue(point_in_polygon(10.0, 10.0, []))
        self.assertTrue(point_in_polygon(10.0, 10.0, [[0.0, 0.0], [10.0, 0.0]]))

    def test_point_inside_convex_polygon(self) -> None:
        poly = [[100.0, 100.0], [300.0, 100.0], [300.0, 300.0], [100.0, 300.0]]
        self.assertTrue(point_in_polygon(200.0, 200.0, poly))
        self.assertTrue(point_in_polygon(150.0, 150.0, poly))

    def test_point_outside_convex_polygon(self) -> None:
        poly = [[100.0, 100.0], [300.0, 100.0], [300.0, 300.0], [100.0, 300.0]]
        self.assertFalse(point_in_polygon(50.0, 50.0, poly))
        self.assertFalse(point_in_polygon(400.0, 200.0, poly))
        self.assertFalse(point_in_polygon(200.0, 500.0, poly))


class TestScheduleEvaluation(unittest.TestCase):
    """Test restricted schedule evaluation with ScheduleWindow and datetime / float timestamps."""

    def test_no_schedule_restricts_24_7(self) -> None:
        engine = ParkingIncidentEngine(schedule=None)
        # Any timestamp is restricted
        self.assertTrue(engine.is_in_schedule(1700000000.0))
        self.assertTrue(engine.is_in_schedule(datetime.now(timezone.utc)))

    def test_schedule_matching_window(self) -> None:
        # Wednesday 2026-04-15 10:00:00 UTC (second_of_day = 36000)
        dt_wed = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        schedule = [
            ScheduleWindow(days=("mon", "tue", "wed", "thu", "fri"), start_second=28800, end_second=61200)
        ]
        engine = ParkingIncidentEngine(schedule=schedule)

        # Within restricted schedule: Wednesday 10:00:00 (36000s in [28800, 61200])
        self.assertTrue(engine.is_in_schedule(dt_wed))
        self.assertTrue(engine.is_in_schedule(dt_wed.timestamp()))

    def test_schedule_outside_hours_allowed(self) -> None:
        # Wednesday 2026-04-15 06:00:00 UTC (second_of_day = 21600 < 28800)
        dt_early = datetime(2026, 4, 15, 6, 0, 0, tzinfo=timezone.utc)
        # Wednesday 2026-04-15 20:00:00 UTC (second_of_day = 72000 > 61200)
        dt_late = datetime(2026, 4, 15, 20, 0, 0, tzinfo=timezone.utc)
        schedule = [
            ScheduleWindow(days=("mon", "tue", "wed", "thu", "fri"), start_second=28800, end_second=61200)
        ]
        engine = ParkingIncidentEngine(schedule=schedule)

        self.assertFalse(engine.is_in_schedule(dt_early))
        self.assertFalse(engine.is_in_schedule(dt_late))

    def test_schedule_outside_days_allowed(self) -> None:
        # Sunday 2026-04-19 12:00:00 UTC
        dt_sun = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
        schedule = [
            ScheduleWindow(days=("mon", "tue", "wed", "thu", "fri"), start_second=28800, end_second=61200)
        ]
        engine = ParkingIncidentEngine(schedule=schedule)

        self.assertFalse(engine.is_in_schedule(dt_sun))

    def test_schedule_as_dict_format(self) -> None:
        dt_wed = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        schedule_dicts = [
            {"days": ["mon", "tue", "wed"], "start_second": 30000, "end_second": 40000}
        ]
        engine = ParkingIncidentEngine(schedule=schedule_dicts)
        self.assertTrue(engine.is_in_schedule(dt_wed))


class TestParkingIncidentDwellDetection(unittest.TestCase):
    """Test stationary dwell time tracking and full event contract generation."""

    def setUp(self) -> None:
        self.roi = [[100.0, 100.0], [400.0, 100.0], [400.0, 400.0], [100.0, 400.0]]
        self.engine = ParkingIncidentEngine(
            camera_id="cam-urban-01",
            device_id="device-edge-01",
            roi_polygon=self.roi,
            max_dwell_seconds=2.0,
            cooldown_seconds=30.0,
        )

    def test_stationary_vehicle_triggers_illegal_parking_event(self) -> None:
        # Vehicle stationary at [200, 200, 260, 260] inside ROI
        track_id = 101
        events: list[dict] = []

        # t = 0.0: first appearance
        t = _make_track(track_id, [200.0, 200.0, 260.0, 260.0], timestamp=0.0)
        evs = self.engine.process_tracks([t], timestamp=0.0)
        self.assertEqual(len(evs), 0)

        # t = 1.0: stationary for 1.0s < 2.0s
        t = _make_track(track_id, [200.0, 200.0, 260.0, 260.0], timestamp=1.0)
        evs = self.engine.process_tracks([t], timestamp=1.0)
        self.assertEqual(len(evs), 0)

        # t = 2.0: stationary for 2.0s >= 2.0s -> triggers!
        t = _make_track(track_id, [200.0, 200.0, 260.0, 260.0], timestamp=2.0)
        evs = self.engine.process_tracks([t], timestamp=2.0)
        self.assertEqual(len(evs), 1)

        event = evs[0]
        # Validate event schema and contract conformance
        validated = validate_event(event)
        self.assertEqual(validated["pipeline_id"], "parking-incident-pipeline-v1")
        self.assertEqual(validated["pipeline_version"], "1")
        self.assertEqual(validated["camera_id"], "cam-urban-01")
        self.assertEqual(validated["device_id"], "device-edge-01")

        payload = validated["payload"]
        self.assertEqual(payload["taxonomy"], "illegal_parking")
        self.assertEqual(payload["severity"], "low")
        self.assertAlmostEqual(payload["dwell_seconds"], 2.0, places=1)
        self.assertEqual(payload["track_id"], track_id)

        # Check Q36 evidence request
        reqs = payload["evidence_requests"]
        self.assertEqual(len(reqs), 1)
        req = reqs[0]
        self.assertEqual(req["evidence_anchor_kind"], "alert_condition")
        self.assertEqual(req["evidence_anchor_time"], 2.0)
        self.assertEqual(req["requested_start"], -8.0)  # 2.0 - 10
        self.assertEqual(req["requested_end"], 22.0)   # 2.0 + 20
        self.assertEqual(req["policy_version"], "lab-pre10-post20-v1")

    def test_alert_cooldown_prevents_spamming(self) -> None:
        track_id = 102
        # Advance to trigger at t=2.0
        for ts in (0.0, 1.0, 2.0):
            t = _make_track(track_id, [200.0, 200.0, 260.0, 260.0], timestamp=ts)
            evs = self.engine.process_tracks([t], timestamp=ts)

        self.assertEqual(len(evs), 1)

        # Continues staying stationary at t=3.0, 4.0, 5.0
        for ts in (3.0, 4.0, 5.0):
            t = _make_track(track_id, [200.0, 200.0, 260.0, 260.0], timestamp=ts)
            evs = self.engine.process_tracks([t], timestamp=ts)
            self.assertEqual(len(evs), 0, f"Spurious alert at ts={ts}")

    def test_configurable_severity_medium(self) -> None:
        engine = ParkingIncidentEngine(
            roi_polygon=self.roi,
            max_dwell_seconds=2.0,
            severity="medium",
        )
        for ts in (0.0, 1.0, 2.0):
            t = _make_track(103, [200.0, 200.0, 260.0, 260.0], timestamp=ts)
            evs = engine.process_tracks([t], timestamp=ts)

        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["severity"], "medium")


class TestHardNegatives(unittest.TestCase):
    """Test all 5 hard negatives required by Ticket #62 / US05."""

    def setUp(self) -> None:
        self.roi = [[100.0, 100.0], [400.0, 100.0], [400.0, 400.0], [100.0, 400.0]]
        self.schedule = [
            ScheduleWindow(days=("mon", "tue", "wed", "thu", "fri"), start_second=28800, end_second=61200)
        ]
        self.engine = ParkingIncidentEngine(
            roi_polygon=self.roi,
            schedule=self.schedule,
            max_dwell_seconds=3.0,
            max_observation_gap=1.0,
        )

    def test_hard_negative_1_normal_driving_moving_through(self) -> None:
        """1) Normal driving / moving through: vehicle passing through ROI without staying stationary does NOT trigger."""
        # Vehicle moving horizontally through ROI: cx advances by 30 px/s (speed = 30 px/s > 8.0 px/s)
        dt_wed = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        base_ts = dt_wed.timestamp()
        track_id = 201

        for step in range(10):
            ts = base_ts + step * 0.5
            x = 120.0 + step * 15.0  # moves 15 px every 0.5s -> 30 px/s
            t = _make_track(track_id, [x, 200.0, x + 50.0, 250.0], timestamp=ts)
            evs = self.engine.process_tracks([t], timestamp=ts)
            self.assertEqual(len(evs), 0, f"False positive during normal driving at step {step}")

        state = self.engine.get_track_state(track_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertFalse(state.is_stationary)
        self.assertIsNone(state.dwell_start_time)

    def test_hard_negative_2_red_light_stop_temporary_queue(self) -> None:
        """2) Red-light stop / traffic jam / temporary queue: vehicles that move before max_dwell_seconds do NOT trigger."""
        dt_wed = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        base_ts = dt_wed.timestamp()
        track_id = 202

        # Stops at red light for 2.0s (max_dwell is 3.0s)
        for step in range(3):
            ts = base_ts + step * 1.0
            t = _make_track(track_id, [200.0, 200.0, 250.0, 250.0], timestamp=ts)
            evs = self.engine.process_tracks([t], timestamp=ts)
            self.assertEqual(len(evs), 0)

        # Light turns green: vehicle accelerates away at ts = base_ts + 3.0s
        ts_green = base_ts + 3.0
        t_moving = _make_track(track_id, [240.0, 200.0, 290.0, 250.0], timestamp=ts_green)
        evs = self.engine.process_tracks([t_moving], timestamp=ts_green)
        self.assertEqual(len(evs), 0)

        # Continues moving away
        ts_away = base_ts + 4.0
        t_away = _make_track(track_id, [290.0, 200.0, 340.0, 250.0], timestamp=ts_away)
        evs = self.engine.process_tracks([t_away], timestamp=ts_away)
        self.assertEqual(len(evs), 0)

        state = self.engine.get_track_state(track_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertFalse(state.is_stationary)
        self.assertIsNone(state.dwell_start_time)

    def test_hard_negative_3_parking_outside_restricted_schedule(self) -> None:
        """3) Parking outside restricted schedule / allowed hours: does NOT trigger."""
        # Sunday 12:00:00 (outside restricted schedule: allowed parking day)
        dt_sun = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
        base_ts = dt_sun.timestamp()
        track_id = 203

        # Vehicle parks stationary for 10.0s in ROI (exceeds max_dwell 3.0s)
        for step in range(11):
            ts = base_ts + step * 1.0
            t = _make_track(track_id, [200.0, 200.0, 250.0, 250.0], timestamp=ts)
            evs = self.engine.process_tracks([t], timestamp=ts)
            self.assertEqual(len(evs), 0, f"False positive during allowed schedule at step {step}")

    def test_hard_negative_4_vehicle_parked_outside_restricted_roi(self) -> None:
        """4) Vehicle parked outside restricted ROI: does NOT trigger."""
        dt_wed = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        base_ts = dt_wed.timestamp()
        track_id = 204

        # Vehicle is parked at [500, 500, 550, 550], outside ROI [100, 100, 400, 400]
        for step in range(11):
            ts = base_ts + step * 1.0
            t = _make_track(track_id, [500.0, 500.0, 550.0, 550.0], timestamp=ts)
            evs = self.engine.process_tracks([t], timestamp=ts)
            self.assertEqual(len(evs), 0, f"False positive outside ROI at step {step}")

    def test_hard_negative_5_observation_gap_resets_dwell_timer(self) -> None:
        """5) Observation gap / track discontinuity: resets dwell timer (does not fabricate long dwell duration across gaps)."""
        dt_wed = datetime(2026, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        base_ts = dt_wed.timestamp()
        track_id = 205

        # Vehicle stationary for 2.0s (ts = 0.0, 1.0, 2.0; max_dwell = 3.0s)
        for step in (0, 1, 2):
            ts = base_ts + step * 1.0
            t = _make_track(track_id, [200.0, 200.0, 250.0, 250.0], timestamp=ts)
            evs = self.engine.process_tracks([t], timestamp=ts)
            self.assertEqual(len(evs), 0)

        # Large observation gap of 10.0 seconds (e.g. camera stream drops / occlusion)
        # Next frame is at base_ts + 12.0s (gap = 10.0s > max_observation_gap 1.0s)
        ts_after_gap = base_ts + 12.0
        t_gap = _make_track(track_id, [200.0, 200.0, 250.0, 250.0], timestamp=ts_after_gap)
        evs = self.engine.process_tracks([t_gap], timestamp=ts_after_gap)

        # Must NOT trigger! The 10s gap must not be fabricated into a 12s dwell.
        self.assertEqual(len(evs), 0, "Dwell duration falsely fabricated across observation gap")

        state = self.engine.get_track_state(track_id)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertAlmostEqual(state.dwell_seconds, 0.0)


class TestLifecycleAndMultiCamera(unittest.TestCase):
    """Test engine lifecycle operations, multi-camera isolation, and multi-track scenes."""

    def test_reset_clears_all_tracks(self) -> None:
        engine = ParkingIncidentEngine()
        t = _make_track(301, [150.0, 150.0, 200.0, 200.0], timestamp=0.0)
        engine.process_tracks([t], timestamp=0.0)
        self.assertIsNotNone(engine.get_track_state(301))

        engine.reset()
        self.assertIsNone(engine.get_track_state(301))

    def test_observation_gap_method_resets_dwell(self) -> None:
        engine = ParkingIncidentEngine(max_dwell_seconds=5.0, max_observation_gap=1.0)
        for ts in (0.0, 1.0, 2.0):
            t = _make_track(302, [150.0, 150.0, 200.0, 200.0], timestamp=ts)
            engine.process_tracks([t], timestamp=ts)

        state = engine.get_track_state(302)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertAlmostEqual(state.dwell_seconds, 2.0)

        # Invoke explicit observation_gap lifecycle method
        engine.observation_gap()
        self.assertAlmostEqual(state.dwell_seconds, 0.0)
        self.assertIsNone(state.dwell_start_time)

    def test_multi_camera_state_isolation(self) -> None:
        """Two camera engines with different configs operate without state leakage."""
        cam1 = ParkingIncidentEngine(
            camera_id="cam-01",
            roi_polygon=[[0.0, 0.0], [200.0, 0.0], [200.0, 200.0], [0.0, 200.0]],
            max_dwell_seconds=2.0,
        )
        cam2 = ParkingIncidentEngine(
            camera_id="cam-02",
            roi_polygon=[[300.0, 300.0], [500.0, 300.0], [500.0, 500.0], [300.0, 500.0]],
            max_dwell_seconds=5.0,
        )

        t_cam1 = _make_track(1, [50.0, 50.0, 100.0, 100.0], timestamp=0.0)
        t_cam2 = _make_track(1, [50.0, 50.0, 100.0, 100.0], timestamp=0.0)  # outside cam2 ROI

        # Step cam1: inside cam1 ROI
        for ts in (0.0, 1.0, 2.0):
            evs1 = cam1.process_tracks([t_cam1], timestamp=ts)
        self.assertEqual(len(evs1), 1)

        # Step cam2: track 1 is outside cam2 ROI -> no alerts
        for ts in (0.0, 1.0, 2.0):
            evs2 = cam2.process_tracks([t_cam2], timestamp=ts)
        self.assertEqual(len(evs2), 0)

    def test_non_vehicle_labels_are_ignored(self) -> None:
        engine = ParkingIncidentEngine(max_dwell_seconds=2.0)
        # Person sitting/stationary in ROI
        for ts in (0.0, 1.0, 2.0):
            t_person = _make_track(401, [150.0, 150.0, 170.0, 200.0], timestamp=ts, label="person")
            evs = engine.process_tracks([t_person], timestamp=ts)
            self.assertEqual(len(evs), 0)

        self.assertIsNone(engine.get_track_state(401))

    def test_supported_vehicle_labels(self) -> None:
        """Vehicles (car, truck, bus, motorcycle) are all supported."""
        for label in DEFAULT_VEHICLE_LABELS:
            engine = ParkingIncidentEngine(max_dwell_seconds=2.0)
            for ts in (0.0, 1.0, 2.0):
                t = _make_track(501, [150.0, 150.0, 200.0, 200.0], timestamp=ts, label=label)
                evs = engine.process_tracks([t], timestamp=ts)
            self.assertEqual(len(evs), 1, f"Failed to detect illegal parking for {label}")

    def test_permitted_vehicle_exceptions_are_respected(self) -> None:
        """Vehicles matching configured exception codes do not trigger illegal parking."""
        from domain.alert_module_config import ExceptionRule
        engine = ParkingIncidentEngine(
            max_dwell_seconds=2.0,
            exceptions=[ExceptionRule(code="permit_car", reason="authorized municipal car")],
        )
        # Car stationary in ROI for 3 seconds
        for ts in (0.0, 1.0, 2.0, 3.0):
            t = _make_track(601, [150.0, 150.0, 200.0, 200.0], timestamp=ts, label="car")
            evs = engine.process_tracks([t], timestamp=ts)
            self.assertEqual(len(evs), 0, "Permitted exception must not trigger illegal parking")

    def test_multi_vehicle_scene(self) -> None:
        """A scene containing parked vehicle, moving vehicle, and vehicle outside ROI."""
        roi = [[100.0, 100.0], [400.0, 100.0], [400.0, 400.0], [100.0, 400.0]]
        engine = ParkingIncidentEngine(roi_polygon=roi, max_dwell_seconds=2.0)

        # Vehicle 1: parked in ROI at [150, 150, 200, 200]
        # Vehicle 2: driving across ROI: [150 + ts * 40, 250, 200 + ts * 40, 300]
        # Vehicle 3: parked outside ROI at [500, 500, 550, 550]
        for ts in (0.0, 1.0, 2.0):
            t1 = _make_track(1, [150.0, 150.0, 200.0, 200.0], timestamp=ts)
            t2 = _make_track(2, [150.0 + ts * 40.0, 250.0, 200.0 + ts * 40.0, 300.0], timestamp=ts)
            t3 = _make_track(3, [500.0, 500.0, 550.0, 550.0], timestamp=ts)
            evs = engine.process_tracks([t1, t2, t3], timestamp=ts)

        # Only vehicle 1 triggers!
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["track_id"], 1)


if __name__ == "__main__":
    unittest.main()
