"""Tests for DangerZoneIncidentEngine and Multi-Module E2E Carrier (Task #57 / US10)."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest

import numpy as np

from apps.edge.danger_zone import DangerZoneIncidentEngine
from apps.edge.incident import IncidentEngine
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline, create_incident_engine
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import ByteTracker, Track
from domain.alert_module_config import (
    AlertModuleDefinition,
    AlertModuleRegistry,
    CameraModuleConfig,
    RegionOfInterest,
    ScheduleWindow,
)
from domain.event_contract import validate_event


def _make_track(
    track_id: int,
    bbox: list[float],
    timestamp: float,
    score: float = 0.9,
    label: str = "person",
) -> Track:
    track = Track(track_id=int(track_id), bbox=bbox, score=score, label=label, timestamp=timestamp)
    track.state = "active"
    return track


class TestDangerZoneIncidentEngine(unittest.TestCase):
    """Unit tests for DangerZoneIncidentEngine."""

    def setUp(self) -> None:
        self.roi = [[200.0, 200.0], [600.0, 200.0], [600.0, 600.0], [200.0, 600.0]]
        self.engine = DangerZoneIncidentEngine(
            camera_id="cam-01",
            device_id="edge-01",
            roi_polygon=self.roi,
            min_dwell_seconds=1.0,
            consecutive_hits=2,
            cooldown_seconds=30.0,
        )

    def test_person_outside_roi_no_alert(self) -> None:
        """Person walking outside ROI never triggers an intrusion alert."""
        # Person at [50, 50, 100, 150], foot point (75, 150) is outside ROI [200..600]
        track = _make_track(1, [50.0, 50.0, 100.0, 150.0], timestamp=0.0)
        events = self.engine.process_tracks([track], timestamp=0.0)
        self.assertEqual(len(events), 0)

        track.update([55.0, 50.0, 105.0, 150.0], 0.9, 1.0)
        events = self.engine.process_tracks([track], timestamp=1.0)
        self.assertEqual(len(events), 0)

    def test_person_inside_roi_triggers_critical_alert(self) -> None:
        """Person entering danger ROI triggers critical intrusion alert with alert_condition anchor."""
        # Foot point is ((350+450)/2, 500) = (400, 500), strictly inside [200..600, 200..600]
        track = _make_track(10, [350.0, 300.0, 450.0, 500.0], timestamp=0.0)

        # Frame 1: entered at t=0.0, consecutive hits = 1 < 2 -> no alert yet
        events = self.engine.process_tracks([track], timestamp=0.0)
        self.assertEqual(len(events), 0)

        # Frame 2: at t=0.5s, consecutive hits = 2, dwell = 0.5s < 1.0s -> no alert yet
        track.update([352.0, 302.0, 452.0, 502.0], 0.92, 0.5)
        events1 = self.engine.process_tracks([track], timestamp=0.5)
        self.assertEqual(len(events1), 0)

        # Frame 3: at t=1.1s, consecutive hits = 3, dwell = 1.1s >= 1.0s -> TRIGGERS
        track.update([352.0, 302.0, 452.0, 502.0], 0.92, 1.1)
        events = self.engine.process_tracks([track], timestamp=1.1)
        self.assertEqual(len(events), 1)

        event = events[0]
        self.assertEqual(event["schema_version"], 1)
        self.assertEqual(event["camera_id"], "cam-01")
        self.assertEqual(event["payload"]["taxonomy"], "danger_zone_intrusion")
        self.assertEqual(event["payload"]["severity"], "critical")
        self.assertEqual(event["payload"]["track_id"], 10)
        self.assertEqual(event["payload"]["anchor_time"], 1.1)
        self.assertEqual(event["payload"]["detection_time"], 1.1)

        # Verify evidence request follows Q36 alert_condition anchor [-10, +20]
        reqs = event["payload"]["evidence_requests"]
        self.assertEqual(reqs[0]["evidence_anchor_kind"], "alert_condition")
        self.assertEqual(reqs[0]["evidence_anchor_time"], 1.1)
        self.assertEqual(reqs[0]["requested_start"], -8.9)
        self.assertEqual(reqs[0]["requested_end"], 21.1)
        validated = validate_event(event)
        self.assertIsNotNone(validated)

    def test_cooldown_prevents_duplicate_spam(self) -> None:
        """Continuous presence inside danger zone respects cooldown."""
        engine = DangerZoneIncidentEngine(
            camera_id="cam-01",
            roi_polygon=self.roi,
            min_dwell_seconds=0.0,
            consecutive_hits=1,
            max_observation_gap=35.0,
            cooldown_seconds=30.0,
        )
        track = _make_track(20, [300.0, 300.0, 400.0, 500.0], timestamp=0.0)
        events = engine.process_tracks([track], timestamp=0.0)
        self.assertEqual(len(events), 1)

        # Stay inside at t=5.0s, t=10.0s, t=25.0s -> no new alert (cooldown is 30s)
        for t in [5.0, 10.0, 25.0]:
            track.update([300.0, 300.0, 400.0, 500.0], 0.9, t)
            events = engine.process_tracks([track], timestamp=t)
            self.assertEqual(len(events), 0)

        # At t=32.0s (> 30s cooldown) -> triggers second alert
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 32.0)
        events = engine.process_tracks([track], timestamp=32.0)
        self.assertEqual(len(events), 1)

    def test_schedule_filter_disables_alerts_outside_window(self) -> None:
        """When schedule window is inactive, no intrusion alerts are fired."""
        # Active only on Mondays between 08:00 (28800s) and 18:00 (64800s)
        window = ScheduleWindow(days=("mon",), start_second=28800, end_second=64800)
        engine = DangerZoneIncidentEngine(
            roi_polygon=self.roi,
            schedule=[window],
            min_dwell_seconds=0.0,
            consecutive_hits=1,
        )

        track = _make_track(30, [300.0, 300.0, 400.0, 500.0], timestamp=0.0)

        # Tuesday timestamp: 2026-10-27 10:00:00 UTC (Tuesday)
        tuesday_ts = datetime(2026, 10, 27, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        events = engine.process_tracks([track], timestamp=tuesday_ts)
        self.assertEqual(len(events), 0)

        # Monday timestamp: 2026-10-26 10:00:00 UTC (Monday, within 08:00-18:00)
        monday_ts = datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, monday_ts)
        events = engine.process_tracks([track], timestamp=monday_ts)
        self.assertEqual(len(events), 1)

    def test_observation_gap_resets_dwell_continuity(self) -> None:
        """Observation gap resets continuous dwell timer and prevents false sustained alert."""
        track = _make_track(40, [300.0, 300.0, 400.0, 500.0], timestamp=0.0)
        self.engine.process_tracks([track], timestamp=0.0)

        # Huge gap of 5 seconds (> max_observation_gap of 1.0s)
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 5.0)
        events = self.engine.process_tracks([track], timestamp=5.0)
        # First frame after gap acts as fresh entry, dwell reset -> 0 events
        self.assertEqual(len(events), 0)

    def test_normalized_roi_against_different_frame_dimensions(self) -> None:
        """Normalized ROI [0, 1] works across 1280x720 and 1920x1080 frame resolutions."""
        # Normalized ROI covering [0.25..0.75, 0.25..0.75]
        norm_roi = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]

        # Resolution 1: 1280x720 (HD)
        engine_720 = DangerZoneIncidentEngine(
            roi_polygon=norm_roi,
            frame_dimensions=(1280.0, 720.0),
            min_dwell_seconds=0.0,
            consecutive_hits=1,
        )
        # Inside 720p: (640, 360) -> normalized is (0.5, 0.5)
        inside_720 = _make_track(51, [600.0, 300.0, 680.0, 360.0], timestamp=1.0)
        self.assertTrue(engine_720.in_roi(inside_720))
        # Outside 720p: (100, 100) -> normalized is (0.078, 0.138)
        outside_720 = _make_track(52, [50.0, 50.0, 150.0, 100.0], timestamp=1.0)
        self.assertFalse(engine_720.in_roi(outside_720))

        # Resolution 2: 1920x1080 (Full HD)
        engine_1080 = DangerZoneIncidentEngine(
            roi_polygon=norm_roi,
            frame_dimensions=(1920.0, 1080.0),
            min_dwell_seconds=0.0,
            consecutive_hits=1,
        )
        # Inside 1080p: (960, 540) -> normalized is (0.5, 0.5)
        inside_1080 = _make_track(61, [900.0, 450.0, 1020.0, 540.0], timestamp=1.0)
        self.assertTrue(engine_1080.in_roi(inside_1080))
        # Outside 1080p: (200, 150) -> normalized is (0.104, 0.138)
        outside_1080 = _make_track(62, [150.0, 100.0, 250.0, 150.0], timestamp=1.0)
        self.assertFalse(engine_1080.in_roi(outside_1080))

    def test_regression_gap_does_not_count_unobserved_time(self) -> None:
        """Regression: observation gap must NOT count unobserved time towards dwell duration."""
        engine = DangerZoneIncidentEngine(
            roi_polygon=self.roi,
            min_dwell_seconds=5.0,
            consecutive_hits=2,
            max_observation_gap=1.0,
        )
        track = _make_track(71, [300.0, 300.0, 400.0, 500.0], timestamp=0.0)
        # Frame at t=0.0
        engine.process_tracks([track], timestamp=0.0)

        # Huge unobserved gap to t=10.0 (dt=10s > max_observation_gap 1.0s)
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 10.0)
        events_10 = engine.process_tracks([track], timestamp=10.0)
        self.assertEqual(len(events_10), 0)

        # Frame at t=10.1: only 0.1s of observed dwell after gap recovery!
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 10.1)
        events_10_1 = engine.process_tracks([track], timestamp=10.1)
        # MUST NOT alert after only 0.1s of recovered observation
        self.assertEqual(len(events_10_1), 0)

        # Frame at t=10.8: dwell = 0.8s < 5.0s
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 10.8)
        events_10_8 = engine.process_tracks([track], timestamp=10.8)
        self.assertEqual(len(events_10_8), 0)

        # Continuous dwelling reaches 5s at t=15.1s (15.1 - 10.0 = 5.1s >= 5.0s, with steps <= 1.0s)
        for t in [11.5, 12.2, 13.0, 14.0, 14.9]:
            track.update([300.0, 300.0, 400.0, 500.0], 0.9, t)
            engine.process_tracks([track], timestamp=t)

        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 15.1)
        events_15_1 = engine.process_tracks([track], timestamp=15.1)
        self.assertEqual(len(events_15_1), 1)
        self.assertAlmostEqual(events_15_1[0]["payload"]["dwell_seconds"], 5.1, places=1)

    def test_regression_roi_exit_and_reentry_restarts_dwell(self) -> None:
        """Regression: leaving danger ROI and re-entering restarts dwell from zero."""
        engine = DangerZoneIncidentEngine(
            roi_polygon=self.roi,
            min_dwell_seconds=5.0,
            consecutive_hits=2,
            max_observation_gap=2.0,
        )
        track = _make_track(81, [300.0, 300.0, 400.0, 500.0], timestamp=0.0)
        engine.process_tracks([track], timestamp=0.0)

        # Stays in ROI for 3.5s
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 1.0)
        engine.process_tracks([track], timestamp=1.0)
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 3.5)
        engine.process_tracks([track], timestamp=3.5)

        # Exits ROI at t=4.5s (outside ROI [200..600])
        track.update([50.0, 50.0, 100.0, 100.0], 0.9, 4.5)
        engine.process_tracks([track], timestamp=4.5)

        # Re-enters ROI at t=6.0s
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 6.0)
        engine.process_tracks([track], timestamp=6.0)

        # At t=7.5s: dwell after re-entry is only 1.5s (< 5.0s), even though total history was 3.5 + 1.5 = 5.0s
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 7.5)
        events_7_5 = engine.process_tracks([track], timestamp=7.5)
        self.assertEqual(len(events_7_5), 0)

        # Stays until t=11.1s (5.1s continuous dwell after re-entry at t=6.0s)
        for t in [8.5, 9.5, 10.5]:
            track.update([300.0, 300.0, 400.0, 500.0], 0.9, t)
            engine.process_tracks([track], timestamp=t)

        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 11.1)
        events_11_1 = engine.process_tracks([track], timestamp=11.1)
        self.assertEqual(len(events_11_1), 1)
        self.assertAlmostEqual(events_11_1[0]["payload"]["dwell_seconds"], 5.1, places=1)

    def test_regression_off_schedule_recovery_restarts_dwell(self) -> None:
        """Regression: person in ROI during off-schedule only counts dwell once schedule turns active."""
        # Schedule active only after second 36000 (10:00 UTC) on Monday
        window = ScheduleWindow(days=("mon",), start_second=36000, end_second=72000)
        engine = DangerZoneIncidentEngine(
            roi_polygon=self.roi,
            schedule=[window],
            min_dwell_seconds=5.0,
            consecutive_hits=2,
            max_observation_gap=2.0,
        )
        # Person present in ROI at 09:55 UTC (35700s, off-schedule)
        ts_off = datetime(2026, 10, 26, 9, 55, 0, tzinfo=timezone.utc).timestamp()
        track = _make_track(91, [300.0, 300.0, 400.0, 500.0], timestamp=ts_off)
        events_off = engine.process_tracks([track], timestamp=ts_off)
        self.assertEqual(len(events_off), 0)

        # Schedule turns active at 10:00:00 (36000s)
        ts_start = datetime(2026, 10, 26, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, ts_start)
        engine.process_tracks([track], timestamp=ts_start)

        # At 10:00:01 (only 1s into active schedule)
        ts_1s = datetime(2026, 10, 26, 10, 0, 1, tzinfo=timezone.utc).timestamp()
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, ts_1s)
        events_1s = engine.process_tracks([track], timestamp=ts_1s)
        self.assertEqual(len(events_1s), 0)

        # At 10:00:06 (6s into active schedule >= 5s min_dwell)
        for sec in range(2, 5):
            t_sec = datetime(2026, 10, 26, 10, 0, sec, tzinfo=timezone.utc).timestamp()
            track.update([300.0, 300.0, 400.0, 500.0], 0.9, t_sec)
            engine.process_tracks([track], timestamp=t_sec)

        ts_5s = datetime(2026, 10, 26, 10, 0, 5, tzinfo=timezone.utc).timestamp()
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, ts_5s)
        events_5s = engine.process_tracks([track], timestamp=ts_5s)
        self.assertEqual(len(events_5s), 1)
        self.assertAlmostEqual(events_5s[0]["payload"]["dwell_seconds"], 5.0, places=1)

    def test_regression_lost_or_empty_track_breaks_dwell_continuity(self) -> None:
        """Regression: when a track disappears from an otherwise healthy stream, dwell resets."""
        engine = DangerZoneIncidentEngine(
            roi_polygon=self.roi,
            min_dwell_seconds=1.0,
            consecutive_hits=2,
            max_observation_gap=2.0,
        )
        track = _make_track(77, [300.0, 300.0, 400.0, 500.0], timestamp=0.0)
        # Frame 1 at t=0.0: observed in ROI
        events_0 = engine.process_tracks([track], timestamp=0.0)
        self.assertEqual(len(events_0), 0)

        # Frame 2 at t=0.5: healthy stream but track disappears (ok_empty, tracks=[])
        events_empty = engine.process_tracks([], timestamp=0.5)
        self.assertEqual(len(events_empty), 0)

        # Frame 3 at t=1.0: track re-acquired in ROI
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 1.0)
        events_reacquired = engine.process_tracks([track], timestamp=1.0)
        # MUST NOT alert at 1.0s (counting 0.0 to 1.0); dwell was reset on frame 2!
        self.assertEqual(len(events_reacquired), 0)

        # Frame 4 at t=1.5: consecutive_hits=2, dwell=0.5s < 1.0s
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 1.5)
        events_1_5 = engine.process_tracks([track], timestamp=1.5)
        self.assertEqual(len(events_1_5), 0)

        # Frame 5 at t=2.1: consecutive_hits=3, dwell=1.1s >= 1.0s -> ALERTS!
        track.update([300.0, 300.0, 400.0, 500.0], 0.9, 2.1)
        events_2_1 = engine.process_tracks([track], timestamp=2.1)
        self.assertEqual(len(events_2_1), 1)
        self.assertAlmostEqual(events_2_1[0]["payload"]["dwell_seconds"], 1.1, places=1)


class TestMultiModuleCarrierPipelineE2E(unittest.TestCase):
    """E2E multi-module tests for Carrier #57 (Person-down + Danger-zone + Linked labels)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "events.sqlite3"
        self.record_dir = self.root / "records"
        self.record_dir.mkdir(parents=True, exist_ok=True)
        self.recorder = FileRecorder(self.record_dir, ring_seconds=60.0)
        self.outbox = EventOutbox(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_multi_module_person_down_and_danger_zone_linked_events(self) -> None:
        """Carrier #57: A person enters danger zone then falls down; both events are emitted and neither cancels the other."""
        danger_roi = [[100.0, 100.0], [500.0, 100.0], [500.0, 500.0], [100.0, 500.0]]
        danger_engine = DangerZoneIncidentEngine(
            camera_id="cam-01",
            device_id="edge-01",
            roi_polygon=danger_roi,
            min_dwell_seconds=0.0,
            consecutive_hits=1,
        )
        fall_engine = IncidentEngine(
            standing_aspect_ratio=0.85,
            lying_aspect_ratio=1.2,
            min_drop_velocity=15.0,
            min_lying_duration=1.0,
            roi_polygon=danger_roi,
        )

        pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            tracker=ByteTracker(activate_after=1),
            camera_id="cam-01",
            device_id="edge-01",
            incident_engines=[fall_engine, danger_engine],
            roi_polygon=danger_roi,
        )

        rgb = np.zeros((720, 1280, 3), dtype=np.uint8)

        # 1. Standing in danger zone from t=0.0 to 0.4s (5 frames)
        standing_det = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.95, "label": "person"}]
        all_emitted: list[dict[str, Any]] = []
        for i in range(5):
            t = round(i * 0.1, 2)
            evs = pipeline.process_frame(rgb, timestamp=t, frame_id=i, detections=standing_det)
            all_emitted.extend(evs)

        danger_events = [e for e in all_emitted if e["payload"]["taxonomy"] == "danger_zone_intrusion"]
        self.assertGreaterEqual(len(danger_events), 1)
        self.assertEqual(danger_events[0]["payload"]["severity"], "critical")
        self.assertEqual(danger_events[0]["stream_session_id"], pipeline.stream_session_id)
        self.assertEqual(danger_events[0]["camera_id"], "cam-01")
        self.assertEqual(danger_events[0]["device_id"], "edge-01")
        reqs = danger_events[0]["payload"]["evidence_requests"]
        self.assertEqual(reqs[0]["session_id"], pipeline.stream_session_id)

        # 2. Dropping (frame 5 to 9)
        fall_boxes = [
            [100.0, 120.0, 165.0, 260.0],
            [100.0, 150.0, 175.0, 260.0],
            [100.0, 180.0, 200.0, 265.0],
            [100.0, 210.0, 230.0, 270.0],
            [100.0, 220.0, 260.0, 280.0],
        ]
        for idx, box in enumerate(fall_boxes, start=5):
            t = round(idx * 0.1, 2)
            evs = pipeline.process_frame(rgb, timestamp=t, frame_id=idx, detections=[{"bbox": box, "score": 0.9, "label": "person"}])
            all_emitted.extend(evs)

        # 3. Lying stationary for 1.5s (frame 10 to 25)
        lying_det = [{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.9, "label": "person"}]
        for i in range(10, 26):
            t = round(i * 0.1, 2)
            evs = pipeline.process_frame(rgb, timestamp=t, frame_id=i, detections=lying_det)
            all_emitted.extend(evs)

        fall_events = [e for e in all_emitted if e["payload"]["taxonomy"] == "person_fall"]
        self.assertEqual(len(fall_events), 1)
        self.assertEqual(fall_events[0]["stream_session_id"], pipeline.stream_session_id)
        self.assertEqual(fall_events[0]["camera_id"], "cam-01")
        self.assertEqual(fall_events[0]["device_id"], "edge-01")
        fall_reqs = fall_events[0]["payload"]["evidence_requests"]
        self.assertEqual(fall_reqs[0]["session_id"], pipeline.stream_session_id)

        # 4. Outbox persistence check: both event types exist, neither erased the other, session IDs match
        pending = self.outbox.pending()
        self.assertEqual(len(pending), 2)
        persisted = [p["event"] for p in pending]
        persisted_taxonomies = [e["payload"]["taxonomy"] for e in persisted]
        self.assertIn("danger_zone_intrusion", persisted_taxonomies)
        self.assertIn("person_fall", persisted_taxonomies)
        for e in persisted:
            self.assertEqual(e["stream_session_id"], pipeline.stream_session_id)
            for req in e["payload"]["evidence_requests"]:
                self.assertEqual(req["session_id"], pipeline.stream_session_id)
    def test_factory_creation_from_camera_module_config(self) -> None:
        """create_incident_engine instantiates correct engine from CameraModuleConfig."""
        norm_roi = RegionOfInterest(points=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9)))
        config = CameraModuleConfig(
            module="danger_zone",
            camera_id="cam-01",
            version=1,
            enabled=True,
            roi=(norm_roi,),
            thresholds=(("consecutive_hits", 3.0), ("min_dwell_seconds", 2.0)),
        )

        engine = create_incident_engine(
            "danger_zone",
            camera_id="cam-01",
            device_id="edge-01",
            config=config,
            frame_dimensions=(1280, 720),
        )

        self.assertIsInstance(engine, DangerZoneIncidentEngine)
        self.assertEqual(engine.camera_id, "cam-01")
        self.assertEqual(engine.min_dwell_seconds, 2.0)
        self.assertEqual(engine.consecutive_hits, 3)
        # Check that ROI was scaled to 1280x720 pixels
        self.assertEqual(engine.roi_polygon, [[128.0, 72.0], [1152.0, 72.0], [1152.0, 648.0]])

    def test_multi_camera_module_config_enabled_and_disabled(self) -> None:
        """Two camera profiles: cam-01 enabled, cam-02 disabled with reason."""
        norm_roi = RegionOfInterest(points=((0.2, 0.2), (0.8, 0.2), (0.8, 0.8)))
        cfg_cam1 = CameraModuleConfig(
            module="danger_zone",
            camera_id="cam-01",
            version=1,
            enabled=True,
            roi=(norm_roi,),
        )
        cfg_cam2 = CameraModuleConfig(
            module="danger_zone",
            camera_id="cam-02",
            version=1,
            enabled=False,
            disabled_reason="restricted area not configured for cam-02",
        )

        pipeline_cam1 = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            camera_id="cam-01",
            module_configs=[cfg_cam1],
        )
        pipeline_cam2 = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            camera_id="cam-02",
            module_configs=[cfg_cam2],
        )

        # cam-01 has DangerZoneIncidentEngine active
        self.assertIsNotNone(pipeline_cam1.get_engine("danger_zone"))

        # cam-02 has all modules disabled -> incident_engines is empty and incident_engine is None
        self.assertEqual(len(pipeline_cam2.incident_engines), 0)
        self.assertIsNone(pipeline_cam2.incident_engine)
        self.assertIsNone(pipeline_cam2.get_engine("danger_zone"))

        # Process frames on disabled camera -> produces 0 events and 0 outbox entries
        rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
        for i in range(5):
            evs = pipeline_cam2.process_frame(
                rgb,
                timestamp=float(i),
                frame_id=i,
                detections=[{"bbox": [100.0, 100.0, 200.0, 200.0], "score": 0.9, "label": "person"}],
            )
            self.assertEqual(len(evs), 0)
        self.assertEqual(len(pipeline_cam2.outbox.pending()), 0)
        # Recording capability is still fully functional
        self.assertIsNotNone(pipeline_cam2.recorder)

    def test_registry_loaded_named_module_with_distinct_config_version(self) -> None:
        """AlertModuleRegistry integration: module='zone_north', factory='danger_zone' preserves distinct config_version and module identity."""
        registry = AlertModuleRegistry()
        defn = AlertModuleDefinition(
            module="zone_north",
            config_version="north-v2.1",
            factory="danger_zone",
            required_fields=frozenset({"roi"}),
            thresholds=frozenset({"consecutive_hits", "min_dwell_seconds"}),
        )
        registry.register(defn)

        norm_roi = RegionOfInterest(points=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9)))
        config = CameraModuleConfig(
            module="zone_north",
            camera_id="cam-01",
            version=1,
            enabled=True,
            roi=(norm_roi,),
            thresholds=(("consecutive_hits", 1.0), ("min_dwell_seconds", 0.0)),
        )

        pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            tracker=ByteTracker(activate_after=1),
            camera_id="cam-01",
            device_id="edge-01",
            config_version="pipeline-global-v1",
            module_configs=[config],
            alert_registry=registry,
        )

        engine = pipeline.get_engine("zone_north")
        self.assertIsNotNone(engine)
        assert engine is not None
        self.assertEqual(engine.module, "zone_north")
        self.assertEqual(engine.factory, "danger_zone")
        self.assertEqual(engine.config_version, "north-v2.1")

        # Process a frame where person enters zone_north
        rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
        # Person in ROI: (640, 360) -> normalized (0.5, 0.5) is inside norm_roi
        det = [{"bbox": [600.0, 300.0, 680.0, 420.0], "score": 0.92, "label": "person"}]
        events = pipeline.process_frame(rgb, timestamp=1.0, frame_id=1, detections=det)

        self.assertEqual(len(events), 1)
        event = events[0]
        # Preserves distinct per-module config_version
        self.assertEqual(event["config_version"], "north-v2.1")
        self.assertEqual(event["payload"]["module"], "zone_north")
        self.assertEqual(event["payload"]["factory"], "danger_zone")
        self.assertEqual(event["payload"]["taxonomy"], "danger_zone_intrusion")

    def test_real_detector_provenance_propagation(self) -> None:
        """Pipeline propagates real detector model_id and model_sha256 artifact hash to module events."""
        danger_engine = DangerZoneIncidentEngine(
            camera_id="cam-01",
            device_id="edge-01",
            roi_polygon=[[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]],
            min_dwell_seconds=0.0,
            consecutive_hits=1,
        )
        pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            tracker=ByteTracker(activate_after=1),
            camera_id="cam-01",
            device_id="edge-01",
            incident_engines=[danger_engine],
            roi_polygon=[[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]],
        )
        # Simulate an observation with known detector provenance
        pipeline.model_lineage = [{"role": "detector", "version": "yolox-tiny-traffic-cctv-v2"}]
        pipeline.model_artifact_hash = "sha256-cctv-model-digest-9876543210abcdef"
        pipeline.calibration_version = "camera-fixed-cctv-calib-v1"

        rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
        det = [{"bbox": [150.0, 150.0, 250.0, 280.0], "score": 0.95, "label": "person"}]
        events = pipeline.process_frame(rgb, timestamp=1.0, frame_id=1, detections=det)

        self.assertEqual(len(events), 1)
        event = events[0]
        # Real detector provenance bound
        self.assertEqual(event["model_artifact_hash"], "sha256-cctv-model-digest-9876543210abcdef")
        self.assertEqual(event["calibration_version"], "camera-fixed-cctv-calib-v1")
        self.assertEqual(event["model_lineage"][0], {"role": "detector", "version": "yolox-tiny-traffic-cctv-v2"})
        # Module rule lineage retained
        module_roles = [m["role"] for m in event["model_lineage"]]
        self.assertIn("danger_zone_incident", module_roles)

    def test_all_five_configured_factories_startup_and_frame_processing(self) -> None:
        """All 5 allowlisted factories can be configured via AlertModuleRegistry and process frames cleanly."""
        registry = AlertModuleRegistry()
        factories = [
            ("mod_person_down", "person_down", "pd-v1"),
            ("mod_danger_zone", "danger_zone", "dz-v1"),
            ("mod_parking", "illegal_parking", "ip-v1"),
            ("mod_crowd", "crowd_incident", "ci-v1"),
            ("mod_vehicle", "vehicle_incident", "vi-v1"),
        ]
        for mod, fact, ver in factories:
            registry.register(
                AlertModuleDefinition(
                    module=mod,
                    config_version=ver,
                    factory=fact,
                )
            )

        norm_roi = RegionOfInterest(points=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9)))
        configs = [
            CameraModuleConfig(
                module=mod,
                camera_id="cam-01",
                version=1,
                enabled=True,
                roi=(norm_roi,),
            )
            for mod, _, _ in factories
        ]

        pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            camera_id="cam-01",
            device_id="edge-01",
            module_configs=configs,
            alert_registry=registry,
        )

        self.assertEqual(len(pipeline.incident_engines), 5)
        for mod, fact, ver in factories:
            eng = pipeline.get_engine(mod)
            self.assertIsNotNone(eng)
            assert eng is not None
            self.assertEqual(eng.module, mod)
            self.assertEqual(eng.factory, fact)
            self.assertEqual(eng.config_version, ver)

        # Frame processing with mixed detections runs cleanly across all 5 engines
        rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
        mixed_dets = [
            {"bbox": [200.0, 200.0, 260.0, 320.0], "score": 0.9, "label": "person"},
            {"bbox": [400.0, 300.0, 550.0, 450.0], "score": 0.88, "label": "car"},
        ]
        events = pipeline.process_frame(rgb, timestamp=1.0, frame_id=1, detections=mixed_dets)
        self.assertIsInstance(events, list)
        status = pipeline.status()
        self.assertEqual(status["camera_id"], "cam-01")

    def test_stream_session_reset_preserves_distinct_module_config_version(self) -> None:
        """Lineage/session reset does NOT clobber per-module config_version with pipeline global config_version."""
        registry = AlertModuleRegistry()
        registry.register(AlertModuleDefinition(module="zone_north", config_version="north-v2.1", factory="danger_zone"))
        config = CameraModuleConfig(module="zone_north", camera_id="cam-01", version=1, enabled=True)
        pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            camera_id="cam-01",
            device_id="edge-01",
            config_version="pipeline-global-v1",
            module_configs=[config],
            alert_registry=registry,
        )
        eng = pipeline.get_engine("zone_north")
        assert eng is not None
        self.assertEqual(eng.config_version, "north-v2.1")

        # Frame 1 under initial session
        rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
        pipeline.process_frame(rgb, timestamp=1.0, frame_id=1, detections=[])

        # Simulate RTSP reconnection / stream session reset
        pipeline.stream_session_id = "session-reconnect-999"
        pipeline.process_frame(rgb, timestamp=2.0, frame_id=2, detections=[])

        # eng.config_version MUST NOT be overwritten to "pipeline-global-v1"
        self.assertEqual(eng.config_version, "north-v2.1")

    def test_multi_module_engine_inherits_pipeline_degraded_quality_state(self) -> None:
        """Multi-module engine alert events inherit pipeline degraded quality state when no per-capability policy is configured."""
        danger_engine = DangerZoneIncidentEngine(
            camera_id="cam-01",
            device_id="edge-01",
            roi_polygon=[[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]],
            min_dwell_seconds=0.0,
            consecutive_hits=1,
        )
        pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            tracker=ByteTracker(activate_after=1),
            camera_id="cam-01",
            device_id="edge-01",
            incident_engines=[danger_engine],
        )
        # Black image -> evaluate_odd sets quality_state to "low_light"
        rgb_black = np.zeros((720, 1280, 3), dtype=np.uint8)
        det = [{"bbox": [100.0, 100.0, 200.0, 250.0], "score": 0.95, "label": "person"}]
        events = pipeline.process_frame(rgb_black, timestamp=1.0, frame_id=1, detections=det)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["quality_state"], "low_light")
        self.assertEqual(ev["payload"]["quality"]["state"], "low_light")

    def test_roi_pixel_caching_performance(self) -> None:
        """Pipeline caches scaled pixel ROI across frames of identical resolution."""
        pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            camera_id="cam-01",
            device_id="edge-01",
            roi_polygon=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        )
        roi1 = pipeline._get_pixel_roi(1280, 720)
        roi2 = pipeline._get_pixel_roi(1280, 720)
        self.assertIs(roi1, roi2)
        self.assertEqual(roi1, [[128.0, 72.0], [1152.0, 72.0], [1152.0, 648.0], [128.0, 648.0]])

    def test_dispatch_engine_process_tracks_signature_tolerance_and_error_propagation(self) -> None:
        """Engine dispatch supports custom 2-arg signatures and propagates internal exceptions without swallowing."""
        class MinimalEngine:
            def process_tracks(self, tracks: Any, timestamp: float) -> list[dict[str, Any]]:
                return []

        class BuggyEngine:
            def process_tracks(self, tracks: Any, timestamp: float) -> list[dict[str, Any]]:
                raise TypeError("internal engine failure: unsupported operand")

        pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            camera_id="cam-01",
            device_id="edge-01",
            incident_engines=[MinimalEngine()],
        )
        # MinimalEngine runs cleanly
        rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
        events = pipeline.process_frame(rgb, timestamp=1.0, frame_id=1, detections=[])
        self.assertEqual(events, [])

        # BuggyEngine raises TypeError which MUST bubble up, not get swallowed
        pipeline.incident_engines = [BuggyEngine()]
        with self.assertRaises(TypeError) as ctx:
            pipeline.process_frame(rgb, timestamp=2.0, frame_id=2, detections=[])
        self.assertIn("internal engine failure", str(ctx.exception))

    def test_incident_engine_in_roi_center_point_fallback(self) -> None:
        """IncidentEngine._in_roi accepts track when center is inside ROI polygon even if foot is outside."""
        engine = IncidentEngine(roi_polygon=[[100.0, 100.0], [300.0, 100.0], [300.0, 300.0], [100.0, 300.0]])
        # Center: (200, 200) inside ROI. Foot: (200, 350) outside ROI.
        track = Track(track_id=1, bbox=[150.0, 50.0, 250.0, 350.0], score=0.9, label="person", timestamp=1.0)
        self.assertTrue(engine._in_roi(track))


if __name__ == "__main__":
    unittest.main()
