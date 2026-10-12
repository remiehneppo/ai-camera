import json
import subprocess
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest import mock

from apps.edge.rtsp import (
    DEFAULT_ENV_FILE,
    RtspProbeError,
    load_rtsp_config,
    probe_rtsp_stream,
    redact_rtsp_url,
    sanitize_probe_output,
)

SECRET_URL = "rtsp://operator:S3cret%40Pass@camera.example:554/h264/ch1/main/av_stream"
ENCODED_PASSWORD = "S3cret%40Pass"
DECODED_PASSWORD = "S3cret@Pass"
USERNAME = "operator"
REDACTED_URL = "rtsp://camera.example:554/h264/ch1/main/av_stream"


def assert_no_credentials(test: unittest.TestCase, text: str) -> None:
    for secret in (SECRET_URL, ENCODED_PASSWORD, DECODED_PASSWORD, USERNAME, "S3cret"):
        test.assertNotIn(secret, text)


def assert_error_is_secret_free(test: unittest.TestCase, error: BaseException) -> None:
    """No message a traceback printer renders may carry credentials."""
    test.assertIsNone(error.__cause__)
    if error.__context__ is not None:
        test.assertTrue(error.__suppress_context__, "raising must use `from None` to hide the raw error")
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert_no_credentials(test, rendered)
    assert_no_credentials(test, f"{error}{error!r}")


def write_env_file(directory: str, content: str) -> Path:
    env_file = Path(directory) / ".env.local"
    env_file.write_text(content)
    return env_file


class RtspConfigTests(unittest.TestCase):
    def test_loads_credentialed_stream_url_from_env_file_without_echoing_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = write_env_file(tmp, f"# local camera lab\n\nCAMERA_RTSP_URL={SECRET_URL}\n")
            config = load_rtsp_config(environ={}, env_file=env_file)

        self.assertEqual(config.stream_url, SECRET_URL)
        self.assertEqual(config.host, "camera.example")
        self.assertEqual(config.port, 554)
        self.assertTrue(config.has_credentials)
        self.assertEqual(config.source, "env_file")
        self.assertNotIn(ENCODED_PASSWORD, repr(config))
        self.assertNotIn(ENCODED_PASSWORD, config.redacted_url)
        self.assertEqual(config.redacted_url, "rtsp://camera.example:554/h264/ch1/main/av_stream")

    def test_environment_value_wins_over_env_file(self) -> None:
        rotated = "rtsp://operator:rotated-secret@camera.local:8554/live"
        with tempfile.TemporaryDirectory() as tmp:
            env_file = write_env_file(tmp, f"CAMERA_RTSP_URL={SECRET_URL}\n")
            config = load_rtsp_config(environ={"CAMERA_RTSP_URL": rotated}, env_file=env_file)

        self.assertEqual(config.source, "environment")
        self.assertEqual(config.stream_url, rotated)
        self.assertEqual((config.host, config.port), ("camera.local", 8554))

    def test_missing_env_file_and_environment_names_field_without_echoing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.env"
            with self.assertRaisesRegex(ValueError, "CAMERA_RTSP_URL") as error:
                load_rtsp_config(environ={"OTHER": ENCODED_PASSWORD}, env_file=missing)

        self.assertNotIn(ENCODED_PASSWORD, str(error.exception))

    def test_placeholder_example_value_is_rejected_without_echoing_value(self) -> None:
        placeholder = "rtsp://<username>:<url-encoded-password>@<camera-host>:554/h264/ch1/main/av_stream"
        with tempfile.TemporaryDirectory() as tmp:
            env_file = write_env_file(tmp, f"CAMERA_RTSP_URL={placeholder}\n")
            with self.assertRaisesRegex(ValueError, "CAMERA_RTSP_URL") as error:
                load_rtsp_config(environ={}, env_file=env_file)

        self.assertNotIn(placeholder, str(error.exception))

    def test_non_rtsp_scheme_and_empty_value_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for value in (
                "http://operator:rotated@camera.example/h264",
                "rtsp://operator:rotated@camera.example/live#fragment",
                "   ",
            ):
                env_file = write_env_file(tmp, f"CAMERA_RTSP_URL={value}\n")
                with self.assertRaisesRegex(ValueError, "CAMERA_RTSP_URL") as error:
                    load_rtsp_config(environ={}, env_file=env_file)
                self.assertNotIn("rotated", str(error.exception))

    def test_quoted_credential_free_url_defaults_port_and_reports_no_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = write_env_file(tmp, 'CAMERA_RTSP_URL="rtsp://camera.local/live"\n')
            config = load_rtsp_config(environ={}, env_file=env_file)

        self.assertEqual((config.host, config.port), ("camera.local", 554))
        self.assertFalse(config.has_credentials)
        self.assertEqual(config.redacted_url, "rtsp://camera.local/live")

    def test_default_env_file_is_the_ignored_repo_root_env_local(self) -> None:
        self.assertEqual(DEFAULT_ENV_FILE, Path(__file__).resolve().parents[1] / ".env.local")


def completed_probe(streams: list[dict], returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ffprobe"], returncode=returncode, stdout=json.dumps({"streams": streams}), stderr=stderr
    )


VIDEO_STREAM = {"codec_name": "h264", "width": 1920, "height": 1080, "avg_frame_rate": "15/1"}


class RtspProbeTests(unittest.TestCase):
    def test_probe_reports_codec_resolution_and_fps_with_a_bounded_timeout(self) -> None:
        with mock.patch("apps.edge.rtsp.subprocess.run", return_value=completed_probe([VIDEO_STREAM])) as run:
            result = probe_rtsp_stream(SECRET_URL, timeout_seconds=5.0)

        command = run.call_args.args[0]
        self.assertEqual(result.codec, "h264")
        self.assertEqual(result.resolution, "1920x1080")
        self.assertEqual((result.width, result.height), (1920, 1080))
        self.assertEqual(result.fps, 15.0)
        self.assertEqual(command[0], "ffprobe")
        self.assertEqual(command[command.index("-rtsp_transport") + 1], "tcp")
        self.assertEqual(command[command.index("-timeout") + 1], "5000000")
        self.assertEqual(command[-1], SECRET_URL)
        self.assertEqual(run.call_args.kwargs["timeout"], 5.0)
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertNotIn(ENCODED_PASSWORD, repr(result))

    def test_fractional_frame_rate_and_r_frame_rate_fallback_are_parsed(self) -> None:
        fractional = {"codec_name": "hevc", "width": 1280, "height": 720, "avg_frame_rate": "30000/1001"}
        fallback = {"codec_name": "h264", "width": 640, "height": 480, "avg_frame_rate": "0/0", "r_frame_rate": "25/1"}
        with mock.patch("apps.edge.rtsp.subprocess.run", return_value=completed_probe([fractional])):
            self.assertAlmostEqual(probe_rtsp_stream(SECRET_URL, timeout_seconds=2.0).fps, 29.97, places=3)
        with mock.patch("apps.edge.rtsp.subprocess.run", return_value=completed_probe([fallback])):
            self.assertEqual(probe_rtsp_stream(SECRET_URL, timeout_seconds=2.0).fps, 25.0)


class RtspProbeFailureTests(unittest.TestCase):
    def test_non_zero_exit_reports_sanitized_stderr_without_credentials(self) -> None:
        stderr = f"[rtsp @ 0x1] Could not open input {SECRET_URL}\n401 Unauthorized for {DECODED_PASSWORD} ({USERNAME})"
        failure = subprocess.CalledProcessError(returncode=1, cmd=["ffprobe", SECRET_URL], stderr=stderr)
        with mock.patch("apps.edge.rtsp.subprocess.run", side_effect=failure):
            with self.assertRaises(RtspProbeError) as raised:
                probe_rtsp_stream(SECRET_URL, timeout_seconds=4.0)

        assert_error_is_secret_free(self, raised.exception)
        self.assertIn(REDACTED_URL, str(raised.exception))
        self.assertIn("exited with 1", str(raised.exception))
        self.assertIn("Could not open input", str(raised.exception))

    def test_timeout_is_reported_without_echoing_the_command(self) -> None:
        with mock.patch("apps.edge.rtsp.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffprobe", SECRET_URL], timeout=3.0)):
            with self.assertRaises(RtspProbeError) as raised:
                probe_rtsp_stream(SECRET_URL, timeout_seconds=3.0)

        assert_error_is_secret_free(self, raised.exception)
        self.assertIn("timed out after 3s", str(raised.exception))

    def test_unusable_probe_output_is_reported_without_echoing_the_url(self) -> None:
        for stdout in ("not-json", json.dumps({"streams": []}), json.dumps({"streams": [{"codec_name": "h264"}]})):
            completed = subprocess.CompletedProcess(args=["ffprobe"], returncode=0, stdout=stdout, stderr="")
            with mock.patch("apps.edge.rtsp.subprocess.run", return_value=completed):
                with self.assertRaises(RtspProbeError) as raised:
                    probe_rtsp_stream(SECRET_URL, timeout_seconds=1.0)
            assert_error_is_secret_free(self, raised.exception)
            self.assertIn("no usable video stream metadata", str(raised.exception))

    def test_missing_ffprobe_binary_is_reported_without_echoing_the_url(self) -> None:
        with mock.patch("apps.edge.rtsp.subprocess.run", side_effect=FileNotFoundError(2, "No such file or directory")):
            with self.assertRaises(RtspProbeError) as raised:
                probe_rtsp_stream(SECRET_URL, timeout_seconds=1.0)

        assert_error_is_secret_free(self, raised.exception)
        self.assertIn("ffprobe is unavailable", str(raised.exception))

    def test_timeout_must_be_finite_positive_and_bounded(self) -> None:
        for timeout in (0, -1, 61, float("inf"), float("nan"), None):
            with mock.patch("apps.edge.rtsp.subprocess.run") as run:
                with self.assertRaises(ValueError) as raised:
                    probe_rtsp_stream(SECRET_URL, timeout_seconds=timeout)  # type: ignore[arg-type]
                run.assert_not_called()
            assert_no_credentials(self, str(raised.exception))

    def test_probe_rejects_a_credentialed_non_rtsp_url_without_echoing_it(self) -> None:
        with self.assertRaises(ValueError) as raised:
            probe_rtsp_stream("http://operator:S3cret%40Pass@camera.example/h264")

        assert_error_is_secret_free(self, raised.exception)
        self.assertIn("CAMERA_RTSP_URL", str(raised.exception))

    def test_redaction_and_sanitization_never_echo_unparseable_values(self) -> None:
        self.assertEqual(redact_rtsp_url("rtsp://operator:S3cret%40Pass@"), "<redacted rtsp url>")
        self.assertEqual(redact_rtsp_url("not a url at all"), "<redacted rtsp url>")
        self.assertNotIn("***", sanitize_probe_output("", SECRET_URL))
        long_output = f"{'x' * 400} {SECRET_URL} {DECODED_PASSWORD}"
        sanitized = sanitize_probe_output(long_output, SECRET_URL)
        assert_no_credentials(self, sanitized)
        self.assertLessEqual(len(sanitized), 300)


if __name__ == "__main__":
    unittest.main()
