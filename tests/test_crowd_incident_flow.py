"""Comprehensive unit and scenario tests for Ticket #63: Crowd Concentration & Suspected Disorder (US06).

Covers:
- Layer 1: Crowd Concentration (crowd_concentration):
  * Pedestrian count in ROI N >= min_crowd_count persisting for duration T >= min_duration_seconds.
  * Severity: "medium" (default) or "low", configurable.
  * Persistence duration, cooldown deduplication, and anchor calculation.
- Layer 2: Suspected Public Disorder (suspected_disorder):
  * Clustered pedestrians exhibiting rapid dispersive divergence (panic scattering).
  * Aggressive kinetic surging (high collective speed & acceleration).
  * Chaotic erratic conflicting motion among the crowd.
  * Severity: "high".
  * Explicitly enforces that crowd concentration alone does NOT imply disorder.
- 5 Hard Negatives Rejections:
  1) Normal orderly queue / bus stop line: steady or low velocity does NOT trigger disorder.
  2) Isolated individual running or waving hands: single person does NOT trigger crowd concentration or disorder.
  3) Transient pedestrian crossing / walking past: brief crossing (T < min_duration_seconds) does NOT trigger crowd concentration.
  4) Pedestrians outside restricted ROI: do NOT count towards crowd threshold.
  5) Observation gap / track discontinuity: resets persistence timer.
- Lifecycle & Operational Controls:
  * reset() clears all internal tracking state, persistence timers, and alert history.
  * observation_gap() resets kinematics and continuity across camera drops.
  * schedule_filter: active vs inactive schedule windows.
  * Multi-camera independence: multiple engine instances do not leak state.
  * Track format flexibility: supports both Track instances and dict representations.
- Rule Facts Validation:
  * Rule facts compliance (anchor_kind="alert_condition", payload scenario fields).
"""

from __future__ import annotations

import math
import unittest
from uuid import uuid4

from apps.edge.crowd_incident import (
    PEDESTRIAN_LABELS,
    CrowdIncidentEngine,
    point_in_polygon,
)
from apps.edge.tracker import Track
from domain.evidence_contract import make_evidence_request


def _make_track(
    track_id: int | str,
    cx: float,
    cy: float,
    timestamp: float,
    label: str = "person",
    score: float = 0.95,
    half_width: float = 15.0,
    height: float = 40.0,
) -> Track:
    """Helper to create a Track with specified center and foot position."""
    bbox = [
        cx - half_width,
        cy - height,
        cx + half_width,
        cy,
    ]
    return Track(
        track_id=track_id if isinstance(track_id, int) else hash(track_id) % 100000,
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


class TestCrowdIncidentEngineUnit(unittest.TestCase):
    """Unit tests for foundational functions and properties."""

    def test_point_in_polygon(self) -> None:
        poly = [[10.0, 10.0], [50.0, 10.0], [50.0, 50.0], [10.0, 50.0]]
        self.assertTrue(point_in_polygon(30.0, 30.0, poly))
        self.assertFalse(point_in_polygon(5.0, 5.0, poly))
        self.assertFalse(point_in_polygon(60.0, 60.0, poly))
        # None or degenerate polygon allows all points
        self.assertTrue(point_in_polygon(100.0, 100.0, None))
        self.assertTrue(point_in_polygon(100.0, 100.0, [[10.0, 10.0], [20.0, 20.0]]))

    def test_pedestrian_label_filtering(self) -> None:
        engine = CrowdIncidentEngine(min_crowd_count=3)
        ts = 100.0
        # 4 tracks, but 2 are non-pedestrian
        tracks = [
            _make_track(1, 100.0, 100.0, ts, label="person"),
            _make_track(2, 110.0, 100.0, ts, label="pedestrian"),
            _make_track(3, 120.0, 100.0, ts, label="car"),
            _make_track(4, 130.0, 100.0, ts, label="motorcycle"),
        ]
        events = engine.process_tracks(tracks, timestamp=ts)
        self.assertEqual(len(events), 0)
        self.assertEqual(engine.current_crowd_count, 2)

    def test_initialization_defaults_and_custom(self) -> None:
        engine = CrowdIncidentEngine(
            camera_id="cam-test-1",
            min_crowd_count=4,
            min_duration_seconds=2.5,
            crowd_severity="low",
            disorder_severity="high",
        )
        self.assertEqual(engine.camera_id, "cam-test-1")
        self.assertEqual(engine.factory, "crowd_incident")
        self.assertEqual(engine.min_crowd_count, 4)
        self.assertEqual(engine.min_duration_seconds, 2.5)
        self.assertEqual(engine.crowd_severity, "low")
        self.assertEqual(engine.disorder_severity, "high")
        self.assertEqual(engine.current_crowd_count, 0)
        self.assertFalse(engine.is_crowd_persisting)
        self.assertEqual(engine.crowd_persistence_duration, 0.0)

    def test_dict_track_support(self) -> None:
        engine = CrowdIncidentEngine(min_crowd_count=3, min_duration_seconds=1.0)
        tracks_dict = [
            {"track_id": 1, "bbox": [90.0, 60.0, 110.0, 100.0], "score": 0.95, "label": "person"},
            {"track_id": 2, "bbox": [110.0, 60.0, 130.0, 100.0], "score": 0.95, "label": "person"},
            {"track_id": 3, "bbox": [130.0, 60.0, 150.0, 100.0], "score": 0.95, "label": "person"},
        ]
        events0 = engine.process_tracks(tracks_dict, timestamp=10.0)
        self.assertEqual(len(events0), 0)
        self.assertEqual(engine.current_crowd_count, 3)
        self.assertTrue(engine.is_crowd_persisting)

        events1 = engine.process_tracks(tracks_dict, timestamp=11.0)
        self.assertEqual(len(events1), 1)
        self.assertEqual(events1[0]["payload"]["taxonomy"], "crowd_concentration")


class TestCrowdConcentrationLayer(unittest.TestCase):
    """Scenario tests for Layer 1: Crowd Concentration (crowd_concentration)."""

    def test_crowd_concentration_triggers_after_min_duration(self) -> None:
        engine = CrowdIncidentEngine(
            camera_id="cam-park-01",
            min_crowd_count=5,
            min_duration_seconds=3.0,
            crowd_severity="medium",
        )

        # 5 pedestrians standing from t=0.0 to t=2.0
        for t in [0.0, 1.0, 2.0]:
            tracks = [_make_track(i, 200.0 + i * 15.0, 200.0, t) for i in range(5)]
            events = engine.process_tracks(tracks, timestamp=t)
            self.assertEqual(len(events), 0, f"Must not trigger before 3.0s at t={t}")
            self.assertEqual(engine.current_crowd_count, 5)
            self.assertTrue(engine.is_crowd_persisting)

        # At t=3.0 (persisted for exactly 3.0s) -> triggers crowd_concentration
        tracks = [_make_track(i, 200.0 + i * 15.0, 200.0, 3.0) for i in range(5)]
        events = engine.process_tracks(tracks, timestamp=3.0)
        self.assertEqual(len(events), 1)

        event = events[0]
        self.assertEqual(event["anchor_kind"], "alert_condition")
        payload = event["payload"]
        self.assertEqual(payload["taxonomy"], "crowd_concentration")
        self.assertEqual(payload["severity"], "medium")
        self.assertEqual(payload["crowd_count"], 5)
        self.assertEqual(payload["anchor_time"], 3.0)
        self.assertEqual(payload["detection_time"], 3.0)
        self.assertEqual(len(payload["track_ids"]), 5)
        self.assertEqual(engine.rule_lineage, [{"role": "crowd_incident", "version": "1.0.0"}])

    def test_crowd_concentration_configurable_thresholds(self) -> None:
        engine = CrowdIncidentEngine(
            min_crowd_count=3,
            min_duration_seconds=1.5,
            crowd_severity="low",
        )
        tracks0 = [_make_track(i, 100.0 + i * 20.0, 100.0, 0.0) for i in range(3)]
        self.assertEqual(len(engine.process_tracks(tracks0, timestamp=0.0)), 0)

        tracks1 = [_make_track(i, 100.0 + i * 20.0, 100.0, 1.0) for i in range(3)]
        self.assertEqual(len(engine.process_tracks(tracks1, timestamp=1.0)), 0)

        tracks2 = [_make_track(i, 100.0 + i * 20.0, 100.0, 1.5) for i in range(3)]
        events = engine.process_tracks(tracks2, timestamp=1.5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["severity"], "low")
        self.assertEqual(events[0]["payload"]["crowd_count"], 3)

    def test_crowd_concentration_cooldown_prevents_duplicate_spam(self) -> None:
        engine = CrowdIncidentEngine(
            min_crowd_count=5,
            min_duration_seconds=3.0,
            cooldown_seconds=10.0,
        )

        # Trigger initial event at t=3.0
        for t in [0.0, 1.0, 2.0, 3.0]:
            tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, t) for i in range(5)]
            evs = engine.process_tracks(tracks, timestamp=t)
            if t == 3.0:
                self.assertEqual(len(evs), 1)

        # During cooldown (t=4.0 to t=12.0), no events emitted despite crowd persisting
        for t in [4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]:
            tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, t) for i in range(5)]
            evs = engine.process_tracks(tracks, timestamp=t)
            self.assertEqual(len(evs), 0, f"Duplicate alert should be suppressed during cooldown at t={t}")

        # At t=13.0 (cooldown elapsed: 13.0 - 3.0 = 10.0 >= cooldown_seconds) -> alert emitted
        tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, 13.0) for i in range(5)]
        evs = engine.process_tracks(tracks, timestamp=13.0)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["taxonomy"], "crowd_concentration")


class TestSuspectedDisorderLayer(unittest.TestCase):
    """Scenario tests for Layer 2: Suspected Public Disorder (suspected_disorder)."""

    def test_disorder_rapid_dispersal_divergence(self) -> None:
        """Test sudden dispersal divergence (e.g. panic scattering outwards)."""
        engine = CrowdIncidentEngine(
            min_crowd_count=5,
            min_disorder_count=3,
            disorder_severity="high",
        )

        # Frame 0: clustered closely at (200, 200) at t=0.0
        tracks0 = [
            _make_track(1, 195.0, 200.0, 0.0),
            _make_track(2, 205.0, 200.0, 0.0),
            _make_track(3, 200.0, 195.0, 0.0),
            _make_track(4, 200.0, 205.0, 0.0),
            _make_track(5, 200.0, 200.0, 0.0),
        ]
        evs0 = engine.process_tracks(tracks0, timestamp=0.0)
        self.assertEqual(len(evs0), 0)

        # Frame 1: scatter outwards rapidly at t=0.2 (speed ~ 75 px/s)
        tracks1 = [
            _make_track(1, 195.0 - 15.0, 200.0, 0.2),  # left (-75 px/s)
            _make_track(2, 205.0 + 15.0, 200.0, 0.2),  # right (+75 px/s)
            _make_track(3, 200.0, 195.0 - 15.0, 0.2),  # up (-75 px/s)
            _make_track(4, 200.0, 205.0 + 15.0, 0.2),  # down (+75 px/s)
            _make_track(5, 200.0 + 10.0, 200.0 + 10.0, 0.2),
        ]
        evs1 = engine.process_tracks(tracks1, timestamp=0.2)
        self.assertEqual(len(evs1), 1)

        event = evs1[0]
        self.assertEqual(event["payload"]["taxonomy"], "suspected_disorder")
        self.assertEqual(event["payload"]["severity"], "high")
        self.assertEqual(event["payload"]["crowd_count"], 5)
        self.assertIn("rapid_dispersal_divergence", event["payload"]["disorder_metrics"]["reasons"])
        self.assertGreater(event["payload"]["disorder_metrics"]["dispersal_rate"], 25.0)

        # Validate contract
        self.assertEqual(event["anchor_kind"], "alert_condition")

    def test_disorder_aggressive_kinetic_surge(self) -> None:
        """Test aggressive kinetic surging (multiple people surging with high speed & acceleration)."""
        engine = CrowdIncidentEngine(
            min_crowd_count=5,
            min_disorder_count=3,
            disorder_speed_threshold=45.0,
            disorder_acceleration_threshold=60.0,
        )

        tracks0 = [
            _make_track(1, 100.0, 100.0, 0.0),
            _make_track(2, 110.0, 100.0, 0.0),
            _make_track(3, 120.0, 100.0, 0.0),
            _make_track(4, 130.0, 100.0, 0.0),
        ]
        engine.process_tracks(tracks0, timestamp=0.0)

        # Surge at t=0.2 (moving 16px in 0.2s = 80 px/s, acceleration ~ 400 px/s^2)
        tracks1 = [
            _make_track(1, 100.0 + 16.0, 100.0, 0.2),
            _make_track(2, 110.0 + 16.0, 100.0, 0.2),
            _make_track(3, 120.0 + 16.0, 100.0, 0.2),
            _make_track(4, 130.0 + 16.0, 100.0, 0.2),
        ]
        evs = engine.process_tracks(tracks1, timestamp=0.2)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["taxonomy"], "suspected_disorder")
        self.assertEqual(evs[0]["payload"]["severity"], "high")
        self.assertIn("aggressive_kinetic_surge", evs[0]["payload"]["disorder_metrics"]["reasons"])

    def test_disorder_chaotic_erratic_motion(self) -> None:
        """Test turbulent/conflicting movement directions among crowd."""
        engine = CrowdIncidentEngine(
            min_crowd_count=4,
            min_disorder_count=3,
            disorder_direction_variance_threshold=0.5,
        )

        tracks0 = [
            _make_track(1, 200.0, 200.0, 0.0),
            _make_track(2, 210.0, 200.0, 0.0),
            _make_track(3, 200.0, 210.0, 0.0),
            _make_track(4, 210.0, 210.0, 0.0),
        ]
        engine.process_tracks(tracks0, timestamp=0.0)

        # Conflicting rapid motion at t=0.2
        tracks1 = [
            _make_track(1, 200.0 - 10.0, 200.0, 0.2),  # moving left
            _make_track(2, 210.0 + 10.0, 200.0, 0.2),  # moving right
            _make_track(3, 200.0, 210.0 - 10.0, 0.2),  # moving up
            _make_track(4, 210.0, 210.0 + 10.0, 0.2),  # moving down
        ]
        evs = engine.process_tracks(tracks1, timestamp=0.2)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["taxonomy"], "suspected_disorder")
        self.assertGreaterEqual(evs[0]["payload"]["disorder_metrics"]["direction_variance"], 0.5)


class TestLayerIndependence(unittest.TestCase):
    """Enforce that Layer 1 (Crowd Concentration) and Layer 2 (Suspected Disorder) are distinct and independent."""

    def test_crowd_concentration_alone_does_not_imply_disorder(self) -> None:
        """Explicitly verify US06 requirement: crowd concentration alone does NOT imply disorder."""
        engine = CrowdIncidentEngine(
            min_crowd_count=5,
            min_duration_seconds=3.0,
        )

        # 8 pedestrians stationary in a plaza for 5 seconds
        for t in [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]:
            tracks = [_make_track(i, 100.0 + i * 20.0, 100.0, t) for i in range(8)]
            evs = engine.process_tracks(tracks, timestamp=t)
            disorder_events = [e for e in evs if e["payload"]["taxonomy"] == "suspected_disorder"]
            self.assertEqual(len(disorder_events), 0, "Orderly crowd must NEVER trigger suspected_disorder")

            if t == 3.0:
                crowd_events = [e for e in evs if e["payload"]["taxonomy"] == "crowd_concentration"]
                self.assertEqual(len(crowd_events), 1)

    def test_disorder_before_crowd_duration_threshold(self) -> None:
        """Disorder can trigger immediately when kinetic threshold is met, even if duration < 3.0s."""
        engine = CrowdIncidentEngine(
            min_crowd_count=5,
            min_duration_seconds=3.0,
        )

        # Frame 0 at t=0.0
        tracks0 = [
            _make_track(1, 195.0, 200.0, 0.0),
            _make_track(2, 205.0, 200.0, 0.0),
            _make_track(3, 200.0, 195.0, 0.0),
            _make_track(4, 200.0, 205.0, 0.0),
            _make_track(5, 200.0, 200.0, 0.0),
        ]
        engine.process_tracks(tracks0, timestamp=0.0)

        # Frame 1 at t=0.2: sudden violent dispersal
        tracks1 = [
            _make_track(1, 195.0 - 15.0, 200.0, 0.2),
            _make_track(2, 205.0 + 15.0, 200.0, 0.2),
            _make_track(3, 200.0, 195.0 - 15.0, 0.2),
            _make_track(4, 200.0, 205.0 + 15.0, 0.2),
            _make_track(5, 200.0 + 10.0, 200.0 + 10.0, 0.2),
        ]
        evs = engine.process_tracks(tracks1, timestamp=0.2)
        # Suspected disorder triggered!
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["taxonomy"], "suspected_disorder")
        # Crowd concentration NOT triggered because duration = 0.2s < 3.0s
        crowd_events = [e for e in evs if e["payload"]["taxonomy"] == "crowd_concentration"]
        self.assertEqual(len(crowd_events), 0)


class TestHardNegativesRejection(unittest.TestCase):
    """Scenario tests verifying rejection of all 5 hard negatives."""

    def test_hard_negative_1_orderly_queue_or_bus_stop(self) -> None:
        """Normal orderly queue / bus stop line: steady or low velocity does NOT trigger disorder,
        and when queue exception rule is configured, does not trigger crowd concentration either."""
        from domain.alert_module_config import ExceptionRule
        engine_with_exception = CrowdIncidentEngine(
            min_crowd_count=5,
            min_duration_seconds=3.0,
            exceptions=[ExceptionRule(code="bus_stop_queue", reason="transit stop queue")],
        )

        # 6 people standing in an orderly line at a transit stop
        for step, t in enumerate([0.0, 1.0, 2.0, 3.0, 4.0]):
            tracks = [
                _make_track(i, 100.0, 100.0 + i * 25.0 + (step % 2) * 1.5, t)
                for i in range(6)
            ]
            evs = engine_with_exception.process_tracks(tracks, timestamp=t)
            self.assertEqual(len(evs), 0, f"Orderly queue under exception must not alert at t={t}")

    def test_recurrent_crowd_alert_updates_anchor_time(self) -> None:
        """Subsequent crowd alerts after cooldown update anchor_time to active condition time."""
        engine = CrowdIncidentEngine(
            min_crowd_count=3,
            min_duration_seconds=2.0,
            cooldown_seconds=5.0,
        )
        tracks0 = [_make_track(i, 100.0 + i * 15.0, 100.0, 0.0) for i in range(3)]

        # Initial trigger at t=2.0
        engine.process_tracks(tracks0, timestamp=0.0)
        engine.process_tracks(tracks0, timestamp=1.0)
        evs1 = engine.process_tracks(tracks0, timestamp=2.0)
        self.assertEqual(len(evs1), 1)
        self.assertEqual(evs1[0]["payload"]["anchor_time"], 2.0)

        # Maintain observation without gap: step from t=3.0 to t=8.0 (cooldown 5.0s elapsed from t=2.0 -> triggers at t=7.0)
        # Recurrent alert triggers with active condition anchor (t=7.0), not frozen past time (t=2.0)!
        evs2 = []
        for t in [3.0, 4.0, 5.0, 6.0, 7.0, 8.0]:
            emitted = engine.process_tracks(tracks0, timestamp=t)
            evs2.extend(emitted)
        self.assertEqual(len(evs2), 1)
        self.assertEqual(evs2[0]["payload"]["anchor_time"], 7.0)

    def test_hard_negative_2_isolated_runner(self) -> None:
        """Isolated individual running or waving hands: single person does NOT trigger crowd concentration or disorder."""
        engine = CrowdIncidentEngine(
            min_crowd_count=5,
            min_disorder_count=3,
        )

        # 1 fast runner sprinting across frame at 100 px/s
        for t in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
            tracks = [_make_track(1, 50.0 + t * 100.0, 200.0, t)]
            evs = engine.process_tracks(tracks, timestamp=t)
            self.assertEqual(len(evs), 0, f"Isolated runner must not trigger events at t={t}")
            self.assertEqual(engine.current_crowd_count, 1)
            self.assertFalse(engine.is_crowd_persisting)

    def test_hard_negative_3_transient_crossing(self) -> None:
        """Transient pedestrian crossing / walking past: brief crossing (T < min_duration_seconds) does NOT trigger crowd concentration."""
        engine = CrowdIncidentEngine(
            min_crowd_count=5,
            min_duration_seconds=3.0,
        )

        # Group of 5 people walking together across crosswalk at steady 25 px/s
        # They enter at t=0.0 and leave ROI at t=2.0 (duration = 2.0s < 3.0s)
        for t in [0.0, 0.5, 1.0, 1.5, 2.0]:
            tracks = [_make_track(i, 100.0 + t * 25.0 + i * 15.0, 200.0, t) for i in range(5)]
            evs = engine.process_tracks(tracks, timestamp=t)
            self.assertEqual(len(evs), 0, f"Transient crossing must not trigger crowd concentration at t={t}")

        # At t=2.5, group has walked out
        evs = engine.process_tracks([], timestamp=2.5)
        self.assertEqual(len(evs), 0)
        self.assertFalse(engine.is_crowd_persisting)

    def test_hard_negative_4_pedestrians_outside_restricted_roi(self) -> None:
        """Pedestrians outside restricted ROI do NOT count towards crowd threshold."""
        # Restricted ROI: [100, 100] to [200, 200]
        roi = [[100.0, 100.0], [200.0, 100.0], [200.0, 200.0], [100.0, 200.0]]
        engine = CrowdIncidentEngine(
            min_crowd_count=5,
            min_duration_seconds=3.0,
            roi_polygon=roi,
        )

        for t in [0.0, 1.0, 2.0, 3.0]:
            tracks = [
                _make_track(1, 150.0, 150.0, t),  # INSIDE ROI
                _make_track(2, 160.0, 160.0, t),  # INSIDE ROI
                _make_track(3, 400.0, 400.0, t),  # OUTSIDE ROI
                _make_track(4, 500.0, 400.0, t),  # OUTSIDE ROI
                _make_track(5, 600.0, 400.0, t),  # OUTSIDE ROI
                _make_track(6, 700.0, 400.0, t),  # OUTSIDE ROI
                _make_track(7, 800.0, 400.0, t),  # OUTSIDE ROI
            ]
            evs = engine.process_tracks(tracks, timestamp=t)
            self.assertEqual(len(evs), 0)
            self.assertEqual(engine.current_crowd_count, 2)
            self.assertFalse(engine.is_crowd_persisting)

    def test_hard_negative_5_observation_gap_resets_persistence(self) -> None:
        """Observation gap / track discontinuity resets persistence timer."""
        engine = CrowdIncidentEngine(
            min_crowd_count=5,
            min_duration_seconds=3.0,
            max_observation_gap=1.0,
        )

        # 5 people present for 2.0 seconds (t=0.0 to t=2.0)
        for t in [0.0, 1.0, 2.0]:
            tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, t) for i in range(5)]
            engine.process_tracks(tracks, timestamp=t)
        self.assertEqual(engine.crowd_persistence_duration, 2.0)

        # 5-second camera observation gap -> next frame arrives at t=7.0
        tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, 7.0) for i in range(5)]
        evs = engine.process_tracks(tracks, timestamp=7.0)
        self.assertEqual(len(evs), 0, "Must not trigger immediately after observation gap")
        self.assertEqual(engine.crowd_persistence_duration, 0.0, "Persistence duration must reset on gap")

        # Now requires full 3.0s continuous persistence from t=7.0
        for t in [8.0, 9.0]:
            tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, t) for i in range(5)]
            self.assertEqual(len(engine.process_tracks(tracks, timestamp=t)), 0)

        # At t=10.0 (7.0 + 3.0s) -> triggers
        tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, 10.0) for i in range(5)]
        evs = engine.process_tracks(tracks, timestamp=10.0)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["taxonomy"], "crowd_concentration")


class TestLifecycleAndOperationalControls(unittest.TestCase):
    """Tests for engine lifecycle methods, multi-camera independence, and schedule."""

    def test_explicit_observation_gap_call(self) -> None:
        engine = CrowdIncidentEngine(min_crowd_count=5, min_duration_seconds=3.0)
        tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, 0.0) for i in range(5)]
        engine.process_tracks(tracks, timestamp=0.0)
        self.assertTrue(engine.is_crowd_persisting)

        engine.observation_gap()
        self.assertFalse(engine.is_crowd_persisting)
        self.assertEqual(engine.current_crowd_count, 0)
        self.assertEqual(engine.crowd_persistence_duration, 0.0)

    def test_reset_clears_all_state(self) -> None:
        engine = CrowdIncidentEngine(min_crowd_count=5, min_duration_seconds=3.0)
        for t in [0.0, 1.0, 2.0, 3.0]:
            tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, t) for i in range(5)]
            engine.process_tracks(tracks, timestamp=t)
        self.assertIsNotNone(engine._last_crowd_alert_time)

        engine.reset()
        self.assertEqual(engine.current_crowd_count, 0)
        self.assertFalse(engine.is_crowd_persisting)
        self.assertIsNone(engine._last_crowd_alert_time)
        self.assertIsNone(engine._last_disorder_alert_time)
        self.assertIsNone(engine._last_timestamp)
        self.assertEqual(len(engine._tracks), 0)

    def test_schedule_filter_callable(self) -> None:
        """Schedule filter controls whether engine is active."""
        # Active only when ts % 24 >= 8 and ts % 24 <= 17 (e.g. daytime 8h-17h)
        schedule = lambda ts: 8.0 <= (ts % 24.0) <= 17.0
        engine = CrowdIncidentEngine(
            min_crowd_count=3,
            min_duration_seconds=1.0,
            schedule_filter=schedule,
        )

        # Inactive at t=2.0 (2am)
        tracks_night = [_make_track(i, 100.0 + i * 15.0, 100.0, 2.0) for i in range(3)]
        evs = engine.process_tracks(tracks_night, timestamp=2.0)
        self.assertEqual(len(evs), 0)
        self.assertFalse(engine.is_crowd_persisting)

        # Active at t=10.0 (10am)
        tracks_day0 = [_make_track(i, 100.0 + i * 15.0, 100.0, 10.0) for i in range(3)]
        engine.process_tracks(tracks_day0, timestamp=10.0)
        self.assertTrue(engine.is_crowd_persisting)

        tracks_day1 = [_make_track(i, 100.0 + i * 15.0, 100.0, 11.0) for i in range(3)]
        evs = engine.process_tracks(tracks_day1, timestamp=11.0)
        self.assertEqual(len(evs), 1)

    def test_schedule_filter_dict(self) -> None:
        """Schedule filter using dict format with active_hours."""
        engine = CrowdIncidentEngine(
            min_crowd_count=3,
            min_duration_seconds=1.0,
            schedule_filter={"active_hours": [(8.0, 17.0)]},
        )
        # 10am -> ts = 10 * 3600 = 36000
        tracks0 = [_make_track(i, 100.0 + i * 15.0, 100.0, 36000.0) for i in range(3)]
        engine.process_tracks(tracks0, timestamp=36000.0)
        self.assertTrue(engine.is_crowd_persisting)

        tracks1 = [_make_track(i, 100.0 + i * 15.0, 100.0, 36001.0) for i in range(3)]
        evs = engine.process_tracks(tracks1, timestamp=36001.0)
        self.assertEqual(len(evs), 1)

    def test_multi_camera_independence(self) -> None:
        """Two camera engines have isolated state and configuration."""
        cam1 = CrowdIncidentEngine(camera_id="cam-001", min_crowd_count=5)
        cam2 = CrowdIncidentEngine(camera_id="cam-002", min_crowd_count=3)

        self.assertNotEqual(cam1.stream_session_id, cam2.stream_session_id)
        # cam1 receives 3 people (below threshold of 5)
        cam1_tracks = [_make_track(i, 100.0, 100.0, 0.0) for i in range(3)]
        cam1.process_tracks(cam1_tracks, timestamp=0.0)
        self.assertFalse(cam1.is_crowd_persisting)

        # cam2 receives 3 people (meets threshold of 3)
        cam2_tracks = [_make_track(i, 200.0, 200.0, 0.0) for i in range(3)]
        cam2.process_tracks(cam2_tracks, timestamp=0.0)
        self.assertTrue(cam2.is_crowd_persisting)

        # Check cam1 is still not persisting
        self.assertFalse(cam1.is_crowd_persisting)

    def test_backward_timestamp_clock_jump_handled(self) -> None:
        """Backward timestamp jumps automatically reset continuity."""
        engine = CrowdIncidentEngine(min_crowd_count=5, min_duration_seconds=3.0)
        tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, 100.0) for i in range(5)]
        engine.process_tracks(tracks, timestamp=100.0)
        self.assertTrue(engine.is_crowd_persisting)

        # Clock jumps backward to t=50.0
        tracks_jump = [_make_track(i, 100.0 + i * 15.0, 100.0, 50.0) for i in range(5)]
        engine.process_tracks(tracks_jump, timestamp=50.0)
        self.assertEqual(engine.crowd_persistence_duration, 0.0)


class TestRuleFactsValidation(unittest.TestCase):
    """Rigorous verification of generated rule facts against contract."""

    def test_all_contract_fields_conformance(self) -> None:
        engine = CrowdIncidentEngine(
            camera_id="camera-market-10",
            device_id="edge-jetson-01",
            min_crowd_count=5,
            min_duration_seconds=3.0,
            quality_state="nominal",
        )

        for t in [0.0, 1.0, 2.0, 3.0]:
            tracks = [_make_track(i, 100.0 + i * 15.0, 100.0, t) for i in range(5)]
            evs = engine.process_tracks(tracks, timestamp=t)
            if t == 3.0:
                self.assertEqual(len(evs), 1)
                evt = evs[0]

        self.assertEqual(evt["anchor_kind"], "alert_condition")
        payload = evt["payload"]
        self.assertEqual(payload["taxonomy"], "crowd_concentration")
        self.assertEqual(payload["severity"], "medium")
        self.assertEqual(payload["crowd_count"], 5)
        self.assertEqual(payload["anchor_time"], 3.0)
        self.assertEqual(payload["detection_time"], 3.0)
        self.assertEqual(len(payload["track_ids"]), 5)
        self.assertEqual(engine.rule_lineage, [{"role": "crowd_incident", "version": "1.0.0"}])
        self.assertEqual(engine.quality_state, "nominal")
        self.assertEqual(engine.camera_id, "camera-market-10")
        self.assertEqual(engine.device_id, "edge-jetson-01")

if __name__ == "__main__":
    unittest.main()
