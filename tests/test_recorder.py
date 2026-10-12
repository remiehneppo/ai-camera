import json
import os
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Callable
from unittest import mock

from apps.edge.recorder import FileRecorder


class ExitedProducer:
    """A producer that is already gone: the publisher may only observe it, never signal it."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    def poll(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        raise AssertionError("a producer that already exited must not be signalled")

    def kill(self) -> None:
        raise AssertionError("a producer that already exited must not be signalled")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires ffmpeg tools")
class FileRecorderTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "fixture.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=64x64:rate=10", "-t", "6", "-c:v", "mpeg4", "-g", "10", "-output_ts_offset", "3", str(self.source),
        ], check=True, capture_output=True)
        self.recorder = FileRecorder(self.root / "ring", ring_seconds=30)

    def tearDown(self):
        self.tempdir.cleanup()

    def live_source(self) -> Path:
        """Matroska fixture: unlike mp4 it demuxes from a non-seekable pipe."""
        source = self.root / "live.mkv"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=64x64:rate=10", "-t", "6", "-c:v", "mpeg4", "-g", "10",
            "-output_ts_offset", "3", str(source),
        ], check=True, capture_output=True)
        return source

    def feed_pipe(self, source: Path, release: threading.Event, *, share: float = 0.5):
        """Write `share` of the source into a fifo, then hold the producer open until `release`."""
        fifo = self.root / f"feed-{source.stem}.mkv"
        os.mkfifo(fifo)
        payload = source.read_bytes()
        cut = int(len(payload) * share)
        failures: list[OSError] = []

        def feed():
            try:
                with fifo.open("wb", buffering=0) as sink:
                    sink.write(payload[:cut])
                    release.wait(30)
                    sink.write(payload[cut:])
            except OSError as exc:
                failures.append(exc)

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        return fifo, feeder, failures

    def wait_until(self, predicate, timeout: float = 20) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def process_pids(self, marker: Path) -> set[int]:
        """PIDs of ffmpeg/ffprobe processes whose argv names `marker`; the temp root makes this unambiguous."""
        needle = str(marker).encode()
        pids = set()
        for entry in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                argv = entry.read_bytes().split(b"\0")
            except OSError:
                continue
            if argv and os.path.basename(argv[0].decode(errors="replace")) in {"ffmpeg", "ffprobe"} \
                    and any(needle in part for part in argv[1:]):
                pids.add(int(entry.parent.name))
        return pids

    def kill_producers(self, marker: Path) -> None:
        for pid in self.process_pids(marker):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def run_bounded(self, action: Callable[[], BaseException | None], message: str,
                    timeout: float = 10) -> BaseException | None:
        """Run `action` under a watchdog, so a blocked exit fails the test instead of hanging the suite."""
        outcome: list[BaseException | None] = []
        worker = threading.Thread(target=lambda: outcome.append(action()), daemon=True)
        worker.start()
        worker.join(timeout)
        self.assertFalse(worker.is_alive(), message)
        return outcome[0]

    def seed_parts(self, directory: Path, *, segment_seconds: float = 2) -> list[Path]:
        """Complete `.part` files, exactly as ffmpeg leaves the ones it has closed."""
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-copyts", "-i", str(self.source),
            "-map", "0:v:0", "-an", "-c:v", "copy", "-f", "segment",
            "-segment_time", str(segment_seconds), "-reset_timestamps", "0",
            str(directory / FileRecorder.PART_PATTERN),
        ], check=True, capture_output=True)
        parts = sorted(directory.glob(FileRecorder.PART_GLOB))
        self.assertGreaterEqual(len(parts), 2)
        return parts

    def crash_window(self, session_id: str) -> Path:
        """A session exactly as a death between the media rename and its sidecar commit leaves it."""
        directory = self.root / "ring" / session_id
        parts = self.seed_parts(directory)
        final = directory / "segment-00000.mkv"
        os.replace(parts[0], final)
        for leftover in parts[1:]:
            leftover.unlink()
        return final

    def publish_exited(self, directory: Path, session_id: str, returncode: int) -> list[BaseException]:
        """Run the publisher against a producer that has already exited with `returncode`."""
        failures: list[BaseException] = []
        self.recorder._publish_closed(directory, session_id, ExitedProducer(returncode), 0.02, failures)
        return failures

    def test_closed_segments_are_queryable_while_ingest_continues(self):
        release = threading.Event()
        fifo, feeder, failures = self.feed_pipe(self.live_source(), release)
        with self.recorder.ingest(fifo, "live", segment_seconds=1, poll_seconds=0.02):
            self.assertTrue(self.wait_until(lambda: len(self.recorder.segments("live")) >= 2),
                            "closed segments must be published while the producer still runs")
            published = self.recorder.segments("live")
            self.assertLess(len(published), 6, "the withheld half of the source must not be published")
            covered = self.recorder.actual_range("live", published[0].start_seconds, published[-1].end_seconds)
            self.assertEqual(covered["completeness"], "complete")
            pending = self.recorder.actual_range("live", 3, 8)
            self.assertEqual((pending["completeness"], pending["reason"]), ("partial", "missing_postroll"))
            release.set()
        feeder.join(10)
        self.assertFalse(failures)
        self.assertEqual([(item.start_seconds, item.end_seconds) for item in self.recorder.segments("live")],
                         [(3.0, 3.9), (4.0, 4.9), (5.0, 5.9), (6.0, 6.9), (7.0, 7.9), (8.0, 8.9)])

    def test_pin_during_ingest_reports_collection_then_finalizes_after_coverage(self):
        release = threading.Event()
        fifo, feeder, failures = self.feed_pipe(self.live_source(), release)
        with self.recorder.ingest(fifo, "pinned-live", segment_seconds=1, poll_seconds=0.02):
            self.assertTrue(self.wait_until(lambda: len(self.recorder.segments("pinned-live")) >= 2))
            live = self.recorder.pin("live-request", "pinned-live", 3, 8, "event-1")
            self.assertEqual(live["state"], "collecting")
            self.assertEqual((live["actual_start"], live["reason"]), (3.0, "missing_postroll"))
            self.assertLess(live["actual_end"], 8)
            self.assertEqual(self.recorder.pin_status("live-request")["state"], "collecting")
            with self.assertRaisesRegex(ValueError, "still collecting post-roll"):
                self.recorder.finalize_pin("live-request")
            release.set()
        feeder.join(10)
        self.assertFalse(failures)
        self.assertEqual(self.recorder.pin_status("live-request")["state"], "held")
        receipt = self.recorder.finalize_pin("live-request")
        self.assertEqual((receipt["build_state"], receipt["state"], receipt["completeness"]),
                         ("finalized", "held", "complete"))
        self.assertEqual((receipt["actual_start"], receipt["actual_end"]), (3.0, 8.9))

    def test_evidence_request_reconciles_during_ingest_without_faking_postroll(self):
        from apps.edge.outbox import EventOutbox
        from domain.evidence_contract import make_evidence_request
        from tests.test_event_delivery import event_fixture

        event = event_fixture()
        request = make_evidence_request("live-intent", event["stream_session_id"], "onset", 13)
        event["payload"]["evidence_requests"] = [request]
        outbox = EventOutbox(self.root / "live-events.sqlite3")
        outbox.enqueue(event)
        release = threading.Event()
        fifo, feeder, failures = self.feed_pipe(self.live_source(), release)
        with self.recorder.ingest(fifo, request["session_id"], segment_seconds=1, poll_seconds=0.02):
            self.assertTrue(self.wait_until(lambda: len(self.recorder.segments(request["session_id"])) >= 2))
            self.assertEqual(outbox.reconcile_evidence(self.recorder), 0)
            self.assertEqual(outbox.evidence_requests()[0]["state"], "collecting")
            release.set()
        feeder.join(10)
        self.assertFalse(failures)
        self.assertEqual(outbox.reconcile_evidence(self.recorder, finish_sessions=[request["session_id"]]), 1)
        result = outbox.evidence_requests()[0]
        self.assertEqual(result["state"], "partial")
        self.assertEqual((result["receipt"]["requested_start"], result["receipt"]["requested_end"]), (3, 33))
        self.assertEqual((result["receipt"]["actual_start"], result["receipt"]["actual_end"]), (3.0, 8.9))
        self.assertEqual((result["receipt"]["completeness"], result["receipt"]["reason"]),
                         ("partial", "missing_postroll"))

    @unittest.skipUnless(Path("/proc").is_dir(), "requires /proc to signal the producer")
    def test_killed_producer_keeps_published_segments_and_discards_open_part(self):
        release = threading.Event()
        fifo, feeder, failures = self.feed_pipe(self.live_source(), release)
        session_dir = self.root / "ring" / "killed-live"
        with self.assertRaises(subprocess.CalledProcessError):
            with self.recorder.ingest(fifo, "killed-live", segment_seconds=1, poll_seconds=0.02):
                self.assertTrue(self.wait_until(lambda: len(self.recorder.segments("killed-live")) >= 2))
                pinned = self.recorder.pin("killed-request", "killed-live", 3, 8, "event-1")
                self.assertEqual(pinned["state"], "collecting")
                self.assertTrue(self.wait_until(lambda: bool(self.process_pids(session_dir))))
                for pid in self.process_pids(session_dir):
                    os.kill(pid, signal.SIGKILL)
                release.set()
        feeder.join(10)
        self.assertTrue(all(isinstance(exc, BrokenPipeError) for exc in failures), failures)
        published = self.recorder.segments("killed-live")
        self.assertTrue(2 <= len(published) < 6, published)
        self.assertLess(max(item.end_seconds for item in published), 8)
        self.assertEqual(list(session_dir.glob(FileRecorder.PART_GLOB)), [], "an unterminated part is never ring data")
        restarted = FileRecorder(self.root / "ring", ring_seconds=30)
        self.assertEqual(restarted.segments("killed-live"), published)
        self.assertEqual(restarted.pin_status("killed-request")["state"], "collecting")
        with self.assertRaisesRegex(ValueError, "still collecting post-roll"):
            restarted.finalize_pin("killed-request")
        partial = restarted.finalize_pin("killed-request", allow_partial=True)
        self.assertEqual((partial["build_state"], partial["completeness"], partial["reason"]),
                         ("finalized", "partial", "missing_postroll"))

    def test_producer_killed_just_after_a_segment_close_still_publishes_that_segment(self):
        """A nonzero producer status cannot drop a part ffmpeg closed just before the kill."""
        session_dir = self.root / "ring" / "killed-after-close"
        parts = self.seed_parts(session_dir)
        self.assertEqual(self.publish_exited(session_dir, "killed-after-close", -9), [])
        published = [Path(item.path).name for item in self.recorder.segments("killed-after-close")]
        self.assertEqual(published, [f"segment-{index:05d}.mkv" for index in range(len(parts))])
        self.assertEqual(list(session_dir.glob(FileRecorder.PART_GLOB)), [])

    def test_unfinished_trailing_part_is_dropped_instead_of_published(self):
        """The probe decides completeness: a part without its trailer never becomes ring data."""
        session_dir = self.root / "ring" / "unfinished-tail"
        parts = self.seed_parts(session_dir)
        payload = parts[-1].read_bytes()
        unfinished = session_dir / (FileRecorder.PART_PATTERN % len(parts))
        unfinished.write_bytes(payload[:len(payload) // 2])
        self.assertEqual(self.publish_exited(session_dir, "unfinished-tail", -9), [])
        published = [Path(item.path).name for item in self.recorder.segments("unfinished-tail")]
        self.assertEqual(published, [f"segment-{index:05d}.mkv" for index in range(len(parts))])
        self.assertFalse(unfinished.exists(), "an unfinished part is never ring data")
        self.assertEqual(list(session_dir.glob(FileRecorder.PART_GLOB)), [])

    def test_renamed_media_is_invisible_until_its_sidecar_commits(self):
        """The media rename alone must not expose a segment; `segments()` lists committed sidecars."""
        session_dir = self.root / "ring" / "half-committed"
        part = self.seed_parts(session_dir)[0]
        final = session_dir / "segment-00000.mkv"
        os.replace(part, final)
        self.assertTrue(final.is_file())
        self.assertEqual(self.recorder.segments("half-committed"), [])

    def test_reconcile_adopts_renamed_media_whose_sidecar_never_committed(self):
        """Crash window: the media rename survived, its sidecar commit did not."""
        final = self.crash_window("crash-window")
        self.assertEqual(self.recorder.segments("crash-window"), [])

        adopted = self.recorder.reconcile("crash-window")

        self.assertEqual([Path(item.path).name for item in adopted], ["segment-00000.mkv"])
        self.assertEqual((adopted[0].session_id, adopted[0].codec), ("crash-window", "mpeg4"))
        self.assertEqual(adopted, self.recorder.segments("crash-window"))
        self.assertEqual(FileRecorder(self.root / "ring").segments("crash-window"), adopted)
        self.assertTrue(final.is_file(), "adoption must not move or rewrite the media")
        sidecar = final.with_suffix(".json").read_bytes()
        self.assertEqual(self.recorder.reconcile("crash-window"), adopted)
        self.assertEqual(final.with_suffix(".json").read_bytes(), sidecar,
                         "a second startup reconcile is a no-op")

    def test_reconcile_never_overwrites_a_committed_segment(self):
        """A media file that already has a sidecar is committed ring data: leave it alone."""
        final = self.crash_window("committed")
        sidecar = final.with_suffix(".json")
        sidecar.write_text(json.dumps({
            "path": str(final), "session_id": "committed", "codec": "kept", "time_base": "1/1000",
            "start_pts": 0, "end_pts": 10, "start_seconds": 0.0, "end_seconds": 0.01,
            "keyframe_pts": [0], "frame_interval_seconds": 0.1,
        }))

        kept = self.recorder.reconcile("committed")

        self.assertEqual([(item.codec, item.frame_interval_seconds) for item in kept], [("kept", 0.1)])
        self.assertEqual(json.loads(sidecar.read_text())["codec"], "kept", "a committed sidecar is never rewritten")

    def test_reconcile_discards_orphan_media_that_is_not_a_whole_segment(self):
        """Only the probe verdict removes a file; a committed neighbour survives."""
        session_dir = self.root / "ring" / "truncated-orphan"
        parts = self.seed_parts(session_dir)
        self.recorder._publish_part(parts[0], "truncated-orphan")
        committed = self.recorder.segments("truncated-orphan")
        orphan = session_dir / "segment-00001.mkv"
        orphan.write_bytes(parts[1].read_bytes()[: len(parts[1].read_bytes()) // 2])
        for leftover in parts[1:]:
            leftover.unlink()

        self.assertEqual(self.recorder.reconcile("truncated-orphan"), committed)

        self.assertFalse(orphan.exists(), "an unfinished media file is not ring data")
        self.assertEqual(self.recorder.segments("truncated-orphan"), committed)

    def test_reconcile_preserves_an_orphan_it_cannot_judge_and_reports_the_failure(self):
        """An IO error is not a verdict on the segment: keep the media and surface the error."""
        orphan = self.crash_window("unreadable")

        with mock.patch.object(self.recorder, "_probe", side_effect=OSError("disk gone")):
            with self.assertRaisesRegex(OSError, "disk gone"):
                self.recorder.reconcile("unreadable")

        self.assertTrue(orphan.is_file(), "an unclassified probe failure must not destroy the media")
        self.assertFalse(orphan.with_suffix(".json").exists())

    def test_reconcile_publishes_a_whole_part_left_by_a_dead_ingest(self):
        session_dir = self.root / "ring" / "left-part"
        parts = self.seed_parts(session_dir)

        published = self.recorder.reconcile("left-part")

        self.assertEqual([Path(item.path).name for item in published],
                         [f"segment-{index:05d}.mkv" for index in range(len(parts))])
        self.assertEqual(list(session_dir.glob(FileRecorder.PART_GLOB)), [])

    def test_reconcile_discards_an_unfinished_part_left_by_a_dead_ingest(self):
        session_dir = self.root / "ring" / "left-unfinished"
        parts = self.seed_parts(session_dir)
        unfinished = session_dir / (FileRecorder.PART_PATTERN % len(parts))
        payload = parts[-1].read_bytes()
        unfinished.write_bytes(payload[: len(payload) // 2])

        published = self.recorder.reconcile("left-unfinished")

        self.assertEqual([Path(item.path).name for item in published],
                         [f"segment-{index:05d}.mkv" for index in range(len(parts))])
        self.assertFalse(unfinished.exists())

    def test_failure_cleanup_publishes_a_whole_part_and_discards_an_unfinished_one(self):
        session_dir = self.root / "ring" / "cleanup"
        parts = self.seed_parts(session_dir)
        unfinished = session_dir / (FileRecorder.PART_PATTERN % len(parts))
        payload = parts[-1].read_bytes()
        unfinished.write_bytes(payload[: len(payload) // 2])

        self.assertEqual(self.recorder._publish_parts(session_dir, "cleanup"), [])

        self.assertEqual([Path(item.path).name for item in self.recorder.segments("cleanup")],
                         [f"segment-{index:05d}.mkv" for index in range(len(parts))])
        self.assertFalse(unfinished.exists())

    def test_failure_cleanup_preserves_a_part_it_cannot_classify(self):
        """A publisher that died on a transient error must not take possibly-whole parts with it."""
        session_dir = self.root / "ring" / "undecided"
        parts = self.seed_parts(session_dir)

        with mock.patch.object(self.recorder, "_probe", side_effect=OSError("transient IO")):
            undecided = self.recorder._publish_parts(session_dir, "undecided")

        self.assertEqual([str(exc) for exc in undecided], ["transient IO"] * len(parts))
        self.assertEqual(sorted(session_dir.glob(FileRecorder.PART_GLOB)), sorted(parts))
        self.assertEqual(self.recorder.segments("undecided"), [], "a preserved part is not ring data yet")

    def test_reconcile_of_a_never_recorded_session_is_empty(self):
        self.assertEqual(self.recorder.reconcile("absent"), [])

    def test_crash_window_orphan_is_never_clobbered_and_stays_queryable(self):
        """Restart after the crash window: the recovered segment is visible and is not overwritten."""
        final = self.crash_window("crashed")
        bytes_before = final.read_bytes()

        with self.assertRaises(FileExistsError):
            self.recorder.record_file(self.source, "crashed", segment_seconds=2)

        self.assertEqual([Path(item.path).name for item in self.recorder.segments("crashed")],
                         ["segment-00000.mkv"])
        self.assertEqual(final.read_bytes(), bytes_before, "a reconciled segment is not overwritten by the refusal")

    def test_invalid_orphan_media_does_not_block_a_restart(self):
        """An orphan the probe rejects is removed, so the session records instead of staying poisoned."""
        orphan_payload = self.seed_parts(self.root / "ring" / "seed")[0].read_bytes()
        truncated = orphan_payload[: len(orphan_payload) // 2]
        session_dir = self.root / "ring" / "poisoned"
        session_dir.mkdir(parents=True)
        orphan = session_dir / "segment-00000.mkv"
        orphan.write_bytes(truncated)

        recorded = self.recorder.record_file(self.source, "poisoned", segment_seconds=2)

        self.assertTrue(recorded)
        self.assertTrue(orphan.with_suffix(".json").is_file(), "the discarded poison is replaced by real ring data")
        self.assertNotEqual(orphan.read_bytes(), truncated)

    def test_abandoned_ingest_discards_open_part_and_keeps_published_segments(self):
        release = threading.Event()
        fifo, feeder, failures = self.feed_pipe(self.live_source(), release)
        session_dir = self.root / "ring" / "timeout-live"
        with self.assertRaises(TimeoutError):
            with self.recorder.ingest(fifo, "timeout-live", segment_seconds=1, poll_seconds=0.02):
                self.assertTrue(self.wait_until(lambda: len(self.recorder.segments("timeout-live")) >= 2))
                published = self.recorder.segments("timeout-live")
                raise TimeoutError("supervisor deadline")
        release.set()
        feeder.join(10)
        self.assertTrue(all(isinstance(exc, BrokenPipeError) for exc in failures), failures)
        self.assertEqual(list(session_dir.glob(FileRecorder.PART_GLOB)), [])
        restarted = FileRecorder(self.root / "ring", ring_seconds=30)
        self.assertEqual(restarted.segments("timeout-live"), published)
        with self.assertRaises(FileExistsError):
            restarted.record_file(self.live_source(), "timeout-live")

    def test_remote_url_source_is_rejected_before_any_subprocess(self):
        """A URL would hand ffmpeg a credential-bearing argv; only an existing local path is accepted."""
        url = "rtsp://operator:s3cret@camera.example/live"
        for entry in ("ingest", "record_file"):
            with self.subTest(entry=entry):
                with mock.patch("apps.edge.recorder.subprocess.Popen") as popen:
                    with self.assertRaises(ValueError) as caught:
                        if entry == "ingest":
                            with self.recorder.ingest(url, "url-session", segment_seconds=1):
                                pass
                        else:
                            self.recorder.record_file(url, "url-session", segment_seconds=1)
                rendered = " ".join((str(caught.exception), repr(caught.exception), repr(caught.exception.args)))
                self.assertNotIn("s3cret", rendered)
                self.assertNotIn("camera.example", rendered)
                self.assertNotIn("rtsp", rendered)
                popen.assert_not_called()
        self.assertFalse((self.root / "ring" / "url-session").exists(),
                         "a rejected source must not create a session directory")

    @unittest.skipUnless(Path("/proc").is_dir(), "requires /proc to observe the producer")
    def test_publisher_failure_stops_the_producer_and_is_re_raised(self):
        """A dead publisher must stop the producer instead of leaving the caller waiting on it."""
        release = threading.Event()
        self.addCleanup(release.set)
        fifo, feeder, failures = self.feed_pipe(self.live_source(), release)
        session_dir = self.root / "ring" / "publisher-down"
        self.addCleanup(self.kill_producers, session_dir)
        attempted = threading.Event()

        def down(part: Path, session_id: str) -> None:
            attempted.set()
            raise OSError("publisher down")

        observed: list[bool] = []

        def attempt() -> BaseException | None:
            try:
                with self.recorder.ingest(fifo, "publisher-down", segment_seconds=1, poll_seconds=0.02):
                    # The feeder still holds the fifo open, so only the publisher's failure can end this.
                    observed.append(attempted.wait(20))
            except BaseException as exc:
                return exc
            return None

        with mock.patch.object(self.recorder, "_publish_part", side_effect=down):
            error = self.run_bounded(attempt, "ingest exit must not block on a producer nobody publishes")
        self.assertTrue(observed and observed[0], "the publisher must have attempted to publish a closed part")
        self.assertIsInstance(error, OSError)
        self.assertIn("publisher down", str(error))
        self.assertEqual(self.process_pids(session_dir), set(), "the producer must not outlive its publisher")
        release.set()
        feeder.join(10)
        self.assertTrue(all(isinstance(exc, BrokenPipeError) for exc in failures), failures)
        self.assertTrue(list(session_dir.glob(FileRecorder.PART_GLOB)),
                        "a part the publisher could not classify is preserved, not destroyed")
        self.assertEqual(self.recorder.segments("publisher-down"), [], "a preserved part is still not ring data")

    @unittest.skipUnless(Path("/proc").is_dir(), "requires /proc to observe the producer")
    def test_replay_delivers_frames_while_the_producer_is_still_reading(self):
        # 12000 frames emit ~170 KiB of PTS metadata, well past the 64 KiB pipe buffer, so a
        # materializing producer would have drained and exited before the first delivery.
        source = self.root / "long-live.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=64x64:rate=10", "-t", "1200", "-c:v", "mpeg4", "-g", "10",
            "-output_ts_offset", "3", str(source),
        ], check=True, capture_output=True)
        alive_during_delivery: list[list[int]] = []
        delivered = []

        def consume(frame):
            if not alive_during_delivery:
                alive_during_delivery.append(sorted(self.process_pids(source)))
            delivered.append(frame.event_time)

        self.assertEqual(self.recorder.replay(source, "streamed", consume, sample_fps=1), 1200)
        self.assertTrue(alive_during_delivery and alive_during_delivery[0],
                        "ffprobe must still be reading and blocked on the pipe while frames are delivered")
        self.assertEqual(delivered[0], 3.0)
        self.assertEqual(list(self.process_pids(source)), [], "replay must reap its producer")

    def test_replay_sampling_plan_and_watermark_survive_a_failing_consumer(self):
        plan = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5]
        delivered = []

        def abort(frame):
            delivered.append(frame.event_time)
            if len(delivered) == 3:
                raise RuntimeError("consumer down")

        with self.assertRaisesRegex(RuntimeError, "consumer down"):
            self.recorder.replay(self.source, "aborted", abort, sample_fps=2)
        self.assertEqual(delivered, plan[:3])
        self.assertEqual(list(self.process_pids(self.source)), [], "an aborted replay must reap its producer")
        self.recorder.advance_watermark("aborted", plan[2])
        with self.assertRaisesRegex(ValueError, "cannot move backwards"):
            self.recorder.advance_watermark("aborted", plan[2] - 0.1)
        full = []
        self.assertEqual(self.recorder.replay(self.source, "retried", full.append, sample_fps=2), len(plan))
        self.assertEqual(len(full), len(plan))
        for frame, expected in zip(full, plan):
            self.assertAlmostEqual(frame.event_time, expected, delta=1e-9)

    def test_segments_preserve_codec_pts_keyframes_and_are_queryable_without_replay(self):
        written = self.recorder.record_file(self.source, "session-1", segment_seconds=2)
        queried = self.recorder.segments("session-1")
        self.assertGreaterEqual(len(written), 2)
        self.assertEqual(written, queried)
        self.assertTrue(all(item.codec == "mpeg4" and item.keyframe_pts for item in queried))
        self.assertTrue(all(Path(item.path).is_file() for item in queried))
        self.assertEqual([item.start_seconds for item in queried], sorted(item.start_seconds for item in queried))
        self.assertGreaterEqual(queried[0].start_seconds, 3)
        self.assertGreaterEqual(queried[-1].end_seconds, 8)
        coverage = self.recorder.actual_range("session-1", -1, 99)
        self.assertEqual((coverage["completeness"], coverage["reason"]), ("partial", "missing_preroll"))
        coverage = self.recorder.actual_range("session-1", queried[0].start_seconds, queried[-1].end_seconds)
        self.assertEqual(coverage["completeness"], "complete")
        sidecar = Path(queried[1].path).with_suffix(".json")
        data = json.loads(sidecar.read_text())
        data["start_seconds"] += 1
        sidecar.write_text(json.dumps(data))
        coverage = self.recorder.actual_range("session-1", queried[0].start_seconds, queried[-1].end_seconds)
        self.assertEqual(coverage["reason"], "continuity_gap")
        self.assertTrue(coverage["gaps"])

    def test_fast_and_realtime_use_same_pts_sampling_plan(self):
        fast, paced = [], []
        self.recorder.replay(self.source, "fast-session", fast.append, sample_fps=2, mode="fast")
        self.recorder.replay(self.source, "paced-session", paced.append, sample_fps=2, mode="realtime")
        self.assertEqual([frame.pts for frame in fast], [frame.pts for frame in paced])
        self.assertEqual([frame.event_time for frame in fast], [frame.event_time for frame in paced])
        self.assertGreater(fast[0].event_time, 2)

    def test_consumer_watermark_cannot_regress(self):
        self.recorder.advance_watermark("session-1", 4)
        with self.assertRaisesRegex(ValueError, "cannot move backwards"):
            self.recorder.advance_watermark("session-1", 3)

    def test_durable_pin_protects_ring_until_idempotent_release(self):
        self.recorder.ring_seconds = 2
        initial = self.recorder.pin("request-1", "pinned", 3, 6, "event-1")
        self.assertEqual(initial["state"], "collecting")
        self.recorder.record_file(self.source, "pinned", segment_seconds=2)
        restarted = FileRecorder(self.root / "ring", ring_seconds=2)
        retained = restarted.segments("pinned")
        self.assertTrue(any(item.start_seconds <= 3 <= item.end_seconds for item in retained))
        self.assertEqual(restarted.pin_status("request-1")["state"], "held")
        self.assertEqual(restarted.pin("request-1", "pinned", 3, 6, "event-1"), initial)
        with self.assertRaisesRegex(ValueError, "different content"):
            restarted.pin("request-1", "pinned", 4, 7, "event-1")
        self.assertTrue(restarted.release_pin("request-1"))
        self.assertFalse(restarted.release_pin("request-1"))
        self.assertEqual(restarted.pin_status("request-1")["state"], "released")

    def test_worker_records_bad_clip_failure_without_starving_other_requests(self):
        from apps.edge.outbox import EventOutbox
        from domain.evidence_contract import make_evidence_request
        from tests.test_event_delivery import event_fixture
        outbox = EventOutbox(self.root / "events.sqlite3")
        bad = event_fixture()
        bad["payload"]["evidence_requests"] = [make_evidence_request("bad", bad["stream_session_id"], "synthetic", 0)]
        outbox.enqueue(bad)
        self.recorder.record_file(self.source, bad["stream_session_id"])
        for segment in self.recorder.segments(bad["stream_session_id"]):
            Path(segment.path).write_bytes(b"invalid video")
        good = event_fixture()
        good.update(event_id="00000000-0000-4000-8000-000000000099", stream_session_id="00000000-0000-4000-8000-000000000098", message_id="good")
        good["payload"]["evidence_requests"] = [make_evidence_request("good", good["stream_session_id"], "synthetic", 0)]
        outbox.enqueue(good)
        self.recorder.record_file(self.source, good["stream_session_id"])
        self.assertEqual(outbox.reconcile_evidence(self.recorder, finish_sessions=[bad["stream_session_id"], good["stream_session_id"]]), 1)
        self.assertEqual([item["state"] for item in outbox.evidence_requests()], ["failed", "partial"])
        self.assertTrue(outbox.evidence_requests()[0]["last_error"])
        self.assertEqual(EventOutbox(self.root / "events.sqlite3").reconcile_evidence(self.recorder), 0)

    def test_full_pre10_post20_clip(self):
        from apps.edge.outbox import EventOutbox
        from domain.evidence_contract import make_evidence_request
        from tests.test_event_delivery import event_fixture
        source = self.root / "long.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc=size=64x64:rate=10", "-t", "40", "-c:v", "mpeg4", "-g", "10",
                        "-output_ts_offset", "3", str(source)], check=True, capture_output=True)
        event = event_fixture()
        request = make_evidence_request("full", event["stream_session_id"], "synthetic", 13)
        event["payload"]["evidence_requests"] = [request]
        outbox = EventOutbox(self.root / "events.sqlite3")
        outbox.enqueue(event)
        outbox.reconcile_evidence(self.recorder)
        self.recorder.record_file(source, request["session_id"])
        self.assertEqual(outbox.reconcile_evidence(self.recorder), 1)
        result = outbox.evidence_requests()[0]["receipt"]
        self.assertEqual((result["requested_start"], result["requested_end"], result["completeness"]), (3, 33, "complete"))
        self.assertGreaterEqual(result["actual_end"] - result["actual_start"], 30)

    def test_overlap_owner_survives_release_and_missing_build_fails(self):
        self.recorder.ring_seconds = 1
        self.recorder.pin("first", "shared", 3, 6, "owner-1")
        self.recorder.pin("second", "shared", 3, 6, "owner-2")
        self.recorder.record_file(self.source, "shared")
        self.recorder.release_pin("first")
        self.assertEqual(self.recorder.pin_status("second")["completeness"], "complete")
        self.recorder.pin("absent", "empty", -10, 20, "owner-3")
        result = self.recorder.finalize_pin("absent", allow_partial=True)
        self.assertEqual((result["build_state"], result["completeness"], result["artifact"]), ("failed", "unknown", None))

    def test_finalize_recovers_renamed_manifest_after_database_failure(self):
        self.recorder.pin("recovery", "session-1", 3, 8, "event-1")
        self.recorder.record_file(self.source, "session-1")
        database = self.root / "ring" / "pins.sqlite3"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TRIGGER fail_finalize BEFORE UPDATE OF receipt ON pins BEGIN SELECT RAISE(ABORT, 'crash window'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.recorder.finalize_pin("recovery")
        manifest_path = next((self.root / "ring" / "manifests").glob("*.json"))
        committed = manifest_path.read_bytes()
        with sqlite3.connect(database) as db:
            db.execute("DROP TRIGGER fail_finalize")
        for segment in self.recorder.segments("session-1"):
            Path(segment.path).unlink()
        restarted = FileRecorder(self.root / "ring")
        receipt = restarted.finalize_pin("recovery")
        self.assertEqual(manifest_path.read_bytes(), committed)
        self.assertEqual(receipt["artifact"], json.loads(committed)["artifact"])

    def test_worker_retries_pin_ack_and_preserves_anchor_lineage(self):
        from apps.edge.outbox import EventOutbox
        from domain.evidence_contract import make_evidence_request
        from tests.test_event_delivery import event_fixture

        event = event_fixture()
        request = make_evidence_request("intent", event["stream_session_id"], "onset", 0)
        event["payload"]["evidence_requests"] = [request]
        outbox = EventOutbox(self.root / "events.sqlite3")
        outbox.enqueue(event)
        self.recorder.record_file(self.source, request["session_id"])
        self.assertEqual(outbox.reconcile_evidence(self.recorder), 0)
        self.assertEqual(outbox.evidence_requests()[0]["state"], "collecting")
        restarted = EventOutbox(self.root / "events.sqlite3")
        self.assertEqual(restarted.reconcile_evidence(self.recorder, finish_sessions=[request["session_id"]]), 1)
        result = restarted.evidence_requests()[0]
        self.assertEqual((result["state"], result["receipt"]["requested_start"], result["receipt"]["requested_end"]), ("partial", -10, 20))
        self.assertEqual(result["receipt"]["evidence_anchor_kind"], "onset")
        artifact = result["receipt"]["artifact"]
        self.recorder.acknowledge_transfer("intent", {
            "request_id": "intent", "sha256": artifact["sha256"], "size_bytes": artifact["size_bytes"],
            "location": "server/clip-1"})
        status = self.recorder.pin_status("intent")
        self.assertEqual((status["build_state"], status["completeness"], status["transfer_state"]),
                         ("finalized", "partial", "acknowledged"))
        changed = event_fixture()
        changed.update(revision=2, message_id="msg-2")
        changed["payload"]["evidence_requests"] = [make_evidence_request("replacement", request["session_id"], "first_qualifying_observation", 4, supersedes_request_id="intent")]
        restarted.enqueue(changed)
        restarted.reconcile_evidence(self.recorder, finish_sessions=[request["session_id"]])
        self.assertEqual(restarted.evidence_requests()[0], result)
        self.assertEqual(restarted.evidence_requests()[1]["receipt"]["supersedes_request_id"], "intent")

    def test_late_pin_reports_partial_after_watermark_prunes_raw_segments(self):
        self.recorder.ring_seconds = 2
        self.recorder.advance_watermark("late-session", 3)
        written = self.recorder.record_file(self.source, "late-session", segment_seconds=2)
        self.assertEqual([item.start_seconds for item in written], [3, 5, 7])
        self.assertTrue(Path(written[0].path).is_file())
        self.recorder.advance_watermark("late-session", 9)
        self.assertFalse(Path(written[0].path).exists())
        self.assertTrue(Path(written[1].path).is_file())
        self.assertEqual([item.start_seconds for item in self.recorder.segments("late-session")], [5, 7])

        within = self.recorder.pin("within", "late-session", 7, 8, "event-1")
        self.assertEqual((within["requested_start"], within["requested_end"],
                          within["actual_start"], within["actual_end"], within["completeness"]),
                         (7, 8, 7, 8.9, "complete"))
        expired = self.recorder.pin("expired", "late-session", 3, 8, "event-2")
        self.assertEqual((expired["requested_start"], expired["requested_end"],
                          expired["actual_start"], expired["actual_end"],
                          expired["completeness"], expired["reason"]),
                         (3, 8, 5, 8.9, "partial", "missing_preroll"))
        with self.assertRaisesRegex(ValueError, "different content"):
            self.recorder.pin("expired", "late-session", 7, 8, "event-2")
        self.assertEqual(self.recorder.pin("expired", "late-session", 3, 8, "event-2"), expired)

    def test_worker_preserves_policy_interval_when_late_pin_follows_raw_pruning(self):
        from apps.edge.outbox import EventOutbox
        from domain.evidence_contract import make_evidence_request
        from tests.test_event_delivery import event_fixture

        source = self.root / "long-fixture.mp4"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "testsrc=size=64x64:rate=10", "-t", "40", "-c:v", "mpeg4", "-g", "10",
            "-output_ts_offset", "3", str(source),
        ], check=True, capture_output=True)
        for retention, expected_start, completeness, reason in (
            (32, 11, "complete", None),
            (12, 29, "partial", "missing_preroll"),
        ):
            with self.subTest(lab_retention_seconds=retention):
                recorder = FileRecorder(self.root / f"late-ring-{retention}", ring_seconds=retention)
                outbox = EventOutbox(self.root / f"late-events-{retention}.sqlite3")
                event = event_fixture()
                request = make_evidence_request("late-intent", event["stream_session_id"], "onset", 22)
                event["payload"]["evidence_requests"] = [request]
                outbox.enqueue(event)
                session = request["session_id"]
                recorder.advance_watermark(session, 3)
                written = recorder.record_file(source, session, segment_seconds=2)
                self.assertTrue(Path(written[0].path).is_file())
                recorder.advance_watermark(session, 43)
                self.assertFalse(Path(written[0].path).exists())
                onset_segment = next(item for item in written if item.start_seconds == 11)
                self.assertEqual(Path(onset_segment.path).is_file(), retention == 32)
                self.assertEqual(recorder.segments(session)[0].start_seconds, 9 if retention == 32 else 29)

                self.assertEqual(outbox.reconcile_evidence(recorder, finish_sessions=[session]), 1)
                result = outbox.evidence_requests()[0]
                receipt = result["receipt"]
                self.assertEqual(result["state"], "fulfilled" if retention == 32 else "partial")
                self.assertEqual((receipt["requested_start"], receipt["requested_end"]), (12, 42))
                self.assertEqual((receipt["actual_start"], receipt["actual_end"]), (expected_start, 42.9))
                self.assertEqual((receipt["completeness"], receipt["reason"]), (completeness, reason))
                self.assertEqual((receipt["evidence_anchor_kind"], receipt["evidence_anchor_time"]), ("onset", 22))
                self.assertEqual(receipt["build_state"], "finalized")
                clip = Path(receipt["artifact"]["path"])
                self.assertTrue(clip.is_file())
                recorder.ring_seconds = 1
                recorder.release_pin("late-intent")
                self.assertFalse(Path(receipt["segments"][0]["path"]).exists())
                self.assertTrue(clip.is_file())
                self.assertEqual(recorder.pin_status("late-intent")["availability"], "available")
                self.assertEqual(outbox.reconcile_evidence(recorder), 0)
                self.assertEqual(outbox.evidence_requests()[0], result)

    def test_request_outside_ring_is_missing_not_complete(self):
        self.recorder.record_file(self.source, "session-1")
        coverage = self.recorder.actual_range("session-1", 10, 20)
        self.assertEqual(coverage["completeness"], "missing")
        self.assertIsNone(coverage["actual_start"])

    def test_finalized_clip_survives_release_and_reports_corruption(self):
        self.recorder.pin("clip-1", "clip-session", 3, 8, "event-1")
        self.recorder.record_file(self.source, "clip-session")
        receipt = self.recorder.finalize_pin("clip-1")
        self.assertEqual(receipt["build_state"], "finalized")
        self.assertEqual(receipt["completeness"], "complete")
        clip = Path(receipt["artifact"]["path"])
        probe = json.loads(subprocess.run([
            "ffprobe", "-v", "error", "-show_frames", "-of", "json", str(clip)
        ], check=True, capture_output=True, text=True).stdout)
        pts = [float(frame["pts_time"]) for frame in probe["frames"]]
        self.assertAlmostEqual(pts[-1] - pts[0], 5.9)
        self.assertTrue(all(abs(right - left - 0.1) < 0.001 for left, right in zip(pts, pts[1:])))
        self.recorder.ring_seconds = 1
        self.recorder.release_pin("clip-1")
        restarted = FileRecorder(self.root / "ring", ring_seconds=1)
        self.assertEqual(restarted.finalize_pin("clip-1"), receipt)
        self.assertEqual(restarted.pin_status("clip-1")["availability"], "available")
        clip.write_bytes(b"corrupt")
        self.assertEqual(restarted.pin_status("clip-1")["integrity"], "corrupt")
        self.assertEqual(restarted.finalize_pin("clip-1"), receipt)


if __name__ == "__main__":
    unittest.main()
