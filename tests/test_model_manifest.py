"""Public manifest loading seam: metadata, artifact integrity and use gates."""
import json
from pathlib import Path
import tempfile
import unittest

from domain.model_manifest import load_manifest

MANIFEST = Path(__file__).resolve().parents[1] / 'models/yolox-tiny/manifest.json'


class ModelManifestTests(unittest.TestCase):
    def test_lab_rejects_substituted_bytes_even_with_matching_manifest_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / 'model.onnx'
            model.write_bytes(b'abc')
            manifest = json.loads(MANIFEST.read_text())
            manifest['artifact'].update(size_bytes=3, sha256='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
            path = root / 'manifest.json'
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'approved artifact'):
                load_manifest(path, model)

    def test_modified_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'model.onnx'
            model.write_bytes(b'not the pinned artifact')
            with self.assertRaisesRegex(ValueError, 'artifact'):
                load_manifest(MANIFEST, model)

    def test_malformed_metadata_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / 'model.onnx'
            model.write_bytes(b'abc')
            path = root / 'manifest.json'
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'manifest'):
                load_manifest(path, model)

    def test_contract_mismatches_are_rejected_before_artifact_access(self):
        changes = [('input', 'dtype', 'float64'), ('input', 'shape', [1, 3, 640, 640]),
                   ('runtime', 'onnxruntime', '0.0'), ('preprocess', 'color', 'RGB'),
                   ('postprocess', 'nms', 'class_agnostic'), ('rights', 'lab_use_approved', False),
                   ('artifact', 'sha256', 'bad'), ('output', 'dtype', None), ('output', 'name', 'wrong'),
                   ('output', 'shape', [1, 3549, 84]), ('postprocess', 'confidence_threshold', None), ('input', 'shape', [True, 3, 416, 416]),
                   ('postprocess', 'iou_pixel_offset', True), ('rights', 'lab_use_approved', 1)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            for section, key, value in changes:
                with self.subTest(section=section, key=key):
                    manifest = json.loads(MANIFEST.read_text())
                    manifest[section][key] = value
                    path.write_text(json.dumps(manifest))
                    with self.assertRaisesRegex(ValueError, 'manifest'):
                        load_manifest(path, Path(directory) / 'absent.onnx')

    def test_production_and_unknown_environments_are_denied(self):
        for environment in ('production', 'unknown'):
            with self.subTest(environment=environment), self.assertRaisesRegex(ValueError, 'clearance'):
                load_manifest(MANIFEST, 'absent.onnx', environment=environment)

    def test_corrupt_json_is_a_clear_validation_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text('not json')
            with self.assertRaisesRegex(ValueError, 'manifest'):
                load_manifest(path, 'absent.onnx')

    def test_missing_artifact_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, 'artifact'):
            load_manifest(MANIFEST, 'absent.onnx')

    def test_same_size_modified_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / 'model.onnx'
            model.write_bytes(b'abd')
            manifest = json.loads(MANIFEST.read_text())
            manifest['artifact'].update(size_bytes=3, sha256='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
            path = root / 'manifest.json'
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'approved artifact'):
                load_manifest(path, model)

    def test_wrong_schema_versions_and_label_order_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            for key, value in [('schema_version', True), ('schema_version', None),
                               ('labels', ['person'] * 80)]:
                with self.subTest(key=key, value=value):
                    manifest = json.loads(MANIFEST.read_text())
                    manifest[key] = value
                    path.write_text(json.dumps(manifest))
                    with self.assertRaisesRegex(ValueError, 'manifest'):
                        load_manifest(path, 'absent.onnx')

    def test_approved_raw_bgr_contract_is_pinned_separately_from_binary(self):
        manifest = json.loads(MANIFEST.read_text())
        self.assertEqual(manifest['preprocess']['color'], 'BGR')
        self.assertEqual(manifest['preprocess']['scale'], 1.0)
        self.assertEqual(manifest['preprocess']['mean'], [0.0, 0.0, 0.0])
        self.assertEqual(manifest['preprocess']['std'], [1.0, 1.0, 1.0])
        self.assertEqual(manifest['preprocess']['source_commit'], '6ddff4824372906469a7fae2dc3206c7aa4bbaee')
        self.assertEqual(manifest['artifact']['source_commit'], 'e1052df71842031413f6030723c3607b839c80ce')

    def test_explicit_numeric_test_fixture_has_nonlab_identity_and_caller_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / 'test.onnx'
            model.write_bytes(b'abc')
            pin = {'size_bytes': 3, 'sha256': 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'}
            manifest = json.loads(MANIFEST.read_text())
            manifest['model_id'] = 'synthetic-yolox-numeric-test'
            manifest['artifact'] = {**pin, 'source_url': 'generated:test-vector', 'source_commit': 'not-applicable', 'release': 'test-vector'}
            manifest['rights'] = {'source_license': 'not-applicable', 'weights_license': 'generated-test-data', 'lab_use_approved': False, 'production_use_approved': False}
            path = root / 'manifest.json'
            path.write_text(json.dumps(manifest))
            self.assertEqual(load_manifest(path, model, environment='numeric-test', expected_artifact=pin), manifest)
            for environment, expected in [('lab', None), ('numeric-test', None), ('numeric-test', {**pin, 'size_bytes': 4})]:
                with self.subTest(environment=environment, expected=expected), self.assertRaises(ValueError):
                    load_manifest(path, model, environment=environment, expected_artifact=expected)
            manifest['model_id'] = 'yolox-tiny-0.1.1rc0'
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'model_id'):
                load_manifest(path, model, environment='numeric-test', expected_artifact=pin)

    def test_lab_never_accepts_explicit_override(self):
        with self.assertRaisesRegex(ValueError, 'overrides'):
            load_manifest(MANIFEST, 'absent.onnx', expected_artifact={'sha256': '0' * 64, 'size_bytes': 3})

    @unittest.skipUnless((MANIFEST.parents[2] / 'data/oracle/yolox_tiny.onnx').exists(), 'requires downloaded approved asset')
    def test_exact_official_asset_loads_in_lab(self):
        manifest = load_manifest(MANIFEST, MANIFEST.parents[2] / 'data/oracle/yolox_tiny.onnx')
        self.assertEqual(manifest['model_id'], 'yolox-tiny-0.1.1rc0')
        self.assertEqual(manifest['artifact']['size_bytes'], 20219662)


if __name__ == '__main__':
    unittest.main()
