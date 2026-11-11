"""Evaluate Vehicle Incident Engine on test video clips.

Runs the shared PerceptionPipeline with explicit vehicle/tracker configuration and local persistence.
Reports detections, tracking, interaction types, and accident events.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.edge.oracle_detector import OracleDetector
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import ByteTracker
from apps.edge.vehicle_incident import VehicleIncidentEngine
from tools.replay_runner import run_replay_session
from tools.eval_clip import extract_effective_config


def evaluate_clip(
    video_path: str | Path,
    detector: OracleDetector,
    *,
    sample_fps: float = 10.0,
    max_frames: int = 300,
    min_moving_speed: float = 8.0,
    impact_deceleration: float = 50.0,
) -> dict[str, Any]:
    vpath = Path(video_path)
    created_pipeline: list[PerceptionPipeline] = []

    def pipeline_factory(tmp_root: Path, width: int, height: int, native_fps: float) -> tuple[PerceptionPipeline, EventOutbox]:
        recorder = FileRecorder(tmp_root / "ring", ring_seconds=60)
        outbox = EventOutbox(tmp_root / "events.sqlite3")
        tracker = ByteTracker(high_threshold=0.25, low_threshold=0.08, match_threshold=0.3)
        engine = VehicleIncidentEngine(
            min_moving_speed=min_moving_speed,
            impact_deceleration_threshold=impact_deceleration,
        )
        p = PerceptionPipeline(
            recorder=recorder,
            outbox=outbox,
            detector=detector,
            tracker=tracker,
            incident_engines=[engine],
            origin="replay",
        )
        created_pipeline.append(p)
        return p, outbox

    res = run_replay_session(
        vpath,
        pipeline_factory,
        sample_fps=sample_fps,
        max_frames=max_frames,
        fail_fast=True,
    )

    events: list[dict[str, Any]] = []
    for snapshot in res.outbox_events:
        p = snapshot.get("payload", {})
        eid = snapshot.get("event_id")
        meta = res.emitted_meta.get(str(eid)) if eid is not None else None
        f_idx = meta[0] if meta else None
        t_stamp = meta[1] if meta else float(p.get("anchor_time", 0.0))
        events.append(
            {
                "frame": f_idx,
                "timestamp": round(t_stamp, 2),
                "interaction_type": p.get("interaction_type"),
                "severity": p.get("severity"),
                "confidence": p.get("confidence"),
                "primary_track": p.get("track_id"),
                "involved_tracks": p.get("track_ids"),
                "event_id": eid,
                "taxonomy": p.get("taxonomy"),
                "origin": snapshot.get("origin"),
                "stream_session_id": snapshot.get("stream_session_id"),
                "details": p,
            }
        )

    active_pipeline = created_pipeline[0] if created_pipeline else res.pipeline
    assert active_pipeline is not None
    effective_cfg = extract_effective_config(
        active_pipeline,
        sample_fps=sample_fps,
        max_frames=max_frames,
    )
    return {
        "video": vpath.name,
        "origin": "replay",
        "frames_processed": res.frames_processed,
        "detections": res.total_detections,
        "classes": res.class_counts,
        "detection_status_counts": res.detection_status_counts,
        "events": events,
        "event_count": len(events),
        "event_count_emitted": res.emitted_count,
        "effective_config": effective_cfg,
    }

def main():
    parser = argparse.ArgumentParser(description="Evaluate vehicle incident detection on video clips")
    parser.add_argument("--video", nargs="+", help="Path(s) to video files")
    parser.add_argument("--sample-fps", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=300)
    parser.add_argument("--impact-decel", type=float, default=150.0)
    parser.add_argument("--min-speed", type=float, default=20.0)
    args = parser.parse_args()

    detector = OracleDetector(ROOT / "models/yolox-tiny/manifest.json", ROOT / "data/oracle/yolox_tiny.onnx")

    videos = args.video
    if not videos:
        # Default test suite: 1 normal 1080p, 1 UCF-crime, 3 DAD-A3D positive, 3 DAD-A3D negative
        videos = [
            "data/benchmark/intersection_traffic_1080p.mp4",
            "data/benchmark/ucfcrime/RoadAccidents002_x264.mp4",
        ]
        dad_pos = Path("/media/tieubaoca/HDD1/F/dataset/video/fall-accident/DAD_A3D/videos/testing/positive")
        dad_neg = Path("/media/tieubaoca/HDD1/F/dataset/video/fall-accident/DAD_A3D/videos/testing/negative")
        if dad_pos.exists():
            videos.extend([str(p) for p in sorted(dad_pos.glob("*.mp4"))[:5]])
        if dad_neg.exists():
            videos.extend([str(p) for p in sorted(dad_neg.glob("*.mp4"))[:5]])

    print(f"=== Evaluating {len(videos)} video clips ===")
    results = []
    try:
        for vid in videos:
            vpath = Path(vid)
            if not vpath.exists() and args.video is None:
                print(f"SKIP (not found): {vid}")
                continue
            res = evaluate_clip(
                vpath,
                detector,
                sample_fps=args.sample_fps,
                max_frames=args.max_frames,
                min_moving_speed=args.min_speed,
                impact_deceleration=args.impact_decel,
            )
            results.append(res)
            tag = "EVENT!" if res["event_count"] > 0 else "zero events"
            print(
                f"[{tag}] {res['video']}: frames={res['frames_processed']}, "
                f"dets={res['detections']}, classes={res['classes']}, events={res['event_count']}"
            )
            print(f"Effective configuration: {json.dumps(res['effective_config'], sort_keys=True)}")
            for ev in res["events"]:
                print(
                    f"    -> Frame {ev['frame']} (t={ev['timestamp']}s): "
                    f"type={ev['interaction_type']}, sev={ev['severity']}, "
                    f"conf={ev['confidence']}, tracks={ev['involved_tracks']}"
                )
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1

    print("\n=== Summary ===")
    total_clips = len(results)
    clips_with_events = sum(1 for r in results if r["event_count"] > 0)
    total_events = sum(r["event_count"] for r in results)
    print(f"Total clips evaluated: {total_clips}")
    print(f"Clips with detected events: {clips_with_events}")
    print(f"Total events emitted: {total_events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
