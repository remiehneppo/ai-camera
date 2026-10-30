"""Unit tests for Track and ByteTracker lifecycle, tentative state, and motion prediction (P1-12)."""

from __future__ import annotations

import unittest
from apps.edge.tracker import ByteTracker, Track, bbox_iou


class TestTrackerLifecycle(unittest.TestCase):
    """Tests for track tentative state, consecutive hits activation, and constant velocity prediction."""

    def test_new_track_starts_as_tentative_and_activates_on_second_hit(self) -> None:
        """P1-12: New tracks must start as 'tentative' and only become 'active' after >= 2 consecutive frames."""
        tracker = ByteTracker(high_threshold=0.5, low_threshold=0.1, match_threshold=0.2)
        det_f1 = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.9, "label": "person"}]

        # Frame 1: Track is tentative -> tracker.update() returns empty (only active tracks returned)
        active_f1 = tracker.update(det_f1, timestamp=1.0)
        self.assertEqual(len(active_f1), 0, "Tentative tracks must not be returned as active on frame 1")
        all_tracks = tracker.get_all_tracks()
        self.assertEqual(len(all_tracks), 1)
        self.assertEqual(all_tracks[0].state, "tentative")
        track_id = all_tracks[0].track_id

        # Frame 2: 2nd consecutive hit -> track transitions to active and is returned by update()
        det_f2 = [{"bbox": [102.0, 101.0, 162.0, 261.0], "score": 0.88, "label": "person"}]
        active_f2 = tracker.update(det_f2, timestamp=1.333)
        self.assertEqual(len(active_f2), 1)
        self.assertEqual(active_f2[0].track_id, track_id)
        self.assertEqual(active_f2[0].state, "active")

    def test_unmatched_tentative_track_is_removed_immediately(self) -> None:
        """P1-12: A tentative track that does not match on the next frame is removed immediately (not marked lost)."""
        tracker = ByteTracker(high_threshold=0.5, low_threshold=0.1, match_threshold=0.2)
        det_f1 = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.9, "label": "person"}]

        # Frame 1: Tentative track created
        tracker.update(det_f1, timestamp=1.0)
        self.assertEqual(len(tracker.get_all_tracks()), 1)
        self.assertEqual(tracker.get_all_tracks()[0].state, "tentative")

        # Frame 2: No detection -> tentative track removed, not lost
        active_f2 = tracker.update([], timestamp=1.333)
        self.assertEqual(len(active_f2), 0)
        self.assertEqual(len(tracker.get_all_tracks()), 0, "Unmatched tentative track must be removed, not retained as lost")

    def test_fast_moving_object_at_3fps_matched_via_constant_velocity(self) -> None:
        """P1-12: Fast moving object at 3 FPS (where static IoU < 0.2) is matched using constant velocity."""
        tracker = ByteTracker(high_threshold=0.5, low_threshold=0.1, match_threshold=0.2)

        # 60x160 box. Frame 1 & 2 establish track and velocity vx ~ 120 px/s (dx=40px in 0.333s)
        # Frame 1 at t=0.0: x=100
        tracker.update([{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.9, "label": "person"}], timestamp=0.0)

        # Frame 2 at t=0.333: x=135 (dx=35px, static IoU = (160-135)/(60+60-25) = 25/95 = 0.263 >= 0.2)
        # Track becomes active, velocity vx = 35 / 0.333 ~ 105 px/s established
        active_f2 = tracker.update([{"bbox": [135.0, 100.0, 195.0, 260.0], "score": 0.9, "label": "person"}], timestamp=0.333)
        self.assertEqual(len(active_f2), 1)
        tid = active_f2[0].track_id

        # Frame 3 at t=0.666: x=180 (dx=45px from Frame 2)
        # Static IoU between Frame 2 [135, 100, 195, 260] and Frame 3 [180, 100, 240, 260] is:
        # intersection = 195 - 180 = 15px. union = 60 + 60 - 15 = 105px.
        # Static IoU = 15 / 105 = 0.1428 < 0.2 (match_threshold)!
        # Static matching would FAIL and assign a new ID.
        # Constant velocity prediction predicts box around [170, 100, 230, 260], resulting in IoU ~ 0.7 > 0.2.
        active_f3 = tracker.update([{"bbox": [180.0, 100.0, 240.0, 260.0], "score": 0.9, "label": "person"}], timestamp=0.666)
        self.assertEqual(len(active_f3), 1)
        self.assertEqual(active_f3[0].track_id, tid, "Track ID must be preserved for fast moving object at 3 FPS")

    def test_lost_track_recovery_with_motion_prediction(self) -> None:
        """P1-12: A lost track is recovered across a missed frame using motion prediction."""
        tracker = ByteTracker(high_threshold=0.5, low_threshold=0.1, match_threshold=0.2, max_lost_time=2.0)

        # Frame 1 (t=0.0): x=100
        tracker.update([{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.9, "label": "person"}], timestamp=0.0)

        # Frame 2 (t=0.333): x=130 -> active, vx = 90 px/s
        active_f2 = tracker.update([{"bbox": [130.0, 100.0, 190.0, 260.0], "score": 0.9, "label": "person"}], timestamp=0.333)
        self.assertEqual(len(active_f2), 1)
        tid = active_f2[0].track_id

        # Frame 3 (t=0.666): detector missed frame -> track becomes lost
        active_f3 = tracker.update([], timestamp=0.666)
        self.assertEqual(len(active_f3), 0)
        all_tracks = tracker.get_all_tracks()
        self.assertEqual(len(all_tracks), 1)
        self.assertEqual(all_tracks[0].state, "lost")

        # Frame 4 (t=1.0): object reappears at x=190 (dt=0.667s from last observation, dx=60px)
        # Static IoU between [130, 100, 190, 260] and [190, 100, 250, 260] is 0.0!
        # Motion prediction predicts box at [190, 100, 250, 260], IoU = 1.0!
        active_f4 = tracker.update([{"bbox": [190.0, 100.0, 250.0, 260.0], "score": 0.9, "label": "person"}], timestamp=1.0)
        self.assertEqual(len(active_f4), 1)
        self.assertEqual(active_f4[0].track_id, tid, "Lost track must be recovered using motion prediction")
        self.assertEqual(active_f4[0].state, "active")

    def test_predict_bbox_unit_geometry(self) -> None:
        """Unit test for Track.predict_bbox calculation."""
        track = Track(
            track_id=1,
            bbox=[100.0, 100.0, 160.0, 200.0],  # w=60, h=100, cx=130, cy=150
            score=0.9,
            label="person",
            timestamp=0.0,
            state="active",
        )
        # Update at t=1.0 with cx=150, cy=170 (+20px x, +20px y in 1.0s)
        track.update([120.0, 120.0, 180.0, 220.0], score=0.9, timestamp=1.0)

        # Predict at t=1.5 (+0.5s -> +10px x, +10px y)
        pred = track.predict_bbox(timestamp=1.5)
        # expected cx=160, cy=180, w=60, h=100 -> [130, 130, 190, 230]
        self.assertAlmostEqual(pred[0], 130.0)
        self.assertAlmostEqual(pred[1], 130.0)
        self.assertAlmostEqual(pred[2], 190.0)
        self.assertAlmostEqual(pred[3], 230.0)

        # Predict with timestamp <= last_time returns current bbox
        pred_same = track.predict_bbox(timestamp=1.0)
        self.assertEqual(pred_same, track.bbox)

    def test_track_states_conform_to_allowed_set(self) -> None:
        """P1-12 / contracts.md: Track states must be in {tentative, active, lost, removed}."""
        allowed_states = {"tentative", "active", "lost", "removed"}
        track = Track(1, [0.0, 0.0, 10.0, 10.0], 0.9, "person", 0.0, state="tentative")
        self.assertIn(track.state, allowed_states)
        track.update([0.0, 0.0, 10.0, 10.0], 0.9, 1.0)
        self.assertIn(track.state, allowed_states)
        track.mark_lost()
        self.assertIn(track.state, allowed_states)
        track.mark_removed()
        self.assertIn(track.state, allowed_states)

    def test_activate_after_is_respected_beyond_two_hits(self) -> None:
        """ocr #2: Track.update must not promote tentative->active before ByteTracker.activate_after hits."""
        tracker = ByteTracker(high_threshold=0.5, low_threshold=0.1, match_threshold=0.2, activate_after=3)
        det = [{"bbox": [100.0, 100.0, 160.0, 260.0], "score": 0.9, "label": "person"}]
        self.assertEqual(len(tracker.update(det, timestamp=1.0)), 0)
        self.assertEqual(len(tracker.update(det, timestamp=1.1)), 0, "2nd hit must stay tentative at activate_after=3")
        self.assertEqual(tracker.get_all_tracks()[0].state, "tentative")
        self.assertEqual(len(tracker.update(det, timestamp=1.2)), 1)
        self.assertEqual(tracker.get_all_tracks()[0].state, "active")

    def test_incompatible_class_does_not_hijack_person_track(self) -> None:
        """Misclassified non-person boxes (e.g. 'bird') must not swallow overlapping 'person' detections, while coarse vehicle groups stay continuous."""
        tracker = ByteTracker(high_threshold=0.3, low_threshold=0.1, match_threshold=0.2, max_lost_time=2.0)
        box = [1100.0, 640.0, 1380.0, 815.0]

        # Active 'bird' track established at same location
        tracker.update([{"bbox": box, "score": 0.5, "label": "bird"}], timestamp=16.0)
        active_bird = tracker.update([{"bbox": box, "score": 0.5, "label": "bird"}], timestamp=16.1)
        self.assertEqual([t.label for t in active_bird], ["bird"])

        # Detector recovers 'person' label at identical bbox -> must start a distinct 'person' track, not stay 'bird'
        tracker.update([{"bbox": box, "score": 0.36, "label": "person"}], timestamp=18.1)
        active_person = tracker.update([{"bbox": box, "score": 0.42, "label": "person"}], timestamp=18.2)
        person_tracks = [t for t in active_person if t.label == "person"]
        self.assertEqual(len(person_tracks), 1)

        # Coarse motor-vehicle labels ('truck' <-> 'bus') continue to associate onto the same track
        v_box = [200.0, 200.0, 360.0, 320.0]
        tracker.update([{"bbox": v_box, "score": 0.8, "label": "truck"}], timestamp=20.0)
        v_active = tracker.update([{"bbox": v_box, "score": 0.8, "label": "bus"}], timestamp=20.1)
        motor_tracks = [t for t in v_active if t.label == "truck"]
        self.assertEqual(len(motor_tracks), 1)
