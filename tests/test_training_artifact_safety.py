"""Regression tests for training artifact safety (F3) and dataset preparation safety (F12).

F3:
  - --dry-run and missing-CUDA preparation must never overwrite active manifest.json,
    trained ONNX weights, or active training recipe in deployment directory.
  - Blueprint artifacts must be distinctly named/located (e.g. blueprint_manifest.json,
    *.blueprint.onnx, blueprint_run_training.sh) and indicate preparation-only status.
  - Missing CUDA in ordinary training must return a nonzero actionable error rather than
    silently succeeding with fake deployment artifacts.
  - Active model loading via load_civiwatch_manifest remains valid and unmodified.

F12:
  - prepare_coco_dataset must regenerate annotations and refresh image links when source
    labels, images, or dataset root change (simple rebuild, no stale cache masking).
  - Existing user source dataset files and referenced targets must never be removed or deleted.
  - Broken symlinks and stale copied destinations must be safely refreshed.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from domain.model_manifest import load_civiwatch_manifest
from tools.train_civiwatch_detector import (
    generate_civiwatch_manifest,
    main as civiwatch_train_main,
)
from tools.train_yolox_detector import prepare_coco_dataset


def _create_minimal_onnx(onnx_path: Path, input_size: int = 640) -> None:
    """Create a minimal ONNX model file for testing without external downloads."""
    if importlib.util.find_spec("onnx") is not None:
        import onnx
        from onnx import TensorProto, helper, numpy_helper

        out_arr = np.zeros((1, 300, 6), dtype=np.float32)
        tensor = numpy_helper.from_array(out_arr, "raw")
        graph = helper.make_graph(
            [helper.make_node("Identity", ["raw"], ["output0"])],
            "test-artifact-safety",
            [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, input_size, input_size])],
            [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 300, 6])],
            initializer=[tensor],
        )
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        model.ir_version = 9
        onnx.save(model, onnx_path)
    else:
        onnx_path.write_bytes(b"TEST_ONNX_MODEL_BYTES_" + str(input_size).encode("ascii"))


class TrainingArtifactSafetyTests(unittest.TestCase):
    """Verify F3: dry-run and missing-CUDA never overwrite active deployment artifacts."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.models_dir = self.root / "models/civiwatch-640"
        self.models_dir.mkdir(parents=True, exist_ok=True)

        # Create active deployment ONNX model
        self.active_onnx = self.models_dir / "yolo26s_civiwatch_640.onnx"
        _create_minimal_onnx(self.active_onnx, 640)
        self.active_onnx_bytes = self.active_onnx.read_bytes()
        self.active_onnx_sha = hashlib.sha256(self.active_onnx_bytes).hexdigest()

        # Create active deployment manifest.json
        manifest_dict = generate_civiwatch_manifest("yolo26s", self.active_onnx, input_size=640, nms_free=True)
        self.active_manifest = self.models_dir / "manifest.json"
        self.active_manifest.write_text(json.dumps(manifest_dict, indent=2), encoding="utf-8")
        self.active_manifest_text = self.active_manifest.read_text(encoding="utf-8")

        # Create active deployment recipe
        self.active_recipe = self.models_dir / "run_training.sh"
        self.active_recipe.write_text("#!/usr/bin/env bash\necho 'ACTIVE RECIPE'\n", encoding="utf-8")
        self.active_recipe_text = self.active_recipe.read_text(encoding="utf-8")

        # Create dummy dataset config
        self.data_yaml = self.root / "dataset.yaml"
        self.data_yaml.write_text("names:\n  0: person\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_civiwatch_dry_run_preserves_active_manifest_and_weights_and_recipe(self) -> None:
        """--dry-run must write blueprint artifacts distinctly and never overwrite active deployment files."""
        rc = civiwatch_train_main([
            "--dry-run",
            "--model", "yolo26s",
            "--imgsz", "640",
            "--data-yaml", str(self.data_yaml),
            "--output-dir", str(self.models_dir),
        ])
        self.assertEqual(rc, 0)

        # Active deployment files must remain 100% byte-for-byte identical
        self.assertEqual(
            self.active_onnx.read_bytes(),
            self.active_onnx_bytes,
            "Active deployment ONNX binary was overwritten by --dry-run!",
        )
        self.assertEqual(
            self.active_manifest.read_text(encoding="utf-8"),
            self.active_manifest_text,
            "Active deployment manifest.json was overwritten by --dry-run!",
        )
        self.assertEqual(
            self.active_recipe.read_text(encoding="utf-8"),
            self.active_recipe_text,
            "Active deployment run_training.sh was overwritten by --dry-run!",
        )

        # Blueprint artifacts must be distinctly named
        blueprint_manifest_path = self.models_dir / "blueprint_manifest.json"
        self.assertTrue(
            blueprint_manifest_path.is_file(),
            "blueprint_manifest.json must be created with distinct blueprint naming",
        )
        blueprint_meta = json.loads(blueprint_manifest_path.read_text(encoding="utf-8"))
        self.assertIn("blueprint", blueprint_meta.get("artifact", {}).get("source_url", "").lower())
        self.assertFalse(
            blueprint_meta.get("rights", {}).get("production_use_approved", True),
            "Blueprint manifest must not declare production use approval",
        )

        # Blueprint recipe must be distinct from active run_training.sh
        blueprint_recipe_path = self.models_dir / "blueprint_run_training.sh"
        self.assertTrue(blueprint_recipe_path.is_file())

        # Active model loading via domain contract must succeed without hash mismatch
        loaded = load_civiwatch_manifest(self.active_manifest, self.active_onnx)
        self.assertEqual(loaded["artifact"]["sha256"], self.active_onnx_sha)

    def test_civiwatch_missing_cuda_without_dry_run_fails_actionable_nonzero(self) -> None:
        """Ordinary training without CUDA must fail with actionable error, never overwrite or fake success."""
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: False, get_device_name=lambda idx: "CPU"),
            __version__="fake-torch-test",
        )
        for mod_override in ({"torch": fake_torch}, {"torch": None}):
            stderr_buf = io.StringIO()
            with patch.dict("sys.modules", mod_override), contextlib.redirect_stderr(stderr_buf):
                rc = civiwatch_train_main([
                    "--model", "yolo26s",
                    "--imgsz", "640",
                    "--data-yaml", str(self.data_yaml),
                    "--output-dir", str(self.models_dir),
                ])
            self.assertNotEqual(
                rc,
                0,
                "Ordinary training invocation without CUDA must exit with nonzero error",
            )
            self.assertIn("--dry-run", stderr_buf.getvalue())

        # Active deployment files must remain untouched
        self.assertEqual(self.active_manifest.read_text(encoding="utf-8"), self.active_manifest_text)
        self.assertEqual(self.active_onnx.read_bytes(), self.active_onnx_bytes)
        self.assertEqual(self.active_recipe.read_text(encoding="utf-8"), self.active_recipe_text)
        self.assertFalse((self.models_dir / "blueprint_manifest.json").exists())

    def test_civiwatch_dry_run_without_onnx_fails_nonzero_and_writes_no_blueprint(self) -> None:
        """--dry-run without optional onnx must fail nonzero without fabricating partial artifacts."""
        stderr_buf = io.StringIO()
        with patch.dict("sys.modules", {"onnx": None}), contextlib.redirect_stderr(stderr_buf):
            rc = civiwatch_train_main([
                "--dry-run",
                "--model", "yolo26s",
                "--imgsz", "640",
                "--data-yaml", str(self.data_yaml),
                "--output-dir", str(self.models_dir),
            ])
        self.assertNotEqual(rc, 0)
        self.assertFalse((self.models_dir / "blueprint_manifest.json").exists())
        self.assertEqual(self.active_manifest.read_text(encoding="utf-8"), self.active_manifest_text)
        self.assertEqual(self.active_onnx.read_bytes(), self.active_onnx_bytes)
        self.assertEqual(self.active_recipe.read_text(encoding="utf-8"), self.active_recipe_text)


class PrepareDatasetSafetyTests(unittest.TestCase):
    """Verify F12: prepare_coco_dataset rebuilds annotations and refreshes links safely."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.mixed_dir_1 = self.root / "mixed_1"
        self.mixed_dir_2 = self.root / "mixed_2"
        self.coco_dir = self.root / "coco_out"

        for md in (self.mixed_dir_1, self.mixed_dir_2):
            for split in ("train", "val"):
                (md / f"images/{split}").mkdir(parents=True, exist_ok=True)
                (md / f"labels/{split}").mkdir(parents=True, exist_ok=True)

        # Seed sample image and label in mixed_dir_1
        img1 = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.imwrite(str(self.mixed_dir_1 / "images/train/frame_01.jpg"), img1)
        (self.mixed_dir_1 / "labels/train/frame_01.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n", encoding="utf-8"
        )
        cv2.imwrite(str(self.mixed_dir_1 / "images/val/val_01.jpg"), img1)
        (self.mixed_dir_1 / "labels/val/val_01.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_prepare_coco_dataset_regenerates_annotations_when_labels_change(self) -> None:
        """Conversion must rebuild annotations rather than skipping due to pre-existing json size."""
        prepare_coco_dataset(self.mixed_dir_1, self.coco_dir)
        ann_path = self.coco_dir / "annotations/instances_train2017.json"
        self.assertTrue(ann_path.is_file())
        doc_1 = json.loads(ann_path.read_text(encoding="utf-8"))
        self.assertEqual(len(doc_1["annotations"]), 1)

        # Pre-seed annotation file with padding so size > 1000 bytes (testing stale cache vulnerability)
        doc_1["_cache_padding"] = "x" * 2000
        ann_path.write_text(json.dumps(doc_1), encoding="utf-8")
        self.assertGreater(ann_path.stat().st_size, 1000)

        # Add a second object in the label file
        (self.mixed_dir_1 / "labels/train/frame_01.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n1 0.7 0.7 0.1 0.1\n", encoding="utf-8"
        )
        # Add a second image and label
        img2 = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.imwrite(str(self.mixed_dir_1 / "images/train/frame_02.jpg"), img2)
        (self.mixed_dir_1 / "labels/train/frame_02.txt").write_text(
            "2 0.4 0.4 0.3 0.3\n", encoding="utf-8"
        )

        # Re-run conversion
        prepare_coco_dataset(self.mixed_dir_1, self.coco_dir)
        doc_2 = json.loads(ann_path.read_text(encoding="utf-8"))

        self.assertEqual(
            len(doc_2["images"]),
            2,
            "Images count did not refresh after adding frame_02!",
        )
        self.assertEqual(
            len(doc_2["annotations"]),
            3,
            "Annotations count did not regenerate after modifying labels!",
        )

    def test_prepare_coco_dataset_refreshes_symlink_when_source_root_changes(self) -> None:
        """Image link destination must refresh to new source root without retaining stale pointer."""
        img2 = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.imwrite(str(self.mixed_dir_2 / "images/train/m2_frame.jpg"), img2)
        (self.mixed_dir_2 / "labels/train/m2_frame.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n", encoding="utf-8"
        )
        cv2.imwrite(str(self.mixed_dir_2 / "images/val/m2_val.jpg"), img2)
        (self.mixed_dir_2 / "labels/val/m2_val.txt").write_text(
            "0 0.5 0.5 0.2 0.2\n", encoding="utf-8"
        )

        # Initial preparation with mixed_dir_1
        prepare_coco_dataset(self.mixed_dir_1, self.coco_dir)
        train_link = self.coco_dir / "train2017"
        expected_src_1 = (self.mixed_dir_1 / "images/train").resolve()
        self.assertEqual(train_link.resolve(), expected_src_1)

        # Second preparation pointing to mixed_dir_2
        prepare_coco_dataset(self.mixed_dir_2, self.coco_dir)
        expected_src_2 = (self.mixed_dir_2 / "images/train").resolve()
        self.assertEqual(
            train_link.resolve(),
            expected_src_2,
            "Image symlink did not refresh to the new mixed_dir_2 source!",
        )

        ann_path = self.coco_dir / "annotations/instances_train2017.json"
        doc = json.loads(ann_path.read_text(encoding="utf-8"))
        self.assertEqual(doc["images"][0]["file_name"], "m2_frame.jpg")

    def test_prepare_coco_dataset_never_deletes_user_source_files(self) -> None:
        """Symlink deletion or cleanup must never follow links to delete user files."""
        user_source_img = self.mixed_dir_1 / "images/train/frame_01.jpg"
        user_source_lbl = self.mixed_dir_1 / "labels/train/frame_01.txt"
        self.assertTrue(user_source_img.is_file())
        self.assertTrue(user_source_lbl.is_file())

        # Run conversion multiple times and switch source root back and forth
        prepare_coco_dataset(self.mixed_dir_1, self.coco_dir)
        prepare_coco_dataset(self.mixed_dir_2, self.coco_dir)
        prepare_coco_dataset(self.mixed_dir_1, self.coco_dir)

        self.assertTrue(
            user_source_img.is_file(),
            "User source image was deleted during dataset preparation!",
        )
        self.assertTrue(
            user_source_lbl.is_file(),
            "User source label was deleted during dataset preparation!",
        )

    def test_prepare_coco_dataset_recovers_from_broken_symlink(self) -> None:
        """Broken symlink in destination must be safely replaced without crashing."""
        train_link = self.coco_dir / "train2017"
        self.coco_dir.mkdir(parents=True, exist_ok=True)
        # Create deliberately broken symlink
        nonexistent = self.root / "does_not_exist"
        train_link.symlink_to(nonexistent)
        self.assertTrue(train_link.is_symlink())
        self.assertFalse(train_link.exists())

        # prepare_coco_dataset should recover and link to mixed_dir_1
        prepare_coco_dataset(self.mixed_dir_1, self.coco_dir)
        self.assertTrue(train_link.exists())
        self.assertEqual(train_link.resolve(), (self.mixed_dir_1 / "images/train").resolve())

    def test_prepare_coco_dataset_refreshes_managed_copy_without_deleting_linked_targets(self) -> None:
        """Managed copy fallback must be replaced cleanly without following symlinks into user data."""
        user_protected = self.root / "user_protected_file.jpg"
        user_protected.write_bytes(b"PROTECTED_DATA")

        with patch.object(Path, "symlink_to", side_effect=OSError("symlinks disabled")):
            prepare_coco_dataset(self.mixed_dir_1, self.coco_dir)

        managed_copy_dir = self.coco_dir / "train2017"
        self.assertTrue(managed_copy_dir.is_dir() and not managed_copy_dir.is_symlink())
        (managed_copy_dir / "link_to_user.jpg").symlink_to(user_protected)

        prepare_coco_dataset(self.mixed_dir_1, self.coco_dir)

        self.assertTrue(
            user_protected.is_file() and user_protected.read_bytes() == b"PROTECTED_DATA",
            "Symlink target outside coco_dir must never be deleted!",
        )
        train_link = self.coco_dir / "train2017"
        self.assertTrue(train_link.exists())
        self.assertEqual(train_link.resolve(), (self.mixed_dir_1 / "images/train").resolve())

    def test_prepare_coco_dataset_refuses_unmarked_copied_destination_and_preserves_files(self) -> None:
        """Existing unmarked directory must be preserved and clearly refused without deleting files or targets."""
        user_protected = self.root / "user_protected_target.jpg"
        user_protected.write_bytes(b"PROTECTED_TARGET")

        unmarked_dir = self.coco_dir / "train2017"
        unmarked_dir.mkdir(parents=True, exist_ok=True)
        user_file = unmarked_dir / "user_dataset_img.jpg"
        user_file.write_bytes(b"USER_ORIGINAL_BYTES")
        (unmarked_dir / "link_to_target.jpg").symlink_to(user_protected)

        with self.assertRaises(FileExistsError):
            prepare_coco_dataset(self.mixed_dir_1, self.coco_dir)

        self.assertTrue(
            user_file.is_file() and user_file.read_bytes() == b"USER_ORIGINAL_BYTES",
            "Unmarked destination file must remain completely intact!",
        )
        self.assertTrue(
            user_protected.is_file() and user_protected.read_bytes() == b"PROTECTED_TARGET",
            "Symlink target must remain completely intact!",
        )

    def test_prepare_coco_dataset_raises_for_missing_source_images_dir(self) -> None:
        """Absent source images directory must raise FileNotFoundError rather than writing empty COCO JSON."""
        missing_root = self.root / "does_not_exist_mixed"
        with self.assertRaises(FileNotFoundError):
            prepare_coco_dataset(missing_root, self.coco_dir)


if __name__ == "__main__":
    unittest.main()
