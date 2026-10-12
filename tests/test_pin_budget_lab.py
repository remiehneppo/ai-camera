import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires ffmpeg tools")
class PinBudgetLabTests(unittest.TestCase):
    def test_report_restarts_pending_intent_and_preserves_anchor(self):
        from apps.edge.pin_budget_lab import run_lab

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "testsrc=size=64x64:rate=10", "-t", "40", "-c:v", "mpeg4", "-g", "10", str(source),
            ], check=True, capture_output=True)
            report = run_lab(source, ring_seconds=40, anchor_time=12,
                             verification_seconds=15, handoff_seconds=5,
                             recovery_seconds=5, margin_seconds=1)
            self.assertEqual(report["scope"], "software_pin_budget_scenario")
            self.assertEqual(report["theoretical"]["required_ring_seconds"], 36)
            self.assertEqual(report["theoretical"]["slack_seconds"], 4)
            self.assertEqual(report["schedule"]["pin_time"], 37)
            self.assertEqual(report["pending_before_restart"], "requested")
            self.assertEqual(report["result"]["state"], "fulfilled")
            self.assertEqual(report["result"]["receipt"]["completeness"], "complete")
            self.assertEqual((report["result"]["receipt"]["requested_start"],
                              report["result"]["receipt"]["requested_end"]), (2, 32))
            self.assertEqual(len(report["source"]["sha256"]), 64)
            self.assertEqual(len(report["config_sha256"]), 64)
            self.assertTrue(report["versions"]["ffprobe"])
            self.assertTrue(report["versions"]["git_revision"])
            self.assertTrue(report["limitations"])

    def test_expired_preroll_and_entire_interval_remain_partial_or_missing(self):
        from apps.edge.pin_budget_lab import run_lab

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "testsrc=size=64x64:rate=10", "-t", "40", "-c:v", "mpeg4", "-g", "10", str(source),
            ], check=True, capture_output=True)
            partial = run_lab(source, ring_seconds=8, anchor_time=12,
                              verification_seconds=15, handoff_seconds=5,
                              recovery_seconds=5, margin_seconds=1)
            self.assertEqual(partial["result"]["state"], "partial")
            self.assertEqual(partial["result"]["receipt"]["reason"], "missing_preroll")
            missing = run_lab(source, ring_seconds=8, anchor_time=0,
                              verification_seconds=15, handoff_seconds=10,
                              recovery_seconds=12, margin_seconds=1)
            self.assertEqual(missing["retained_before_pin"]["completeness"], "missing")
            self.assertEqual(missing["result"]["state"], "failed")
            self.assertEqual(missing["result"]["receipt"]["completeness"], "unknown")
            self.assertIsNone(missing["result"]["receipt"]["artifact"])

    def test_invalid_scenario_parameters_fail_before_source_access(self):
        from apps.edge.pin_budget_lab import run_lab

        valid = dict(ring_seconds=40, anchor_time=12, verification_seconds=15,
                     handoff_seconds=5, recovery_seconds=5, margin_seconds=1)
        for key in valid:
            for invalid in (float("nan"), float("inf"), -1, True):
                with self.subTest(key=key, invalid=invalid):
                    with self.assertRaises(ValueError):
                        run_lab("not-present.mp4", **{**valid, key: invalid})
        with self.assertRaises(ValueError):
            run_lab("not-present.mp4", **{**valid, "ring_seconds": 0})

    def test_cli_rejects_invalid_scenario_without_traceback(self):
        import sys

        result = subprocess.run([
            sys.executable, "-m", "apps.edge.pin_budget_lab", "not-present.mp4",
            "--ring-seconds", "40", "--anchor-time", "12", "--verification-seconds", "15",
            "--handoff-seconds", "5", "--recovery-seconds", "5", "--margin-seconds", "nan",
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("margin_seconds must be finite", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
