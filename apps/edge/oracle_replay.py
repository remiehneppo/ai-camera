"""Software pixel replay for the lab oracle; no live or notification path."""
import argparse
from contextlib import closing
from collections.abc import Generator
from typing import Any
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be finite and positive')


def _read_bytes(process, count, timeout):
    data = bytearray()
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while len(data) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise RuntimeError('decoder timed out')
            chunk = os.read(process.stdout.fileno(), min(count - len(data), 65536))
            if not chunk:
                break
            data.extend(chunk)
    return data


def iter_video_frames(source: str | Path, *, sample_fps: float = 2, mode: str = 'fast',
                      camera_id: str = 'lab-camera', session_id: str = 'lab-replay',
                      timeout_seconds: float = 30) -> Generator[tuple[Any, dict[str, Any]], None, None]:
    """Yield (owned RGB array, metadata) using actual PTS and bounded pixel memory.

    Timestamp inventory is disk-spooled; only one decoded frame is retained here.
    A stalled probe or decoder raises, never masquerading as a negative detection.
    """
    _positive(sample_fps, 'sample_fps')
    _positive(timeout_seconds, 'timeout_seconds')
    if mode not in ('fast', 'realtime'):
        raise ValueError('mode must be fast or realtime')
    if not isinstance(camera_id, str) or not camera_id or not isinstance(session_id, str) or not session_id:
        raise ValueError('camera and session identity required')
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    import numpy as np
    try:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                '-show_entries', 'stream=width,height,time_base', '-of', 'json', str(source)],
                               capture_output=True, timeout=timeout_seconds, check=True)
        stream = json.loads(probe.stdout)['streams'][0]
        width, height = int(stream['width']), int(stream['height'])
        time_base = Fraction(stream['time_base'])
        if width <= 0 or height <= 0 or width * height > 33554432 or time_base <= 0:
            raise ValueError('invalid video dimensions/timebase')
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError) as error:
        raise RuntimeError(f'video probe failed: {error}') from error
    with tempfile.TemporaryFile() as timestamps, tempfile.TemporaryFile() as errors:
        try:
            subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
                            '-show_entries', 'frame=pts,width,height', '-of', 'compact=p=0:nk=0', str(source)],
                           stdout=timestamps, stderr=errors, timeout=timeout_seconds, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f'timestamp probe failed: {error}') from error
        timestamps.seek(0)
        try:
            process = subprocess.Popen(['ffmpeg', '-v', 'error', '-nostdin', '-threads', '1',
                                        '-i', str(source), '-map', '0:v:0', '-vsync', '0',
                                        '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'],
                                       stdout=subprocess.PIPE, stderr=errors)
        except OSError as error:
            raise RuntimeError(f'decoder start failed: {error}') from error
        assert process.stdout is not None
        previous = None
        next_sample = None
        first_time = 0.0
        wall_start = time.monotonic()
        frame_count = 0
        try:
            for line in timestamps:
                fields = dict(field.split('=', 1) for field in line.decode().strip().split('|') if '=' in field)
                if not fields:
                    continue
                try:
                    pts = int(fields['pts'])
                except (KeyError, ValueError) as error:
                    raise RuntimeError('missing or invalid frame PTS') from error
                if previous is not None and pts <= previous:
                    raise RuntimeError('frame PTS must increase; discontinuity unsupported')
                previous = pts
                if int(fields.get('width', 0)) != width or int(fields.get('height', 0)) != height:
                    raise RuntimeError('dynamic frame dimensions unsupported')
                pixels = _read_bytes(process, width * height * 3, timeout_seconds)
                if len(pixels) != width * height * 3:
                    raise RuntimeError('decoder/PTS mismatch: truncated frame')
                frame_count += 1
                event_time = float(pts * time_base)
                if next_sample is None:
                    first_time = event_time
                    next_sample = event_time
                if event_time + 1e-9 < next_sample:
                    continue
                if mode == 'realtime':
                    time.sleep(max(0, wall_start + event_time - first_time - time.monotonic()))
                rgb = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 3).copy()
                frame = {'camera_id': camera_id, 'stream_session_id': session_id, 'session_id': session_id,
                         'frame_id': frame_count - 1, 'pts': pts, 'time_base': str(time_base),
                         'event_time': event_time, 'width': width, 'height': height,
                         'pixel_format': 'rgb24', 'core_epoch': 1, 'origin': 'replay'}
                yield rgb, frame
                next_sample = event_time + 1 / sample_fps
            if not frame_count:
                raise RuntimeError('video has no timestamped frames')
            if _read_bytes(process, 1, timeout_seconds):
                raise RuntimeError('decoder/PTS mismatch: extra pixels')
            if process.wait(timeout=timeout_seconds) != 0:
                raise RuntimeError('decoder failed')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=timeout_seconds)
            process.stdout.close()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run_oracle(source: str | Path, manifest_path: str | Path, model_path: str | Path, *,
               sample_fps: float = 2, mode: str = 'fast', camera_id: str = 'lab-camera',
               session_id: str = 'lab-replay', timeout_seconds: float = 30) -> dict[str, Any]:
    _positive(sample_fps, 'sample_fps')
    _positive(timeout_seconds, 'timeout_seconds')
    if mode not in ('fast', 'realtime'):
        raise ValueError('mode must be fast or realtime')
    if not Path(source).is_file():
        raise FileNotFoundError(source)
    paths = {'source': source, 'manifest': manifest_path, 'model': model_path}
    fingerprints = {name: _sha256(path) for name, path in paths.items()}
    from apps.edge.oracle_detector import OracleDetector
    detector = OracleDetector(manifest_path, model_path, environment='lab')
    observations = []
    with closing(iter_video_frames(source, sample_fps=sample_fps, mode=mode,
                                  camera_id=camera_id, session_id=session_id,
                                  timeout_seconds=timeout_seconds)) as frames:
        for rgb, frame in frames:
            observation = detector.detect(rgb, frame)
            if observation.get('provenance', {}).get('model_sha256') != fingerprints['model']:
                raise RuntimeError('detector model provenance differs from captured model fingerprint')
            observations.append(observation)
    for name, path in paths.items():
        try:
            unchanged = _sha256(path) == fingerprints[name]
        except OSError as error:
            raise RuntimeError(f'{name} changed during replay') from error
        if not unchanged:
            raise RuntimeError(f'{name} changed during replay')
    failed = any(item['detection_status'] == 'failed' for item in observations)
    return {'schema_version': 1, 'origin': 'replay', 'status': 'failed' if failed else 'ok',
            'source_sha256': fingerprints['source'], 'manifest_sha256': fingerprints['manifest'],
            'model_sha256': fingerprints['model'], 'sample_fps': sample_fps, 'mode': mode,
            'camera_id': camera_id, 'stream_session_id': session_id, 'observations': observations,
            'limitations': ['before/after content fingerprints detect changes, not immutable file handles',
                            'disk-spooled timestamp inventory; materialized observation report',
                            'detector-only lab oracle, not an application PerceptionPipeline',
                            'no tracking, pose, native parity, hardware or target acceptance']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--sample-fps', type=float, default=2)
    parser.add_argument('--mode', choices=('fast', 'realtime'), default='fast')
    parser.add_argument('--camera-id', default='lab-camera')
    parser.add_argument('--session-id', default='lab-replay')
    args = parser.parse_args()
    try:
        report = run_oracle(args.video, args.manifest, args.model, sample_fps=args.sample_fps,
                            mode=args.mode, camera_id=args.camera_id, session_id=args.session_id)
        serialized = json.dumps(report, allow_nan=False)
    except (ValueError, RuntimeError, OSError, ImportError, TypeError) as error:
        parser.exit(1, f'oracle replay failed: {error}\n')
    print(serialized)
    if report['status'] == 'failed':
        parser.exit(1)


if __name__ == '__main__':
    main()
