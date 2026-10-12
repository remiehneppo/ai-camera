"""Independent, lab-only versioned golden comparison."""
import math

# Reference portions adapted from Megvii Apache-2.0; see fixtures/oracle/YOLOX-LICENSE.txt.
from typing import Any


def compare_batch(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    for key in ('detection_status', 'provenance', 'transform', *FRAME.keys()):
        if key not in expected:
            continue
        if expected[key] != actual[key]:
            raise ValueError(f'{key} mismatch')
    if len(expected['detections']) != len(actual['detections']):
        raise ValueError('detection count mismatch')
    for wanted, found in zip(expected['detections'], actual['detections']):
        for key in ('class_id', 'label'):
            if wanted[key] != found[key]:
                raise ValueError(f'{key} mismatch')
        for key, tolerance in (('score', 1e-6), ('bbox_xyxy', 1e-3)):
            if key == 'score' and (type(wanted[key]) not in (int, float) or type(found[key]) not in (int, float)):
                raise ValueError('score must be scalar')
            if key == 'bbox_xyxy' and (not isinstance(wanted[key], list) or not isinstance(found[key], list) or len(wanted[key]) != 4 or len(found[key]) != 4):
                raise ValueError('bbox must have four coordinates')
            left = wanted[key] if isinstance(wanted[key], list) else [wanted[key]]
            right = found[key] if isinstance(found[key], list) else [found[key]]
            if len(left) != len(right) or any(not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > tolerance for a, b in zip(left, right)):
                raise ValueError(f'{key} mismatch')


MODEL = 'data/oracle/yolox_tiny.onnx'
MANIFEST = 'models/yolox-tiny/manifest.json'
GOLDEN = 'fixtures/oracle/golden-v1.json'
FRAME = dict(camera_id='golden-camera', stream_session_id='golden-session', core_epoch=1,
             origin='replay', frame_id=0, pts=0, time_base='1/2', event_time=0.)


def reference_postprocess(raw: Any, height: int, width: int, labels: list[str]) -> list[dict[str, Any]]:
    """Adapted e1052df demo_postprocess/multiclass_nms; no production helpers."""
    import numpy as np
    output = raw.copy()
    grids, strides = [], []
    for stride in (8, 16, 32):
        xv, yv = np.meshgrid(np.arange(416 // stride), np.arange(416 // stride))
        grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
        grids.append(grid)
        strides.append(np.full((*grid.shape[:2], 1), stride))
    grid = np.concatenate(grids, 1)
    expanded = np.concatenate(strides, 1)
    output[..., :2] = (output[..., :2] + grid) * expanded
    output[..., 2:4] = np.exp(output[..., 2:4]) * expanded
    predictions = output[0]
    boxes = np.ones_like(predictions[:, :4])
    boxes[:, :2] = predictions[:, :2] - predictions[:, 2:4] / 2
    boxes[:, 2:] = predictions[:, :2] + predictions[:, 2:4] / 2
    boxes /= min(416 / height, 416 / width)
    scores = predictions[:, 4:5] * predictions[:, 5:]
    final = []
    for class_id, label in enumerate(labels):
        valid = scores[:, class_id] > .1
        valid_boxes, valid_scores = boxes[valid], scores[valid, class_id]
        x1, y1, x2, y2 = valid_boxes.T
        areas = (x2-x1+1)*(y2-y1+1)
        order = valid_scores.argsort()[::-1]
        while order.size:
            i = order[0]
            if valid_scores[i] >= .3:
                clipped = np.clip(valid_boxes[i], [0, 0, 0, 0], [width, height, width, height])
                final.append(dict(class_id=class_id, label=label, score=float(valid_scores[i]), bbox_xyxy=clipped.tolist()))
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            intersection = np.maximum(0., xx2-xx1+1)*np.maximum(0., yy2-yy1+1)
            overlap = intersection/(areas[i]+areas[order[1:]]-intersection)
            order = order[np.where(overlap <= .45)[0]+1]
    final.sort(key=lambda item: (-item['score'], item['class_id'], *item['bbox_xyxy']))
    return final


def reference_batch(rgb: Any) -> dict[str, Any]:
    import cv2
    import numpy as np
    import onnxruntime as ort  # type: ignore[import-untyped]
    import json
    import hashlib
    from pathlib import Path
    manifest = json.loads(Path(MANIFEST).read_text())
    if hashlib.sha256(Path(MODEL).read_bytes()).hexdigest() != manifest['artifact']['sha256']:
        raise ValueError('model hash mismatch')
    from importlib.metadata import version
    if (ort.__version__ != manifest['runtime']['onnxruntime'] or np.__version__ != manifest['runtime']['numpy'] or
            version('opencv-python-headless') != manifest['runtime']['opencv_python_headless']):
        raise ValueError('reference runtime mismatch')
    height, width = rgb.shape[:2]
    bgr = rgb[:, :, ::-1]
    padded = np.ones((416, 416, 3), dtype=np.uint8)*114
    ratio = min(416/height, 416/width)
    resized = cv2.resize(bgr, (int(width*ratio), int(height*ratio)), interpolation=cv2.INTER_LINEAR).astype(np.uint8)
    padded[:int(height*ratio), :int(width*ratio)] = resized
    tensor = np.ascontiguousarray(padded.transpose(2, 0, 1), dtype=np.float32)[None]
    session = ort.InferenceSession(MODEL, providers=['CPUExecutionProvider'])
    output = session.run(None, {'images': tensor})[0]
    detections = reference_postprocess(output, height, width, manifest['labels'])
    config = {key: manifest[key] for key in ('input', 'output', 'labels', 'preprocess', 'postprocess', 'runtime')}
    provenance = dict(model_id=manifest['model_id'], model_sha256=manifest['artifact']['sha256'],
                      config_sha256=hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                      runtime=dict(name='onnxruntime', version=ort.__version__), provider='CPUExecutionProvider')
    return dict(detection_status='ok' if detections else 'ok_empty', detections=detections, provenance=provenance,
                transform=dict(original_size=[height,width], model_size=[416,416], scale=ratio, pad=[0,0]))


def fixture_pixels() -> dict[str, Any]:
    import cv2
    import numpy as np
    rgb = cv2.imread('data/oracle/shibuya_people.jpg')[:, :, ::-1].copy()
    return {'shibuya_original': rgb, 'shibuya_lower_center': rgb[757:2272, 426:1278].copy(),
            'authored_black': np.zeros((480, 640, 3), dtype=np.uint8)}


def golden_pins() -> dict[str, Any]:
    import hashlib
    import json
    import platform
    from pathlib import Path
    from importlib.metadata import version
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return dict(model_sha256=digest(MODEL), manifest_sha256=digest(MANIFEST),
                original_sha256=digest('data/oracle/shibuya_people.jpg'),
                reference_sources=json.loads(Path('fixtures/oracle/reference-sources.json').read_text()),
                implementation_sha256=digest(__file__),
                runtime=dict(python=platform.python_version(), numpy=version('numpy'),
                             onnxruntime=version('onnxruntime'), opencv=version('opencv-python-headless')))


POLICY = dict(candidate='>0.1', final='>=0.3', nms=.45, inclusive_pixel_offset=1,
              ties='NumPy1.26.4 argsort default reversed', canonical='clip after NMS; sort(-score,class_id,*bbox)',
              bbox_atol=1e-3, score_atol=1e-6)


def record_golden() -> None:
    import hashlib
    import json
    from pathlib import Path
    entries = {}
    for name, rgb in fixture_pixels().items():
        entries[name] = dict(rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(), shape=list(rgb.shape),
                             batch=reference_batch(rgb))
    golden = dict(schema_version=1, pins=golden_pins(), fixtures=entries,
                  policy=POLICY)
    Path(GOLDEN).write_text(json.dumps(golden, indent=2, allow_nan=False)+'\n')


def check_golden() -> dict[str, Any]:
    import hashlib
    import json
    from pathlib import Path
    from time import perf_counter
    from apps.edge.oracle_detector import OracleDetector
    golden = json.loads(Path(GOLDEN).read_text())
    if golden['schema_version'] != 1 or golden['pins'] != golden_pins() or golden['policy'] != POLICY:
        raise ValueError('golden provenance mismatch')
    detector = OracleDetector(MANIFEST, MODEL)
    report = {}
    for name, rgb in fixture_pixels().items():
        expected = golden['fixtures'][name]
        if expected['rgb_sha256'] != hashlib.sha256(rgb.tobytes()).hexdigest() or expected['shape'] != list(rgb.shape):
            raise ValueError('fixture provenance mismatch')
        compare_batch(expected['batch'], reference_batch(rgb))
        started = perf_counter()
        actual = detector.detect(rgb, FRAME)
        compare_batch(expected['batch'], actual)
        report[name] = dict(status=actual['detection_status'], count=len(actual['detections']),
                            person_count=sum(d['label'] == 'person' for d in actual['detections']),
                            elapsed_ms=(perf_counter()-started)*1000, timings=actual['timings'])
    return report


def main() -> None:
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true', help='Explicitly regenerate from independent reference')
    args = parser.parse_args()
    try:
        if args.record:
            record_golden()
        print(json.dumps(check_golden(), indent=2, allow_nan=False))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f'oracle conformance failed: {error}\n')


if __name__ == '__main__':
    main()
