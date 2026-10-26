"""Evaluate one local clip through the full edge pipeline (decode -> detect -> track -> incident).

Prints event-level metrics: detections, incident events by taxonomy/lifecycle/severity, pose outcomes
and latency. Ground-truth labels are NOT implied: without an annotated label file this reports what the
pipeline produced, not precision/recall.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.edge.outbox import EventOutbox  # noqa: E402
from apps.edge.pipeline import PerceptionPipeline  # noqa: E402
from apps.edge.pose import PoseManager, PoseScheduler, RtmposeEstimator  # noqa: E402
from apps.edge.recorder import FileRecorder  # noqa: E402


def events_from_outbox(outbox: EventOutbox) -> list[dict[str, Any]]:
    """Persisted incidents as flat records (EventOutbox.pending() rows carry a parsed 'event')."""
    events: list[dict[str, Any]] = []
    for row in outbox.pending():
        snapshot = row["event"]
        payload = snapshot.get("payload", {})
        events.append(
            {
                "taxonomy": payload.get("taxonomy"),
                "lifecycle": payload.get("lifecycle"),
                "severity": payload.get("severity"),
                "origin": snapshot.get("origin"),
                "revision": snapshot.get("revision"),
                "pose_status": (payload.get("pose_evidence") or {}).get("status"),
            }
        )
    return events


def evaluate(video_path: Path, *, sample_fps: float, max_frames: int, with_pose: bool) -> dict[str, Any]:
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(native_fps / sample_fps)))

    with tempfile.TemporaryDirectory(prefix="ai-camera-eval-") as tmp:
        tmp_path = Path(tmp)
        recorder = FileRecorder(tmp_path / "ring", ring_seconds=60)
        outbox = EventOutbox(tmp_path / "events.sqlite3")
        manager = scheduler = None
        if with_pose:
            manager = PoseManager(
                estimator=RtmposeEstimator(
                    manifest_path=ROOT / "models/rtmpose-tiny/manifest.json",
                    model_path=ROOT / "models/rtmpose-tiny/rtmpose_tiny.onnx",
                ),
                max_queue_size=30,
                max_cached_frames=30,
            )
            scheduler = PoseScheduler(batch_budget=8)
        pipeline = PerceptionPipeline(
            recorder=recorder,
            outbox=outbox,
            manifest_path=ROOT / "models/yolox-tiny/manifest.json",
            model_path=ROOT / "data/oracle/yolox_tiny.onnx",
            pose_manager=manager,
            pose_scheduler=scheduler,
            origin="replay",
        )

        latencies: list[float] = []
        class_counts: dict[str, int] = {}
        detections = 0
        pose_outcomes = 0
        emitted = 0
        frame_idx = 0
        processed = 0
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break
            if frame_idx % step:
                frame_idx += 1
                continue
            if max_frames and processed >= max_frames:
                break
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            started = time.perf_counter()
            emitted_events = pipeline.process_frame(rgb, timestamp=frame_idx / native_fps, frame_id=frame_idx)
            latencies.append((time.perf_counter() - started) * 1000.0)
            observation = pipeline.last_observation or {}
            dets = observation.get("detections", [])
            detections += len(dets)
            for det in dets:
                label = det.get("label", "unknown")
                class_counts[label] = class_counts.get(label, 0) + 1
            pose_outcomes += len(observation.get("pose_outcomes", []))
            # process_frame already persists an incident to the outbox; only count what it emitted.
            emitted += len(emitted_events or [])
            processed += 1
            frame_idx += 1
        cap.release()

        events = events_from_outbox(outbox)
        by_taxonomy: dict[str, int] = {}
        for event in events:
            by_taxonomy[event["taxonomy"]] = by_taxonomy.get(event["taxonomy"], 0) + 1
        return {
            "video": video_path.name,
            "origin": "replay",
            "with_pose": with_pose,
            "native_fps": native_fps,
            "frames_processed": processed,
            "detections": detections,
            "class_counts": class_counts,
            "pose_outcomes": pose_outcomes,
            "events": events,
            "events_by_taxonomy": by_taxonomy,
            "event_count": len(events),
            "event_count_emitted": emitted,
            "latency_ms": {
                "p50": round(statistics.median(latencies), 2) if latencies else None,
                "p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", action="append", required=True, help="local clip; repeatable")
    parser.add_argument("--sample-fps", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=0, help="0 = every sampled frame")
    parser.add_argument("--pose", action="store_true", help="also run pose estimation")
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args()
    results = []
    for item in args.video:
        results.append(
            evaluate(Path(item), sample_fps=args.sample_fps, max_frames=args.max_frames, with_pose=args.pose)
        )
    payload = json.dumps(results, indent=2, sort_keys=True)
    if args.output_json:
        Path(args.output_json).write_text(payload)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
