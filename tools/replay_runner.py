"""Semantic replay session runner consolidating video decode, rational timestamps,
ephemeral SQLite storage lifecycle, and fail-fast pipeline execution (ADR-0006)."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import math
from pathlib import Path
import tempfile
import time
from typing import Any, Callable

import cv2
import numpy as np

from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder

LATENCY_SCOPE = (
    "pipeline.process_frame including local persistence (excludes decode, sampling, model startup)"
)


@dataclass(frozen=True)
class ReplayFrameStep:
    """Record of a single processed video frame step."""

    source_frame_idx: int
    processed_idx: int
    timestamp: float
    decode_ms: float
    step_ms: float
    events: list[dict[str, Any]]
    observation: dict[str, Any]
    rgb: np.ndarray


@dataclass
class ReplaySessionResult:
    """Consolidated outcome of running a video through PerceptionPipeline."""

    video_path: Path
    status: str  # "completed" | "failed" | "unavailable"
    error: str | None = None
    native_fps: float = 0.0
    width: int = 0
    height: int = 0
    frames_processed: int = 0
    total_detections: int = 0
    total_events: int = 0
    emitted_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    class_counts: dict[str, int] = field(default_factory=dict)
    detection_status_counts: dict[str, int] = field(default_factory=dict)
    pose_status_counts: dict[str, int] = field(default_factory=dict)
    total_pose_inferences: int = 0
    emitted_events: list[dict[str, Any]] = field(default_factory=list)
    emitted_meta: dict[str, tuple[int, float]] = field(default_factory=dict)
    outbox_events: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    pipeline: PerceptionPipeline | None = None
    recorder: FileRecorder | None = None
    outbox: EventOutbox | None = None
    steps: list[ReplayFrameStep] = field(default_factory=list)


def run_replay_session(
    video_path: str | Path,
    pipeline_factory: Callable[[Path, int, int, float], tuple[PerceptionPipeline, EventOutbox]],
    *,
    sample_fps: float = 10.0,
    max_frames: int = 0,
    fail_fast: bool = True,
    collect_steps: bool = False,
    on_step: Callable[[ReplayFrameStep, PerceptionPipeline], None] | None = None,
) -> ReplaySessionResult:
    """Execute a video replay session through a PerceptionPipeline instance.

    Encapsulates:
    1. Video opening and dimension / native_fps validation.
    2. Ephemeral FileRecorder and EventOutbox SQLite lifecycle in tempfile.TemporaryDirectory.
    3. Pipeline construction via pipeline_factory.
    4. Subsampling step stride: max(1, int(round(native_fps / sample_fps))).
    5. Exact rational microsecond timestamp calculation from source frame index.
    6. Synchronous execution through pipeline.process_frame, latency tracking,
       and detection status fail-fast verification.
    7. Clean capture release and storage teardown.
    """
    vpath = Path(video_path)
    if not vpath.is_file():
        if fail_fast:
            raise FileNotFoundError(f"video not found: {video_path}")
        return ReplaySessionResult(
            video_path=vpath,
            status="unavailable",
            error=f"video file not found: {video_path}",
        )

    if sample_fps <= 0 or not math.isfinite(sample_fps):
        if fail_fast:
            raise ValueError(f"invalid sample_fps: {sample_fps}")
        return ReplaySessionResult(
            video_path=vpath,
            status="failed",
            error=f"invalid sample_fps: {sample_fps}",
        )

    cap = cv2.VideoCapture(str(vpath))
    try:
        if not cap.isOpened():
            if fail_fast:
                raise RuntimeError(f"failed to open video: {video_path}")
            return ReplaySessionResult(
                video_path=vpath,
                status="failed",
                error=f"failed to open video: {video_path}",
            )

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        native_fps = float(cap.get(cv2.CAP_PROP_FPS))

        if not math.isfinite(native_fps) or native_fps <= 0.0 or width <= 0 or height <= 0:
            if fail_fast:
                raise RuntimeError(f"Invalid source frame rate or dimensions: {video_path}")
            return ReplaySessionResult(
                video_path=vpath,
                status="failed",
                error=f"invalid video stream dimensions ({width}x{height}) or native_fps ({native_fps})",
            )

        step = max(1, int(round(native_fps / sample_fps)))

        with tempfile.TemporaryDirectory(prefix="civiwatch-replay-session-") as tmp:
            tmp_root = Path(tmp)
            pipeline, outbox = pipeline_factory(tmp_root, width, height, native_fps)
            recorder = getattr(pipeline, "recorder", None)
            t_start = time.perf_counter()
            processed = 0
            raw_idx = 0
            total_dets = 0
            total_events = 0
            emitted_count = 0
            total_pose_inferences = 0
            latencies_ms: list[float] = []
            class_counts: dict[str, int] = {}
            detection_status_counts: dict[str, int] = {}
            pose_status_counts: dict[str, int] = {}
            emitted_events: list[dict[str, Any]] = []
            emitted_meta: dict[str, tuple[int, float]] = {}
            steps: list[ReplayFrameStep] = []

            while True:
                if max_frames and processed >= max_frames:
                    break
                t_dec0 = time.perf_counter()
                ok, bgr = cap.read()
                if not ok:
                    break

                source_frame_idx = raw_idx
                raw_idx += 1
                if source_frame_idx % step != 0:
                    continue

                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                decode_ms = (time.perf_counter() - t_dec0) * 1000.0
                raw_ts = source_frame_idx / native_fps
                pts = round(raw_ts * 1_000_000)
                ts = float(pts * Fraction("1/1000000"))

                t0 = time.perf_counter()
                try:
                    evs = pipeline.process_frame(rgb, timestamp=ts, frame_id=source_frame_idx)
                except Exception as exc:
                    if fail_fast:
                        raise
                    return ReplaySessionResult(
                        video_path=vpath,
                        status="failed",
                        error=f"Pipeline exception on frame {source_frame_idx}: {exc}",
                        native_fps=native_fps,
                        width=width,
                        height=height,
                        frames_processed=processed,
                        total_detections=total_dets,
                        total_events=total_events,
                    )
                step_ms = (time.perf_counter() - t0) * 1000.0
                latencies_ms.append(step_ms)

                obs = pipeline.last_observation or {}
                det_status = obs.get("detection_status")
                if det_status:
                    detection_status_counts[det_status] = (
                        detection_status_counts.get(det_status, 0) + 1
                    )
                if det_status not in {"ok", "ok_empty"}:
                    err_msg = (
                        f"Detection failed on frame {source_frame_idx} of {vpath.name}: "
                        f"status={det_status}, error={obs.get('error')}"
                    )
                    if fail_fast:
                        raise RuntimeError(err_msg)
                    return ReplaySessionResult(
                        video_path=vpath,
                        status="failed",
                        error=err_msg,
                        native_fps=native_fps,
                        width=width,
                        height=height,
                        frames_processed=processed,
                        total_detections=total_dets,
                        total_events=total_events,
                        detection_status_counts=detection_status_counts,
                    )

                dets = obs.get("detections", [])
                total_dets += len(dets)
                for d in dets:
                    lbl = d.get("label", "unknown")
                    class_counts[lbl] = class_counts.get(lbl, 0) + 1

                obs_pose_outcomes = obs.get("pose_outcomes", [])
                total_pose_inferences += len(obs_pose_outcomes)
                for po in obs_pose_outcomes:
                    st = po.get("status") if isinstance(po, dict) else getattr(po, "status", None)
                    if st:
                        pose_status_counts[st] = pose_status_counts.get(st, 0) + 1

                for ev in evs or []:
                    eid = ev.get("event_id")
                    if eid:
                        emitted_meta[eid] = (source_frame_idx, ts)
                emitted_events.extend(evs or [])
                emitted_count += len(evs or [])

                step_record = ReplayFrameStep(
                    source_frame_idx=source_frame_idx,
                    processed_idx=processed,
                    timestamp=ts,
                    decode_ms=decode_ms,
                    step_ms=step_ms,
                    events=evs or [],
                    observation=obs,
                    rgb=rgb,
                )
                if collect_steps:
                    steps.append(step_record)
                if on_step is not None:
                    on_step(step_record, pipeline)

                processed += 1

            if processed == 0:
                err_msg = f"No frames processed from video: {video_path}"
                if fail_fast:
                    raise RuntimeError(err_msg)
                return ReplaySessionResult(
                    video_path=vpath,
                    status="failed",
                    error=err_msg,
                    native_fps=native_fps,
                    width=width,
                    height=height,
                    frames_processed=0,
                )

            outbox_rows = [row["event"] for row in outbox.pending()]
            elapsed = time.perf_counter() - t_start

            return ReplaySessionResult(
                video_path=vpath,
                status="completed",
                native_fps=native_fps,
                width=width,
                height=height,
                frames_processed=processed,
                total_detections=total_dets,
                total_events=len(outbox_rows),
                emitted_count=emitted_count,
                latencies_ms=latencies_ms,
                class_counts=class_counts,
                detection_status_counts=detection_status_counts,
                pose_status_counts=pose_status_counts,
                total_pose_inferences=total_pose_inferences,
                emitted_events=emitted_events,
                emitted_meta=emitted_meta,
                outbox_events=outbox_rows,
                elapsed_seconds=elapsed,
                pipeline=pipeline,
                recorder=recorder,
                outbox=outbox,
                steps=steps,
            )
    finally:
        cap.release()
