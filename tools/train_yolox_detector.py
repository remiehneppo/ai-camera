"""YOLOX (YOLOX-Tiny 416x416 & YOLOX-s 640x640) Training & Export Pipeline for CiviWatch.

Converts the 6-class mixed HCMC dataset (`data/mixed_traffic/`) into COCO format,
trains Megvii YOLOX-Tiny and YOLOX-s using official transfer learning on RTX 5060 Ti,
exports raw-grid ONNX models, and generates standard CiviWatch manifests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

import cv2

try:
    from PIL import Image  # type: ignore[import-not-found]
except ImportError:
    Image = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent

CIVIWATCH_CLASSES = [
    "person",
    "two_wheeler",
    "car",
    "bus",
    "truck",
    "obstacle_object",
]


def yolo_split_to_coco_json(
    images_dir: Path,
    labels_dir: Path,
    output_json: Path,
    *,
    max_images: int = 0,
) -> dict[str, Any]:
    """Convert YOLO normalized labels into COCO instances JSON using fast header inspection."""
    categories = [
        {"id": idx + 1, "name": name, "supercategory": "urban_safety"}
        for idx, name in enumerate(CIVIWATCH_CLASSES)
    ]
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []

    img_files = sorted(
        p for p in images_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if max_images > 0:
        img_files = img_files[:max_images]

    ann_id = 1
    for img_id, img_path in enumerate(img_files, start=1):
        lbl_path = labels_dir / f"{img_path.stem}.txt"
        if not lbl_path.is_file():
            continue
        w, h = 0, 0
        if Image is not None:
            try:
                with Image.open(img_path) as im:
                    w, h = im.size
            except Exception:
                w, h = 0, 0
        if w <= 0 or h <= 0:
            bgr = cv2.imread(str(img_path))
            if bgr is None:
                continue
            h, w = bgr.shape[:2]

        images.append({
            "id": img_id,
            "file_name": img_path.name,
            "width": int(w),
            "height": int(h),
        })

        lbl_text = lbl_path.read_text(encoding="utf-8").strip()
        if not lbl_text:
            continue

        for line in lbl_text.splitlines():
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            cls_idx = int(parts[0])
            cx, cy, bw, bh = map(float, parts[1:5])
            abs_w = bw * w
            abs_h = bh * h
            abs_x = (cx * w) - abs_w * 0.5
            abs_y = (cy * h) - abs_h * 0.5
            annotations.append({
                "id": ann_id,
                "image_id": img_id,
                "category_id": cls_idx + 1,
                "bbox": [round(abs_x, 2), round(abs_y, 2), round(abs_w, 2), round(abs_h, 2)],
                "area": round(abs_w * abs_h, 2),
                "iscrowd": 0,
                "segmentation": [],
            })
            ann_id += 1

    coco_doc = {
        "images": images,
        "annotations": annotations,
        "categories": categories,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(coco_doc), encoding="utf-8")
    return {
        "images": len(images),
        "annotations": len(annotations),
        "output_json": str(output_json),
    }


def write_yolox_experiment_file(
    exp_path: Path,
    *,
    dataset_dir: Path,
    variant: str = "yolox_tiny",
    input_size: int = 416,
    max_epoch: int = 10,
    output_dir: Path | None = None,
) -> Path:
    """Generate Megvii YOLOX Experiment configuration for CiviWatch 6-class HCMC dataset."""
    depth, width = (0.33, 0.375) if variant == "yolox_tiny" else (0.33, 0.50)
    enable_mixup = variant != "yolox_tiny"
    out_dir_str = str((output_dir or (ROOT / "data/YOLOX_outputs")).resolve())
    content = f'''#!/usr/bin/env python3
import os
from yolox.exp import Exp as MyExp


class Exp(MyExp):
    def __init__(self):
        super().__init__()
        self.depth = {depth}
        self.width = {width}
        self.input_size = ({input_size}, {input_size})
        self.test_size = ({input_size}, {input_size})
        self.multiscale_range = 0
        self.num_classes = {len(CIVIWATCH_CLASSES)}
        self.data_dir = r"{dataset_dir.resolve()}"
        self.train_ann = "instances_train2017.json"
        self.val_ann = "instances_val2017.json"
        self.output_dir = r"{out_dir_str}"
        self.max_epoch = {max_epoch}
        self.warmup_epochs = 1
        self.no_aug_epochs = 2
        self.enable_mixup = {enable_mixup}
        self.basic_lr_per_img = 0.005 / 64.0
        self.data_num_workers = 6
        self.eval_interval = 2
        self.save_history_ckpt = False
        self.exp_name = "civiwatch_{variant}_{input_size}"
'''
    exp_path.parent.mkdir(parents=True, exist_ok=True)
    exp_path.write_text(content, encoding="utf-8")
    return exp_path


def generate_yolox_manifest(
    model_name: str,
    onnx_path: Path,
    *,
    input_size: int = 416,
    classes: list[str] | None = None,
) -> dict[str, Any]:
    """Generate CiviWatch manifest conforming to yolox_grid decode specifications."""
    blob = onnx_path.read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    size = len(blob)
    labels = classes or CIVIWATCH_CLASSES

    # YOLOX multi-level grid shape: (size/8)^2 + (size/16)^2 + (size/32)^2
    grid_cells = (input_size // 8) ** 2 + (input_size // 16) ** 2 + (input_size // 32) ** 2
    output_shape = [1, grid_cells, len(labels) + 5]

    return {
        "schema_version": 1,
        "model_id": f"civiwatch-{model_name}-{input_size}",
        "artifact": {
            "sha256": sha,
            "size_bytes": size,
            "source_url": f"local:{onnx_path.name}",
            "source_commit": "civi-watch-v2",
            "release": "v2.0",
        },
        "input": {
            "name": "images",
            "shape": [1, 3, input_size, input_size],
            "dtype": "float32",
        },
        "output": {
            "name": "output",
            "shape": output_shape,
            "dtype": "float32",
        },
        "labels": labels,
        "preprocess": {
            "color": "BGR",
            "layout": "NCHW",
            "resize": "bilinear",
            "letterbox": "top_left",
            "pad_value": 114,
            "scale": 1.0,
            "mean": [0.0, 0.0, 0.0],
            "std": [1.0, 1.0, 1.0],
        },
        "postprocess": {
            "decode": "yolox_grid",
            "strides": [8, 16, 32],
            "score": "objectness_times_class",
            "confidence_threshold": 0.25,
            "nms_threshold": 0.45,
            "nms": "per_class",
            "box_format": "xyxy",
            "person_class_id": 0,
            "candidate_threshold": 0.1,
        },
        "runtime": {
            "onnxruntime": "1.20.1",
            "numpy": "1.26.4",
            "provider": "CPUExecutionProvider",
            "opencv_python_headless": "4.10.0.84",
        },
        "rights": {
            "source_license": "Apache-2.0",
            "weights_license": "internal-lab-civiwatch",
            "lab_use_approved": True,
            "production_use_approved": True,
        },
    }


def prepare_coco_dataset(mixed_dir: Path, coco_dir: Path) -> Path:
    """Prepare and link COCO dataset directory from mixed traffic directory."""
    ann_dir = coco_dir / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)

    for split, coco_name in (("train", "train2017"), ("val", "val2017")):
        img_src = mixed_dir / f"images/{split}"
        lbl_src = mixed_dir / f"labels/{split}"
        link_dst = coco_dir / coco_name
        if not link_dst.exists() and img_src.is_dir():
            try:
                link_dst.symlink_to(img_src.resolve())
            except OSError:
                shutil.copytree(img_src, link_dst)

        out_json = ann_dir / f"instances_{coco_name}.json"
        if not out_json.is_file() or out_json.stat().st_size < 1000:
            print(f"[COCO] Converting {split} labels to {out_json.name} ...")
            stats = yolo_split_to_coco_json(img_src, lbl_src, out_json)
            print(f"       -> {stats['images']} images, {stats['annotations']} annotations.")

    return coco_dir


def train_and_export(
    variant: str,
    *,
    imgsz: int,
    epochs: int,
    batch_size: int,
    coco_dir: Path,
    output_dir: Path,
    python_bin: str = "/home/tieubaoca/ai_venv/bin/python",
) -> Path:
    """Execute YOLOX training and export ONNX model."""
    exp_file = write_yolox_experiment_file(
        output_dir / f"civiwatch_{variant}_{imgsz}_exp.py",
        dataset_dir=coco_dir,
        variant=variant,
        input_size=imgsz,
        max_epoch=epochs,
    )

    base_ckpt = ROOT / f"data/weights/{variant}.pth"
    if not base_ckpt.is_file():
        raise FileNotFoundError(f"Missing base weights: {base_ckpt}")

    print(f"\n[{variant.upper()}] Starting transfer-learning ({epochs} epochs, {imgsz}x{imgsz}, batch={batch_size}) ...")
    t0 = time.time()
    train_cmd = [
        python_bin,
        str(ROOT / "data/YOLOX/tools/train.py"),
        "-f", str(exp_file),
        "-d", "1",
        "-b", str(batch_size),
        "--fp16",
        "-c", str(base_ckpt),
        "--logger", "tensorboard",
    ]
    subprocess.run(train_cmd, check=True)
    elapsed = time.time() - t0
    print(f"[{variant.upper()}] Training finished in {elapsed / 60:.1f} minutes.")

    # Locate best_ckpt.pth inside data/YOLOX_outputs
    yolox_exp_dir = ROOT / f"data/YOLOX_outputs/civiwatch_{variant}_{imgsz}"
    best_ckpt = yolox_exp_dir / "best_ckpt.pth"
    if not best_ckpt.is_file():
        best_ckpt = yolox_exp_dir / "last_epoch_ckpt.pth"
    if not best_ckpt.is_file():
        raise FileNotFoundError(f"Training did not produce a checkpoint at {yolox_exp_dir}")

    onnx_dest = output_dir / f"{variant}_civiwatch_{imgsz}.onnx"
    print(f"[{variant.upper()}] Exporting best checkpoint ({best_ckpt}) to ONNX ...")
    export_cmd = [
        python_bin,
        str(ROOT / "data/YOLOX/tools/export_onnx.py"),
        "-f", str(exp_file),
        "-c", str(best_ckpt),
        "--output-name", str(onnx_dest),
        "--no-onnxsim",
    ]
    subprocess.run(export_cmd, check=True)
    if not onnx_dest.is_file() or onnx_dest.stat().st_size < 100_000:
        raise RuntimeError(f"ONNX export failed or produced empty file: {onnx_dest}")

    manifest = generate_yolox_manifest(variant.replace("_", "-"), onnx_dest, input_size=imgsz)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[{variant.upper()}] Saved {onnx_dest.name} ({onnx_dest.stat().st_size / 1e6:.1f} MB) and manifest.json.")

    return onnx_dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["all", "yolox_tiny", "yolox_s"], default="all")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--mixed-dir", type=Path, default=ROOT / "data/mixed_traffic")
    parser.add_argument("--coco-dir", type=Path, default=ROOT / "data/mixed_traffic_coco")
    args = parser.parse_args(argv)

    print("=" * 68)
    print("      CIVIWATCH YOLOX TRAINING & EXPORT RUNNER")
    print("=" * 68)

    coco_dir = prepare_coco_dataset(args.mixed_dir, args.coco_dir)

    variants_to_train = [
        ("yolox_tiny", 416, ROOT / "models/yolox-tiny-hcmc"),
        ("yolox_s", 640, ROOT / "models/yolox-s-hcmc"),
    ] if args.variant == "all" else (
        [("yolox_tiny", 416, ROOT / "models/yolox-tiny-hcmc")] if args.variant == "yolox_tiny"
        else [("yolox_s", 640, ROOT / "models/yolox-s-hcmc")]
    )

    for var, imgsz, out_dir in variants_to_train:
        out_dir.mkdir(parents=True, exist_ok=True)
        train_and_export(
            var,
            imgsz=imgsz,
            epochs=args.epochs,
            batch_size=args.batch,
            coco_dir=coco_dir,
            output_dir=out_dir,
        )

    print("\n[COMPLETE] All requested YOLOX models trained and exported successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
