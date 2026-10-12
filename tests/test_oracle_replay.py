import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipUnless(np is not None and shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'pixel replay requires optional numpy and ffmpeg/ffprobe')
class OracleReplayTests(unittest.TestCase):
    def test_pixels_pts_and_sampling_are_same_in_fast_and_paced_modes(self):
        from apps.edge.oracle_replay import iter_video_frames
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'red.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=red:s=16x12:r=4', '-t', '0.75', '-c:v', 'ffv1',
                            '-output_ts_offset', '3', str(source)], check=True, capture_output=True)
            fast = list(iter_video_frames(source, sample_fps=2, camera_id='camera', session_id='session'))
            paced = list(iter_video_frames(source, sample_fps=2, mode='realtime',
                                           camera_id='camera', session_id='session'))
            self.assertEqual(len(fast), 2)
            self.assertEqual([frame for _, frame in fast], [frame for _, frame in paced])
            self.assertEqual([frame['event_time'] for _, frame in fast], [3.0, 3.5])
            for rgb, frame in fast:
                self.assertEqual(rgb.shape, (12, 16, 3))
                self.assertEqual(rgb.dtype, np.uint8)
                self.assertGreater(int(rgb[0, 0, 0]), 240)
                self.assertLess(int(rgb[0, 0, 1]), 10)
                self.assertEqual(frame['camera_id'], 'camera')
                self.assertEqual(frame['session_id'], 'session')
                self.assertEqual(frame['pixel_format'], 'rgb24')

    def test_invalid_fps_missing_and_bad_sources_are_explicit(self):
        from apps.edge.oracle_replay import iter_video_frames
        for fps in (0, -1, math.nan, math.inf, True):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                list(iter_video_frames('missing.mp4', sample_fps=fps))
        with self.assertRaises(FileNotFoundError):
            list(iter_video_frames('missing.mp4', sample_fps=1))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'invalid.mp4'
            source.write_bytes(b'not video')
            with self.assertRaisesRegex(RuntimeError, 'probe'):
                list(iter_video_frames(source, sample_fps=1))

    def test_cli_requires_explicit_inputs_and_reports_bad_input_nonzero(self):
        import sys
        result = subprocess.run([sys.executable, '-m', 'apps.edge.oracle_replay'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--video', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_dynamic_dimensions_and_missing_pts_are_rejected(self):
        from unittest.mock import patch
        from apps.edge.oracle_replay import iter_video_frames
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'red.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=red:s=16x12:r=4', '-t', '0.5', '-c:v', 'ffv1',
                            str(source)], check=True, capture_output=True)
            real_run = subprocess.run
            for line, message in ((b'pts=0|width=32|height=12\n', 'dynamic'),
                                  (b'pts=N/A|width=16|height=12\n', 'PTS')):
                def changed_probe(command, **kwargs):
                    if '-show_frames' in command:
                        kwargs['stdout'].write(line)
                        return subprocess.CompletedProcess(command, 0)
                    return real_run(command, **kwargs)
                with patch('apps.edge.oracle_replay.subprocess.run', side_effect=changed_probe):
                    with self.assertRaisesRegex(RuntimeError, message):
                        list(iter_video_frames(source))

    def test_bad_run_arguments_do_not_construct_detector(self):
        from unittest.mock import patch
        from apps.edge.oracle_replay import run_oracle
        with patch('apps.edge.oracle_detector.OracleDetector') as detector:
            with self.assertRaises(ValueError):
                run_oracle('missing', 'missing', 'missing', sample_fps=float('nan'))
            with self.assertRaises(ValueError):
                run_oracle('missing', 'missing', 'missing', mode='live')
            with self.assertRaises(FileNotFoundError):
                run_oracle('missing', 'missing', 'missing')
            detector.assert_not_called()

    def test_report_failure_status_and_consumer_exception_close_source(self):
        from unittest.mock import patch
        from apps.edge.oracle_replay import run_oracle
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            source.write_bytes(b'fixture')
            closed = []
            def frames(*args, **kwargs):
                try:
                    yield np.zeros((1, 1, 3), dtype=np.uint8), {}
                finally:
                    closed.append(True)
            with patch('apps.edge.oracle_detector.OracleDetector') as detector, \
                    patch('apps.edge.oracle_replay.iter_video_frames', frames):
                detector.return_value.detect.return_value = {'detection_status': 'failed', 'error': 'invalid',
                    'provenance': {'model_sha256':
                    'f16d05ec6b29248d2c61adb1e9263f78e4f7bace1b955014a2d17872cfe4064d'}}
                report = run_oracle(source, source, source)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['source_sha256'],
                                 'f16d05ec6b29248d2c61adb1e9263f78e4f7bace1b955014a2d17872cfe4064d')
                self.assertEqual(closed, [True])
                detector.return_value.detect.side_effect = RuntimeError('consumer failed')
                with self.assertRaisesRegex(RuntimeError, 'consumer failed'):
                    run_oracle(source, source, source)
                self.assertEqual(closed, [True, True])

    def test_report_rejects_input_mutation_and_model_provenance_mismatch(self):
        from unittest.mock import patch
        from apps.edge.oracle_replay import run_oracle
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('source', 'manifest', 'model')]
            for changed in range(3):
                for path in paths:
                    path.write_bytes(b'fixture')
                def frames(*args, **kwargs):
                    yield np.zeros((1, 1, 3), dtype=np.uint8), {}
                    paths[changed].write_bytes(b'replaced while running')
                with patch('apps.edge.oracle_detector.OracleDetector') as detector, \
                        patch('apps.edge.oracle_replay.iter_video_frames', frames):
                    detector.return_value.detect.return_value = {
                        'detection_status': 'ok_empty', 'provenance': {'model_sha256':
                        'f16d05ec6b29248d2c61adb1e9263f78e4f7bace1b955014a2d17872cfe4064d'}}
                    with self.subTest(changed=changed), self.assertRaisesRegex(RuntimeError, 'changed during replay'):
                        run_oracle(*paths)
            for path in paths:
                path.write_bytes(b'fixture')
            def one_frame(*args, **kwargs):
                yield np.zeros((1, 1, 3), dtype=np.uint8), {}
            with patch('apps.edge.oracle_detector.OracleDetector') as detector, \
                    patch('apps.edge.oracle_replay.iter_video_frames', one_frame):
                detector.return_value.detect.return_value = {'detection_status': 'ok_empty',
                                                              'provenance': {'model_sha256': 'wrong'}}
                with self.assertRaisesRegex(RuntimeError, 'model provenance'):
                    run_oracle(*paths)

    def test_stalled_decoder_times_out_and_is_reaped(self):
        import sys
        from unittest.mock import patch
        from apps.edge.oracle_replay import iter_video_frames
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'red.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=red:s=16x12:r=4', '-t', '0.5', '-c:v', 'ffv1',
                            str(source)], check=True, capture_output=True)
            real_popen = subprocess.Popen
            decoders = []
            def stalled_decoder(command, **kwargs):
                if command[0] == 'ffmpeg':
                    command = [sys.executable, '-c', 'import time; time.sleep(5)']
                    process = real_popen(command, **kwargs)
                    decoders.append(process)
                    return process
                return real_popen(command, **kwargs)
            with patch('apps.edge.oracle_replay.subprocess.Popen', side_effect=stalled_decoder):
                with self.assertRaisesRegex(RuntimeError, 'decoder timed out'):
                    list(iter_video_frames(source, sample_fps=2, timeout_seconds=0.5))
            self.assertIsNotNone(decoders[0].returncode)
            self.assertTrue(decoders[0].stdout.closed)

    def test_decoder_failure_is_not_successful_eof(self):
        from unittest.mock import patch
        from apps.edge.oracle_replay import iter_video_frames
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'red.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=red:s=16x12:r=4', '-t', '0.5', '-c:v', 'ffv1',
                            str(source)], check=True, capture_output=True)
            real_popen = subprocess.Popen
            def broken_decoder(command, **kwargs):
                if command[0] == 'ffmpeg':
                    command = list(command)
                    command[command.index('-i') + 1] = str(source.parent / 'missing.mkv')
                return real_popen(command, **kwargs)
            with patch('apps.edge.oracle_replay.subprocess.Popen', side_effect=broken_decoder):
                with self.assertRaisesRegex(RuntimeError, 'decoder/PTS mismatch'):
                    list(iter_video_frames(source, sample_fps=2))


if __name__ == '__main__':
    unittest.main()
