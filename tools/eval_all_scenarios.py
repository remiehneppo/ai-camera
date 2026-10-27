"""Comprehensive Edge Multi-Scenario Evaluation Suite.

Evaluates test video datasets across all edge perception alert engines:
1. US09 Person-Down (IncidentEngine + RTMPose-Tiny):
   - person_fall
   - person_lying_persistent
   - person_on_stationary_vehicle
2. US08 Vehicle Incidents (VehicleIncidentEngine):
   - vehicle_vehicle
   - vehicle_pedestrian
   - vehicle_rollover_or_barrier
3. US05 Illegal Parking (ParkingIncidentEngine):
   - illegal_parking (dwell time tracking)
4. US06 Crowd Incidents (CrowdIncidentEngine):
   - crowd_concentration (layer 1)
   - suspected_disorder (layer 2)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.edge.crowd_incident import CrowdIncidentEngine
from apps.edge.incident import IncidentEngine
from apps.edge.oracle_detector import OracleDetector
from apps.edge.parking_incident import ParkingIncidentEngine
from apps.edge.pose import PoseManager, PoseScheduler, RtmposeEstimator
from apps.edge.tracker import ByteTracker
from apps.edge.vehicle_incident import VehicleIncidentEngine


def evaluate_video(
    video_path: Path,
    detector: OracleDetector,
    *,
    sample_fps: float = 10.0,
    max_frames: int = 300,
    with_pose: bool = True,
    parking_max_dwell: float = 20.0,
    crowd_min_count: int = 5,
    crowd_min_duration: float = 3.0,
    impact_deceleration: float = 120.0,
) -> dict[str, Any]:
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"failed to open video: {video_path}")

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, int(round(native_fps / sample_fps)))

    # Pose estimator
    pose_mgr = None
    pose_scheduler = None
    if with_pose:
        pose_estimator = RtmposeEstimator(
            manifest_path=ROOT / "models/rtmpose-tiny/manifest.json",
            model_path=ROOT / "models/rtmpose-tiny/rtmpose_tiny.onnx",
        )
        pose_mgr = PoseManager(estimator=pose_estimator, max_queue_size=30, max_cached_frames=30)
        pose_scheduler = PoseScheduler(batch_budget=8)

    # Multi-object tracker
    tracker = ByteTracker(high_threshold=0.25, low_threshold=0.08, match_threshold=0.3)

    # 4 Alert Feature Engines
    fall_engine = IncidentEngine(standing_aspect_ratio=0.85, lying_aspect_ratio=1.2, min_drop_velocity=15.0)
    vehicle_engine = VehicleIncidentEngine(impact_deceleration_threshold=impact_deceleration, min_moving_speed=15.0)
    parking_engine = ParkingIncidentEngine(max_dwell_seconds=parking_max_dwell)
    crowd_engine = CrowdIncidentEngine(min_crowd_count=crowd_min_count, min_duration_seconds=crowd_min_duration)

    frame_idx = 0
    processed = 0
    latencies: list[float] = []
    class_counts: dict[str, int] = {}
    total_detections = 0
    total_pose_inferences = 0
    emitted_events: list[dict[str, Any]] = []

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

            t0 = time.perf_counter()

            # 1. Detection
            obs = detector.detect(rgb, {
                "camera_id": "eval-cam",
                "stream_session_id": "eval-session",
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
                lbl = d["label"]
                class_counts[lbl] = class_counts.get(lbl, 0) + 1
            total_detections += len(dets)

            # 2. Tracking
            tracks = tracker.update(dets, timestamp=ts)

            # 3. Optional Pose Estimation
            pose_outcomes = []
            if pose_scheduler is not None and pose_mgr is not None:
                active_person_tracks = [t for t in tracks if t.state == "active" and t.label in ("person", "pedestrian")]
                pose_mgr.cache_frame("eval-cam", "eval-session", 1, frame_idx, rgb)
                cands = pose_scheduler.schedule_tracks(
                    tracks=active_person_tracks,
                    current_time=ts,
                    frame_id=frame_idx,
                    camera_id="eval-cam",
                    stream_session_id="eval-session",
                    core_epoch=1,
                )
                for cand in cands:
                    pose_mgr.submit_request(cand)
                pose_outcomes = pose_mgr.process_pending(current_time=ts)
                total_pose_inferences += len(pose_outcomes)

            # 4. Alert Modules
            ev_fall = fall_engine.process_tracks(tracks, timestamp=ts, pose_outcomes=pose_outcomes)
            ev_veh = vehicle_engine.process_tracks(tracks, timestamp=ts)
            ev_park = parking_engine.process_tracks(tracks, timestamp=ts)
            ev_crowd = crowd_engine.process_tracks(tracks, timestamp=ts)

            latencies.append((time.perf_counter() - t0) * 1000.0)

            for ev in (ev_fall or []):
                emitted_events.append({
                    "engine": "person_down",
                    "taxonomy": ev.get("taxonomy"),
                    "frame": frame_idx,
                    "timestamp": round(ts, 2),
                    "severity": ev.get("severity"),
                    "details": ev,
                })
            for ev in (ev_veh or []):
                p = ev.get("payload", {})
                emitted_events.append({
                    "engine": "vehicle_incident",
                    "taxonomy": p.get("taxonomy"),
                    "interaction_type": p.get("interaction_type"),
                    "frame": frame_idx,
                    "timestamp": round(ts, 2),
                    "severity": p.get("severity"),
                    "details": p,
                })
            for ev in (ev_park or []):
                p = ev.get("payload", {})
                emitted_events.append({
                    "engine": "illegal_parking",
                    "taxonomy": p.get("taxonomy"),
                    "frame": frame_idx,
                    "timestamp": round(ts, 2),
                    "severity": p.get("severity"),
                    "dwell_seconds": p.get("dwell_seconds"),
                    "details": p,
                })
            for ev in (ev_crowd or []):
                p = ev.get("payload", {})
                emitted_events.append({
                    "engine": "crowd_incident",
                    "taxonomy": p.get("taxonomy"),
                    "frame": frame_idx,
                    "timestamp": round(ts, 2),
                    "severity": p.get("severity"),
                    "crowd_count": p.get("crowd_count"),
                    "details": p,
                })

            processed += 1
            frame_idx += 1
    finally:
        cap.release()

    events_by_taxonomy: dict[str, int] = {}
    for ev in emitted_events:
        tax = ev["taxonomy"]
        events_by_taxonomy[tax] = events_by_taxonomy.get(tax, 0) + 1

    return {
        "video": video_path.name,
        "resolution": f"{width}x{height}",
        "native_fps": native_fps,
        "frames_processed": processed,
        "total_detections": total_detections,
        "class_counts": class_counts,
        "total_pose_inferences": total_pose_inferences,
        "event_count": len(emitted_events),
        "events_by_taxonomy": events_by_taxonomy,
        "events": emitted_events,
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate video clips across all edge perception engines")
    parser.add_argument("--videos", nargs="+", help="Video path(s) to evaluate")
    parser.add_argument("--sample-fps", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=200)
    parser.add_argument("--no-pose", action="store_true", help="Disable pose estimation")
    parser.add_argument("--json-out", type=str, default="", help="Path to write JSON output")
    args = parser.parse_args()

    detector = OracleDetector(ROOT / "models/yolox-tiny/manifest.json", ROOT / "data/oracle/yolox_tiny.onnx")

    targets = args.videos
    if not targets:
        # Benchmark suite spanning different scenarios and ODDs
        targets = [
            # 1. Fall Positive 1080p
            "data/benchmark/unidata/fall_0001.mp4",
            # 2. Fall Negative / Normal ADL 1080p
            "data/benchmark/unidata/fall_0003.mp4",
            # 3. Dense pedestrian + vehicle crossing 1080p (Shibuya)
            "data/benchmark/shibuya_crossing_1080p.mp4",
            # 4. Normal vehicle intersection 1080p
            "data/benchmark/intersection_traffic_1080p.mp4",
            # 5. UCF-Crime Accident Positive (320x240)
            "data/benchmark/ucfcrime/RoadAccidents002_x264.mp4",
            # 6. UCF-Crime Fighting (320x240)
            "data/benchmark/ucfcrime/Fighting002_x264.mp4",
        ]
        # 7-8. DAD_A3D Accident vs Normal (720p)
        dad_pos = Path("/media/tieubaoca/HDD1/F/dataset/video/fall-accident/DAD_A3D/videos/testing/positive/000456.mp4")
        dad_neg = Path("/media/tieubaoca/HDD1/F/dataset/video/fall-accident/DAD_A3D/videos/testing/negative/000830.mp4")
        if dad_pos.exists():
            targets.append(str(dad_pos))
        if dad_neg.exists():
            targets.append(str(dad_neg))

    all_results = []
    print(f"\n=======================================================")
    print(f"   AI CAMERA MULTI-SCENARIO EDGE PERCEPTION BENCHMARK")
    print(f"=======================================================")
    print(f"Evaluating {len(targets)} test video clips (sample_fps={args.sample_fps}, max_frames={args.max_frames})...\n")

    for vpath_str in targets:
        vpath = Path(vpath_str)
        if not vpath.exists():
            print(f"SKIP: {vpath_str} (file not found)")
            continue

        res = evaluate_video(
            vpath,
            detector,
            sample_fps=args.sample_fps,
            max_frames=args.max_frames,
            with_pose=not args.no_pose,
        )
        all_results.append(res)

        print(f"-------------------------------------------------------------------------------")
        print(f"Video: {res['video']} [{res['resolution']} @ {res['native_fps']}fps] -> {res['frames_processed']} frames evaluated")
        print(f"Detections: {res['total_detections']} (classes: {res['class_counts']}) | Pose: {res['total_pose_inferences']}")
        print(f"Latency P50: {res['latency_ms']['p50']}ms, P95: {res['latency_ms']['p95']}ms")
        print(f"Events Emitted: {res['event_count']} -> By Taxonomy: {res['events_by_taxonomy']}")
        for ev in res["events"][:8]:
            extra = ""
            if "interaction_type" in ev:
                extra += f" type={ev['interaction_type']}"
            if "dwell_seconds" in ev:
                extra += f" dwell={ev['dwell_seconds']:.1f}s"
            if "crowd_count" in ev:
                extra += f" count={ev['crowd_count']}"
            print(f"   [{ev['engine']}] {ev['taxonomy']} (t={ev['timestamp']}s, sev={ev['severity']}){extra}")
        if len(res["events"]) > 8:
            print(f"   ... and {len(res['events']) - 8} more events")
        print()

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(all_results, indent=2), encoding="utf-8")
        print(f"Wrote full JSON report to: {args.json_out}")


if __name__ == "__main__":
    main()
