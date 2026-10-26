"""Turn A3D per-frame accident labels into a clip label set (needs the external id mapping).

The A3D frame labels are keyed `<youtube_id>_<index>.txt` (one line per frame, `<frame> <0|1>`),
while the released clips are numbered `000001.mp4`. That mapping is NOT shipped with the local
dataset copy, so it must be supplied explicitly (`--mapping`): a JSON object from label stem to
clip path. This tool then emits one jsonl record per clip that a scorer can consume; it never
guesses the mapping.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile
from typing import Any

FPS = 25.0


def load_frame_labels(source: Path) -> dict[str, list[int]]:
    """stem -> per-frame 0/1 labels (zip or directory of `<youtube_id>_<index>.txt`)."""
    labels: dict[str, list[int]] = {}
    if source.is_dir():
        items = [(path.name, path.read_text(errors="replace")) for path in sorted(source.glob("*.txt"))]
    elif source.suffix == ".zip":
        with zipfile.ZipFile(source) as archive:
            items = [
                (Path(name).name, archive.read(name).decode("utf-8", "replace"))
                for name in sorted(archive.namelist())
                if name.endswith(".txt")
            ]
    else:
        raise ValueError("frame labels must be a .zip or a directory of .txt files")
    for name, text in items:
        stem = Path(name).stem
        flags = []
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] in ("0", "1"):
                flags.append(int(parts[1]))
        if flags:
            labels[stem] = flags
    return labels


def build_labels(labels: dict[str, list[int]], mapping: dict[str, str], videos_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """`onset_frame` is a 0-based index into the decoded clip (the label file numbers frames from 1)."""
    records: list[dict[str, Any]] = []
    problems: list[str] = []
    for stem, flags in sorted(labels.items()):
        relative = mapping.get(stem)
        if relative is None:
            problems.append("no mapping for " + stem)
            continue
        clip = videos_root / relative
        if not clip.is_file():
            problems.append("clip missing for " + stem + ": " + str(clip))
            continue
        onset = next((index for index, flag in enumerate(flags) if flag == 1), None)
        records.append(
            {
                "clip": str(clip),
                "label_stem": stem,
                "frames": len(flags),
                "positive": onset is not None,
                "onset_frame": onset,
                "onset_seconds": round(onset / FPS, 3) if onset is not None else None,
                "duration_seconds": round(len(flags) / FPS, 3),
            }
        )
    for stem in mapping:
        if stem not in labels:
            problems.append("mapping entry without a label file: " + stem)
    return records, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame-labels", required=True, help="A3D_frame_labels.zip or its extracted directory")
    parser.add_argument("--mapping", required=True, help="JSON object: label stem -> clip path relative to --videos-root")
    parser.add_argument("--videos-root", required=True, help="root that contains the numbered clips (e.g. DAD_A3D/)")
    parser.add_argument("--output-jsonl", default=None)
    parser.add_argument("--allow-partial", action="store_true", help="write labels even when the mapping is incomplete")
    args = parser.parse_args()

    labels = load_frame_labels(Path(args.frame_labels))
    mapping = json.loads(Path(args.mapping).read_text())
    if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
        print("[ERROR] mapping must be a JSON object of label stem -> clip path", file=sys.stderr)
        return 2
    records, problems = build_labels(labels, mapping, Path(args.videos_root))
    report = {
        "label_files": len(labels),
        "mapping_entries": len(mapping),
        "labelled_clips": len(records),
        "positives": sum(1 for record in records if record["positive"]),
        "problems": problems[:20],
        "problem_count": len(problems),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if problems and not args.allow_partial:
        print("[ERROR] mapping is incomplete or inconsistent; pass --allow-partial to write what matched", file=sys.stderr)
        return 1
    if args.output_jsonl:
        Path(args.output_jsonl).write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
