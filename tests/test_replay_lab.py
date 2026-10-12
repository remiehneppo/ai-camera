import json
import os
import shutil
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires ffmpeg tools")
class ReplayLabTests(unittest.TestCase):
    def test_cli_outputs_json_and_fails_cleanly_for_bad_media(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "testsrc=size=64x64:rate=10", "-t", "0.4", "-c:v", "mpeg4", "-g", "2", str(source),
            ], check=True, capture_output=True)
            command = [sys.executable, "-m", "apps.edge.replay_lab", str(source),
                       "--sample-fps", "5", "--slow-callback-seconds", "0.01"]
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(command, capture_output=True, text=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["trace_parity"])
            self.assertEqual(report["runs"]["fast"]["delivered_count"], 2)
            source.write_text("not video")
            failed = subprocess.run(command, capture_output=True, text=True, env=environment)
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(failed.stdout, "")
            self.assertIn("replay lab failed", failed.stderr)
            self.assertNotIn("Traceback", failed.stderr)

    def test_single_frame_media_reports_clear_range_error(self):
        from apps.edge.replay_lab import run_lab

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "single.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "testsrc=size=64x64:rate=10", "-frames:v", "1", "-c:v", "mpeg4", str(source),
            ], check=True, capture_output=True)
            with self.assertRaisesRegex(ValueError, "at least two distinct"):
                run_lab(source)

    def test_invalid_sampling_delay_and_missing_source_fail_before_processing(self):
        from apps.edge.replay_lab import run_lab

        for fps, delay in ((0, 0), (float("nan"), 0), (float("inf"), 0),
                           (2, -1), (2, float("nan")), (2, float("inf"))):
            with self.subTest(fps=fps, delay=delay):
                with self.assertRaisesRegex(ValueError, "finite"):
                    run_lab("missing.mp4", sample_fps=fps, slow_callback_seconds=delay)
        with self.assertRaises(FileNotFoundError):
            run_lab("missing.mp4")

    def test_report_compares_real_replay_traces_and_queries_raw_during_slow_callbacks(self):
        from apps.edge.replay_lab import run_lab

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "testsrc=size=64x64:rate=10", "-t", "0.6", "-c:v", "mpeg4", "-g", "2",
                "-output_ts_offset", "3", str(source),
            ], check=True, capture_output=True)
            report = run_lab(source, sample_fps=5, slow_callback_seconds=0.25)

        self.assertEqual(report["scope"], "software_semantic_replay")
        self.assertTrue(report["trace_parity"])
        self.assertEqual(report["raw"]["coverage"]["completeness"], "complete")
        self.assertEqual(report["raw"]["coverage"]["actual_start"], 3)
        self.assertAlmostEqual(report["raw"]["coverage"]["actual_end"], 3.5)
        for run in report["runs"].values():
            self.assertEqual(run["delivered_count"], 3)
            self.assertEqual([row["event_time"] for row in run["trace"]], [3, 3.2, 3.4])
            self.assertEqual(run["raw_query_count"], 3)
            self.assertTrue(run["raw_coverage_unchanged"])
            self.assertAlmostEqual(run["last_consumer_event_time"], 3.4)
        self.assertGreaterEqual(report["runs"]["slow_realtime"]["elapsed_seconds"], 0.75)
        self.assertGreaterEqual(report["runs"]["slow_realtime"]["max_callback_completion_lag_seconds"], 0.25)
        self.assertIn("not analytics/domain parity", report["limitations"])
        self.assertIn("not realtime queue/drop stress", report["limitations"])


if __name__ == "__main__":
    unittest.main()
