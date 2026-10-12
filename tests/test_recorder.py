import json
import shutil
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


if __name__ == "__main__":
    unittest.main()
