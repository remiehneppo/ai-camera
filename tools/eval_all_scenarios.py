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
from fractions import Fraction
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

import tempfile

from apps.edge.crowd_incident import CrowdIncidentEngine
from apps.edge.incident import IncidentEngine
from apps.edge.oracle_detector import OracleDetector
from apps.edge.outbox import EventOutbox
from apps.edge.parking_incident import ParkingIncidentEngine
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.pose import PoseManager, RtmposeEstimator
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import ByteTracker
from apps.edge.vehicle_incident import VehicleIncidentEngine
from tools.eval_clip import LATENCY_SCOPE, extract_effective_config

TAXONOMY_ENGINE_MAP: dict[str, str] = {
    "person_fall": "person_down",
    "person_lying_persistent": "person_down",
    "person_on_stationary_vehicle": "person_down",
    "vehicle_incident": "vehicle_incident",
    "vehicle_vehicle": "vehicle_incident",
    "vehicle_pedestrian": "vehicle_incident",
    "vehicle_rollover_or_barrier": "vehicle_incident",
    "illegal_parking": "illegal_parking",
    "crowd_concentration": "crowd_incident",
    "suspected_disorder": "crowd_incident",
}

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
    try:
        if not cap.isOpened():
            raise RuntimeError(f"failed to open video: {video_path}")
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        step = max(1, int(round(native_fps / sample_fps)))
        with tempfile.TemporaryDirectory(prefix="ai-camera-eval-all-") as tmp:
            tmp_path = Path(tmp)
            recorder = FileRecorder(tmp_path / "ring", ring_seconds=60)
            outbox = EventOutbox(tmp_path / "events.sqlite3")

            pose_mgr = None
            if with_pose:
                pose_estimator = RtmposeEstimator(
                    manifest_path=ROOT / "models/rtmpose-tiny/manifest.json",
                    model_path=ROOT / "models/rtmpose-tiny/rtmpose_tiny.onnx",
                )
                pose_mgr = PoseManager(estimator=pose_estimator, max_queue_size=30, max_cached_frames=30)

            tracker = ByteTracker(high_threshold=0.25, low_threshold=0.08, match_threshold=0.3)
            fall_engine = IncidentEngine(
                standing_aspect_ratio=0.85,
                lying_aspect_ratio=1.2,
                min_drop_velocity=15.0,
                min_lying_duration=3.0,
                cooldown_seconds=30.0,
            )
            vehicle_engine = VehicleIncidentEngine(
                impact_deceleration_threshold=impact_deceleration,
                min_moving_speed=15.0,
            )
            parking_engine = ParkingIncidentEngine(max_dwell_seconds=parking_max_dwell)
            crowd_engine = CrowdIncidentEngine(
                min_crowd_count=crowd_min_count,
                min_duration_seconds=crowd_min_duration,
            )
            pipeline = PerceptionPipeline(
                recorder=recorder,
                outbox=outbox,
                detector=detector,
                tracker=tracker,
                incident_engines=[fall_engine, vehicle_engine, parking_engine, crowd_engine],
                pose_manager=pose_mgr,
                origin="replay",
            )

            frame_idx = 0
            processed = 0
            latencies: list[float] = []
            class_counts: dict[str, int] = {}
            detection_status_counts: dict[str, int] = {}
            pose_status_counts: dict[str, int] = {}
            total_detections = 0
            total_pose_inferences = 0
            emitted_meta: dict[str, tuple[int, float]] = {}

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
                raw_ts = frame_idx / native_fps
                pts = round(raw_ts * 1_000_000)
                time_base = "1/1000000"
                ts = float(pts * Fraction(time_base))

                t0 = time.perf_counter()
                emitted_events = pipeline.process_frame(rgb, timestamp=ts, frame_id=frame_idx)
                latencies.append((time.perf_counter() - t0) * 1000.0)

                obs = pipeline.last_observation or {}
                detection_status = obs.get("detection_status")
                if detection_status:
                    detection_status_counts[detection_status] = (
                        detection_status_counts.get(detection_status, 0) + 1
                    )
                if detection_status not in {"ok", "ok_empty"}:
                    raise RuntimeError(
                        f"Detection failed on frame {frame_idx} of {video_path.name}: "
                        f"status={detection_status}, error={obs.get('error')}"
                    )

                dets = obs.get("detections", [])
                for d in dets:
                    lbl = d.get("label", "unknown")
                    class_counts[lbl] = class_counts.get(lbl, 0) + 1
                total_detections += len(dets)

                obs_pose_outcomes = obs.get("pose_outcomes", [])
                total_pose_inferences += len(obs_pose_outcomes)
                for po in obs_pose_outcomes:
                    st = po.get("status") if isinstance(po, dict) else getattr(po, "status", None)
                    if st:
                        pose_status_counts[st] = pose_status_counts.get(st, 0) + 1

                for ev in (emitted_events or []):
                    eid = ev.get("event_id")
                    if eid:
                        emitted_meta[eid] = (frame_idx, ts)

                processed += 1
                frame_idx += 1

            events: list[dict[str, Any]] = []
            for row in outbox.pending():
                snapshot = row["event"]
                p = snapshot.get("payload", {})
                tax = p.get("taxonomy") or snapshot.get("taxonomy")
                eng = TAXONOMY_ENGINE_MAP.get(str(tax), "incident")
                eid = snapshot.get("event_id")
                meta = emitted_meta.get(eid)
                f_idx = meta[0] if meta else None
                t_stamp = meta[1] if meta else float(p.get("anchor_time", 0.0))
                rec: dict[str, Any] = {
                    "engine": eng,
                    "taxonomy": tax,
                    "frame": f_idx,
                    "timestamp": round(t_stamp, 2),
                    "severity": p.get("severity"),
                    "event_id": eid,
                    "origin": snapshot.get("origin"),
                    "stream_session_id": snapshot.get("stream_session_id"),
                    "details": p,
                }
                if "interaction_type" in p:
                    rec["interaction_type"] = p["interaction_type"]
                if "dwell_seconds" in p:
                    rec["dwell_seconds"] = p["dwell_seconds"]
                if "crowd_count" in p:
                    rec["crowd_count"] = p["crowd_count"]
                events.append(rec)

            events_by_taxonomy: dict[str, int] = {}
            for ev in events:
                t = ev.get("taxonomy")
                if t:
                    events_by_taxonomy[t] = events_by_taxonomy.get(t, 0) + 1

            effective_cfg = extract_effective_config(
                pipeline,
                sample_fps=sample_fps,
                max_frames=max_frames,
                with_pose=with_pose,
            )
            return {
                "video": video_path.name,
                "origin": "replay",
                "resolution": f"{width}x{height}",
                "native_fps": native_fps,
                "frames_processed": processed,
                "total_detections": total_detections,
                "class_counts": class_counts,
                "total_pose_inferences": total_pose_inferences,
                "detection_status_counts": detection_status_counts,
                "pose_status_counts": pose_status_counts,
                "event_count": len(events),
                "events_by_taxonomy": events_by_taxonomy,
                "events": events,
                "latency_ms": {
                    "p50": round(statistics.median(latencies), 2) if latencies else None,
                    "p95": (
                        round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2)
                        if latencies
                        else None
                    ),
                    "scope": LATENCY_SCOPE,
                },
                "latency_scope": LATENCY_SCOPE,
                "effective_config": effective_cfg,
            }
    finally:
        cap.release()


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
            # 1. Fall Positive 1080p (Fixed camera, UniDataPro)
            "data/benchmark/unidata/fall_0001.mp4",
            # 2. Fall Negative / Normal ADL 1080p (Fixed camera, UniDataPro)
            "data/benchmark/unidata/fall_0003.mp4",
            # 3. Dense pedestrian + vehicle crossing 1080p (Fixed camera, Shibuya)
            "data/benchmark/shibuya_crossing_1080p.mp4",
            # 4. Normal vehicle intersection 1080p (Fixed camera, Pie-IX)
            "data/benchmark/intersection_traffic_1080p.mp4",
        ]
        # 5-8. HD 720p Fixed CCTV traffic camera accidents (ODD compliant, AccidentBench)
        cctv_hd_dir = ROOT / "data/benchmark/traffic_cctv_hd"
        if cctv_hd_dir.exists():
            for p in sorted(cctv_hd_dir.glob("*.mp4"))[:6]:
                targets.append(str(p))

    all_results = []
    print(f"\n=======================================================")
    print(f"   AI CAMERA MULTI-SCENARIO EDGE PERCEPTION BENCHMARK")
    print(f"=======================================================")
    print(f"Evaluating {len(targets)} test video clips (sample_fps={args.sample_fps}, max_frames={args.max_frames})...\n")

    for vpath_str in targets:
        vpath = Path(vpath_str)
        if not vpath.exists() and args.videos is None:
            print(f"SKIP: {vpath_str} (file not found)")
            continue

        try:
            res = evaluate_video(
                vpath,
                detector,
                sample_fps=args.sample_fps,
                max_frames=args.max_frames,
                with_pose=not args.no_pose,
            )
        except Exception as exc:
            print(f"Evaluation failed on {vpath_str}: {exc}", file=sys.stderr)
            return 1
        all_results.append(res)

        print(f"-------------------------------------------------------------------------------")
        print(
            f"Video: {res['video']} [{res['resolution']} @ {res['native_fps']}fps] -> "
            f"{res['frames_processed']} frames evaluated"
        )
        print(
            f"Detections: {res['total_detections']} (classes: {res['class_counts']}) | "
            f"Pose: {res['total_pose_inferences']}"
        )
        print(f"Latency P50: {res['latency_ms']['p50']}ms, P95: {res['latency_ms']['p95']}ms")
        print(f"Timing scope: {res['latency_scope']}")
        print(f"Effective configuration: {json.dumps(res['effective_config'], sort_keys=True)}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
