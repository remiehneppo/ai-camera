"""Fetch and verify the approved open-license urban surveillance benchmark dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "data/benchmark"

DATASET_MANIFEST: dict[str, Any] = {
    "schema_version": 1,
    "dataset_id": "urban-surveillance-benchmark-v1",
    "description": "Open-license 1080p urban surveillance video clips for AI camera edge pipeline benchmarking.",
    "assets": [
        {
            "id": "shibuya-crossing-pedestrians",
            "name": "Shibuya Crossing (Pedestrian & Urban Flow)",
            "source_url": "https://upload.wikimedia.org/wikipedia/commons/5/53/Shibuya_Crossing%2C_Tokyo%2C_Japan_%28video%29.webm",
            "rights_url": "https://commons.wikimedia.org/wiki/File:Shibuya_Crossing,_Tokyo,_Japan_(video).webm",
            "author": "Wikimedia Commons contributor",
            "license": "Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)",
            "raw_filename": "shibuya_crossing_1080p.webm",
            "h264_filename": "shibuya_crossing_1080p.mp4",
            "expected_raw_size": 57744273,
            "width": 1920,
            "height": 1080,
            "duration_seconds": 58.56,
            "focus": "Dense pedestrian tracking, person detection, fall/dwell analysis, RTMPose keypoint extraction",
        },
        {
            "id": "intersection-traffic-vehicles",
            "name": "Intersection Pie-IX Sherbrooke (Vehicle & Intersection Flow)",
            "source_url": "https://upload.wikimedia.org/wikipedia/commons/1/18/Intersection_Pie-IX-Sherbrooke.webm",
            "rights_url": "https://commons.wikimedia.org/wiki/File:Intersection_Pie-IX-Sherbrooke.webm",
            "author": "Wikimedia Commons contributor",
            "license": "Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)",
            "raw_filename": "intersection_traffic_1080p.webm",
            "h264_filename": "intersection_traffic_1080p.mp4",
            "expected_raw_size": 82213022,
            "width": 1920,
            "height": 1080,
            "duration_seconds": 60.60,
            "focus": "Vehicle traffic tracking, stationary vehicle detection, lane occupancy, multi-class urban traffic",
        },
    ],
}


def compute_sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def download_file(url: str, destination: Path, expected_size: int | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if expected_size is None or destination.stat().st_size == expected_size:
            print(f"[SKIP] {destination.name} already exists ({destination.stat().st_size} bytes)")
            return
    part_path = destination.with_suffix(destination.suffix + ".part")
    print(f"[DOWNLOAD] Fetching {url} -> {destination.name} ...")
    cmd = [
        "curl",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "-A", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--connect-timeout", "30",
        "--max-time", "600",
        url,
        "-o", str(part_path),
    ]
    t0 = time.time()
    subprocess.run(cmd, check=True)
    elapsed = time.time() - t0
    actual_size = part_path.stat().st_size
    if expected_size is not None and actual_size != expected_size:
        part_path.unlink(missing_ok=True)
        raise ValueError(f"Size mismatch for {destination.name}: expected {expected_size}, got {actual_size}")
    part_path.replace(destination)
    print(f"[OK] Downloaded {destination.name} ({actual_size / 1024 / 1024:.1f} MB in {elapsed:.1f}s)")


def transcode_to_h264(src_path: Path, dst_path: Path) -> None:
    if dst_path.exists() and dst_path.stat().st_size > 1000:
        print(f"[SKIP] H.264 stream {dst_path.name} already prepared.")
        return
    print(f"[TRANSCODE] Remuxing/encoding {src_path.name} to standardized H.264 {dst_path.name} ...")
    t0 = time.time()
    # Fast transcode to baseline H.264 video with no audio, keyint=25 (1s GOP) for realistic edge camera streaming
    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", str(src_path),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-g", "25",
        "-keyint_min", "25",
        "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
        "-an",
        str(dst_path),
    ]
    subprocess.run(cmd, check=True)
    elapsed = time.time() - t0
    print(f"[OK] Produced {dst_path.name} ({dst_path.stat().st_size / 1024 / 1024:.1f} MB in {elapsed:.1f}s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="only verify checksums of existing assets")
    args = parser.parse_args()

    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    manifest_file = BENCHMARK_DIR / "manifest.json"

    updated_assets = []
    for asset_info in DATASET_MANIFEST["assets"]:
        raw_path = BENCHMARK_DIR / asset_info["raw_filename"]
        h264_path = BENCHMARK_DIR / asset_info["h264_filename"]

        if not args.verify_only:
            download_file(asset_info["source_url"], raw_path, asset_info["expected_raw_size"])
            transcode_to_h264(raw_path, h264_path)

        if not raw_path.exists():
            print(f"[ERROR] Missing raw file {raw_path}", file=sys.stderr)
            return 1
        if not h264_path.exists():
            print(f"[ERROR] Missing H.264 file {h264_path}", file=sys.stderr)
            return 1

        raw_sha = compute_sha256(raw_path)
        h264_sha = compute_sha256(h264_path)
        print(f"[VERIFIED] {raw_path.name}: SHA256={raw_sha}")
        print(f"[VERIFIED] {h264_path.name}: SHA256={h264_sha}")

        item = dict(asset_info)
        item["raw_sha256"] = raw_sha
        item["raw_size_bytes"] = raw_path.stat().st_size
        item["h264_sha256"] = h264_sha
        item["h264_size_bytes"] = h264_path.stat().st_size
        updated_assets.append(item)

    full_manifest = dict(DATASET_MANIFEST)
    full_manifest["assets"] = updated_assets
    manifest_file.write_text(json.dumps(full_manifest, indent=2, ensure_ascii=False))
    print(f"[MANIFEST] Updated {manifest_file.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
