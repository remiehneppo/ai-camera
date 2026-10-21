"""Unit tests for ByteTracker and Fall Detection IncidentEngine."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np

from apps.edge.incident import IncidentEngine
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import ByteTracker, Track


class TestByteTracker(unittest.TestCase):
    """Test suite for ByteTracker multi-object tracking logic."""

    def test_track_initialization_and_properties(self) -> None:
        track = Track(
            track_id=1,
            bbox=[100.0, 100.0, 160.0, 260.0],
            score=0.92,
            label="person",
            timestamp=10.0,
        )
        self.assertEqual(track.track_id, 1)
        self.assertEqual(track.state, "active")
        self.assertAlmostEqual(track.width, 60.0)
        self.assertAlmostEqual(track.height, 160.0)
        self.assertAlmostEqual(track.cx, 130.0)
        self.assertAlmostEqual(track.cy, 180.0)
        self.assertAlmostEqual(track.aspect_ratio, 60.0 / 160.0, places=3)
        self.assertEqual(len(track.history), 1)

    def test_bytetracker_single_object_tracking(self) -> None:
        tracker = ByteTracker(high_threshold=0.5, low_threshold=0.1, match_threshold=0.2)
        
        # Frame 1: Person at (100, 100, 160, 260)
        dets_f1 = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.9, "label": "person"}]
        tracks_f1 = tracker.update(dets_f1, timestamp=1.0)
        # P1-12: a new track is tentative and is not reported until its second hit.
        self.assertEqual(len(tracks_f1), 0)

        # Frame 2: Person moves slightly to (105, 102, 165, 262) -> track activates
        dets_f2 = [{"bbox": [105.0, 102.0, 165.0, 262.0], "score": 0.88, "label": "person"}]
        tracks_f2 = tracker.update(dets_f2, timestamp=1.1)
        self.assertEqual(len(tracks_f2), 1)
        track_id = tracks_f2[0].track_id
        self.assertEqual(tracks_f2[0].state, "active")

        # Frame 3: Person at (110, 104, 170, 264)
        dets_f3 = [{"bbox": [110.0, 104.0, 170.0, 264.0], "score": 0.85, "label": "person"}]
        tracks_f3 = tracker.update(dets_f3, timestamp=1.2)
        self.assertEqual(len(tracks_f3), 1)
        self.assertEqual(tracks_f3[0].track_id, track_id)
        self.assertEqual(len(tracks_f3[0].history), 3)

    def test_bytetracker_two_stage_low_score_association(self) -> None:
        """ByteTrack recovers occluded track using low score detection in stage 2."""
        tracker = ByteTracker(high_threshold=0.6, low_threshold=0.2, match_threshold=0.2)

        # Frame 1: High score detection
        dets_f1 = [{"bbox": [200.0, 200.0, 260.0, 360.0], "score": 0.95, "label": "person"}]
        self.assertEqual(len(tracker.update(dets_f1, timestamp=0.0)), 0)  # tentative
        dets_f1b = [{"bbox": [201.0, 200.0, 261.0, 360.0], "score": 0.95, "label": "person"}]
        tracks_f1 = tracker.update(dets_f1b, timestamp=0.1)
        self.assertEqual(len(tracks_f1), 1)
        tid = tracks_f1[0].track_id

        # Frame 3: Occlusion causes score to drop to 0.35 (below high_threshold 0.6, but >= low_threshold 0.2)
        dets_f2 = [{"bbox": [202.0, 201.0, 262.0, 361.0], "score": 0.35, "label": "person"}]
        tracks_f2 = tracker.update(dets_f2, timestamp=0.2)
        self.assertEqual(len(tracks_f2), 1)
        self.assertEqual(tracks_f2[0].track_id, tid)
        self.assertAlmostEqual(tracks_f2[0].score, 0.35)

    def test_bytetracker_lost_and_removed_lifecycle(self) -> None:
        tracker = ByteTracker(max_lost_time=2.0)
        dets = [{"bbox": [50.0, 50.0, 100.0, 200.0], "score": 0.9, "label": "person"}]
        self.assertEqual(len(tracker.update(dets, timestamp=-0.1)), 0)  # tentative
        tracks = tracker.update(dets, timestamp=0.0)
        self.assertEqual(len(tracks), 1)
        tid = tracks[0].track_id

        # Missing detection for 0.5s -> track becomes lost
        tracks_empty = tracker.update([], timestamp=0.5)
        self.assertEqual(len(tracks_empty), 0)
        all_tracks = tracker.get_all_tracks()
        self.assertEqual(len(all_tracks), 1)
        self.assertEqual(all_tracks[0].state, "lost")

        # Re-detect at 1.0s -> track re-activates with same ID
        tracks_recovered = tracker.update(dets, timestamp=1.0)
        self.assertEqual(len(tracks_recovered), 1)
        self.assertEqual(tracks_recovered[0].track_id, tid)
        self.assertEqual(tracks_recovered[0].state, "active")

        # Disappear for > max_lost_time (2.0s), e.g. from 1.0s to 3.5s
        tracker.update([], timestamp=3.5)
        all_tracks_after_timeout = tracker.get_all_tracks()
        # Should be removed
        self.assertTrue(all(t.state == "removed" for t in all_tracks_after_timeout if t.track_id == tid))

    def test_track_velocity_and_aspect_ratio_computation(self) -> None:
        track = Track(
            track_id=1,
            bbox=[100.0, 100.0, 160.0, 260.0],  # cx=130, cy=180, w/h = 60/160 = 0.375
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        # Drop down 100px over 1.0 second
        track.update([100.0, 200.0, 160.0, 360.0], score=0.9, timestamp=1.0)  # cx=130, cy=280
        # Positive downward velocity: (280 - 180) / 1.0 = 100 px/s
        self.assertAlmostEqual(track.vertical_velocity(window_seconds=1.5), 100.0, delta=1.0)

        # Aspect ratio change
        track.update([100.0, 250.0, 260.0, 310.0], score=0.9, timestamp=1.5)  # w=160, h=60, AR=2.67
        ar_change = track.aspect_ratio_change(window_seconds=2.0)
        self.assertGreater(ar_change, 1.5)


class TestIncidentEngine(unittest.TestCase):
    """Test suite for IncidentEngine fall detection and false positive rejection."""

    def setUp(self) -> None:
        self.engine = IncidentEngine(
            standing_aspect_ratio=0.85,
            lying_aspect_ratio=1.2,
            min_drop_velocity=15.0,
            min_lying_duration=3.0,
            cooldown_seconds=30.0,
        )

    def test_standing_and_walking_produces_no_incidents(self) -> None:
        """A person walking normally (vertical aspect ratio ~0.4) never triggers an incident."""
        track = Track(
            track_id=10,
            bbox=[100.0, 100.0, 160.0, 260.0],
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        # Simulate walking for 5 seconds (50 frames at 10 FPS)
        for i in range(1, 51):
            t = i * 0.1
            x_offset = i * 2.0  # walking horizontally
            track.update([100.0 + x_offset, 100.0, 160.0 + x_offset, 260.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

    def test_sitting_down_produces_no_incidents(self) -> None:
        """Sitting down reduces height but aspect ratio remains vertical/compact (< 1.2)."""
        track = Track(
            track_id=11,
            bbox=[100.0, 100.0, 160.0, 260.0],  # standing: w=60, h=160, AR=0.375
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        # Sits down at t=1.0: height becomes 95, width becomes 65 -> AR = 65/95 = 0.684 < 0.85
        for i in range(1, 10):
            t = i * 0.1
            track.update([100.0, 100.0, 160.0, 260.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

        # Seated position maintained for 5 seconds
        for i in range(10, 60):
            t = i * 0.1
            track.update([98.0, 150.0, 163.0, 245.0], score=0.9, timestamp=t)  # w=65, h=95, AR=0.68
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

    def test_bending_down_and_standing_up_produces_no_incidents(self) -> None:
        """Bending down briefly then standing up does not maintain horizontal pose for 3s."""
        track = Track(
            track_id=12,
            bbox=[100.0, 100.0, 160.0, 260.0],  # standing
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        # Bends down for 1.2 seconds (t=1.0 to t=2.2)
        for i in range(1, 10):
            t = i * 0.1
            track.update([100.0, 100.0, 160.0, 260.0], score=0.9, timestamp=t)
            self.assertEqual(self.engine.process_tracks([track], timestamp=t), [])

        for i in range(10, 22):
            t = i * 0.1
            # Bending: wider box, w=110, h=80, AR=1.375
            track.update([100.0, 180.0, 210.0, 260.0], score=0.88, timestamp=t)
            self.assertEqual(self.engine.process_tracks([track], timestamp=t), [])

        # Stands back up at t=2.3 onwards
        for i in range(22, 60):
            t = i * 0.1
            track.update([100.0, 100.0, 160.0, 260.0], score=0.9, timestamp=t)
            self.assertEqual(self.engine.process_tracks([track], timestamp=t), [])

    def test_authentic_fall_sequence_detection(self) -> None:
        """Standing -> rapid downward drop & AR inversion -> lying > 3.0s triggers incident."""
        track = Track(
            track_id=20,
            bbox=[100.0, 100.0, 160.0, 260.0],  # standing: cx=130, cy=180, AR=0.375
            score=0.92,
            label="person",
            timestamp=0.0,
        )

        # Phase 1: Standing (t=0.0 to 1.0)
        for i in range(1, 11):
            t = round(i * 0.1, 2)
            track.update([100.0, 100.0, 160.0, 260.0], score=0.92, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

        # Phase 2: Rapid fall drop between t=1.0 and t=1.5
        # Centroid Y drops from 180 to 250 (+70px in 0.5s = 140px/s velocity)
        # AR flips to horizontal (w=160, h=60, AR=2.67 >= 1.2)
        fall_steps = [
            (1.1, [100.0, 120.0, 165.0, 260.0]),  # dropping
            (1.2, [100.0, 150.0, 175.0, 260.0]),  # tumbling
            (1.3, [100.0, 180.0, 200.0, 265.0]),  # collapsing
            (1.4, [100.0, 210.0, 230.0, 270.0]),  # near floor
            (1.5, [100.0, 220.0, 260.0, 280.0]),  # on floor: cx=180, cy=250, w=160, h=60, AR=2.67
        ]
        for t, bbox in fall_steps:
            track.update(bbox, score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

        # Phase 3: Lying stationary on the floor for 3.5s (from t=1.5 to t=5.0)
        # Prior to t=4.5 (3.0s after onset at ~1.5), no incident should be emitted
        for i in range(16, 45):
            t = round(i * 0.1, 2)
            # small jitter to simulate sensor noise
            jitter = (i % 2) * 0.5
            track.update([100.0 + jitter, 220.0, 260.0 + jitter, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [], f"Triggered prematurely at t={t}")

        # At t=4.6 (> 3.0s of continuous lying since onset at t=1.5):
        t_trigger = 4.6
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t_trigger)
        incidents = self.engine.process_tracks([track], timestamp=t_trigger)
        self.assertEqual(len(incidents), 1, "Expected fall incident confirmation at t=4.6")

        incident = incidents[0]
        self.assertEqual(incident["taxonomy"], "person_fall")
        self.assertEqual(incident["severity"], "critical")
        self.assertEqual(incident["anchor_kind"], "onset")
        self.assertEqual(incident["track_id"], 20)
        self.assertAlmostEqual(incident["detection_time"], 4.6, delta=0.05)
        # Onset timestamp should point back to when the fall started/reached ground (~1.0 - 1.5s)
        self.assertGreaterEqual(incident["anchor_time"], 1.0)
        self.assertLessEqual(incident["anchor_time"], 1.6)
        self.assertGreaterEqual(incident["confidence"], 0.8)
        self.assertTrue(len(incident["detections"]) > 0)

    def test_cooldown_prevents_duplicate_incidents(self) -> None:
        """30-second cooldown per track_id suppresses duplicate events."""
        track = Track(
            track_id=30,
            bbox=[100.0, 100.0, 160.0, 260.0],  # standing
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        # Establish standing
        for i in range(1, 10):
            track.update([100.0, 100.0, 160.0, 260.0], score=0.9, timestamp=i * 0.1)
            self.engine.process_tracks([track], timestamp=i * 0.1)

        # Drop and lie down at t=1.0
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=1.0)
        self.engine.process_tracks([track], timestamp=1.0)

        # Lie for 3.1 seconds -> trigger at t=4.1
        for i in range(11, 41):
            t = i * 0.1
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            self.engine.process_tracks([track], timestamp=t)

        t_trigger = 4.1
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t_trigger)
        incidents = self.engine.process_tracks([track], timestamp=t_trigger)
        self.assertEqual(len(incidents), 1)

        # Continued lying over the next 25 seconds (within 30s cooldown)
        for i in range(42, 250):
            t = i * 0.1
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [], f"Cooldown violated at t={t}")

    def test_fall_with_early_recovery_does_not_trigger(self) -> None:
        """If person falls but recovers/stands up before 3.0s lying, no alert is emitted."""
        track = Track(
            track_id=40,
            bbox=[100.0, 100.0, 160.0, 260.0],
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        # Standing
        track.update([100.0, 100.0, 160.0, 260.0], score=0.9, timestamp=0.5)
        self.engine.process_tracks([track], timestamp=0.5)

        # Falls at t=1.0
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=1.0)
        self.engine.process_tracks([track], timestamp=1.0)

        # Lies down for only 1.8 seconds (until t=2.8)
        for i in range(11, 29):
            t = i * 0.1
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

        # Stands back up at t=3.0 (AR flips back to vertical 0.375)
        for i in range(29, 60):
            t = i * 0.1
            track.update([100.0, 100.0, 160.0, 260.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

    def test_already_lying_without_prior_standing_triggers_persistent_lying(self) -> None:
        """Person already lying on ground from first observation triggers person_lying_persistent after duration."""
        track = Track(
            track_id=50,
            bbox=[100.0, 220.0, 260.0, 280.0],  # horizontal from the start: AR = 2.67
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        self.assertEqual(self.engine.process_tracks([track], timestamp=0.0), [])

        # First 3.0 seconds: no incident emitted yet
        for i in range(1, 31):
            t = round(i * 0.1, 2)
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [], f"Triggered prematurely at t={t}")

        # At t=3.1 (> min_lying_duration 3.0s since first qualifying observation at t=0.0)
        t_trigger = 3.1
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t_trigger)
        incidents = self.engine.process_tracks([track], timestamp=t_trigger)
        self.assertEqual(len(incidents), 1, "Expected persistent lying incident at t=3.1")

        incident = incidents[0]
        self.assertEqual(incident["taxonomy"], "person_lying_persistent")
        self.assertEqual(incident["severity"], "high")
        self.assertEqual(incident["anchor_kind"], "first_qualifying_observation")
        self.assertAlmostEqual(incident["anchor_time"], 0.0, delta=0.05)
        self.assertAlmostEqual(incident["detection_time"], 3.1, delta=0.05)
        self.assertEqual(incident["track_id"], 50)
        self.assertGreaterEqual(incident["confidence"], 0.8)
        self.assertTrue(len(incident["detections"]) > 0)

    def test_persistent_lying_separate_duration_and_severity(self) -> None:
        """Configuring separate duration (e.g. 5.0s) and severity ('high') is respected."""
        engine = IncidentEngine(
            standing_aspect_ratio=0.85,
            lying_aspect_ratio=1.2,
            min_drop_velocity=15.0,
            min_lying_duration=2.0,
            persistent_lying_duration=5.0,
            persistent_lying_severity="high",
            cooldown_seconds=30.0,
        )
        track = Track(
            track_id=55,
            bbox=[100.0, 220.0, 260.0, 280.0],  # horizontal from the start
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        self.assertEqual(engine.process_tracks([track], timestamp=0.0), [])

        # Even after min_lying_duration (2.0s), persistent lying shouldn't trigger until 5.0s
        for i in range(1, 50):
            t = round(i * 0.1, 2)
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            incidents = engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

        # At t=5.1s (> persistent_lying_duration 5.0s)
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=5.1)
        incidents = engine.process_tracks([track], timestamp=5.1)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["taxonomy"], "person_lying_persistent")
        self.assertEqual(incidents[0]["severity"], "high")
        self.assertEqual(incidents[0]["anchor_kind"], "first_qualifying_observation")
        self.assertAlmostEqual(incidents[0]["anchor_time"], 0.0, delta=0.05)

    def test_persistent_lying_early_recovery_cancels_candidate(self) -> None:
        """Standing or sitting semi-upright before duration cancels persistent lying candidate."""
        track = Track(
            track_id=56,
            bbox=[100.0, 220.0, 260.0, 280.0],  # horizontal: AR = 2.67
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        self.assertEqual(self.engine.process_tracks([track], timestamp=0.0), [])

        # Lies for 2.0s (< 3.0s min_lying_duration)
        for i in range(1, 21):
            t = round(i * 0.1, 2)
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

        # Recovers to standing at t=2.1 (AR = 60/160 = 0.375)
        for i in range(21, 50):
            t = round(i * 0.1, 2)
            track.update([100.0, 100.0, 160.0, 260.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [], f"Triggered after recovery at t={t}")

    def test_persistent_lying_track_gap_and_observation_gap_breaks_candidate(self) -> None:
        """Track disappearance or observation_gap breaks persistent candidate and resets qualifying time."""
        # 1. Observation gap test
        track1 = Track(track_id=57, bbox=[100.0, 220.0, 260.0, 280.0], score=0.9, label="person", timestamp=0.0)
        self.assertEqual(self.engine.process_tracks([track1], timestamp=0.0), [])
        for i in range(1, 21):
            t = round(i * 0.1, 2)
            track1.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            self.assertEqual(self.engine.process_tracks([track1], timestamp=t), [])

        # Observation gap occurs at t=2.1
        self.engine.observation_gap()

        # Re-observation lying starting at t=2.5
        track1.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=2.5)
        self.assertEqual(self.engine.process_tracks([track1], timestamp=2.5), [])

        # At t=3.5 (1.0s after gap, 3.5s total), candidate must NOT trigger because gap broke it
        for i in range(26, 55):
            t = round(i * 0.1, 2)
            track1.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track1], timestamp=t)
            self.assertEqual(incidents, [], f"Premature trigger after gap at t={t}")

        # At t=5.6 (> 3.0s after re-appearance at t=2.5), candidate triggers with anchor_time = 2.5
        track1.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=5.6)
        incidents = self.engine.process_tracks([track1], timestamp=5.6)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["taxonomy"], "person_lying_persistent")
        self.assertAlmostEqual(incidents[0]["anchor_time"], 2.5, delta=0.05)

    def test_persistent_lying_cooldown_prevents_duplicate_spam(self) -> None:
        """Persistent lying triggers once, and cooldown suppresses repeated alerts."""
        track = Track(track_id=58, bbox=[100.0, 220.0, 260.0, 280.0], score=0.9, label="person", timestamp=0.0)
        self.assertEqual(self.engine.process_tracks([track], timestamp=0.0), [])
        for i in range(1, 31):
            t = round(i * 0.1, 2)
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            self.engine.process_tracks([track], timestamp=t)

        # Trigger at t=3.1
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=3.1)
        incidents = self.engine.process_tracks([track], timestamp=3.1)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["taxonomy"], "person_lying_persistent")

        # Continues lying through t=25.0 (within 30s cooldown) -> no spam
        for i in range(32, 250):
            t = round(i * 0.1, 2)
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [], f"Repeated alert at t={t}")

    def test_second_fall_after_cooldown_triggers(self) -> None:
        """After 30s cooldown and re-standing, a second authentic fall triggers again."""
        track = Track(
            track_id=60,
            bbox=[100.0, 100.0, 160.0, 260.0],  # standing
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        # Establish standing
        track.update([100.0, 100.0, 160.0, 260.0], score=0.9, timestamp=0.5)
        self.engine.process_tracks([track], timestamp=0.5)

        # Fall 1 at t=1.0, lying until t=4.1 -> triggers incident 1
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=1.0)
        self.engine.process_tracks([track], timestamp=1.0)
        for i in range(11, 41):
            t = i * 0.1
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            self.engine.process_tracks([track], timestamp=t)

        incidents_1 = self.engine.process_tracks([track], timestamp=4.1)
        self.assertEqual(len(incidents_1), 1)

        # Person recovers and stands back up from t=10.0 to t=34.9
        for i in range(100, 350):
            t = round(i * 0.1, 2)
            track.update([100.0, 100.0, 160.0, 260.0], score=0.9, timestamp=t)
            self.engine.process_tracks([track], timestamp=t)

        # Second fall at t=35.0 (30.9s after first alert at 4.1s)
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=35.0)
        self.engine.process_tracks([track], timestamp=35.0)
        for i in range(351, 381):
            t = round(i * 0.1, 2)
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            self.engine.process_tracks([track], timestamp=t)

        incidents_2 = self.engine.process_tracks([track], timestamp=38.1)
        self.assertEqual(len(incidents_2), 1)
        self.assertEqual(incidents_2[0]["track_id"], 60)
        self.assertAlmostEqual(incidents_2[0]["anchor_time"], 35.0, delta=0.1)

    def test_engine_reset_clears_states(self) -> None:
        track = Track(track_id=70, bbox=[100.0, 100.0, 160.0, 260.0], score=0.9, label="person", timestamp=0.0)
        self.engine.process_tracks([track], timestamp=0.0)
        self.assertIn(70, self.engine._states)
        self.engine.reset()
        self.assertEqual(len(self.engine._states), 0)

    def test_persistent_lying_transient_speed_jitter_preserves_anchor_time(self) -> None:
        """Transient speed/jitter during persistent lying must not shift first_qualifying_time forward."""
        track = Track(
            track_id=80,
            bbox=[100.0, 220.0, 260.0, 280.0],  # horizontal from start: AR = 2.67
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        self.assertEqual(self.engine.process_tracks([track], timestamp=0.0), [])

        # Frames up to t=0.9: steady lying
        for i in range(1, 10):
            t = round(i * 0.1, 2)
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            self.assertEqual(self.engine.process_tracks([track], timestamp=t), [])

        # Transient jitter at t=1.0: bbox shifts by 8px in 0.1s -> speed = 80 px/s > max_motion_speed (50.0)
        # Person is still lying (w=160, h=60, AR=2.67)
        track.update([108.0, 220.0, 268.0, 280.0], score=0.9, timestamp=1.0)
        self.assertEqual(self.engine.process_tracks([track], timestamp=1.0), [])

        # Continues lying steadily until t=3.1 (> 3.0s from t=0.0)
        for i in range(11, 31):
            t = round(i * 0.1, 2)
            track.update([108.0, 220.0, 268.0, 280.0], score=0.9, timestamp=t)
            self.assertEqual(self.engine.process_tracks([track], timestamp=t), [])

        # At t=3.1 (> 3.0s duration from initial observation at t=0.0):
        # Should trigger with anchor_time = 0.0, NOT shifted to 1.0 due to jitter
        track.update([108.0, 220.0, 268.0, 280.0], score=0.9, timestamp=3.1)
        incidents = self.engine.process_tracks([track], timestamp=3.1)
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["taxonomy"], "person_lying_persistent")
        self.assertEqual(incidents[0]["anchor_kind"], "first_qualifying_observation")
        self.assertAlmostEqual(incidents[0]["anchor_time"], 0.0, delta=0.05)

    def test_id_switch_without_prior_standing_triggers_persistent_lying(self) -> None:
        """When an ID switch occurs on a lying person without prior standing, the new track triggers persistent lying with its first observation anchor."""
        # Initial track 85 is standing briefly then disappears
        track1 = Track(
            track_id=85,
            bbox=[100.0, 100.0, 160.0, 260.0],  # standing
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        self.engine.process_tracks([track1], timestamp=0.0)

        # ID switch happens: track 85 is lost, new track 86 appears already lying at t=1.0
        # Track 86 has NO standing history
        track2 = Track(
            track_id=86,
            bbox=[100.0, 220.0, 260.0, 280.0],  # lying
            score=0.9,
            label="person",
            timestamp=1.0,
        )
        self.assertEqual(self.engine.process_tracks([track2], timestamp=1.0), [])

        # Track 2 stays lying for 3.1s (until t=4.1)
        for i in range(11, 41):
            t = round(i * 0.1, 2)
            track2.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            self.assertEqual(self.engine.process_tracks([track2], timestamp=t), [])

        # At t=4.1 (> 3.0s after track 2 first qualifying observation at t=1.0)
        track2.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=4.1)
        incidents = self.engine.process_tracks([track2], timestamp=4.1)
        self.assertEqual(len(incidents), 1)
        incident = incidents[0]
        self.assertEqual(incident["taxonomy"], "person_lying_persistent")
        self.assertEqual(incident["track_id"], 86)
        self.assertEqual(incident["anchor_kind"], "first_qualifying_observation")
        self.assertAlmostEqual(incident["anchor_time"], 1.0, delta=0.05)

    def test_non_person_tracks_ignored_by_incident_engine(self) -> None:
        """P0-01: IncidentEngine strictly ignores non-person tracks (e.g., car, truck)."""
        car_track = Track(
            track_id=90,
            bbox=[100.0, 220.0, 260.0, 280.0],
            score=0.9,
            label="car",
            timestamp=0.0,
        )
        motorcycle_track = Track(
            track_id=91,
            bbox=[100.0, 220.0, 260.0, 280.0],
            score=0.9,
            label="motorcycle",
            timestamp=0.0,
        )
        for i in range(40):
            t = round(i * 0.1, 2)
            car_track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            motorcycle_track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([car_track, motorcycle_track], timestamp=t)
            self.assertEqual(incidents, [], f"Non-person tracks should not emit incidents at t={t}")

    def test_persistent_lying_anchor_is_first_stationary_observation(self) -> None:
        """Review (spec #26 / contracts §3): anchor is the FIRST qualifying (stationary) observation,
        not the last frame that was still moving."""
        track = Track(track_id=93, bbox=[100.0, 220.0, 260.0, 280.0], score=0.9, label="person", timestamp=0.0)
        self.engine.process_tracks([track], timestamp=0.0)
        for i in range(1, 21):  # moving fast through t=2.0
            t = round(i * 0.1, 2)
            track.update([100.0 + i * 10.0, 220.0, 260.0 + i * 10.0, 280.0], score=0.9, timestamp=t)
            self.engine.process_tracks([track], timestamp=t)
        anchors = []
        for i in range(21, 60):  # stationary from t=2.1
            t = round(i * 0.1, 2)
            track.update([300.0, 220.0, 460.0, 280.0], score=0.9, timestamp=t)
            for incident in self.engine.process_tracks([track], timestamp=t):
                anchors.append(incident["anchor_time"])
        self.assertEqual(len(anchors), 1)
        self.assertAlmostEqual(anchors[0], 2.1, delta=0.01)

    def test_out_of_roi_track_state_is_dropped_so_reentry_starts_fresh(self) -> None:
        """ocr #7: a track outside the ROI must not keep stale per-track state that is reused on re-entry."""
        roi = [[0.0, 0.0], [500.0, 0.0], [500.0, 400.0], [0.0, 400.0]]
        engine = IncidentEngine(min_lying_duration=3.0, cooldown_seconds=30.0, roi_polygon=roi)
        track = Track(track_id=201, bbox=[100.0, 220.0, 260.0, 280.0], score=0.9, label="person", timestamp=0.0)
        for i in range(0, 20):  # inside ROI, lying and stationary for ~1.9s
            t = round(i * 0.1, 2)
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            engine.process_tracks([track], timestamp=t)
        self.assertIn(201, engine._states)
        for i in range(20, 60):  # leaves the ROI for a long time
            t = round(i * 0.1, 2)
            track.update([600.0, 220.0, 760.0, 280.0], score=0.9, timestamp=t)
            engine.process_tracks([track], timestamp=t)
        self.assertNotIn(201, engine._states, "state of a track outside the ROI must be dropped")
        emitted = []
        for i in range(60, 75):  # re-enters, lying ~1.4s: stale state would wrongly fire (anchor from t<2)
            t = round(i * 0.1, 2)
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            emitted.extend(engine.process_tracks([track], timestamp=t))
        self.assertEqual(emitted, [], "re-entry must restart the persistence window, not reuse stale state")

    def test_person_lying_persistent_requires_stationary_speed(self) -> None:
        """P0-02: person_lying_persistent requires speed <= max_motion_speed; motion resets first_qualifying_time."""
        track = Track(
            track_id=92,
            bbox=[100.0, 220.0, 260.0, 280.0],  # cx=180, cy=250, lying AR=2.67
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        self.engine.process_tracks([track], timestamp=0.0)

        # Phase 1: Moving fast while lying from t=0.1 to t=2.0 (speed: 10px / 0.1s = 100px/s > 50px/s max_motion_speed)
        for i in range(1, 21):
            t = round(i * 0.1, 2)
            offset = i * 10.0
            track.update([100.0 + offset, 220.0, 260.0 + offset, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [], f"Moving lying track must not trigger incident at t={t}")

        # Phase 2: Stationary from t=2.1 onwards.
        # Needs 3.0s of continuous stationary lying (until t > 2.0 + 3.0 = 5.0s, i.e., t=5.1)
        triggered = False
        for i in range(21, 55):
            t = round(i * 0.1, 2)
            offset = 200.0  # stationary
            track.update([100.0 + offset, 220.0, 260.0 + offset, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            if t <= 5.0:
                self.assertEqual(incidents, [], f"Triggered prematurely at t={t} (needs 3.0s continuous stationary)")
            elif len(incidents) > 0:
                self.assertEqual(len(incidents), 1)
                self.assertEqual(incidents[0]["taxonomy"], "person_lying_persistent")
                self.assertAlmostEqual(incidents[0]["anchor_time"], 2.0, delta=0.15)
                triggered = True
                break
        self.assertTrue(triggered, "Expected persistent lying incident after 3.0s stationary")

    def test_person_lying_on_stationary_upright_vehicle_is_low_priority(self) -> None:
        """#27: lying on a stationary upright motorcycle keeps review but at low priority."""
        engine = IncidentEngine(
            min_lying_duration=3.0,
            persistent_lying_duration=1.0,
            cooldown_seconds=30.0,
        )
        bike_bbox = [300.0, 180.0, 360.0, 280.0]  # AR 0.6: upright
        bike = Track(track_id=900, bbox=bike_bbox, score=0.9, label="motorcycle", timestamp=0.0)
        engine.process_tracks([bike], timestamp=0.0)

        person_bbox = [245.0, 200.0, 405.0, 260.0]  # lying AR 2.67, center inside bike bbox
        person = Track(track_id=901, bbox=person_bbox, score=0.88, label="person", timestamp=1.0)
        emitted: list[dict[str, Any]] = []
        for i in range(20):
            t = round(1.0 + i * 0.1, 2)
            bike.update(bike_bbox, score=0.9, timestamp=t)
            person.update(person_bbox, score=0.88, timestamp=t)
            emitted.extend(engine.process_tracks([bike, person], timestamp=t))

        self.assertEqual(len(emitted), 1, "on-vehicle must still emit a review event")
        incident = emitted[0]
        self.assertEqual(incident["taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(incident["severity"], "low")
        self.assertEqual(incident["anchor_kind"], "first_qualifying_observation")
        self.assertAlmostEqual(incident["anchor_time"], 1.0, delta=0.05)
        self.assertEqual(incident["track_id"], 901)
        self.assertEqual(incident["vehicle_track_id"], 900)

    def test_rapid_fall_over_stationary_vehicle_stays_critical(self) -> None:
        """#27 danger override: an observed falling onset is never demoted for bbox overlap."""
        engine = IncidentEngine(min_lying_duration=3.0, cooldown_seconds=30.0)
        bike_bbox = [300.0, 180.0, 360.0, 280.0]
        bike = Track(track_id=910, bbox=bike_bbox, score=0.9, label="motorcycle", timestamp=0.0)
        engine.process_tracks([bike], timestamp=0.0)

        standing_bbox = [300.0, 120.0, 360.0, 280.0]  # AR 0.375, overlapping the bike
        person = Track(track_id=911, bbox=standing_bbox, score=0.9, label="person", timestamp=1.0)
        bike.update(bike_bbox, score=0.9, timestamp=1.0)
        engine.process_tracks([bike, person], timestamp=1.0)

        lying_bbox = [245.0, 200.0, 405.0, 260.0]
        emitted: list[dict[str, Any]] = []
        for i in range(1, 50):
            t = round(1.0 + i * 0.1, 2)
            bike.update(bike_bbox, score=0.9, timestamp=t)
            person.update(lying_bbox, score=0.9, timestamp=t)
            emitted.extend(engine.process_tracks([bike, person], timestamp=t))
            if emitted:
                break

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["taxonomy"], "person_fall")
        self.assertEqual(emitted[0]["severity"], "critical")
        self.assertEqual(emitted[0]["anchor_kind"], "onset")

    def test_fallen_vehicle_beside_lying_person_is_not_low_priority(self) -> None:
        """#27 danger override: a fallen/overturned 2-wheeler keeps the high review priority."""
        engine = IncidentEngine(persistent_lying_duration=1.0, cooldown_seconds=30.0)
        fallen_bike_bbox = [300.0, 240.0, 440.0, 280.0]  # AR 3.5: lying on its side
        bike = Track(track_id=920, bbox=fallen_bike_bbox, score=0.9, label="motorcycle", timestamp=0.0)
        engine.process_tracks([bike], timestamp=0.0)

        person_bbox = [280.0, 210.0, 440.0, 270.0]
        person = Track(track_id=921, bbox=person_bbox, score=0.88, label="person", timestamp=1.0)
        emitted: list[dict[str, Any]] = []
        for i in range(20):
            t = round(1.0 + i * 0.1, 2)
            bike.update(fallen_bike_bbox, score=0.9, timestamp=t)
            person.update(person_bbox, score=0.88, timestamp=t)
            emitted.extend(engine.process_tracks([bike, person], timestamp=t))

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["taxonomy"], "person_lying_persistent")
        self.assertEqual(emitted[0]["severity"], "high")
        self.assertNotIn("vehicle_track_id", emitted[0])

    def test_moving_vehicle_arriving_after_lying_is_not_on_vehicle(self) -> None:
        """#27: a vehicle that was moving/arrived after the lying state started cannot demote."""
        engine = IncidentEngine(persistent_lying_duration=1.0, cooldown_seconds=30.0)
        bike = Track(track_id=930, bbox=[100.0, 180.0, 160.0, 280.0], score=0.9,
                     label="motorcycle", timestamp=0.0)
        engine.process_tracks([bike], timestamp=0.0)

        person_bbox = [245.0, 200.0, 405.0, 260.0]
        person = Track(track_id=931, bbox=person_bbox, score=0.88, label="person", timestamp=1.0)
        emitted: list[dict[str, Any]] = []
        for i in range(1, 30):
            t = round(1.0 + i * 0.1, 2)
            offset = min(i * 20.0, 200.0)  # drives toward the person, stops overlapping
            bike.update([100.0 + offset, 180.0, 160.0 + offset, 280.0], score=0.9, timestamp=t)
            person.update(person_bbox, score=0.88, timestamp=t)
            emitted.extend(engine.process_tracks([bike, person], timestamp=t))

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["taxonomy"], "person_lying_persistent")
        self.assertEqual(emitted[0]["severity"], "high")
        self.assertNotIn("vehicle_track_id", emitted[0])

    def test_vehicle_tilting_after_lying_onset_activates_danger_override(self) -> None:
        """#27 danger override: the qualifying vehicle must stay upright for low priority."""
        engine = IncidentEngine(persistent_lying_duration=1.0, cooldown_seconds=30.0)
        bike_bbox = [300.0, 180.0, 360.0, 280.0]
        bike = Track(track_id=940, bbox=bike_bbox, score=0.9, label="motorcycle", timestamp=0.0)
        engine.process_tracks([bike], timestamp=0.0)

        person_bbox = [245.0, 200.0, 405.0, 260.0]
        person = Track(track_id=941, bbox=person_bbox, score=0.88, label="person", timestamp=1.0)
        emitted: list[dict[str, Any]] = []
        for i in range(20):
            t = round(1.0 + i * 0.1, 2)
            current_bike_bbox = [300.0, 240.0, 440.0, 280.0] if t >= 2.0 else bike_bbox
            bike.update(current_bike_bbox, score=0.9, timestamp=t)
            person.update(person_bbox, score=0.88, timestamp=t)
            emitted.extend(engine.process_tracks([bike, person], timestamp=t))

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["taxonomy"], "person_lying_persistent")
        self.assertEqual(emitted[0]["severity"], "high")
        self.assertNotIn("vehicle_track_id", emitted[0])

    def test_fall_candidate_motion_does_not_overwrite_onset_time(self) -> None:
        """P1-10: Motion while in fall candidate updates lying_start_time but preserves onset_time."""
        track = Track(
            track_id=95,
            bbox=[100.0, 100.0, 160.0, 260.0],  # standing
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        self.engine.process_tracks([track], timestamp=0.0)

        # Drop down at t=0.5 -> triggers fall candidate onset
        track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=0.5)
        self.engine.process_tracks([track], timestamp=0.5)
        state = self.engine._states[95]
        self.assertTrue(state.in_fall_candidate)
        self.assertAlmostEqual(state.onset_time, 0.5)

        # Continues moving fast while tumbling on floor at t=1.0 (dx=50px in 0.5s = 100px/s > 50px/s)
        track.update([150.0, 220.0, 310.0, 280.0], score=0.9, timestamp=1.0)
        self.engine.process_tracks([track], timestamp=1.0)
        state = self.engine._states[95]
        self.assertTrue(state.in_fall_candidate)
        self.assertAlmostEqual(state.lying_start_time, 1.0)

        # Now stationary lying on floor from t=1.1 until t=4.5 (> 3.0s after settling at t=1.0)
        incidents = []
        for i in range(11, 45):
            t = round(i * 0.1, 2)
            track.update([150.0, 220.0, 310.0, 280.0], score=0.9, timestamp=t)
            res = self.engine.process_tracks([track], timestamp=t)
            if res:
                incidents.extend(res)
                break

        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["taxonomy"], "person_fall")
        # Onset time must be the original fall start at 0.5, NOT the motion settling time at 1.0!
        self.assertAlmostEqual(incidents[0]["anchor_time"], 0.5, delta=0.05)

    def test_incident_engine_roi_polygon_filtering(self) -> None:
        """P1-13: IncidentEngine filters tracks by bounding box foot point against roi_polygon."""
        roi = [[0.0, 0.0], [500.0, 0.0], [500.0, 400.0], [0.0, 400.0]]
        engine = IncidentEngine(
            min_lying_duration=3.0,
            cooldown_seconds=30.0,
            roi_polygon=roi,
        )

        # Track 1 inside ROI: foot point is ((100+260)/2, 280) = (180, 280) -> INSIDE
        track_inside = Track(
            track_id=101,
            bbox=[100.0, 220.0, 260.0, 280.0],
            score=0.9,
            label="person",
            timestamp=0.0,
        )

        # Track 2 outside ROI: foot point is ((600+760)/2, 280) = (680, 280) -> OUTSIDE
        track_outside = Track(
            track_id=102,
            bbox=[600.0, 220.0, 760.0, 280.0],
            score=0.9,
            label="person",
            timestamp=0.0,
        )

        emitted = []
        for i in range(35):
            t = round(i * 0.1, 2)
            track_inside.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            track_outside.update([600.0, 220.0, 760.0, 280.0], score=0.9, timestamp=t)
            incidents = engine.process_tracks([track_inside, track_outside], timestamp=t)
            emitted.extend(incidents)

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["track_id"], 101)
        self.assertEqual(emitted[0]["taxonomy"], "person_lying_persistent")





class TestEdgePipelineIncidents(unittest.TestCase):
    """Integration tests for EdgePipeline incident handling (person_fall and person_lying_persistent)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.recorder_dir = Path(self.tmp_dir) / "recorder"
        self.recorder_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(self.tmp_dir) / "outbox.db"
        self.recorder = FileRecorder(self.recorder_dir)
        self.outbox = EventOutbox(self.db_path)
        self.pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            incident_engine=IncidentEngine(
                min_lying_duration=3.0,
                cooldown_seconds=30.0,
            ),
        )
        self.rgb = np.zeros((360, 640, 3), dtype=np.uint8)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_pipeline_emits_valid_event_and_evidence_for_persistent_lying(self) -> None:
        """Pipeline handles person_lying_persistent with anchor_kind first_qualifying_observation."""
        # Person appears already lying in frame 0 at t=0.0
        lying_det = [{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.9, "label": "person"}]

        emitted: list[dict[str, Any]] = []
        for i in range(35):
            t = round(i * 0.1, 2)
            events = self.pipeline.process_frame(self.rgb, timestamp=t, frame_id=i, detections=lying_det)
            emitted.extend(events)

        self.assertEqual(len(emitted), 1, "Expected exactly 1 persistent lying event emitted by pipeline")
        event = emitted[0]
        payload = event["payload"]
        self.assertEqual(payload["taxonomy"], "person_lying_persistent")
        self.assertEqual(payload["severity"], "high")
        self.assertNotIn("anchor_kind", payload)
        # P1-12: the track is tentative at t=0.0 and active from t=0.1, so the first
        # qualifying observation seen by the incident engine is one frame later.
        self.assertAlmostEqual(payload["anchor_time"], 0.1, delta=0.05)

        # Evidence request verification per docs/architecture/contracts.md:42
        self.assertEqual(len(payload["evidence_requests"]), 1)
        req = payload["evidence_requests"][0]
        self.assertEqual(req["evidence_anchor_kind"], "first_qualifying_observation")
        self.assertNotEqual(req["evidence_anchor_kind"], "onset")
        self.assertAlmostEqual(req["evidence_anchor_time"], 0.1, delta=0.05)
        self.assertAlmostEqual(req["requested_start"], -9.9, delta=0.05)
        self.assertAlmostEqual(req["requested_end"], 20.1, delta=0.05)

        # Check outbox persistence
        pending = self.outbox.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event"]["event_id"], event["event_id"])

    def test_pipeline_emits_low_priority_event_for_person_on_stationary_vehicle(self) -> None:
        """#27: pipeline keeps the low-severity on-vehicle review event and its anchor."""
        bike_det = [{"bbox": [300.0, 180.0, 360.0, 280.0], "score": 0.9, "label": "motorcycle"}]
        for i in range(6):  # the motorcycle is already parked before the person lies on it
            self.pipeline.process_frame(self.rgb, timestamp=round(i * 0.1, 2), frame_id=i, detections=bike_det)

        person_det = {"bbox": [245.0, 200.0, 405.0, 260.0], "score": 0.88, "label": "person"}
        emitted: list[dict[str, Any]] = []
        for i in range(6, 50):
            t = round(i * 0.1, 2)
            events = self.pipeline.process_frame(
                self.rgb, timestamp=t, frame_id=i, detections=[*bike_det, person_det])
            emitted.extend(events)

        self.assertEqual(len(emitted), 1, "Expected exactly 1 on-vehicle review event")
        payload = emitted[0]["payload"]
        self.assertEqual(payload["taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(payload["severity"], "low")
        self.assertIn("vehicle_track_id", payload)
        self.assertEqual(payload["evidence_requests"][0]["evidence_anchor_kind"],
                         "first_qualifying_observation")
        self.assertAlmostEqual(payload["anchor_time"], 0.7, delta=0.05)
        self.assertEqual(len(self.outbox.pending()), 1)

    def test_pipeline_emits_valid_event_and_evidence_for_person_fall(self) -> None:
        """Pipeline handles person_fall with anchor_kind onset."""
        # Frame 0 to 10: standing
        standing_det = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.92, "label": "person"}]
        for i in range(11):
            t = round(i * 0.1, 2)
            self.pipeline.process_frame(self.rgb, timestamp=t, frame_id=i, detections=standing_det)

        # Frame 11 to 15: rapid drop
        fall_boxes = [
            [100.0, 120.0, 165.0, 260.0],
            [100.0, 150.0, 175.0, 260.0],
            [100.0, 180.0, 200.0, 265.0],
            [100.0, 210.0, 230.0, 270.0],
            [100.0, 220.0, 260.0, 280.0],
        ]
        for idx, box in enumerate(fall_boxes, start=11):
            t = round(idx * 0.1, 2)
            self.pipeline.process_frame(self.rgb, timestamp=t, frame_id=idx, detections=[{"bbox": box, "score": 0.9, "label": "person"}])

        # Frame 16 to 48: lying stationary
        lying_det = [{"bbox": [100.0, 220.0, 260.0, 280.0], "score": 0.9, "label": "person"}]
        emitted: list[dict[str, Any]] = []
        for i in range(16, 48):
            t = round(i * 0.1, 2)
            events = self.pipeline.process_frame(self.rgb, timestamp=t, frame_id=i, detections=lying_det)
            emitted.extend(events)

        self.assertEqual(len(emitted), 1, "Expected exactly 1 fall event emitted by pipeline")
        event = emitted[0]
        payload = event["payload"]
        self.assertEqual(payload["taxonomy"], "person_fall")
        self.assertEqual(payload["severity"], "critical")
        self.assertNotIn("anchor_kind", payload)

        req = payload["evidence_requests"][0]
        self.assertEqual(req["evidence_anchor_kind"], "onset")
        self.assertAlmostEqual(req["requested_start"], req["evidence_anchor_time"] - 10, delta=0.05)
        self.assertAlmostEqual(req["requested_end"], req["evidence_anchor_time"] + 20, delta=0.05)

    def test_pipeline_handles_id_switch_lying_without_prior_standing(self) -> None:
        """Pipeline correctly processes ID switch resulting in persistent lying without prior standing."""
        # Initial track 1 standing
        standing_det = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.9, "label": "person"}]
        self.pipeline.process_frame(self.rgb, timestamp=0.0, frame_id=0, detections=standing_det)

        # Reappears at a different position lying down (new track ID) at t=3.0 across frames
        lying_det = [{"bbox": [300.0, 220.0, 460.0, 280.0], "score": 0.9, "label": "person"}]
        emitted: list[dict[str, Any]] = []
        for i in range(35):
            t = round(3.0 + i * 0.1, 2)
            events = self.pipeline.process_frame(self.rgb, timestamp=t, frame_id=10 + i, detections=lying_det)
            emitted.extend(events)

        self.assertEqual(len(emitted), 1)
        event = emitted[0]
        payload = event["payload"]
        self.assertEqual(payload["taxonomy"], "person_lying_persistent")
        self.assertEqual(payload["severity"], "high")
        self.assertNotIn("anchor_kind", payload)
        # P1-12: new track is tentative for its first frame (t=3.0), active from t=3.1.
        self.assertAlmostEqual(payload["anchor_time"], 3.1, delta=0.05)
        self.assertEqual(payload["evidence_requests"][0]["evidence_anchor_kind"], "first_qualifying_observation")
        self.assertAlmostEqual(payload["evidence_requests"][0]["evidence_anchor_time"], 3.1, delta=0.05)

    def test_handle_fall_incident_backward_compatibility(self) -> None:
        """_handle_fall_incident delegates cleanly to _handle_incident without aliasing."""
        incident = {
            "taxonomy": "person_fall",
            "severity": "critical",
            "anchor_kind": "onset",
            "anchor_time": 10.0,
            "detection_time": 13.5,
            "track_id": 99,
            "confidence": 0.95,
            "detections": [],
        }
        event = self.pipeline._handle_fall_incident(incident, 13.5)
        self.assertEqual(event["payload"]["taxonomy"], "person_fall")
        self.assertNotIn("anchor_kind", event["payload"])
        self.assertEqual(event["payload"]["severity"], "critical")
        self.assertEqual(event["payload"]["evidence_requests"][0]["evidence_anchor_kind"], "onset")
        self.assertFalse(self.pipeline._handle_incident is self.pipeline._handle_fall_incident)


if __name__ == "__main__":
    unittest.main()
