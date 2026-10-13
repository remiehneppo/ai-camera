"""Unit tests for ByteTracker and Fall Detection IncidentEngine."""

from __future__ import annotations

import unittest
from typing import Any

from apps.edge.tracker import ByteTracker, Track
from apps.edge.incident import IncidentEngine


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
        self.assertEqual(len(tracks_f1), 1)
        track_id = tracks_f1[0].track_id
        self.assertEqual(tracks_f1[0].state, "active")

        # Frame 2: Person moves slightly to (105, 102, 165, 262)
        dets_f2 = [{"bbox": [105.0, 102.0, 165.0, 262.0], "score": 0.88, "label": "person"}]
        tracks_f2 = tracker.update(dets_f2, timestamp=1.1)
        self.assertEqual(len(tracks_f2), 1)
        self.assertEqual(tracks_f2[0].track_id, track_id)

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
        tracks_f1 = tracker.update(dets_f1, timestamp=0.0)
        self.assertEqual(len(tracks_f1), 1)
        tid = tracks_f1[0].track_id

        # Frame 2: Occlusion causes score to drop to 0.35 (below high_threshold 0.6, but >= low_threshold 0.2)
        dets_f2 = [{"bbox": [202.0, 201.0, 262.0, 361.0], "score": 0.35, "label": "person"}]
        tracks_f2 = tracker.update(dets_f2, timestamp=0.1)
        self.assertEqual(len(tracks_f2), 1)
        self.assertEqual(tracks_f2[0].track_id, tid)
        self.assertAlmostEqual(tracks_f2[0].score, 0.35)

    def test_bytetracker_lost_and_removed_lifecycle(self) -> None:
        tracker = ByteTracker(max_lost_time=2.0)
        dets = [{"bbox": [50.0, 50.0, 100.0, 200.0], "score": 0.9, "label": "person"}]
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

    def test_already_lying_without_prior_standing_produces_no_incidents(self) -> None:
        """Person already lying on ground at initial appearance never triggers fall onset."""
        track = Track(
            track_id=50,
            bbox=[100.0, 220.0, 260.0, 280.0],  # horizontal from the start: AR = 2.67
            score=0.9,
            label="person",
            timestamp=0.0,
        )
        for i in range(1, 60):
            t = i * 0.1
            track.update([100.0, 220.0, 260.0, 280.0], score=0.9, timestamp=t)
            incidents = self.engine.process_tracks([track], timestamp=t)
            self.assertEqual(incidents, [])

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


if __name__ == "__main__":
    unittest.main()
