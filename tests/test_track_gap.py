"""Ticket #23: gaps, discontinuities and clock jumps must not create certainty or motion."""

from __future__ import annotations

import unittest

from apps.edge.incident import IncidentEngine
from apps.edge.tracker import ByteTracker, Track

STAND = [100.0, 100.0, 160.0, 260.0]
LIE = [100.0, 220.0, 260.0, 280.0]


def det(bbox, score=0.9):
    return {"bbox": list(bbox), "score": score, "label": "person"}


class TestTrackerGap(unittest.TestCase):
    def test_reacquired_lost_track_has_no_cross_gap_velocity(self) -> None:
        tr = ByteTracker(max_lost_time=10.0, activate_after=1)
        for t in (0.0, 0.5, 1.0):
            tr.update([det(STAND)], t)
        tr.update([], 2.0)  # lost
        moved = [100.0, 150.0, 160.0, 310.0]  # 50px lower, overlapping so it re-associates
        active = tr.update([det(moved)], 6.0)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].track_id, 1)
        self.assertEqual(active[0].vertical_velocity(1.5), 0.0)
        self.assertEqual(len(active[0].history), 1)

    def test_tentative_hits_do_not_span_gap(self) -> None:
        tr = ByteTracker(activate_after=2)
        tr.update([det(STAND)], 0.0)
        self.assertEqual(tr.update([det(STAND)], 9.0), [])

    def test_backward_clock_jump_clears_history(self) -> None:
        tr = ByteTracker(activate_after=1)
        for t in (10.0, 10.5, 11.0):
            tr.update([det(STAND)], t)
        active = tr.update([det([100.0, 130.0, 160.0, 290.0])], 2.0)
        self.assertEqual(active[0].vertical_velocity(1.5), 0.0)
        self.assertEqual(len(active[0].history), 1)

    def test_normal_cadence_keeps_history(self) -> None:
        tr = ByteTracker(activate_after=1)
        for t in (0.0, 0.33, 0.66):
            active = tr.update([det(STAND)], t)
        self.assertEqual(len(active[0].history), 3)


class TestIncidentGap(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = IncidentEngine()

    def _run(self, track, times, bbox):
        out = []
        for t in times:
            track.update(bbox, 0.9, t)
            out += self.engine.process_tracks([track], t)
        return out

    def test_forward_clock_jump_does_not_complete_persistent_lying(self) -> None:
        track = Track(1, LIE, 0.9, "person", 0.0)
        self.assertEqual(self.engine.process_tracks([track], 0.0), [])
        self.assertEqual(self._run(track, [0.5, 1.0], LIE), [])
        self.assertEqual(self._run(track, [10.0], LIE), [])
        self.assertEqual(self._run(track, [10.5, 11.0, 11.5, 12.0, 12.5], LIE), [])
        out = self._run(track, [13.0, 13.5], LIE)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0]["anchor_time"], 10.0, delta=0.05)

    def test_backward_clock_jump_resets_state(self) -> None:
        track = Track(1, LIE, 0.9, "person", 5.0)
        self.engine.process_tracks([track], 5.0)
        self.assertEqual(self._run(track, [5.5, 6.0], LIE), [])
        self.assertEqual(self._run(track, [1.0, 1.5, 2.0], LIE), [])

    def test_fall_candidate_not_completed_across_gap(self) -> None:
        track = Track(1, STAND, 0.9, "person", 0.0)
        self.engine.process_tracks([track], 0.0)
        self._run(track, [0.1], STAND)
        self._run(track, [0.2], LIE)  # onset candidate
        self.assertEqual(self._run(track, [10.0], LIE), [])

    def test_missing_track_frame_resets_dwell(self) -> None:
        track = Track(1, LIE, 0.9, "person", 0.0)
        self.engine.process_tracks([track], 0.0)
        self.assertEqual(self._run(track, [0.5, 1.0, 1.5, 2.0, 2.5], LIE), [])
        self.assertEqual(self.engine.process_tracks([], 3.0), [])  # missing, not negative
        self.assertEqual(self._run(track, [3.5, 4.0, 4.5, 5.0], LIE), [])

    def test_normal_cadence_still_triggers(self) -> None:
        track = Track(1, LIE, 0.9, "person", 0.0)
        self.engine.process_tracks([track], 0.0)
        out = self._run(track, [i * 0.33 for i in range(1, 15)], LIE)
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
