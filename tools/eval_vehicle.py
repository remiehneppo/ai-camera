"""Evaluate Vehicle Incident Engine on test video clips.

Runs OracleDetector (YOLOX-Tiny) -> ByteTracker -> VehicleIncidentEngine.
Reports detections, tracking, interaction types, and accident events.
"""
from __future__ import annotations

import argparse
import cv2
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.edge.oracle_detector import OracleDetector
from apps.edge.tracker import ByteTracker
from apps.edge.vehicle_incident import VehicleIncidentEngine


def evaluate_clip(
    video_path: str | Path,
    detector: OracleDetector,
    *,
    sample_fps: float = 10.0,
    max_frames: int = 300,
    min_moving_speed: float = 8.0,
    impact_deceleration: float = 50.0,
) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"video": str(video_path), "error": "cannot open video"}

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(native_fps / sample_fps)))
    
    tracker = ByteTracker(high_threshold=0.25, low_threshold=0.08, match_threshold=0.3)
    engine = VehicleIncidentEngine(
        min_moving_speed=min_moving_speed,
        impact_deceleration_threshold=impact_deceleration,
    )

    frame_idx = 0
    processed = 0
    events = []
    det_count = 0
    classes: dict[str, int] = {}

    try:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break
            if frame_idx % step != 0:
                frame_idx += 1
                continue
            if max_frames and processed >= max_frames:
                break

            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            ts = round(frame_idx / native_fps, 4)
            obs = detector.detect(rgb, {
                "camera_id": "eval-cam",
                "stream_session_id": "eval-sess",
                "core_epoch": 1,
                "origin": "replay",
                "frame_id": frame_idx,
                "pts": frame_idx,
                "time_base": f"1/{int(round(native_fps))}",
                "event_time": ts,
            })
            dets = obs.get("detections", [])
            for d in dets:
                if "bbox" not in d and "bbox_xyxy" in d:
                    d["bbox"] = d["bbox_xyxy"]
            det_count += len(dets)
            for d in dets:
                lbl = d["label"]
                classes[lbl] = classes.get(lbl, 0) + 1

            tracks = tracker.update(dets, timestamp=ts)
            emitted = engine.process_tracks(tracks, timestamp=ts)
            for ev in emitted:
                p = ev["payload"]
                events.append({
                    "frame": frame_idx,
                    "timestamp": round(ts, 2),
                    "interaction_type": p.get("interaction_type"),
                    "severity": p.get("severity"),
                    "confidence": p.get("confidence"),
                    "primary_track": p.get("track_id"),
                    "involved_tracks": p.get("track_ids"),
                })
            processed += 1
            frame_idx += 1
    finally:
        cap.release()
    return {
        "video": Path(video_path).name,
        "frames_processed": processed,
        "detections": det_count,
        "classes": classes,
        "events": events,
        "event_count": len(events),
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
    for vid in videos:
        vpath = Path(vid)
        if not vpath.exists():
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
        tag = "EVENT!" if res["event_count"] > 0 else "clean (0 events)"
        print(f"[{tag}] {res['video']}: frames={res['frames_processed']}, dets={res['detections']}, classes={res['classes']}, events={res['event_count']}")
        for ev in res["events"]:
            print(f"    -> Frame {ev['frame']} (t={ev['timestamp']}s): type={ev['interaction_type']}, sev={ev['severity']}, conf={ev['confidence']}, tracks={ev['involved_tracks']}")

    print("\n=== Summary ===")
    total_clips = len(results)
    clips_with_events = sum(1 for r in results if r["event_count"] > 0)
    total_events = sum(r["event_count"] for r in results)
    print(f"Total clips evaluated: {total_clips}")
    print(f"Clips with detected events: {clips_with_events}")
    print(f"Total events emitted: {total_events}")


if __name__ == "__main__":
    main()
