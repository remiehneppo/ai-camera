"""Concurrent probe drains and timeout cleanup without a physical camera."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from tools.rtsp_session_probe import main


class RtspSessionProbeTests(unittest.TestCase):
    def test_sessions_drain_concurrently_and_redact_output(self):
        barrier = threading.Barrier(2)
        url = "rtsp://user:secret@camera.test/live"
        config = SimpleNamespace(stream_url=url, redacted_url="rtsp://camera.test/live")
        info = SimpleNamespace(codec="h264", width=1920, height=1080, fps=15.0)
        processes = [MagicMock() for _ in range(3)]
        for process in processes:
            process.__enter__.return_value = process
            process.returncode = 0
        processes[0].communicate.return_value = ("packet\n" * 300, "")

        def drain(timeout):
            barrier.wait(timeout=2)
            return "packet\n" * 300, url

        for process in processes[1:]:
            process.communicate.side_effect = drain
        with tempfile.TemporaryDirectory() as tmp, \
                patch("tools.rtsp_session_probe.load_rtsp_config", return_value=config), \
                patch("tools.rtsp_session_probe.probe_rtsp_stream", return_value=info), \
                patch("tools.rtsp_session_probe.subprocess.Popen", side_effect=processes):
            output = Path(tmp) / "probe.json"
            self.assertEqual(main(["--output", str(output), "--max-sessions", "2"]), 0)
            report = json.loads(output.read_text())
            self.assertEqual([level["sessions"] for level in report["levels"]], [1, 2])
            self.assertTrue(all(row["ok"] for level in report["levels"] for row in level["results"]))
            self.assertNotIn("secret", output.read_text())

    def test_timeout_kills_and_drains_process(self):
        config = SimpleNamespace(stream_url="rtsp://camera.test/live", redacted_url="rtsp://camera.test/live")
        info = SimpleNamespace(codec="h264", width=1920, height=1080, fps=15.0)
        process = MagicMock()
        process.__enter__.return_value = process
        process.communicate.side_effect = [subprocess.TimeoutExpired("ffmpeg", 35), ("packet\n", "timed out")]
        with tempfile.TemporaryDirectory() as tmp, \
                patch("tools.rtsp_session_probe.load_rtsp_config", return_value=config), \
                patch("tools.rtsp_session_probe.probe_rtsp_stream", return_value=info), \
                patch("tools.rtsp_session_probe.subprocess.Popen", return_value=process):
            output = Path(tmp) / "probe.json"
            self.assertEqual(main(["--output", str(output), "--max-sessions", "1"]), 0)
            row = json.loads(output.read_text())["levels"][0]["results"][0]
            self.assertFalse(row["ok"])
            self.assertIsNone(row["exit_code"])
            process.kill.assert_called_once()
            self.assertEqual(process.communicate.call_count, 2)
