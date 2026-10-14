import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
class EdgeRuntimeTests(unittest.TestCase):
    def video(self, directory, seconds=1):
        source = Path(directory) / 'source.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=red:s=32x24:r=4', '-t', str(seconds), '-c:v', 'ffv1', '-g', '1',
                        str(source)], check=True, capture_output=True)
        return source

    def test_disabled_analytics_records_real_raw_ring_and_missing_range_is_not_negative(self):
        from apps.edge.runtime import EdgeRuntime
        with tempfile.TemporaryDirectory() as directory:
            runtime = EdgeRuntime(source=self.video(directory), output_dir=Path(directory) / 'ring',
                                  analytics_enabled=False, disabled_reason='operator disabled',
                                  session_id='session', segment_seconds=.5)
            self.assertEqual(runtime.actual_range(0, 1)['completeness'], 'missing')
            runtime.start()
            status = runtime.wait(timeout_seconds=10)
            self.assertEqual(status['outcome'], 'ok')
            self.assertEqual(status['analytics']['state'], 'disabled')
            self.assertEqual(status['analytics']['reason'], 'operator disabled')
            self.assertEqual(status['recorder']['state'], 'completed')
            self.assertGreaterEqual(len(runtime.segments()), 2)
            self.assertEqual(runtime.actual_range(0, .75)['completeness'], 'complete')
            self.assertFalse(status['recorder']['alive'])
            runtime.stop()

    def test_analytics_startup_failure_does_not_unwind_recording(self):
        from apps.edge.runtime import EdgeRuntime
        with tempfile.TemporaryDirectory() as directory:
            runtime = EdgeRuntime(source=self.video(directory), output_dir=Path(directory) / 'ring',
                                  manifest_path=Path(directory) / 'missing.json',
                                  model_path=Path(directory) / 'missing.onnx', segment_seconds=.5)
            try:
                runtime.start()
                status = runtime.wait(timeout_seconds=10)
                self.assertEqual(status['analytics']['state'], 'failed')
                self.assertTrue(status['analytics']['error'])
                self.assertIsNotNone(status['analytics']['pid'])
                self.assertNotEqual(status['analytics']['pid'], status['recorder']['pid'])
                self.assertFalse(status['analytics']['alive'])
                self.assertEqual(status['outcome'], 'failed')
                self.assertTrue(status['degraded'])
                self.assertEqual(status['recorder']['state'], 'completed')
                self.assertEqual(runtime.actual_range(0, .75)['completeness'], 'complete')
            finally:
                runtime.stop()

    @unittest.skipUnless(Path('data/oracle/yolox_tiny.onnx').is_file(), 'requires real cleared oracle asset')
    def test_real_ort_observations_preserve_pts_provenance_without_drops(self):
        import time
        from apps.edge.runtime import EdgeRuntime
        with tempfile.TemporaryDirectory() as directory:
            runtime = EdgeRuntime(source=self.video(directory, seconds=1.5),
                                  output_dir=Path(directory) / 'ring', camera_id='camera', session_id='session',
                                  manifest_path='models/yolox-tiny/manifest.json',
                                  model_path='data/oracle/yolox_tiny.onnx', sample_fps=4,
                                  queue_capacity=1, observation_capacity=1, segment_seconds=.5)
            try:
                runtime.start()
                received = []
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    status = runtime.status()
                    self.assertLessEqual(status['observations_retained'], 1)
                    received.extend(runtime.observations())
                    if status['outcome'] != 'running':
                        break
                    time.sleep(.01)
                final = runtime.wait(timeout_seconds=5)
                received.extend(runtime.observations())
                self.assertEqual(final['outcome'], 'ok')
                self.assertEqual(final['analytics']['state'], 'completed')
                self.assertEqual([item['event_time'] for item in received], [0, .25, .5, .75, 1, 1.25])
                self.assertEqual([item['frame_id'] for item in received], list(range(6)))
                for item in received:
                    self.assertIn(item['detection_status'], ('ok', 'ok_empty'))
                    self.assertEqual(item['origin'], 'replay')
                    self.assertEqual(item['camera_id'], 'camera')
                    self.assertEqual(item['stream_session_id'], 'session')
                    self.assertEqual(item['provenance']['provider'], 'CPUExecutionProvider')
                    self.assertEqual(item['provenance']['model_sha256'],
                                     __import__('json').loads(Path('models/yolox-tiny/manifest.json').read_text())['artifact']['sha256'])
            finally:
                runtime.stop()

    @unittest.skipUnless(Path('data/oracle/yolox_tiny.onnx').is_file(), 'requires real cleared oracle asset')
    def test_slow_consumer_backpressure_can_stop_analytics_without_stopping_recorder(self):
        import time
        from apps.edge.runtime import EdgeRuntime
        with tempfile.TemporaryDirectory() as directory:
            runtime = EdgeRuntime(source=self.video(directory, seconds=4), output_dir=Path(directory) / 'ring',
                                  manifest_path='models/yolox-tiny/manifest.json',
                                  model_path='data/oracle/yolox_tiny.onnx', sample_fps=4,
                                  queue_capacity=1, observation_capacity=1, stop_timeout_seconds=.5)
            try:
                runtime.start()
                with self.assertRaises(TimeoutError):
                    runtime.wait(timeout_seconds=1.5)
                status = runtime.status()
                self.assertEqual(status['observations_retained'], 1)
                self.assertTrue(status['analytics']['alive'])
                self.assertEqual(status['recorder']['state'], 'completed')
                started = time.monotonic()
                stopped = runtime.stop_analytics()
                self.assertLess(time.monotonic() - started, 1)
                self.assertFalse(stopped['analytics']['alive'])
                self.assertEqual(stopped['analytics']['state'], 'stopped')
                self.assertEqual(stopped['recorder']['state'], 'completed')
                self.assertEqual(runtime.wait(timeout_seconds=2)['outcome'], 'ok')
                self.assertTrue(runtime.segments())
            finally:
                # Test-only emergency cleanup lets the RED stub fail without orphaning a blocked worker.
                import os
                import signal
                status = runtime.status()
                if status['analytics']['alive']:
                    os.killpg(status['analytics']['pid'], signal.SIGKILL)
                runtime.stop()

    def test_realtime_mode_is_explicitly_rejected_not_silently_unpaced(self):
        from apps.edge.runtime import EdgeRuntime
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'fast file replay only'):
                EdgeRuntime(source=self.video(directory), output_dir=Path(directory) / 'ring',
                            analytics_enabled=False, disabled_reason='operator disabled', mode='realtime')
            self.assertFalse((Path(directory) / 'ring').exists())


def partial_transport_worker(values, messages, observations):
    """Explicit test-only worker: leave a declared large result frame incomplete."""
    import os
    import struct
    import time
    os.setsid()
    messages.put(('running', None))
    if hasattr(observations, 'socket'):
        observations.socket.sendall(struct.pack('!I', 100000) + b'{')
    else:
        os.write(observations._writer.fileno(), struct.pack('!i', 100000) + b'{')
    time.sleep(.1)
    os._exit(9)


class RuntimeCrashTests(unittest.TestCase):
    video = EdgeRuntimeTests.video
    def test_partial_result_worker_death_does_not_block_public_supervisor(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            source = self.video(directory)
            program = """
import time
from unittest.mock import patch
from test_edge_runtime import partial_transport_worker
from apps.edge.runtime import EdgeRuntime
with patch('apps.edge.runtime._analytics_worker', partial_transport_worker):
    runtime = EdgeRuntime(source=SOURCE, output_dir=ROOT, stop_timeout_seconds=.5)
    runtime.start()
    time.sleep(.05)
    final = runtime.wait(timeout_seconds=3)
    assert final['outcome'] == 'failed', final
    assert final['recorder']['state'] == 'completed', final
    runtime.stop()
""".replace('SOURCE', repr(str(source))).replace('ROOT', repr(str(Path(directory) / 'ring')))
            result = subprocess.run([sys.executable, '-c', program], env={**__import__('os').environ,
                                    'PYTHONPATH': 'tests:.'}, capture_output=True, text=True, timeout=6)
            self.assertEqual(result.returncode, 0, result.stderr)


def descendant_worker(values, messages, observations):
    """Test-only crash leaves an actual FFmpeg child in the owned session."""
    import os
    import time
    os.setsid()
    child = subprocess.Popen(['ffmpeg', '-v', 'error', '-re', '-f', 'lavfi', '-i',
                              'color=s=16x16:r=2', '-t', '30', '-f', 'null', '-'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Path(values['output_dir'], 'descendant.pid').write_text(str(child.pid))
    messages.put(('running', None))
    time.sleep(.1)
    os._exit(9)


class RuntimeCleanupTests(unittest.TestCase):
    video = EdgeRuntimeTests.video

    def test_dead_worker_owned_ffmpeg_is_terminated_without_touching_unrelated_child(self):
        import os
        import sys
        import time
        from unittest.mock import patch
        from apps.edge.runtime import EdgeRuntime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'ring'
            unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
            runtime = EdgeRuntime(source=self.video(directory), output_dir=root, stop_timeout_seconds=.5)
            try:
                with patch('apps.edge.runtime._analytics_worker', descendant_worker):
                    runtime.start()
                final = runtime.wait(timeout_seconds=5)
                pid = int((root / 'descendant.pid').read_text())
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    stat = Path(f'/proc/{pid}/stat')
                    if not stat.exists() or stat.read_text().split(') ')[1].split()[0] == 'Z':
                        break
                    time.sleep(.02)
                else:
                    self.fail('owned FFmpeg survived worker death')
                self.assertEqual(final['outcome'], 'failed')
                self.assertIsNone(unrelated.poll())
                runtime.stop()
            finally:
                if (root / 'descendant.pid').exists():
                    try: os.kill(int((root / 'descendant.pid').read_text()), 9)
                    except ProcessLookupError: pass
                unrelated.kill()
                unrelated.wait()
                runtime.stop()

    def test_immediate_tiny_budget_stop_is_safe_and_idempotent(self):
        from apps.edge.runtime import EdgeRuntime
        with tempfile.TemporaryDirectory() as directory:
            runtime = EdgeRuntime(source=self.video(directory), output_dir=Path(directory) / 'ring',
                                  analytics_enabled=False, disabled_reason='operator', stop_timeout_seconds=.001)
            runtime.start()
            runtime.stop()
            runtime.stop()

    def test_startup_reconciles_evidence_outbox_before_analytics_worker_starts(self):
        from apps.edge.runtime import EdgeRuntime
        from apps.edge.outbox import EventOutbox
        from tests.test_event_delivery import event_fixture
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'events.sqlite3'
            outbox = EventOutbox(db_path)
            # Enqueue a valid event fixture
            event = event_fixture()
            outbox.enqueue(event)

            runtime = EdgeRuntime(
                source=self.video(directory),
                output_dir=Path(directory) / 'ring',
                outbox_path=db_path,
                analytics_enabled=False,
                disabled_reason='test',
            )
            # Reconcile hook should be executed during start() before workers start
            status = runtime.start().wait(timeout_seconds=5)
            self.assertEqual(status['outcome'], 'ok')
            reconcile_result = runtime.reconcile_result()
            self.assertIsNotNone(reconcile_result)
            self.assertIn('cleaned_files', reconcile_result)
            runtime.stop()

    @unittest.skipUnless(Path('data/oracle/yolox_tiny.onnx').is_file(), 'requires real cleared oracle asset')
    def test_graceful_drain_flushes_inflight_observations_before_forced_kill(self):
        import time
        from apps.edge.runtime import EdgeRuntime
        with tempfile.TemporaryDirectory() as directory:
            runtime = EdgeRuntime(
                source=self.video(directory, seconds=2),
                output_dir=Path(directory) / 'ring',
                manifest_path='models/yolox-tiny/manifest.json',
                model_path='data/oracle/yolox_tiny.onnx',
                sample_fps=4,
                queue_capacity=1,
                observation_capacity=1,
                stop_timeout_seconds=1.0,
                drain_timeout_seconds=0.5,
            )
            runtime.start()
            # Wait until at least one observation is produced by the analytics worker
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if runtime.status()['observations_retained'] > 0:
                    break
                time.sleep(0.01)

            # Test graceful drain via public stop_analytics lifecycle method
            stopped = runtime.stop_analytics()
            self.assertFalse(stopped['analytics']['alive'])
            self.assertEqual(stopped['analytics']['state'], 'stopped')
            obs = runtime.observations()
            self.assertGreaterEqual(len(obs), 1)
            for item in obs:
                self.assertIn(item['detection_status'], ('ok', 'ok_empty'))
            runtime.stop()

    def test_support_session_and_epoch_reset_upon_recovery_or_restart(self):
        from apps.edge.runtime import EdgeRuntime
        from apps.edge.outbox import EventOutbox
        from tests.test_event_delivery import event_fixture
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'events.sqlite3'
            outbox = EventOutbox(db_path)
            outbox.enqueue(event_fixture())

            runtime = EdgeRuntime(
                source=self.video(directory),
                output_dir=Path(directory) / 'ring',
                session_id='session-1',
                core_epoch=1,
                outbox_path=db_path,
                analytics_enabled=False,
                disabled_reason='test',
            )
            status = runtime.status()
            self.assertEqual(status['stream_session_id'], 'session-1')
            self.assertEqual(status['core_epoch'], 1)

            # Reset session and epoch
            runtime.reset_session(session_id='session-2', core_epoch=2)
            status2 = runtime.status()
            self.assertEqual(status2['stream_session_id'], 'session-2')
            self.assertEqual(status2['core_epoch'], 2)
            runtime.stop()

            # Recovery after stop/forced kill: start a fresh runtime with incremented epoch
            recovered = EdgeRuntime(
                source=self.video(directory),
                output_dir=Path(directory) / 'ring',
                session_id='session-2',
                core_epoch=2,
                outbox_path=db_path,
                analytics_enabled=False,
                disabled_reason='test',
            )
            recovered.start()
            reconcile_res = recovered.reconcile_result()
            self.assertIsNotNone(reconcile_res)
            self.assertIn('cleaned_files', reconcile_res)
            final = recovered.wait(timeout_seconds=5)
            self.assertEqual(final['outcome'], 'ok')
            self.assertEqual(final['core_epoch'], 2)
            self.assertEqual(final['stream_session_id'], 'session-2')
            recovered.stop()

    @unittest.skipUnless(Path('data/oracle/yolox_tiny.onnx').is_file(), 'requires real cleared oracle asset')
    def test_kill_or_hang_of_analytics_leaves_recorder_functional_and_status_degraded(self):
        import os
        import signal
        import time
        from apps.edge.runtime import EdgeRuntime
        with tempfile.TemporaryDirectory() as directory:
            runtime = EdgeRuntime(
                source=self.video(directory, seconds=3),
                output_dir=Path(directory) / 'ring',
                segment_seconds=0.5,
                analytics_enabled=True,
                manifest_path='models/yolox-tiny/manifest.json',
                model_path='data/oracle/yolox_tiny.onnx',
                sample_fps=4,
            )
            runtime.start()
            analytics_pid = runtime._pids['analytics']
            self.assertIsNotNone(analytics_pid)

            # Wait briefly to ensure both processes are running
            time.sleep(0.05)
            status_init = runtime.status()
            self.assertTrue(status_init['recorder']['alive'])
            self.assertTrue(status_init['analytics']['alive'])

            # Send SIGKILL to analytics process
            os.kill(analytics_pid, signal.SIGKILL)

            # Wait briefly for OS to terminate the killed process
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                status_after = runtime.status()
                if not status_after['analytics']['alive']:
                    break
                time.sleep(0.02)

            # Verify analytics process terminated while recorder process remains functional
            self.assertFalse(status_after['analytics']['alive'])
            self.assertEqual(status_after['analytics']['state'], 'failed')
            self.assertTrue(status_after['recorder']['alive'])
            self.assertTrue(status_after['degraded'])

            # Wait for recorder to complete producing segments
            final = runtime.wait(timeout_seconds=10)
            self.assertEqual(final['recorder']['state'], 'completed')
            self.assertEqual(final['analytics']['state'], 'failed')
            self.assertTrue(final['degraded'])
            self.assertFalse(final['analytics']['alive'])
            self.assertGreaterEqual(len(runtime.segments()), 2)

            # Verify status accurately reflects degraded state without falsely declaring healthy
            status = runtime.status()
            self.assertTrue(status['degraded'])
            self.assertEqual(status['outcome'], 'failed')
            self.assertEqual(status['analytics']['state'], 'failed')
            self.assertTrue(status['analytics']['error'])
            runtime.stop()

