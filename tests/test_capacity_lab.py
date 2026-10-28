"""Ticket #31: exploratory capacity profiling harness (never a capacity sign-off)."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from apps.edge.capacity_lab import gap_totals, percentiles, run_lab
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder


def frame_factory(i):
    rgb = np.random.RandomState(i % 7).randint(40, 210, (16, 16, 3), dtype=np.uint8)
    return i + 1, float(i + 1), rgb


class FallEngine:
    """Always emits one incident, so the outbox path is actually exercised."""

    def process_tracks(self, tracks, timestamp):
        return [{"taxonomy": "person_fall"}]

    def reset(self): pass
    def observation_gap(self): pass


def make_pipeline(root, **kw):
    return PerceptionPipeline(recorder=FileRecorder(Path(root) / "ring"),
                              outbox=EventOutbox(Path(root) / "events.sqlite3"), **kw)


class TestPercentiles(unittest.TestCase):
    def test_empty_is_zeroed(self):
        self.assertEqual(percentiles([]),
                         {"mean": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0})

    def test_tail_percentiles_are_ordered(self):
        result = percentiles([float(v) for v in range(1, 101)])
        self.assertLessEqual(result["p50"], result["p90"])
        self.assertLessEqual(result["p90"], result["p95"])
        self.assertLessEqual(result["p95"], result["p99"])
        self.assertLessEqual(result["p99"], result["max"])
        self.assertAlmostEqual(result["p99"], 99.01, places=2)


class TestGapTotals(unittest.TestCase):
    def test_counts_and_sums_gap_seconds(self):
        self.assertEqual(gap_totals([]), {"count": 0, "seconds": 0.0})
        self.assertEqual(gap_totals([[1.0, 2.5], [10.0, 10.5]]), {"count": 2, "seconds": 2.0})


class TestFsyncCounter(unittest.TestCase):
    def test_counts_real_fsync_calls(self):
        import os
        from apps.edge.capacity_lab import _FsyncCounter
        with tempfile.TemporaryFile() as handle:
            with _FsyncCounter() as counter:
                os.fsync(handle.fileno())
                os.fsync(handle.fileno())
            report = counter.report()
        self.assertEqual(report["calls"], 2)
        self.assertGreaterEqual(report["seconds"], 0.0)


class TestRunLab(unittest.TestCase):
    def test_report_is_labelled_exploratory_and_never_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            report = run_lab(make_pipeline(root), frames=6, frame_factory=frame_factory)
        self.assertEqual(report["kind"], "exploratory_capacity_profile")
        self.assertIs(report["accepted_capacity"], False)
        self.assertIn("not a capacity sign-off", report["disclaimer"])
        self.assertTrue(report["missing_gates"])

    def test_per_camera_reports_latency_queue_fsync_and_wal(self):
        with tempfile.TemporaryDirectory() as root:
            report = run_lab(make_pipeline(root), frames=8, frame_factory=frame_factory,
                             camera_id="cam-01")
        camera = report["per_camera"]["cam-01"]
        self.assertEqual(camera["frames"], 8)
        self.assertEqual(set(camera["latency_ms"]), {"mean", "p50", "p90", "p95", "p99", "max"})
        self.assertGreater(camera["latency_ms"]["max"], 0.0)
        self.assertIn("max_pending_events", camera["queue"])
        self.assertEqual(camera["wal"]["journal_mode"], "wal")
        self.assertIsInstance(camera["fsync"]["calls"], int)

    def test_outbox_axis_can_be_non_zero_when_events_are_emitted(self):
        with tempfile.TemporaryDirectory() as root:
            report = run_lab(make_pipeline(root, incident_engine=FallEngine()), frames=5,
                             frame_factory=frame_factory, camera_id="cam-01")
        self.assertGreaterEqual(report["per_camera"]["cam-01"]["queue"]["max_pending_events"], 1)

    def test_drops_are_reported_as_unmeasured_not_zero(self):
        with tempfile.TemporaryDirectory() as root:
            report = run_lab(make_pipeline(root), frames=4, frame_factory=frame_factory,
                             camera_id="cam-01")
        queue = report["per_camera"]["cam-01"]["queue"]
        self.assertIsNone(queue["drops"])
        self.assertTrue(queue["drops_reason"])

    def test_unmeasured_axes_are_labelled_not_faked(self):
        with tempfile.TemporaryDirectory() as root:
            report = run_lab(make_pipeline(root), frames=4, frame_factory=frame_factory,
                             camera_id="cam-01")
        self.assertEqual(report["pose"]["status"], "unmeasured")
        self.assertIn("reason", report["pose"])
        storage = report["per_camera"]["cam-01"]["storage"]
        self.assertEqual(storage["status"], "measured")
        self.assertIn("headroom_bytes", storage)

    def test_upload_hook_drains_concurrently_and_is_counted(self):
        calls = []
        with tempfile.TemporaryDirectory() as root:
            report = run_lab(make_pipeline(root), frames=6, frame_factory=frame_factory,
                             upload_hook=lambda: calls.append(1))
        self.assertGreaterEqual(len(calls), 1)
        self.assertIs(report["upload"]["exercised"], True)
        self.assertEqual(report["upload"]["drains"], len(calls))

    def test_failed_upload_drains_are_counted_not_swallowed(self):
        def boom():
            raise RuntimeError("upload down")

        with tempfile.TemporaryDirectory() as root:
            report = run_lab(make_pipeline(root), frames=4, frame_factory=frame_factory,
                             upload_hook=boom)
        self.assertGreaterEqual(report["upload"]["failed_drains"], 1)
        self.assertEqual(report["upload"]["last_error"], "RuntimeError")

    def test_skipped_frames_are_counted(self):
        def stale_factory(i):
            return (5 if i >= 3 else i + 1), float(i + 1), np.zeros((8, 8, 3), dtype=np.uint8)

        with tempfile.TemporaryDirectory() as root:
            report = run_lab(make_pipeline(root), frames=5, frame_factory=stale_factory,
                             camera_id="cam-01")
        self.assertGreater(report["per_camera"]["cam-01"]["skipped_frames"], 0)


if __name__ == "__main__":
    unittest.main()
