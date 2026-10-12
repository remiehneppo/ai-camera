import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


READY = (all(importlib.util.find_spec(name) for name in ('numpy', 'cv2', 'onnxruntime'))
         and shutil.which('ffmpeg') and shutil.which('ffprobe')
         and Path('data/oracle/yolox_tiny.onnx').is_file())


@unittest.skipUnless(READY, 'requires optional oracle runtime, model and FFmpeg')
class DetectorRecorderLabTests(unittest.TestCase):
    def test_cli_invalid_sampling_is_nonzero(self):
        import sys
        result = subprocess.run([sys.executable, '-m', 'apps.edge.oracle_recorder_lab',
                                 '--video', 'missing', '--manifest', 'missing', '--model', 'missing',
                                 '--sample-fps', 'nan'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('sample_fps must be finite', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_parity_checks_lineage_and_detection_tolerances(self):
        from copy import deepcopy
        from unittest.mock import patch
        from apps.edge.oracle_recorder_lab import run_detector_recorder_lab
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'black.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=black:s=32x24:r=5', '-t', '0.6', '-c:v', 'ffv1',
                            str(source)], check=True)
            base = {'origin': 'replay', 'camera_id': 'lab-camera', 'stream_session_id': 'lab-replay',
                    'source_sha256': 'source', 'manifest_sha256': 'manifest', 'model_sha256': 'model',
                    'sample_fps': 2, 'status': 'ok', 'observations': [
                        {'event_time': 0.0, 'origin': 'replay', 'stream_session_id': 'lab-replay',
                         'detection_status': 'ok', 'provenance': {'config_sha256': 'config', 'model_sha256': 'model'},
                         'detections': [{'class_id': 0, 'label': 'person', 'score': 0.5,
                                         'bbox_xyxy': [1.0, 2.0, 3.0, 4.0]}]}]}
            for change, expected in [('within', True), ('box', False), ('score', False),
                                     ('origin', False), ('session', False), ('config', False),
                                     ('model', False), ('label', False), ('status', False), ('count', False)]:
                paced = deepcopy(base)
                observation = paced['observations'][0]
                if change in ('within', 'box'):
                    observation['detections'][0]['bbox_xyxy'][0] += 0.0005 if change == 'within' else 0.002
                elif change == 'score':
                    observation['detections'][0]['score'] += 0.000002
                elif change == 'origin':
                    observation['origin'] = 'live'
                elif change == 'session':
                    observation['stream_session_id'] = 'other'
                elif change in ('config', 'model'):
                    observation['provenance'][change + '_sha256'] = 'other'
                elif change == 'label':
                    observation['detections'][0]['label'] = 'vehicle'
                elif change == 'status':
                    observation['detection_status'] = 'ok_empty'
                elif change == 'count':
                    observation['detections'] = []
                def oracle(*args, **kwargs):
                    result = deepcopy(base if kwargs['mode'] == 'fast' else paced)
                    kwargs['observation_consumer'](result['observations'][0])
                    return result
                with self.subTest(change=change), patch('apps.edge.oracle_recorder_lab.run_oracle', oracle):
                    report = run_detector_recorder_lab(source, 'unused', 'unused')
                    self.assertEqual(report['detector_semantic_parity'], expected)
                    self.assertEqual(report['status'], 'ok' if expected else 'failed')

    def test_consumer_queries_complete_before_watermark_and_failure_stays_failed(self):
        from unittest.mock import patch
        from apps.edge.oracle_recorder_lab import run_detector_recorder_lab
        from apps.edge.recorder import FileRecorder
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'black.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=black:s=32x24:r=5', '-t', '0.6', '-c:v', 'ffv1',
                            str(source)], check=True)
            actions = []
            original_query = FileRecorder.actual_range
            original_advance = FileRecorder.advance_watermark
            def query(recorder, *args):
                result = original_query(recorder, *args)
                actions.append('query_complete')
                return result
            def advance(recorder, session, timestamp):
                if timestamp != float('-inf'):
                    self.assertEqual(actions[-1], 'query_complete')
                    actions.append('watermark')
                return original_advance(recorder, session, timestamp)
            def failed_oracle(*args, **kwargs):
                observation = {'event_time': 0.0, 'origin': 'replay',
                               'detection_status': 'failed', 'detections': [], 'error': 'inference failed'}
                kwargs['observation_consumer'](observation)
                return {'origin': 'replay', 'camera_id': 'lab-camera', 'stream_session_id': 'lab-replay',
                        'source_sha256': 'source', 'manifest_sha256': 'manifest', 'model_sha256': 'model',
                        'sample_fps': 2, 'status': 'failed', 'observations': [observation]}
            with patch.object(FileRecorder, 'actual_range', query), \
                    patch.object(FileRecorder, 'advance_watermark', advance), \
                    patch('apps.edge.oracle_recorder_lab.run_oracle', failed_oracle):
                report = run_detector_recorder_lab(source, 'unused', 'unused')
            self.assertEqual(actions.count('watermark'), 2)
            self.assertEqual(report['status'], 'failed')
            self.assertTrue(report['detector_semantic_parity'])
            for run in report['runs'].values():
                self.assertEqual(run['failure_count'], 1)
                self.assertEqual(run['oracle']['observations'][0]['detection_status'], 'failed')
                self.assertEqual(run['raw_after_consumer']['completeness'], 'complete')

    def test_real_detector_semantics_and_raw_queries_survive_consumer_completion(self):
        from apps.edge.oracle_recorder_lab import run_detector_recorder_lab
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'black.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=black:s=32x24:r=5', '-t', '0.6', '-c:v', 'ffv1',
                            str(source)], check=True)
            report = run_detector_recorder_lab(source, 'models/yolox-tiny/manifest.json',
                                               'data/oracle/yolox_tiny.onnx', sample_fps=5)
            self.assertTrue(report['detector_semantic_parity'])
            self.assertEqual(report['origin'], 'replay')
            self.assertEqual(report['status'], 'ok')
            for run in report['runs'].values():
                self.assertEqual(run['delivered_count'], 3)
                self.assertEqual(run['failure_count'], 0)
                self.assertEqual(run['last_consumed_event_time'], 0.4)
                self.assertEqual(run['raw_query_count'], 3)
                self.assertTrue(run['raw_coverage_unchanged'])
                self.assertEqual(run['raw_after_consumer']['completeness'], 'complete')
                self.assertEqual([o['detection_status'] for o in run['oracle']['observations']],
                                 ['ok_empty'] * 3)
