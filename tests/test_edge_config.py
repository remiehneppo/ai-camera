import dataclasses
from pathlib import Path
import tempfile
import unittest


class EdgeConfigTests(unittest.TestCase):
    def test_realtime_mode_is_explicitly_unsupported_by_edge_runtime_config(self):
        from apps.edge.config import load_edge_config
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            source.touch()
            with self.assertRaisesRegex(ValueError, 'fast'):
                load_edge_config(dict(source=str(source), output_dir=directory,
                                      analytics_enabled=False, mode='realtime'))

    def test_unsupported_config_is_rejected_without_echoing_values(self):
        from apps.edge.config import load_edge_config
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            source.touch()
            base = dict(source=str(source), output_dir=directory, analytics_enabled=False)
            invalid = [dict(backend='secret-rknn'), dict(source_type='secret-rtsp'),
                       dict(source='rtsp://user:secret@camera'), dict(unknown='secret'),
                       dict(sample_fps=float('nan')), dict(queue_capacity=True),
                       dict(analytics_enabled='false'), dict(mode='live'), dict(model_path=[]),
                       dict(disabled_reason=['secret']), dict(manifest_path='rtsp://secret'),
                       dict(camera_id='../secret'), dict(session_id='../secret')]
            for change in invalid:
                with self.subTest(change=change):
                    with self.assertRaises(ValueError) as caught:
                        load_edge_config({**base, **change})
                    self.assertNotIn('secret', str(caught.exception))

    def test_file_config_is_frozen_with_stable_public_fingerprint(self):
        from apps.edge.config import load_edge_config
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            source.write_bytes(b'file')
            values = dict(source=str(source), output_dir=directory, analytics_enabled=False)
            config = load_edge_config(values)
            self.assertEqual(config.source_type, 'file')
            self.assertEqual(config.backend, 'onnx_cpu')
            self.assertEqual(config.disabled_reason, 'analytics disabled by configuration')
            self.assertEqual(config.config_hash, load_edge_config(dict(reversed(list(values.items())))).config_hash)
            self.assertEqual(len(config.config_hash), 64)
            changed = load_edge_config({**values, 'queue_capacity': 1})
            self.assertNotEqual(config.config_hash, changed.config_hash)
            with self.assertRaises(dataclasses.FrozenInstanceError):
                config.backend = 'rknn'
