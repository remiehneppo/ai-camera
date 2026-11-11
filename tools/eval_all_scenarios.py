"""Comprehensive Edge Multi-Scenario Evaluation Suite.

Evaluates test video datasets across edge perception alert engines:
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
5. Extended scenarios with VLM (UrbanSafetyScenarioEngine):
   - Evaluates: US01 (fire/smoke), US02 (flooding), US03 (dumping), US07 (altercation),
     US11 (abandoned object), US12 (fallen tree), US13 (streetlight outage).
   - Unconfigured/unsupported without camera ROI and specialized configuration:
     US04 (sidewalk encroachment), US10 (danger zone), US14 (property vandalism).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from apps.edge.crowd_incident import CrowdIncidentEngine
from apps.edge.homography import GroundPlaneHomography
from apps.edge.incident import IncidentEngine
from apps.edge.outbox import EventOutbox
from apps.edge.parking_incident import ParkingIncidentEngine
from apps.edge.perception import PerceptionExecution
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.pose import PoseManager, RtmposeEstimator
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import ByteTracker
from apps.edge.urban_safety_engine import UrbanSafetyScenarioEngine
from apps.edge.vehicle_incident import VehicleIncidentEngine
from domain.urban_scenarios import SCENARIO_SPECS
from tools.eval_clip import LATENCY_SCOPE, extract_effective_config
from tools.replay_runner import run_replay_session

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
for _spec in SCENARIO_SPECS:
    for _tax in _spec.taxonomies:
        if _tax not in TAXONOMY_ENGINE_MAP:
            TAXONOMY_ENGINE_MAP[_tax] = _spec.factory


def evaluate_video(
    video_path: Path,
    detector: Any,
    *,
    sample_fps: float = 10.0,
    max_frames: int = 300,
    with_pose: bool = True,
    parking_max_dwell: float = 20.0,
    crowd_min_count: int = 5,
    crowd_min_duration: float = 3.0,
    impact_deceleration: float = 120.0,
    extended_scenarios: bool = False,
) -> dict[str, Any]:
    if extended_scenarios:
        evaluated_scenarios = [
            "US01", "US02", "US03", "US05", "US06", "US07", "US08", "US09", "US11", "US12", "US13"
        ]
        unconfigured_scenarios = ["US04", "US10", "US14"]
    else:
        evaluated_scenarios = ["US05", "US06", "US08", "US09"]
        unconfigured_scenarios = [
            "US01", "US02", "US03", "US04", "US07", "US10", "US11", "US12", "US13", "US14"
        ]

    created_pipeline: list[PerceptionPipeline] = []

    def pipeline_factory(tmp_root: Path, width: int, height: int, native_fps: float) -> tuple[PerceptionPipeline, EventOutbox]:
        recorder = FileRecorder(tmp_root / "ring", ring_seconds=60)
        outbox = EventOutbox(tmp_root / "events.sqlite3")
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
        hom = GroundPlaneHomography.default_urban_cctv(width, height)
        vehicle_engine = VehicleIncidentEngine(
            impact_deceleration_threshold=impact_deceleration,
            min_moving_speed=15.0,
            homography=hom,
        )
        parking_engine = ParkingIncidentEngine(max_dwell_seconds=parking_max_dwell)
        crowd_engine = CrowdIncidentEngine(
            min_crowd_count=crowd_min_count,
            min_duration_seconds=crowd_min_duration,
        )
        engines = [fall_engine, vehicle_engine, parking_engine, crowd_engine]
        if extended_scenarios:
            engines.append(UrbanSafetyScenarioEngine(factory="urban_safety_vlm"))

        p = PerceptionPipeline(
            recorder=recorder,
            outbox=outbox,
            detector=detector,
            tracker=tracker,
            incident_engines=engines,
            pose_manager=pose_mgr,
            origin="replay",
        )
        created_pipeline.append(p)
        return p, outbox

    res = run_replay_session(
        video_path,
        pipeline_factory,
        sample_fps=sample_fps,
        max_frames=max_frames,
        fail_fast=True,
    )

    events: list[dict[str, Any]] = []
    for snapshot in res.outbox_events:
        p = snapshot.get("payload", {})
        tax = p.get("taxonomy") or snapshot.get("taxonomy")
        eng = TAXONOMY_ENGINE_MAP.get(str(tax), "incident")
        eid = snapshot.get("event_id")
        meta = res.emitted_meta.get(str(eid)) if eid is not None else None
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

    active_pipeline = created_pipeline[0] if created_pipeline else res.pipeline
    assert active_pipeline is not None
    effective_cfg = extract_effective_config(
        active_pipeline,
        sample_fps=sample_fps,
        max_frames=max_frames,
        with_pose=with_pose,
    )

    return {
        "video": Path(video_path).name,
        "origin": "replay",
        "resolution": f"{res.width}x{res.height}",
        "native_fps": res.native_fps,
        "frames_processed": res.frames_processed,
        "evaluated_scenarios": evaluated_scenarios,
        "unconfigured_scenarios": unconfigured_scenarios,
        "total_detections": res.total_detections,
        "class_counts": res.class_counts,
        "total_pose_inferences": res.total_pose_inferences,
        "detection_status_counts": res.detection_status_counts,
        "pose_status_counts": res.pose_status_counts,
        "event_count": len(events),
        "events_by_taxonomy": events_by_taxonomy,
        "events": events,
        "latency_ms": {
            "p50": round(statistics.median(res.latencies_ms), 2) if res.latencies_ms else None,
            "p95": (
                round(sorted(res.latencies_ms)[max(0, int(len(res.latencies_ms) * 0.95) - 1)], 2)
                if res.latencies_ms
                else None
            ),
            "scope": LATENCY_SCOPE,
        },
        "latency_scope": LATENCY_SCOPE,
        "effective_config": effective_cfg,
    }

def main():
    parser = argparse.ArgumentParser(description="Evaluate video clips across configured edge perception engines")
    parser.add_argument("--videos", nargs="+", help="Video path(s) to evaluate")
    parser.add_argument("--sample-fps", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=200)
    parser.add_argument("--no-pose", action="store_true", help="Disable pose estimation")
    parser.add_argument(
        "--extended-scenarios",
        action="store_true",
        help=(
            "Enable extended urban safety scenario evaluation with VLM "
            "(evaluates US01, US02, US03, US07, US11, US12, US13; "
            "US04, US10, US14 remain unconfigured without camera ROI and specialized configuration)"
        ),
    )
    parser.add_argument("--manifest", type=Path, default=ROOT / "models/yolox-tiny/manifest.json", help="Detector manifest path")
    parser.add_argument("--model", type=Path, default=ROOT / "data/oracle/yolox_tiny.onnx", help="Detector model path")
    parser.add_argument("--json-out", type=str, default="", help="Path to write JSON output")
    args = parser.parse_args()

    pe = PerceptionExecution(manifest_path=args.manifest, model_path=args.model, origin="replay")
    detector = pe.detector
    if detector is None:
        raise RuntimeError(f"Failed to initialize detector from {args.manifest} and {args.model}")

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
    print(f"   CIVIWATCH MULTI-SCENARIO EDGE PERCEPTION BENCHMARK")
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
                extended_scenarios=args.extended_scenarios,
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
        print(f"Evaluated scenarios ({len(res['evaluated_scenarios'])}): {', '.join(res['evaluated_scenarios'])}")
        print(f"Unconfigured/unsupported scenarios ({len(res['unconfigured_scenarios'])}): {', '.join(res['unconfigured_scenarios'])}")
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
