import contextlib
import io
import importlib.util
import json
import os
import signal
import time
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ORT_AVAILABLE = all(importlib.util.find_spec(name) for name in ('numpy', 'cv2', 'onnxruntime')) and Path('data/oracle/yolox_tiny.onnx').is_file()
FFMPEG_AVAILABLE = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


class EdgeDoctorTests(unittest.TestCase):
    def test_realtime_cli_configuration_rejected_before_execution_without_secret_leaks(self):
        from apps.edge.doctor import main
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            source.touch()
            config_path = Path(directory) / 'config.json'
            config_path.write_text(json.dumps(dict(source=str(source), output_dir=directory,
                analytics_enabled=False, disabled_reason='secret-test-value', mode='realtime')))
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                code = main(['--config', str(config_path), '--start'])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(captured.getvalue())['reason'], 'invalid edge configuration')
            self.assertNotIn('secret-test-value', captured.getvalue())

    @unittest.skipUnless(ORT_AVAILABLE and FFMPEG_AVAILABLE, 'requires real pinned ORT artifact and FFmpeg')
    def test_start_failure_is_nonzero_only_after_recorder_completion(self):
        from apps.edge.doctor import main
        from apps.edge.runtime import EdgeRuntime
        real_start = EdgeRuntime.start
        runtimes = []
        def kill_real_analytics(runtime):
            runtimes.append(runtime)
            real_start(runtime)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                status = runtime.status()
                if status['analytics']['state'] == 'running':
                    os.kill(status['analytics']['pid'], signal.SIGKILL)
                    return runtime
                if status['analytics']['state'] == 'failed':
                    self.fail('real analytics failed before test-only termination')
                time.sleep(.01)
            self.fail('real analytics never reached running')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=32x24:r=4',
                            '-t', '3', '-c:v', 'ffv1', str(source)], check=True, capture_output=True)
            config_path = Path(directory) / 'config.json'
            output = Path(directory) / 'raw'
            config_path.write_text(json.dumps(dict(source=str(source), output_dir=str(output), mode='fast', sample_fps=4,
                manifest_path='models/yolox-tiny/manifest.json', model_path='data/oracle/yolox_tiny.onnx')))
            captured = io.StringIO()
            try:
                # Explicit test-only process death injection; execution otherwise uses the real runtime.
                with patch.object(EdgeRuntime, 'start', kill_real_analytics), contextlib.redirect_stdout(captured):
                    code = main(['--config', str(config_path), '--start'])
                self.assertEqual(code, 1)
                reports = [json.loads(line) for line in captured.getvalue().splitlines()]
                self.assertIn('runtime', reports[-1], captured.getvalue())
                final = reports[-1]['runtime']
                self.assertEqual(final['analytics']['state'], 'failed')
                self.assertTrue(final['degraded'])
                self.assertEqual(final['recorder']['state'], 'completed')
                self.assertFalse(final['recorder']['alive'])
                self.assertTrue(list(output.rglob('*.mkv')))
            finally:
                for runtime in runtimes:
                    runtime.stop()

    @unittest.skipUnless(FFMPEG_AVAILABLE, 'requires real FFmpeg')
    def test_start_cli_disabled_analytics_records_to_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=32x24:r=4',
                            '-t', '1', '-c:v', 'ffv1', str(source)], check=True, capture_output=True)
            config_path = Path(directory) / 'config.json'
            output = Path(directory) / 'raw'
            config_path.write_text(json.dumps(dict(source=str(source), output_dir=str(output), analytics_enabled=False)))
            result = subprocess.run([sys.executable, '-m', 'apps.edge.doctor', '--config', str(config_path), '--start'],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(report['runtime']['recorder']['state'], 'completed')
            self.assertEqual(report['runtime']['analytics']['state'], 'disabled')
            self.assertEqual(report['observations_consumed'], 0)
            self.assertTrue(list(output.rglob('*.mkv')))

    @unittest.skipUnless(ORT_AVAILABLE and FFMPEG_AVAILABLE, 'requires real pinned ORT artifact and FFmpeg')
    def test_start_cli_runs_real_ffmpeg_ort_and_records_raw_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=32x24:r=4',
                            '-t', '1', '-c:v', 'ffv1', str(source)], check=True, capture_output=True)
            config_path = Path(directory) / 'config.json'
            output = Path(directory) / 'raw'
            config_path.write_text(json.dumps(dict(source=str(source), output_dir=str(output),
                manifest_path='models/yolox-tiny/manifest.json', model_path='data/oracle/yolox_tiny.onnx',
                sample_fps=2, segment_seconds=.5, queue_capacity=1, observation_capacity=1)))
            result = subprocess.run([sys.executable, '-m', 'apps.edge.doctor', '--config', str(config_path), '--start'],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            reports = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(reports[-1]['scope'], 'runtime')
            self.assertEqual(reports[-1]['runtime']['outcome'], 'ok')
            self.assertEqual(reports[-1]['runtime']['recorder']['state'], 'completed')
            self.assertEqual(reports[-1]['observations_consumed'], 2)
            self.assertTrue(list(output.rglob('*.mkv')))

    def test_doctor_cli_reports_disabled_and_invalid_configuration_nonzero_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            source.touch()
            path = Path(directory) / 'config.json'
            values = dict(source=str(source), output_dir=directory, analytics_enabled=False)
            path.write_text(json.dumps(values))
            command = [sys.executable, '-m', 'apps.edge.doctor', '--config', str(path)]
            good = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads(good.stdout)['scope'], 'preflight')
            for change in (dict(backend='rknn-secret'), dict(source='rtsp://user:secret@host'),
                           dict(password='secret'), dict(analytics_enabled=True,
                           manifest_path='secret-missing', model_path='secret-missing')):
                path.write_text(json.dumps({**values, **change}))
                bad = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(bad.returncode, 1)
                self.assertNotIn('secret', bad.stdout + bad.stderr)
                self.assertEqual(json.loads(bad.stdout)['status'], 'error')

    @unittest.skipUnless(ORT_AVAILABLE, 'requires real pinned ORT artifact')
    def test_enabled_preflight_validates_real_pinned_ort_and_rejects_bad_artifact(self):
        from apps.edge.config import load_edge_config
        from apps.edge.doctor import preflight
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            source.touch()
            base = dict(source=str(source), output_dir=directory,
                        manifest_path='models/yolox-tiny/manifest.json', model_path='data/oracle/yolox_tiny.onnx')
            good = preflight(load_edge_config(base))
            self.assertEqual(good['capabilities']['analytics']['status'], 'available')
            self.assertEqual(good['capabilities']['analytics']['provider'], 'CPUExecutionProvider')
            bad = preflight(load_edge_config({**base, 'model_path': str(source)}))
            self.assertEqual(bad['status'], 'error')
            self.assertEqual(bad['capabilities']['analytics']['status'], 'unavailable')
            self.assertNotIn(str(source), json.dumps(bad))

    def test_disabled_preflight_never_initializes_ort_and_is_not_runtime_health(self):
        from apps.edge.config import load_edge_config
        from apps.edge.doctor import preflight
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            source.touch()
            config = load_edge_config(dict(source=str(source), output_dir=directory, analytics_enabled=False))
            with patch('apps.edge.oracle_detector.OracleDetector', side_effect=AssertionError('ORT must not initialize')):
                report = preflight(config)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['scope'], 'preflight')
        self.assertEqual(report['capabilities']['analytics']['status'], 'disabled')
        self.assertIn('reason', report['capabilities']['analytics'])
        self.assertNotIn('running', json.dumps(report))
