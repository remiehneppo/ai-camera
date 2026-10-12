"""Detector-stage semantic replay with copied raw coverage; not domain/stress acceptance."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from apps.edge.oracle_replay import run_oracle
from apps.edge.recorder import FileRecorder


def _same_observation(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = ('camera_id', 'stream_session_id', 'core_epoch', 'origin', 'frame_id',
            'pts', 'time_base', 'event_time', 'detection_status', 'provenance', 'transform', 'error')
    if any(left.get(key) != right.get(key) for key in keys):
        return False
    if len(left['detections']) != len(right['detections']):
        return False
    for expected, actual in zip(left['detections'], right['detections']):
        if any(expected[key] != actual[key] for key in ('class_id', 'label')):
            return False
        if not math.isfinite(actual['score']) or abs(expected['score'] - actual['score']) > 1e-6:
            return False
        if len(expected['bbox_xyxy']) != 4 or len(actual['bbox_xyxy']) != 4:
            return False
        if any(not math.isfinite(b) or abs(a - b) > 1e-3
               for a, b in zip(expected['bbox_xyxy'], actual['bbox_xyxy'])):
            return False
    return True


def run_detector_recorder_lab(source: str | Path, manifest_path: str | Path,
                              model_path: str | Path, *, sample_fps: float = 2,
                              camera_id: str = 'lab-camera', session_id: str = 'lab-replay',
                              timeout_seconds: float = 30) -> dict[str, Any]:
    for name, value in (('sample_fps', sample_fps), ('timeout_seconds', timeout_seconds)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{name} must be finite and positive')
    if not isinstance(camera_id, str) or not camera_id or not isinstance(session_id, str) or not session_id:
        raise ValueError('camera and session identity required')
    with tempfile.TemporaryDirectory(prefix='oracle-recorder-lab-') as directory:
        runs: dict[str, Any] = {}
        for mode in ('fast', 'realtime'):
            recorder = FileRecorder(Path(directory) / mode)
            # Register consumer progress before recording so initial cleanup cannot outrun it.
            recorder.advance_watermark(session_id, -math.inf)
            segments = recorder.record_file(source, session_id)
            if not segments:
                raise ValueError('source has no recorded video segments')
            start = min(item.start_seconds for item in segments)
            end = max(item.end_seconds for item in segments)
            if end <= start:
                raise ValueError('source needs distinct video timestamps for raw coverage')
            coverage = recorder.actual_range(session_id, start, end)
            progress: list[float] = []
            unchanged = True

            def consume(observation: dict[str, Any]) -> None:
                nonlocal unchanged
                unchanged = (recorder.actual_range(session_id, start, end) == coverage) and unchanged
                progress.append(observation['event_time'])
                recorder.advance_watermark(session_id, observation['event_time'])

            oracle = run_oracle(source, manifest_path, model_path, sample_fps=sample_fps,
                                mode=mode, camera_id=camera_id, session_id=session_id,
                                timeout_seconds=timeout_seconds, observation_consumer=consume)
            runs[mode] = {'oracle': oracle, 'delivered_count': len(progress),
                          'failure_count': sum(o['detection_status'] == 'failed' for o in oracle['observations']),
                          'last_consumed_event_time': progress[-1] if progress else None,
                          'raw_query_count': len(progress), 'raw_coverage_unchanged': unchanged,
                          'raw_before_consumer': coverage,
                          'raw_after_consumer': recorder.actual_range(session_id, start, end)}
        fast, paced = runs['fast']['oracle'], runs['realtime']['oracle']
        identity = ('origin', 'camera_id', 'stream_session_id', 'source_sha256',
                    'manifest_sha256', 'model_sha256', 'sample_fps')
        parity = (all(fast[key] == paced[key] for key in identity)
                  and len(fast['observations']) == len(paced['observations'])
                  and all(_same_observation(a, b) for a, b in zip(fast['observations'], paced['observations'])))
        return {'schema_version': 1, 'scope': 'detector_recorder_semantic_lab', 'origin': 'replay',
                'status': 'ok' if parity and all(run['oracle']['status'] == 'ok' for run in runs.values()) else 'failed',
                'detector_semantic_parity': parity,
                'tolerances': {'bbox_absolute_pixels': 1e-3, 'score_absolute': 1e-6}, 'runs': runs,
                'limitations': ['not analytics/domain, tracking or pose parity',
                                'not realtime queue/drop stress or target capacity',
                                'raw fully recorded before inference; not concurrent ingest or crash isolation',
                                'consumer progress is observed, not persisted watermark evidence',
                                'temporary raw artifacts removed after report; observations materialized',
                                'lab authorization only; production model/data/privacy clearance unresolved',
                                'no notifications, RTSP, upload/playback or ticket 08 acceptance']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--sample-fps', type=float, default=2)
    args = parser.parse_args()
    try:
        report = run_detector_recorder_lab(args.video, args.manifest, args.model, sample_fps=args.sample_fps)
        print(json.dumps(report, allow_nan=False, sort_keys=True))
        return 0 if report['status'] == 'ok' else 1
    except (OSError, ValueError, RuntimeError, ImportError, TypeError, subprocess.SubprocessError) as error:
        print(f'detector recorder lab failed: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
