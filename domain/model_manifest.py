"""Load the lab oracle's pinned model contract without importing its runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_LABELS = ['person',
 'bicycle',
 'car',
 'motorcycle',
 'airplane',
 'bus',
 'train',
 'truck',
 'boat',
 'traffic light',
 'fire hydrant',
 'stop sign',
 'parking meter',
 'bench',
 'bird',
 'cat',
 'dog',
 'horse',
 'sheep',
 'cow',
 'elephant',
 'bear',
 'zebra',
 'giraffe',
 'backpack',
 'umbrella',
 'handbag',
 'tie',
 'suitcase',
 'frisbee',
 'skis',
 'snowboard',
 'sports ball',
 'kite',
 'baseball bat',
 'baseball glove',
 'skateboard',
 'surfboard',
 'tennis racket',
 'bottle',
 'wine glass',
 'cup',
 'fork',
 'knife',
 'spoon',
 'bowl',
 'banana',
 'apple',
 'sandwich',
 'orange',
 'broccoli',
 'carrot',
 'hot dog',
 'pizza',
 'donut',
 'cake',
 'chair',
 'couch',
 'potted plant',
 'bed',
 'dining table',
 'toilet',
 'tv',
 'laptop',
 'mouse',
 'remote',
 'keyboard',
 'cell phone',
 'microwave',
 'oven',
 'toaster',
 'sink',
 'refrigerator',
 'book',
 'clock',
 'vase',
 'scissors',
 'teddy bear',
 'hair drier',
 'toothbrush']
_EXPECTED = {'schema_version': 1,
 'model_id': 'yolox-tiny-0.1.1rc0',
 'input': {'name': 'images', 'shape': [1, 3, 416, 416], 'dtype': 'float32'},
 'output': {'name': 'output', 'shape': [1, 3549, 85], 'dtype': 'float32'},
 'preprocess': {'color': 'BGR',
                'layout': 'NCHW',
                'resize': 'bilinear',
                'letterbox': 'top_left',
                'pad_value': 114,
                'scale': 1.0,
                'mean': [0.0, 0.0, 0.0],
                'std': [1.0, 1.0, 1.0],
                'source_commit': '6ddff4824372906469a7fae2dc3206c7aa4bbaee',
                'source_url': 'https://github.com/Megvii-BaseDetection/YOLOX/blob/6ddff4824372906469a7fae2dc3206c7aa4bbaee/yolox/data/data_augment.py'},
 'postprocess': {'decode': 'yolox_grid',
                 'strides': [8, 16, 32],
                 'score': 'objectness_times_class',
                 'confidence_threshold': 0.3,
                 'nms_threshold': 0.45,
                 'nms': 'per_class',
                 'iou_pixel_offset': 1,
                 'box_format': 'xyxy',
                 'person_class_id': 0,
                 'candidate_threshold': 0.1,
                 'candidate_comparator': '>',
                 'confidence_comparator': '>='},
 'runtime': {'onnxruntime': '1.20.1',
             'numpy': '1.26.4',
             'provider': 'CPUExecutionProvider',
             'opencv_python_headless': '4.10.0.84'},
 'rights': {'source_license': 'Apache-2.0',
            'weights_license': 'unknown',
            'lab_use_approved': True,
            'production_use_approved': False}}


def load_manifest(path: str | Path, model_path: str | Path, *, environment: str = 'lab',
                  expected_artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    if environment not in ('lab', 'numeric-test'):
        raise ValueError('clearance permits lab use only; production weights rights unresolved')
    try:
        manifest = json.loads(Path(path).read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'manifest cannot be read: {error}') from error
    required = {'schema_version', 'model_id', 'artifact', 'input', 'output', 'labels',
                'preprocess', 'postprocess', 'runtime', 'rights'}
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ValueError('manifest fields are invalid')
    expected_contract = _EXPECTED.copy()
    if environment == 'numeric-test':
        if not isinstance(expected_artifact, dict) or set(expected_artifact) != {'sha256', 'size_bytes'}:
            raise ValueError('numeric-test requires an explicit expected artifact pin')
        expected_contract['model_id'] = 'synthetic-yolox-numeric-test'
        expected_contract['rights'] = {'source_license': 'not-applicable',
                                       'weights_license': 'generated-test-data',
                                       'lab_use_approved': False, 'production_use_approved': False}
    elif expected_artifact is not None:
        raise ValueError('lab clearance does not allow expected artifact overrides')
    for key, expected in expected_contract.items():
        if json.dumps(manifest[key], sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise ValueError(f'manifest {key} contract mismatch')
    if manifest['labels'] != _LABELS:
        raise ValueError('manifest COCO labels mismatch')
    artifact = manifest['artifact']
    if not isinstance(artifact, dict) or set(artifact) != {'sha256', 'size_bytes', 'source_url', 'source_commit', 'release'}:
        raise ValueError('manifest artifact fields are invalid')
    digest = artifact['sha256']
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('manifest artifact SHA-256 is invalid')
    if type(artifact['size_bytes']) is not int or artifact['size_bytes'] <= 0:
        raise ValueError('manifest artifact size is invalid')
    if environment == 'numeric-test':
        if (artifact['source_url'] != 'generated:test-vector' or
                artifact['source_commit'] != 'not-applicable' or artifact['release'] != 'test-vector'):
            raise ValueError('manifest numeric-test source must identify generated test data')
        if json.dumps({key: artifact[key] for key in ('sha256', 'size_bytes')}, sort_keys=True) != json.dumps(expected_artifact, sort_keys=True):
            raise ValueError('manifest numeric-test artifact differs from explicit caller pin')
    else:
        if artifact['source_commit'] != 'e1052df71842031413f6030723c3607b839c80ce' or artifact['release'] != '0.1.1rc0':
            raise ValueError('manifest artifact source pin mismatch')
        if artifact['source_url'] != 'https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx':
            raise ValueError('manifest artifact source URL mismatch')
        if artifact['sha256'] != '427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7' or artifact['size_bytes'] != 20219662:
            raise ValueError('manifest differs from exact approved artifact')
    model = Path(model_path)
    try:
        if model.stat().st_size != artifact['size_bytes']:
            raise ValueError('artifact size mismatch')
        with model.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    except OSError as error:
        raise ValueError(f'artifact cannot be read: {error}') from error
    if digest != artifact['sha256']:
        raise ValueError('artifact SHA-256 mismatch')
    return manifest
