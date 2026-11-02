"""Tests for run_edge fail-fast startup and CLI entrypoint."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import run_edge


class TestRunEdgeStartup(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.stop_event = threading.Event()
        self.stop_event.set()  # Don't block during tests

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_config(self, payload: dict) -> Path:
        path = self.root / f"config-{os.urandom(4).hex()}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _run_main(self, args: list[str], env: dict[str, str] | None = None) -> tuple[int, list[dict], str, str]:
        base_env = {
            "SERVER_URL": "http://127.0.0.1:9",
            "DEVICE_TOKEN": "fixture-device-token",
        }
        if env is not None:
            base_env.update(env)

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        with patch.dict(os.environ, base_env, clear=False), \
             patch("sys.stdout", stdout_buf), \
             patch("sys.stderr", stderr_buf):
            code = run_edge.main(args, stop_event=self.stop_event)

        stdout_val = stdout_buf.getvalue()
        stderr_val = stderr_buf.getvalue()
        lines: list[dict] = []
        for line in stdout_val.strip().splitlines():
            line_str = line.strip()
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    lines.append(json.loads(line_str))
                except json.JSONDecodeError:
                    pass
        return code, lines, stdout_val, stderr_val

    def test_missing_roi_for_enabled_module_fails_fast(self) -> None:
        """1. Missing roi for enabled module -> exit 1, error.code == 'missing_required_field', error.field == 'roi', runner mock not called."""
        doc = {
            "modules": [
                {
                    "module": "person_down",
                    "config_version": "v1",
                    "factory": "person_down",
                    "required_fields": ["roi"],
                    "thresholds": [],
                    "cameras": {
                        "cam-01": {"version": 1, "enabled": True}  # missing roi
                    },
                }
            ]
        }
        cfg_path = self._write_config(doc)
        with patch("run_edge.LivePerceptionRunner") as mock_runner:
            code, lines, _, _ = self._run_main([
                "--module-config", str(cfg_path),
                "--camera-id", "cam-01",
                "--root", str(self.root / "edge"),
                "--source", "file",
                "--file", str(cfg_path),
            ])
            self.assertEqual(code, 1)
            mock_runner.assert_not_called()
            self.assertTrue(lines)
            err_line = lines[0]
            self.assertEqual(err_line.get("scope"), "startup")
            self.assertEqual(err_line.get("status"), "error")
            self.assertEqual(err_line.get("error", {}).get("code"), "missing_required_field")
            self.assertEqual(err_line.get("error", {}).get("field"), "roi")

    def test_secret_field_in_camera_config_never_leaked(self) -> None:
        """2. Camera config containing api_key -> exit 1, secret string never appears in stdout/stderr."""
        secret = "sk-live-should-not-leak"
        doc = {
            "modules": [
                {
                    "module": "person_down",
                    "config_version": "v1",
                    "factory": "person_down",
                    "required_fields": ["roi"],
                    "thresholds": [],
                    "cameras": {
                        "cam-01": {
                            "version": 1,
                            "enabled": True,
                            "roi": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]],
                            "api_key": secret,
                        }
                    },
                }
            ]
        }
        cfg_path = self._write_config(doc)
        code, lines, stdout, stderr = self._run_main([
            "--module-config", str(cfg_path),
            "--camera-id", "cam-01",
            "--root", str(self.root / "edge"),
            "--source", "file",
            "--file", str(cfg_path),
        ])
        self.assertEqual(code, 1)
        self.assertNotIn(secret, stdout)
        self.assertNotIn(secret, stderr)
        self.assertTrue(lines)
        self.assertEqual(lines[0].get("error", {}).get("code"), "secret_field_not_allowed")

    def test_untunable_threshold_fails_fast_in_real_runner(self) -> None:
        """3. Module person_down with untunable min_score -> real runner with empty temp file -> exit 1, unknown_threshold."""
        empty_file = self.root / "empty.mkv"
        empty_file.touch()
        doc = {
            "modules": [
                {
                    "module": "person_down",
                    "config_version": "v1",
                    "factory": "person_down",
                    "required_fields": ["roi"],
                    "thresholds": ["min_score"],
                    "cameras": {
                        "cam-01": {
                            "version": 1,
                            "enabled": True,
                            "roi": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]],
                            "thresholds": {"min_score": 0.5},
                        }
                    },
                }
            ]
        }
        cfg_path = self._write_config(doc)
        code, lines, _, _ = self._run_main([
            "--module-config", str(cfg_path),
            "--camera-id", "cam-01",
            "--root", str(self.root / "edge"),
            "--source", "file",
            "--file", str(empty_file),
        ])
        self.assertEqual(code, 1)
        self.assertTrue(lines)
        err = lines[0].get("error", {})
        self.assertEqual(err.get("code"), "unknown_threshold")
        self.assertEqual(err.get("field"), "thresholds.min_score")

    def test_all_modules_disabled_runs_recorder_only(self) -> None:
        """4. All modules disabled with reason -> exit 0, analytics_enabled=false, mock recorder used as CM, runner not called."""
        doc = {
            "modules": [
                {
                    "module": "person_down",
                    "config_version": "v1",
                    "factory": "person_down",
                    "required_fields": ["roi"],
                    "thresholds": [],
                    "cameras": {
                        "cam-01": {"version": 1, "enabled": False, "disabled_reason": "operator manual pause"}
                    },
                }
            ]
        }
        cfg_path = self._write_config(doc)
        dummy_file = self.root / "dummy.mkv"
        dummy_file.touch()

        mock_recorder_inst = MagicMock()
        mock_recorder_inst.__enter__.return_value = mock_recorder_inst
        mock_recorder_inst.__exit__.return_value = False

        with patch("run_edge.RtspRingRecorder", return_value=mock_recorder_inst) as mock_recorder_cls, \
             patch("run_edge.LivePerceptionRunner") as mock_runner:
            code, lines, _, _ = self._run_main([
                "--module-config", str(cfg_path),
                "--camera-id", "cam-01",
                "--root", str(self.root / "edge"),
                "--source", "file",
                "--file", str(dummy_file),
            ])
            self.assertEqual(code, 0)
            mock_runner.assert_not_called()
            mock_recorder_cls.assert_called_once()
            mock_recorder_inst.__enter__.assert_called_once()
            mock_recorder_inst.__exit__.assert_called_once()
            self.assertTrue(lines)
            ok_line = lines[0]
            self.assertEqual(ok_line.get("scope"), "startup")
            self.assertEqual(ok_line.get("status"), "ok")
            self.assertFalse(ok_line.get("analytics_enabled"))
            self.assertIn("operator manual pause", ok_line.get("disabled_reason", ""))

    def test_missing_server_url_fails_fast(self) -> None:
        """5. Missing SERVER_URL -> exit 1, reason == 'missing_environment', field == 'SERVER_URL'."""
        cfg_path = self._write_config({"modules": []})
        with patch.dict(os.environ, {}, clear=True):
            code, lines, _, _ = self._run_main(
                ["--module-config", str(cfg_path)],
                env={"SERVER_URL": "", "DEVICE_TOKEN": "token"},
            )
            self.assertEqual(code, 1)
            self.assertTrue(lines)
            self.assertEqual(lines[0].get("reason"), "missing_environment")
            self.assertEqual(lines[0].get("field"), "SERVER_URL")


if __name__ == "__main__":
    unittest.main()
