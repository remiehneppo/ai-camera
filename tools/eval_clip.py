"""Evaluate one local clip through the full edge pipeline (decode -> detect -> track -> incident).

Prints event-level metrics: detections, incident events by taxonomy/lifecycle/severity, pose outcomes
and latency. Ground-truth labels are NOT implied: without an annotated label file this reports what the
pipeline produced, not precision/recall.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
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

from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.pose import PoseManager, PoseScheduler, RtmposeEstimator
from apps.edge.recorder import FileRecorder

LATENCY_SCOPE: str = (
    "pipeline.process_frame including local persistence (excludes decode, sampling, model startup)"
)


def extract_effective_config(
    pipeline: PerceptionPipeline,
    *,
    sample_fps: float,
    max_frames: int,
    with_pose: bool | None = None,
) -> dict[str, Any]:
    """Extract actual effective runtime parameters from constructed pipeline objects."""
    tracker = pipeline.tracker
    tracker_cfg = {
        "high_threshold": getattr(tracker, "high_threshold", None),
        "low_threshold": getattr(tracker, "low_threshold", None),
        "match_threshold": getattr(tracker, "match_threshold", None),
        "match_threshold_low": getattr(tracker, "match_threshold_low", None),
        "max_lost_time": getattr(tracker, "max_lost_time", None),
        "activate_after": getattr(tracker, "activate_after", None),
        "max_observation_gap": getattr(tracker, "max_observation_gap", None),
    }

    engines_cfg: dict[str, dict[str, Any]] = {}
    for eng in getattr(pipeline, "incident_engines", []):
        name = getattr(eng, "factory", getattr(eng, "module", eng.__class__.__name__))
        eng_dict: dict[str, Any] = {}
        for k, v in getattr(eng, "__dict__", {}).items():
            if k.startswith("_") or k in {
                "camera_id",
                "device_id",
                "stream_session_id",
                "origin",
                "config_version",
                "calibration_version",
                "quality_state",
            }:
                continue
            if isinstance(v, (int, float, bool, str)) or v is None:
                eng_dict[k] = v
        engines_cfg[str(name)] = eng_dict

    pose_cfg: dict[str, Any] | None = None
    if pipeline.pose_manager is not None or getattr(pipeline, "pose_scheduler", None) is not None:
        sched = getattr(pipeline, "pose_scheduler", None) or getattr(
            pipeline.pose_manager, "scheduler", None
        )
        mgr = pipeline.pose_manager
        sched_dict: dict[str, Any] = {}
        if sched is not None:
            for k, v in getattr(sched, "__dict__", {}).items():
                if k.startswith("_") or k in {"capability_status", "degraded_reason"}:
                    continue
                if isinstance(v, (int, float, bool, str)) or v is None:
                    sched_dict[k] = v
        pose_cfg = {
            "enabled": True,
            "max_queue_size": getattr(mgr, "max_queue_size", None),
            "max_cached_frames": getattr(mgr, "max_cached_frames", None),
            "scheduler": sched_dict,
        }
    elif with_pose is not None:
        pose_cfg = {"enabled": False}

    eval_cfg: dict[str, Any] = {
        "sample_fps": sample_fps,
        "max_frames": max_frames,
    }
    if with_pose is not None:
        eval_cfg["with_pose"] = with_pose

    return {
        "evaluator": eval_cfg,
        "tracker": tracker_cfg,
        "engines": engines_cfg,
        "pose": pose_cfg,
    }


def events_from_outbox(outbox: EventOutbox) -> list[dict[str, Any]]:
    """Persisted incidents as flat records (EventOutbox.pending() rows carry a parsed 'event')."""
    events: list[dict[str, Any]] = []
    for row in outbox.pending():
        snapshot = row["event"]
        payload = snapshot.get("payload", {})
        evidence_requests = payload.get("evidence_requests", [])
        first_req = evidence_requests[0] if evidence_requests else {}
        events.append(
            {
                "event_id": snapshot.get("event_id"),
                "taxonomy": payload.get("taxonomy"),
                "lifecycle": payload.get("lifecycle"),
                "severity": payload.get("severity"),
                "origin": snapshot.get("origin"),
                "revision": snapshot.get("revision"),
                "stream_session_id": snapshot.get("stream_session_id"),
                "pose_status": (payload.get("pose_evidence") or {}).get("status"),
                "anchor_time": payload.get("anchor_time"),
                "anchor_kind": first_req.get("evidence_anchor_kind"),
                "evidence_session_id": first_req.get("session_id"),
                "evidence_requests": evidence_requests,
                "confidence": payload.get("confidence"),
                "details": payload,
            }
        )
    return events

def evaluate(
    video_path: Path,
    *,
    sample_fps: float,
    max_frames: int,
    with_pose: bool,
) -> dict[str, Any]:
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
    cap = cv2.VideoCapture(str(video_path))
    try:
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
                pose_manager=manager,
                pose_scheduler=scheduler,
                origin="replay",
                manifest_path=ROOT / "models/yolox-tiny/manifest.json",
                model_path=ROOT / "data/oracle/yolox_tiny.onnx",
            )

            latencies: list[float] = []
            class_counts: dict[str, int] = {}
            detection_status_counts: dict[str, int] = {}
            pose_status_counts: dict[str, int] = {}
            detections = 0
            pose_outcomes = 0
            emitted = 0
            frame_idx = 0
            processed = 0
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
                ts = float(pts * Fraction("1/1000000"))
                started = time.perf_counter()
                emitted_events = pipeline.process_frame(
                    rgb, timestamp=ts, frame_id=frame_idx
                )
                latencies.append((time.perf_counter() - started) * 1000.0)

                observation = pipeline.last_observation or {}
                detection_status = observation.get("detection_status")
                if detection_status:
                    detection_status_counts[detection_status] = (
                        detection_status_counts.get(detection_status, 0) + 1
                    )
                if detection_status not in {"ok", "ok_empty"}:
                    raise RuntimeError(
                        f"Detection failed on frame {frame_idx} of {video_path.name}: "
                        f"status={detection_status}, error={observation.get('error')}"
                    )

                dets = observation.get("detections", [])
                detections += len(dets)
                for det in dets:
                    label = det.get("label", "unknown")
                    class_counts[label] = class_counts.get(label, 0) + 1

                obs_pose_outcomes = observation.get("pose_outcomes", [])
                pose_outcomes += len(obs_pose_outcomes)
                for po in obs_pose_outcomes:
                    st = po.get("status") if isinstance(po, dict) else getattr(po, "status", None)
                    if st:
                        pose_status_counts[st] = pose_status_counts.get(st, 0) + 1

                emitted += len(emitted_events or [])
                processed += 1
                frame_idx += 1

            events = events_from_outbox(outbox)
            by_taxonomy: dict[str, int] = {}
            for event in events:
                tax = event.get("taxonomy")
                if tax:
                    by_taxonomy[tax] = by_taxonomy.get(tax, 0) + 1

            effective_cfg = extract_effective_config(
                pipeline,
                sample_fps=sample_fps,
                max_frames=max_frames,
                with_pose=with_pose,
            )
            return {
                "video": video_path.name,
                "origin": "replay",
                "with_pose": with_pose,
                "native_fps": native_fps,
                "frames_processed": processed,
                "detections": detections,
                "class_counts": class_counts,
                "pose_outcomes": pose_outcomes,
                "detection_status_counts": detection_status_counts,
                "pose_status_counts": pose_status_counts,
                "events": events,
                "events_by_taxonomy": by_taxonomy,
                "event_count": len(events),
                "event_count_emitted": emitted,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", action="append", required=True, help="local clip; repeatable")
    parser.add_argument("--sample-fps", type=float, default=10.0)
    parser.add_argument("--max-frames", type=int, default=0, help="0 = every sampled frame")
    parser.add_argument("--pose", action="store_true", help="also run pose estimation")
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args()
    results = []
    try:
        for item in args.video:
            results.append(
                evaluate(
                    Path(item),
                    sample_fps=args.sample_fps,
                    max_frames=args.max_frames,
                    with_pose=args.pose,
                )
            )
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(results, indent=2, sort_keys=True)
    if args.output_json:
        Path(args.output_json).write_text(payload, encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
