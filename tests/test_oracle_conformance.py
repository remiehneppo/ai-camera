import copy
import importlib.util
from pathlib import Path
import shutil
import unittest
from typing import Any

from tools.oracle_conformance import compare_batch


class GoldenComparisonTests(unittest.TestCase):
    def test_exact_identity_and_provenance_are_required(self):
        expected: dict[str, Any] = {'detection_status': 'ok_empty', 'detections': [], 'provenance': {'model_sha256': 'abc'}}
        compare_batch(expected, expected)
        actual = copy.deepcopy(expected)
        actual['provenance']['model_sha256'] = 'changed'
        with self.assertRaises(ValueError):
            compare_batch(expected, actual)

class GoldenToleranceTests(unittest.TestCase):
    def test_float_drift_count_label_status_and_nonfinite_rejected(self):
        expected: dict[str, Any] = {'detection_status': 'ok', 'provenance': {}, 'detections': [{'class_id': 0, 'label': 'person', 'score': .5, 'bbox_xyxy': [0., 0., 10., 10.]}]}
        for key, replacement in [('detection_status', 'ok_empty'), ('detections', [])]:
            changed = copy.deepcopy(expected)
            changed[key] = replacement
            with self.assertRaises(ValueError):
                compare_batch(expected, changed)
        for field, value in [('score', .50001), ('bbox_xyxy', [0, 0, 10.01, 10]), ('label', 'car'), ('score', float('nan'))]:
            actual = copy.deepcopy(expected)
            actual['detections'][0][field] = value
            with self.assertRaises(ValueError):
                compare_batch(expected, actual)

RUNTIME_AVAILABLE = all(importlib.util.find_spec(name) for name in ('numpy', 'cv2', 'onnxruntime'))
ARTIFACTS_AVAILABLE = all(Path(path).is_file() for path in (
    'data/oracle/yolox_tiny.onnx', 'data/oracle/shibuya_people.jpg',
    'models/yolox-tiny/manifest.json', 'fixtures/oracle/golden-v1.json',
    'fixtures/oracle/reference-sources.json'))


@unittest.skipUnless(RUNTIME_AVAILABLE and ARTIFACTS_AVAILABLE, 'requires optional pinned oracle runtime and approved artifacts')
class RealGoldenTests(unittest.TestCase):
    def test_independent_reference_observes_positive_and_negative(self):
        from tools.oracle_conformance import reference_batch
        import cv2
        import numpy as np
        rgb = cv2.imread('data/oracle/shibuya_people.jpg')[:, :, ::-1].copy()
        positive = reference_batch(rgb)
        negative = reference_batch(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual(positive['detection_status'], 'ok')
        self.assertGreater(sum(d['label'] == 'person' for d in positive['detections']), 1)
        self.assertEqual(negative['detection_status'], 'ok_empty')

@unittest.skipUnless(RUNTIME_AVAILABLE and ARTIFACTS_AVAILABLE, 'requires optional pinned oracle runtime and approved artifacts')
class RecordedGoldenTests(unittest.TestCase):
    def test_real_detector_matches_versioned_independent_reference(self):
        from tools.oracle_conformance import check_golden
        self.assertEqual(check_golden()['authored_black']['status'], 'ok_empty')

    def test_changed_fixture_pin_rejected(self):
        import json
        from pathlib import Path
        from unittest.mock import patch
        from tools.oracle_conformance import check_golden, golden_pins
        pins = golden_pins()
        pins['original_sha256'] = 'tampered'
        with patch('tools.oracle_conformance.golden_pins', return_value=pins):
            with self.assertRaises(ValueError):
                check_golden()

    def test_golden_policy_and_expected_nonfinite_are_rejected(self):
        import json
        from pathlib import Path
        from unittest.mock import patch
        from tools.oracle_conformance import check_golden, GOLDEN
        golden = json.loads(Path(GOLDEN).read_text())
        golden['policy']['final'] = '>0.3'
        with patch('pathlib.Path.read_text', return_value=json.dumps(golden)):
            with self.assertRaises(ValueError):
                check_golden()
        invalid: dict[str, Any] = {'detection_status':'ok', 'provenance':{}, 'detections':[{'class_id':0,'label':'person','score':float('nan'),'bbox_xyxy':[0,0,1,1]}]}
        with self.assertRaises(ValueError):
            compare_batch(invalid, invalid)

    @unittest.skipUnless(importlib.util.find_spec('onnx'), 'requires optional ONNX numeric fixture generator')
    def test_independent_border_and_exact_threshold_vector_through_public_detector(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path
        import numpy as np
        import onnx
        from onnx import helper, numpy_helper, TensorProto
        from apps.edge.oracle_detector import OracleDetector
        from tools.oracle_conformance import FRAME, reference_postprocess
        raw = np.zeros((1, 3549, 85), dtype=np.float32)
        # Grid cell0 centered at0 with8x8 box clips to[0,0,4,4].
        raw[0, 0, :7] = [0, 0, 0, 0, 1, .3, .2999]
        labels = json.loads(Path('models/yolox-tiny/manifest.json').read_text())['labels']
        reference = reference_postprocess(raw, 416, 416, labels)
        self.assertEqual(len(reference), 1)
        self.assertEqual(reference[0]['bbox_xyxy'], [0, 0, 4, 4])
        self.assertEqual(reference[0]['label'], 'person')
        with tempfile.TemporaryDirectory() as directory:
            graph = helper.make_graph([helper.make_node('Identity', ['raw'], ['output'])], 'independent-border-vector',
                                      [helper.make_tensor_value_info('images', TensorProto.FLOAT, [1,3,416,416])],
                                      [helper.make_tensor_value_info('output', TensorProto.FLOAT, [1,3549,85])],
                                      initializer=[numpy_helper.from_array(raw, 'raw')])
            model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 11)])
            model.ir_version = 9
            path = Path(directory)/'vector.onnx'
            onnx.save(model, path)
            manifest = json.loads(Path('models/yolox-tiny/manifest.json').read_text())
            pin = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size_bytes=path.stat().st_size)
            manifest['model_id'] = 'synthetic-yolox-numeric-test'
            manifest['artifact'].update(**pin, source_url='generated:test-vector', source_commit='not-applicable', release='test-vector')
            manifest['rights'] = dict(source_license='not-applicable', weights_license='generated-test-data', lab_use_approved=False, production_use_approved=False)
            spec = Path(directory)/'manifest.json'
            spec.write_text(json.dumps(manifest))
            actual = OracleDetector(spec, path, environment="numeric-test", expected_artifact=pin).detect(np.zeros((416,416,3), dtype=np.uint8), FRAME)
            compare_batch({'detection_status':'ok', 'detections': reference, 'provenance':actual['provenance']}, actual)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires ffmpeg and ffprobe replay tools')
    def test_fast_and_paced_replay_match_independent_decoded_pixel_reference(self):
        import tempfile
        import subprocess
        from pathlib import Path
        import cv2
        from apps.edge.oracle_replay import run_oracle
        from tools.oracle_conformance import MANIFEST, MODEL, reference_batch
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory)/'fixture.mkv'
            subprocess.run(['ffmpeg','-v','error','-loop','1','-i','data/oracle/shibuya_people.jpg',
                            '-vf','scale=320:426','-r','2','-frames:v','2','-c:v','ffv1',str(video)], check=True)
            # Decode separately, not through production replay iterator.
            raw = subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','rawvideo','-pix_fmt','rgb24','pipe:1'],
                                 check=True,capture_output=True).stdout
            import numpy as np
            pixels = np.frombuffer(raw,dtype=np.uint8).reshape(2,426,320,3)
            refs = [reference_batch(rgb) for rgb in pixels]
            fast = run_oracle(video,MANIFEST,MODEL,sample_fps=2,mode='fast')
            paced = run_oracle(video,MANIFEST,MODEL,sample_fps=2,mode='realtime')
            self.assertEqual(len(fast['observations']),2)
            for expected,a,b in zip(refs,fast['observations'],paced['observations']):
                compare_batch(expected,a)
                compare_batch(expected,b)
                for key in ('pts','time_base','event_time','frame_id','camera_id','stream_session_id','core_epoch','origin'):
                    self.assertEqual(a[key],b[key])
            self.assertEqual([x['event_time'] for x in fast['observations']],[0.,.5])


if __name__ == "__main__":
    unittest.main()
