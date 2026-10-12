import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from apps.edge.recorder import FileRecorder


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
