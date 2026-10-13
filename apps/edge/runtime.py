"""Independent file recorder and detector-only CPU replay lifecycle.

Budgets are configurable lab conveniences, not capacity or recovery guarantees.
"""
from contextlib import closing
from copy import deepcopy
import math
import json
import socket
import struct
import multiprocessing as mp
import os
from pathlib import Path
import queue
import signal
import time
from typing import Any

from apps.edge.recorder import FileRecorder, Segment


class _Sender:
    def __init__(self, channel: socket.socket, *, acknowledged: bool = False) -> None:
        self.socket = channel
        self.acknowledged = acknowledged

    def put(self, value: Any) -> None:
        payload = json.dumps(value, allow_nan=False, separators=(',', ':')).encode()
        if len(payload) > 4 * 1024 * 1024:
            raise ValueError('transport message exceeds 4MiB lab bound')
        if not self.acknowledged and len(payload) > 4096:
            raise ValueError('status transport exceeds 4KiB bound')
        self.socket.sendall(struct.pack('!I', len(payload)) + payload)
        if self.acknowledged and self.socket.recv(1) != b'a':
            raise InterruptedError('observation transport closed')

    def cancel_join_thread(self) -> None:
        pass


class _Receiver:
    def __init__(self, channel: socket.socket, *, acknowledged: bool = False) -> None:
        self.socket = channel
        self.socket.setblocking(False)
        self.acknowledged = acknowledged
        self.buffer = bytearray()
        self.eof = False

    def get_nowait(self) -> Any:
        # Incremental reads never wait for a frame remainder, even if its writer dies.
        for _ in range(65):
            if len(self.buffer) >= 4:
                count = struct.unpack('!I', self.buffer[:4])[0]
                if count > (4 * 1024 * 1024 if self.acknowledged else 4096):
                    raise ValueError('transport message exceeds bound')
                if len(self.buffer) >= count + 4:
                    payload = bytes(self.buffer[4:count + 4])
                    del self.buffer[:count + 4]
                    value = json.loads(payload)
                    if self.acknowledged:
                        try:
                            self.socket.send(b'a')
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    return value
            try:
                data = self.socket.recv(65536)
            except (BlockingIOError, ConnectionResetError):
                break
            if not data:
                self.eof = True
                break
            self.buffer.extend(data)
        raise queue.Empty

    def close(self) -> None:
        self.socket.close()
        self.buffer.clear()


def _channel() -> tuple[_Receiver, _Sender]:
    parent, child = socket.socketpair()
    return _Receiver(parent), _Sender(child)


def _recorder_worker(values: dict[str, Any], messages: Any) -> None:
    os.setsid()

    def cancel(signum: int, frame: Any) -> None:
        raise InterruptedError('recording stopped')

    signal.signal(signal.SIGTERM, cancel)
    try:
        recorder = FileRecorder(values['output_dir'], values['ring_seconds'],
                                probe_timeout_seconds=values['io_timeout_seconds'])
        messages.put(('running', None))
        with recorder.ingest(values['source'], values['session_id'], values['segment_seconds']):
            pass
        messages.put(('completed', None))
    except InterruptedError:
        messages.put(('stopped', None))
    except Exception as error:
        messages.put(('failed', type(error).__name__))


def _analytics_worker(values: dict[str, Any], messages: Any, observations: Any) -> None:
    os.setsid()

    def cancel(signum: int, frame: Any) -> None:
        raise InterruptedError('analytics stopped')

    signal.signal(signal.SIGTERM, cancel)
    try:
        from apps.edge.oracle_detector import OracleDetector
        from apps.edge.oracle_replay import iter_video_frames, _sha256
        paths = {name: values[name] for name in ('source', 'manifest_path', 'model_path')}
        fingerprints = {name: _sha256(path) for name, path in paths.items()}
        detector = OracleDetector(values['manifest_path'], values['model_path'],
                                  environment=values['environment'], expected_artifact=values['expected_artifact'])
        messages.put(('running', None))
        failed = False
        with closing(iter_video_frames(values['source'], sample_fps=values['sample_fps'],
                                       mode=values['mode'], camera_id=values['camera_id'],
                                       session_id=values['session_id'],
                                       timeout_seconds=values['io_timeout_seconds'])) as frames:
            for rgb, frame in frames:
                observation = detector.detect(rgb, frame)
                if observation.get('provenance', {}).get('model_sha256') != fingerprints['model_path']:
                    raise RuntimeError('model provenance changed')
                observations.put(observation)
                if observation['detection_status'] == 'failed' and not failed:
                    failed = True
                    messages.put(('failed', 'failed observation'))
        if any(_sha256(path) != fingerprints[name] for name, path in paths.items()):
            raise RuntimeError('input changed during replay')
        messages.put(('failed' if failed else 'completed', 'failed observation' if failed else None))
    except InterruptedError:
        # Explicit cancellation abandons unconsumed transport, never normal replay.
        observations.cancel_join_thread()
        messages.put(('stopped', None))
    except Exception as error:
        messages.put(('failed', type(error).__name__))


class EdgeRuntime:
    def __init__(self, *, source: str | Path, output_dir: str | Path,
                 camera_id: str = 'lab-camera', session_id: str = 'lab-replay',
                 analytics_enabled: bool = True, disabled_reason: str | None = None,
                 manifest_path: str | Path | None = None, model_path: str | Path | None = None,
                 sample_fps: float = 2, mode: str = 'fast', segment_seconds: float = 2,
                 ring_seconds: float = 600, queue_capacity: int = 8, observation_capacity: int = 64,
                 stop_timeout_seconds: float = 3, io_timeout_seconds: float = 30,
                 environment: str = 'lab', expected_artifact: dict[str, Any] | None = None) -> None:
        for name, value in (('sample_fps', sample_fps), ('segment_seconds', segment_seconds),
                            ('ring_seconds', ring_seconds), ('stop_timeout_seconds', stop_timeout_seconds),
                            ('io_timeout_seconds', io_timeout_seconds)):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        for value in (queue_capacity, observation_capacity):
            if type(value) is not int or value < 1:
                raise ValueError('capacities must be positive integers')
        if mode != 'fast':
            raise ValueError('EdgeRuntime supports fast file replay only; realtime recorder continuity is unverified')
        if not camera_id or not session_id:
            raise ValueError('invalid replay identity')
        if type(analytics_enabled) is not bool or (not analytics_enabled and not disabled_reason):
            raise ValueError('disabled analytics requires explicit reason')
        source = Path(source).resolve()
        if not source.is_file():
            raise ValueError('runtime source must be an existing local file')
        self._values: dict[str, Any] = dict(source=str(source), output_dir=str(output_dir), camera_id=camera_id,
                            session_id=session_id, manifest_path=manifest_path, model_path=model_path,
                            sample_fps=sample_fps, mode=mode, segment_seconds=segment_seconds,
                            ring_seconds=ring_seconds, io_timeout_seconds=io_timeout_seconds,
                            environment=environment, expected_artifact=deepcopy(expected_artifact))
        self._ring = FileRecorder(output_dir, ring_seconds, probe_timeout_seconds=io_timeout_seconds)
        self._context = mp.get_context('spawn')
        self._recorder_messages, self._recorder_sender = _channel()
        self._analytics_messages, self._analytics_sender = _channel()
        self._observation_messages, self._observation_sender = _channel()
        self._observation_messages.acknowledged = True
        self._observation_sender.acknowledged = True
        self._recorder: Any = None
        self._analytics: Any = None
        self._recorder_state = 'not_started'
        self._analytics_state = 'not_started' if analytics_enabled else 'disabled'
        self._reason = disabled_reason
        self._recorder_error: str | None = None
        self._analytics_error: str | None = None
        self._stop_budget = stop_timeout_seconds
        self._queue_capacity = queue_capacity
        self._retention = observation_capacity
        self._observations: list[dict[str, Any]] = []
        self._started = False
        self._analytics_cancelled = False
        self._transport_closed = False
        self._closed = False
        self._pids: dict[str, int | None] = {'recorder': None, 'analytics': None}
        self._cleaned: set[int] = set()

    def start(self) -> 'EdgeRuntime':
        if self._started:
            raise RuntimeError('runtime already started')
        self._started = True
        self._recorder_state = 'starting'
        self._recorder = self._context.Process(target=_recorder_worker,
                                               args=(self._values, self._recorder_sender))
        self._recorder.start()
        self._pids['recorder'] = self._recorder.pid
        self._recorder_sender.socket.close()
        if self._analytics_state != 'disabled':
            self._analytics_state = 'starting'
            self._analytics = self._context.Process(target=_analytics_worker,
                                                    args=(self._values, self._analytics_sender,
                                                          self._observation_sender))
            try:
                self._analytics.start()
                self._pids['analytics'] = self._analytics.pid
                self._analytics_sender.socket.close()
                self._observation_sender.socket.close()
            except Exception as error:
                self._analytics_state, self._analytics_error = 'failed', type(error).__name__
        return self

    def _refresh(self) -> None:
        if self._closed:
            return
        while not self._transport_closed and len(self._observations) < self._retention:
            try:
                self._observations.append(self._observation_messages.get_nowait())
            except queue.Empty:
                break
        while True:
            try:
                self._recorder_state, self._recorder_error = self._recorder_messages.get_nowait()
            except queue.Empty:
                break
        if self._recorder is not None and not self._recorder.is_alive():
            self._cleanup_descendants(self._recorder)
            self._recorder.join(0)
            if self._recorder_state in ('starting', 'running'):
                # Queue feeder may deliver its terminal message just after process exit.
                try:
                    self._recorder_state, self._recorder_error = self._recorder_messages.get_nowait()
                except queue.Empty:
                    self._recorder_state, self._recorder_error = 'failed', 'recorder exited without outcome'

        while True:
            try:
                self._analytics_state, self._analytics_error = self._analytics_messages.get_nowait()
            except queue.Empty:
                break
        if self._analytics is not None and self._analytics.pid is not None and not self._analytics.is_alive():
            self._cleanup_descendants(self._analytics)
            self._analytics.join(0)
            if self._analytics_state in ('starting', 'running'):
                try:
                    self._analytics_state, self._analytics_error = self._analytics_messages.get_nowait()
                except queue.Empty:
                    self._analytics_state, self._analytics_error = 'failed', 'analytics exited without outcome'

    def status(self) -> dict[str, Any]:
        self._refresh()
        running = (self._recorder_state in ('not_started', 'starting', 'running')
                   or self._analytics_state in ('not_started', 'starting', 'running')
                   or bool(self._recorder and self._recorder.is_alive())
                   or bool(self._analytics and self._analytics.is_alive()))
        failed = self._recorder_state == 'failed' or self._analytics_state == 'failed'
        return {'origin': 'replay', 'camera_id': self._values['camera_id'],
                'stream_session_id': self._values['session_id'],
                'outcome': 'running' if running else ('failed' if failed else 'ok'),
                'degraded': failed,
                'recorder': {'state': self._recorder_state, 'error': self._recorder_error,
                             'pid': self._pids['recorder'],
                             'alive': bool(self._recorder and self._recorder.is_alive())},
                'analytics': {'state': self._analytics_state, 'error': self._analytics_error,
                              'reason': self._reason, 'pid': self._pids['analytics'],
                              'alive': bool(self._analytics and self._analytics.is_alive())},
                'queue_capacity': self._queue_capacity, 'transport_inflight_bound': 1,
                'transport_message_bytes': 4 * 1024 * 1024, 'observations_retained': len(self._observations)}

    def wait(self, timeout_seconds: float | None = None) -> dict[str, Any]:
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        while True:
            status = self.status()
            if status['outcome'] != 'running':
                return status
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('runtime wait deadline exceeded')
            time.sleep(.01)

    def stop_analytics(self) -> dict[str, Any]:
        self._refresh()
        if self._analytics is not None and self._analytics.is_alive():
            self._analytics_cancelled = True
            failed = self._analytics_state == 'failed'
            deadline = time.monotonic() + self._stop_budget
            self._analytics.terminate()
            self._analytics.join(max(0, deadline - time.monotonic() - min(.1, self._stop_budget / 2)))
            if self._analytics.is_alive():
                self._kill_group(self._analytics)
                self._analytics.join(max(0, deadline - time.monotonic()))
            self._transport_closed = True
            self._refresh()
            self._analytics_state = 'failed' if failed else 'stopped'
            self._reason = 'explicit stop; unconsumed observations may be incomplete'
            if self._analytics.is_alive():
                self._analytics_state = 'failed'
                self._analytics_error = 'stop deadline exceeded; child may require external reaping'
            # A killed queue writer can leave a partial pickle. Do not read it after cancellation.
            self._transport_closed = True
            self._observation_messages.close()
        return self.status()

    @staticmethod
    def _kill_group(process: Any) -> None:
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass

    def stop(self) -> dict[str, Any]:
        self.stop_analytics()
        if self._recorder is not None and self._recorder.is_alive():
            self._recorder.terminate()
            self._recorder.join(self._stop_budget)
            if self._recorder.is_alive():
                self._kill_group(self._recorder)
                self._recorder.join(.1)
                self._recorder_state = 'failed'
                self._recorder_error = 'stop deadline exceeded; storage publication may be incomplete'
        snapshot = self.status()
        if not snapshot['recorder']['alive'] and not snapshot['analytics']['alive']:
            self._close()
        return snapshot

    def _close(self) -> None:
        if self._closed:
            return
        for receiver in (self._recorder_messages, self._analytics_messages, self._observation_messages):
            receiver.close()
        for sender in (self._recorder_sender, self._analytics_sender, self._observation_sender):
            sender.socket.close()
        for process in (self._recorder, self._analytics):
            if process is not None and process.pid is not None:
                process.close()
        self._recorder = self._analytics = None
        self._closed = True

    def _cleanup_descendants(self, process: Any) -> None:
        if process.pid in self._cleaned:
            return
        # Run only at worker exit. pidfds bind each signal to captured process identity.
        # Orphans are not our children: OS init owns their zombie reaping, not waitpid here.
        for stat in Path('/proc').glob('[0-9]*/stat'):
            try:
                fields = stat.read_text().rsplit(') ', 1)[1].split()
                pid = int(stat.parent.name)
                if int(fields[3]) != process.pid or pid == process.pid:
                    continue
                start = fields[19]
                fd = os.pidfd_open(pid)
                try:
                    current = stat.read_text().rsplit(') ', 1)[1].split()
                    if current[19] == start and int(current[3]) == process.pid:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                finally:
                    os.close(fd)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
        self._cleaned.add(process.pid)

    def segments(self) -> list[Segment]:
        return self._ring.segments(self._values['session_id'])

    def actual_range(self, start: float, end: float) -> dict[str, Any]:
        return self._ring.actual_range(self._values['session_id'], start, end)

    def observations(self) -> list[dict[str, Any]]:
        self._refresh()
        result, self._observations = self._observations, []
        return deepcopy(result)
