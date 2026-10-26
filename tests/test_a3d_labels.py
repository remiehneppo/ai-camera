"""Ticket-less tool support: A3D frame labels need an explicit id mapping (external asset)."""

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.a3d_labels import build_labels, load_frame_labels


class A3DLabelsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.labels_zip = self.root / "labels.zip"
        with zipfile.ZipFile(self.labels_zip, "w") as archive:
            archive.writestr("ABC_000001.txt", "\n".join(f"{i} {1 if i >= 60 else 0}" for i in range(1, 101)))
            archive.writestr("ABC_000002.txt", "\n".join(f"{i} 0" for i in range(1, 101)))
        self.videos = self.root / "videos"
        (self.videos / "positive").mkdir(parents=True)
        (self.videos / "negative").mkdir(parents=True)
        (self.videos / "positive" / "000001.mp4").write_bytes(b"clip")
        (self.videos / "negative" / "000002.mp4").write_bytes(b"clip")

    def test_labels_come_from_the_zip_and_need_a_mapping(self):
        labels = load_frame_labels(self.labels_zip)
        self.assertEqual(sorted(labels), ["ABC_000001", "ABC_000002"])
        mapping = {"ABC_000001": "positive/000001.mp4", "ABC_000002": "negative/000002.mp4"}
        records, problems = build_labels(labels, mapping, self.videos)
        self.assertEqual(problems, [])
        positive = next(record for record in records if record["label_stem"] == "ABC_000001")
        # label line "60 1" is the 60th frame; the record reports a 0-based index for OpenCV readers.
        self.assertEqual((positive["positive"], positive["onset_frame"], positive["onset_seconds"]), (True, 59, 2.36))
        self.assertEqual(positive["duration_seconds"], 4.0)
        negative = next(record for record in records if record["label_stem"] == "ABC_000002")
        self.assertEqual((negative["positive"], negative["onset_frame"]), (False, None))

    def test_a_missing_or_extra_mapping_entry_is_reported_not_guessed(self):
        labels = load_frame_labels(self.labels_zip)
        records, problems = build_labels(labels, {"ABC_000001": "positive/missing.mp4"}, self.videos)
        self.assertEqual(records, [])
        self.assertTrue(any("clip missing" in problem for problem in problems))
        self.assertTrue(any("no mapping for ABC_000002" in problem for problem in problems))
        records, problems = build_labels(labels, {"ABC_000001": "positive/000001.mp4", "ZZZ": "x.mp4"}, self.videos)
        self.assertTrue(any("mapping entry without a label file" in problem for problem in problems))

    def test_directory_source_matches_zip_source(self):
        extracted = self.root / "extracted"
        extracted.mkdir()
        (extracted / "ABC_000003.txt").write_text("1 0\n2 1")
        labels = load_frame_labels(extracted)
        self.assertEqual(labels["ABC_000003"], [0, 1])


if __name__ == "__main__":
    unittest.main()
