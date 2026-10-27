"""Fetch and verify approved HD/2MP fixed traffic camera surveillance video clips.

Enforces project ODD constraints:
- ONLY fixed traffic CCTV cameras (no dashcams, no handhelds, no UAVs).
- ONLY HD to 2MP resolutions (>= 720p / 1280x720 up to 1080p / 1920x1080).
- Curated from Open-Space-Reasoning/AccidentBench (land_space short fixed CCTV cameras).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "data/benchmark/traffic_cctv_hd"

CCTV_CLIPS = [
    {"name": f"{i:06d}.mp4", "id": i}
    for i in range(1, 11)
]
BASE_URL = "https://huggingface.co/datasets/Open-Space-Reasoning/AccidentBench/resolve/main/land_space/short/videos"


def compute_sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def probe_video(path: Path) -> dict[str, str | int | float]:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration,nb_frames",
        "-of", "default=noprint_wrappers=1", str(path)
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out: dict[str, str | int | float] = {}
    for line in p.stdout.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k in ("width", "height", "nb_frames"):
                out[k] = int(v)
            elif k == "duration":
                out[k] = float(v)
            else:
                out[k] = v
    return out


def fetch_and_verify(dest_dir: Path, count: int = 10) -> list[dict]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    verified = []
    
    print(f"Fetching {count} HD CCTV accident video clips into {dest_dir}...")
    for item in CCTV_CLIPS[:count]:
        fname = str(item["name"])
        dst = dest_dir / fname
        url = f"{BASE_URL}/{fname}"
        
        if not dst.exists() or dst.stat().st_size == 0:
            print(f"Downloading {fname} from {url}...")
            urllib.request.urlretrieve(url, dst)
        
        info = probe_video(dst)
        w = int(info.get("width", 0))
        h = int(info.get("height", 0))
        if w < 1280 or h < 720:
            raise ValueError(f"Clip {fname} resolution {w}x{h} does not satisfy HD requirement (>= 1280x720)")
        
        sha = compute_sha256(dst)
        rec = {
            "file": fname,
            "width": w,
            "height": h,
            "fps": info.get("r_frame_rate"),
            "duration_seconds": info.get("duration"),
            "size_bytes": dst.stat().st_size,
            "sha256": sha,
            "odd": "fixed_traffic_cctv_720p",
            "source": f"AccidentBench/{fname}",
        }
        verified.append(rec)
        print(f"  [OK] {fname}: {w}x{h} @ {info.get('r_frame_rate')}fps, {info.get('duration')}s, sha256={sha[:12]}...")

    manifest_path = dest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(verified, indent=2), encoding="utf-8")
    print(f"Wrote manifest with {len(verified)} clips to {manifest_path}")
    return verified


def main():
    parser = argparse.ArgumentParser(description="Fetch and verify approved HD/2MP fixed CCTV traffic datasets")
    parser.add_argument("--count", type=int, default=10, help="Number of clips to fetch (default 10)")
    parser.add_argument("--out", type=str, default=str(DATASET_DIR), help="Output directory")
    args = parser.parse_args()
    
    fetch_and_verify(Path(args.out), count=args.count)


if __name__ == "__main__":
    main()
