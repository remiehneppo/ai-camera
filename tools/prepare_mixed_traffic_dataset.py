"""Prepare Mixed Traffic & Pedestrian Dataset for CiviWatch Detector (640x640).

Merges AIC_HCMC_2020 traffic CCTV dataset (two-wheels, four-wheels, bus, truck)
with pedestrian (person) and obstacle objects (backpack, suitcase) to prevent
catastrophic forgetting of pedestrian detection during fine-tuning.

Canonical CiviWatch 6-Class Schema:
  0: person
  1: two_wheeler   (motorcycle, bicycle)
  2: car           (four-wheels, automobile)
  3: bus
  4: truck
  5: obstacle_object (suitcase, backpack, road hazard)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import shutil
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

CIVIWATCH_CLASSES = [
    "person",
    "two_wheeler",
    "car",
    "bus",
    "truck",
    "obstacle_object",
]

# Mapping from AIC_HCMC_2020 YOLO class index to CiviWatch 6-class index
AIC_TO_CIVIWATCH = {
    0: 1,  # two-wheels  -> two_wheeler
    1: 2,  # four-wheels -> car
    2: 3,  # bus         -> bus
    3: 4,  # truck       -> truck
}


def build_dataset_yaml(output_dir: Path) -> Path:
    """Generate YOLO-format dataset.yaml pointing to train and val directories."""
    output_dir.mkdir(parents=True, exist_ok=True)
    yaml_content = f"""# CiviWatch Mixed Urban Traffic & Pedestrian Dataset
path: {output_dir.resolve()}
train: images/train
val: images/val

names:
  0: person
  1: two_wheeler
  2: car
  3: bus
  4: truck
  5: obstacle_object
"""
    yaml_path = output_dir / "dataset.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")
    return yaml_path


def convert_and_copy_split(
    split_name: str,
    src_images_dir: Path,
    src_labels_dir: Path,
    dst_images_dir: Path,
    dst_labels_dir: Path,
    *,
    max_samples: int = 0,
    seed: int = 42,
) -> dict[str, Any]:
    """Convert AIC YOLO labels to CiviWatch 6-class labels and link/copy images."""
    dst_images_dir.mkdir(parents=True, exist_ok=True)
    dst_labels_dir.mkdir(parents=True, exist_ok=True)

    label_files = sorted(src_labels_dir.glob("*.txt"))
    if not label_files:
        return {"images": 0, "labels": 0, "boxes": 0}

    rng = random.Random(seed)
    if max_samples and max_samples < len(label_files):
        label_files = rng.sample(label_files, max_samples)

    class_counts: dict[int, int] = {i: 0 for i in range(len(CIVIWATCH_CLASSES))}
    processed_images = 0
    total_boxes = 0

    for lbl_path in label_files:
        stem = lbl_path.stem
        # Corresponding image can be jpg, png, or jpeg
        img_candidates = [
            src_images_dir / f"{stem}.jpg",
            src_images_dir / f"{stem}.png",
            src_images_dir / f"{stem}.jpeg",
        ]
        img_src = next((c for c in img_candidates if c.is_file()), None)
        if img_src is None:
            continue

        # Convert label lines
        converted_lines = []
        for line in lbl_path.read_text(encoding="utf-8").strip().splitlines():
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            src_cls = int(parts[0])
            dst_cls = AIC_TO_CIVIWATCH.get(src_cls, 1)
            converted_lines.append(f"{dst_cls} {' '.join(parts[1:])}\n")
            class_counts[dst_cls] += 1
            total_boxes += 1

        if not converted_lines:
            continue

        dst_lbl = dst_labels_dir / f"{stem}.txt"
        dst_lbl.write_text("".join(converted_lines), encoding="utf-8")

        dst_img = dst_images_dir / img_src.name
        # Use symlink if on same filesystem, otherwise copy
        try:
            if dst_img.is_symlink() or dst_img.exists():
                dst_img.unlink()
            dst_img.symlink_to(img_src.resolve())
        except OSError:
            shutil.copy2(img_src, dst_img)

        processed_images += 1

    return {
        "images": processed_images,
        "labels": processed_images,
        "boxes": total_boxes,
        "classes": {CIVIWATCH_CLASSES[k]: v for k, v in class_counts.items()},
    }


def pseudo_label_missing_classes(
    images_dir: Path,
    labels_dir: Path,
    teacher_weights: Path,
    *,
    conf: float = 0.38,
    batch_size: int = 32,
) -> dict[str, int]:
    """Run pretrained teacher model to annotate unlabeled person (0) and obstacle_object (5) inside HCMC images."""
    from ultralytics import YOLO  # type: ignore[import-not-found]

    COCO_PERSON_CLS = 0
    COCO_OBSTACLE_CLASSES = {24, 25, 26, 28, 56, 58}  # backpack, umbrella, handbag, suitcase, chair, potted plant

    img_paths = sorted(
        p for p in images_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"} and not p.name.startswith("civi_pedestrian_sample_")
    )
    if not img_paths:
        return {"person": 0, "obstacle_object": 0}

    model = YOLO(str(teacher_weights))
    added_person = 0
    added_obstacle = 0

    for start_idx in range(0, len(img_paths), batch_size):
        chunk = img_paths[start_idx : start_idx + batch_size]
        results = model.predict(
            [str(p) for p in chunk],
            imgsz=640,
            conf=conf,
            classes=[COCO_PERSON_CLS, *sorted(COCO_OBSTACLE_CLASSES)],
            verbose=False,
            device=0,
        )
        for img_path, res in zip(chunk, results):
            lbl_path = labels_dir / f"{img_path.stem}.txt"
            if not lbl_path.is_file():
                continue
            extra_lines: list[str] = []
            for box in res.boxes:
                coco_cls = int(box.cls[0])
                xywhn = box.xywhn[0].tolist()
                if coco_cls == COCO_PERSON_CLS:
                    dst_cls = 0
                    added_person += 1
                elif coco_cls in COCO_OBSTACLE_CLASSES:
                    dst_cls = 5
                    added_obstacle += 1
                else:
                    continue
                extra_lines.append(
                    f"{dst_cls} {xywhn[0]:.6f} {xywhn[1]:.6f} {xywhn[2]:.6f} {xywhn[3]:.6f}\n"
                )
            if extra_lines:
                with lbl_path.open("a", encoding="utf-8") as f:
                    f.writelines(extra_lines)

    return {"person": added_person, "obstacle_object": added_obstacle}


def inject_pedestrian_samples(
    output_dir: Path,
    *,
    count: int = 100,
) -> int:
    """Inject balanced pedestrian samples (class 0) into train split from bundled assets."""
    train_img_dir = output_dir / "images/train"
    train_lbl_dir = output_dir / "labels/train"
    train_img_dir.mkdir(parents=True, exist_ok=True)
    train_lbl_dir.mkdir(parents=True, exist_ok=True)

    sample_img = ROOT / "data/oracle/shibuya_people.jpg"
    if not sample_img.is_file():
        return 0

    # Shibuya reference image dimensions: 640x480 with people walking across + carried bags/obstacles
    # Known reference pedestrian (0) and obstacle_object (5) boxes normalized to [cx, cy, w, h]
    pedestrian_and_obstacle_boxes = [
        "0 0.285 0.442 0.125 0.354",
        "0 0.512 0.385 0.098 0.292",
        "0 0.720 0.480 0.140 0.380",
        "0 0.410 0.520 0.110 0.320",
        "5 0.310 0.510 0.055 0.095",
        "5 0.745 0.560 0.065 0.110",
    ]
    injected = 0
    for i in range(max(1, count)):
        name = f"civi_pedestrian_sample_{i:04d}"
        dst_img = train_img_dir / f"{name}.jpg"
        dst_lbl = train_lbl_dir / f"{name}.txt"
        shutil.copy2(sample_img, dst_img)
        dst_lbl.write_text("\n".join(pedestrian_and_obstacle_boxes) + "\n", encoding="utf-8")
        injected += 1
    return injected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src-dir",
        type=Path,
        default=Path(os.environ.get("CIVIWATCH_AIC_HCMC_DIR", "/media/tieubaoca/HDD1/F/dataset/video/AIC_HCMC_2020")),
        help="Path to extracted AIC_HCMC_2020 dataset directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data/mixed_traffic",
        help="Destination directory for mixed CiviWatch dataset",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=500,
        help="Maximum image samples per split (0 for all ~26,000 images, default: 500 for fast setup)",
    )
    parser.add_argument(
        "--pedestrian-count",
        type=int,
        default=50,
        help="Number of pedestrian training samples to mix in",
    )
    parser.add_argument(
        "--pseudo-label-model",
        type=Path,
        default=None,
        help="Optional pretrained YOLO weights (e.g. data/yolo26s.pt) to auto-label person & obstacle_object in HCMC images",
    )
    args = parser.parse_args(argv)

    src_yolo = args.src_dir / "yolo_annotations"
    if not src_yolo.is_dir():
        print(f"[ERROR] Source yolo_annotations directory not found at: {src_yolo}", file=sys.stderr)
        return 1

    print("=" * 68)
    print("   CIVIWATCH MIXED TRAFFIC & PEDESTRIAN DATASET BUILDER")
    print("=" * 68)
    print(f"Source AIC dataset: {args.src_dir}")
    print(f"Output directory:   {args.output_dir}")
    print(f"Max samples/split:  {args.max_samples or 'ALL (~26,195 images)'}")
    print()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    yaml_file = build_dataset_yaml(args.output_dir)
    print(f"[1/3] Created dataset configuration: {yaml_file}")

    # Process train split
    print("[2/3] Converting and linking train split...")
    train_stats = convert_and_copy_split(
        "train",
        src_images_dir=src_yolo / "train/images",
        src_labels_dir=src_yolo / "train/labels",
        dst_images_dir=args.output_dir / "images/train",
        dst_labels_dir=args.output_dir / "labels/train",
        max_samples=args.max_samples,
    )
    print(f"      Train: {train_stats['images']} images, {train_stats['boxes']} boxes: {train_stats.get('classes')}")

    # Process val split
    print("[3/3] Converting and linking val split...")
    val_stats = convert_and_copy_split(
        "val",
        src_images_dir=src_yolo / "val/images",
        src_labels_dir=src_yolo / "val/labels",
        dst_images_dir=args.output_dir / "images/val",
        dst_labels_dir=args.output_dir / "labels/val",
        max_samples=max(1, args.max_samples // 5) if args.max_samples else 0,
    )
    print(f"      Val:   {val_stats['images']} images, {val_stats['boxes']} boxes: {val_stats.get('classes')}")

    # Inject balanced pedestrian samples into train split
    injected_p = inject_pedestrian_samples(args.output_dir, count=args.pedestrian_count)
    print(f"[INFO] Injected {injected_p} pedestrian-balanced frames into train split to prevent forgetting.")

    pseudo_stats: dict[str, Any] = {}
    if args.pseudo_label_model is not None and args.pseudo_label_model.is_file():
        print(f"[4/4] Auto-labeling missing person (0) and obstacle_object (5) via {args.pseudo_label_model}...")
        p_train = pseudo_label_missing_classes(
            args.output_dir / "images/train",
            args.output_dir / "labels/train",
            args.pseudo_label_model,
        )
        p_val = pseudo_label_missing_classes(
            args.output_dir / "images/val",
            args.output_dir / "labels/val",
            args.pseudo_label_model,
        )
        pseudo_stats = {"train": p_train, "val": p_val}
        print(f"      Pseudo-labels added -> Train: {p_train} | Val: {p_val}")

    manifest_info = {
        "dataset_name": "CiviWatch-Mixed-Traffic-HCMC-v1",
        "classes": CIVIWATCH_CLASSES,
        "input_resolution": [640, 640],
        "train_samples": train_stats["images"] + injected_p,
        "val_samples": val_stats["images"],
        "pseudo_labels": pseudo_stats,
        "dataset_yaml": str(yaml_file.relative_to(ROOT) if yaml_file.is_relative_to(ROOT) else yaml_file),
    }
    manifest_dst = args.output_dir / "manifest.json"
    manifest_dst.write_text(json.dumps(manifest_info, indent=2), encoding="utf-8")
    print(f"[SAVED] Generated dataset manifest: {manifest_dst}")
    print("\nDataset preparation completed successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
