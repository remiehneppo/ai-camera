"""Exploratory capacity profiling under record/outbox/pose load (ticket #31).

This measures what one lab process can actually observe: frame ingest latency including P99,
recorder fsync activity, outbox depth, SQLite WAL journal state, storage headroom, continuity
gaps from committed segments, and pose scheduler state.

It is NOT a capacity sign-off. A signed target needs a 24-72h soak on the actual hardware with
an approved workload manifest and a named owner. Reports therefore carry accepted_capacity
False, an explicit disclaimer and missing_gates, and any quantity this run could not observe is
reported as unmeasured rather than as zero.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Callable

import numpy as np

DISCLAIMER = (
    "Exploratory profiling only: this is not a capacity sign-off. Accepted capacity requires "
    "a 24-72h soak on the actual target hardware with an approved workload manifest and a "
    "named owner signature."
)

MISSING_GATES: tuple[str, ...] = (
    "24-72h soak on the actual target SKU/RAM/OS/SDK",
    "thermal and power endurance under sustained load",
    "approved quality/ODD/workload manifest with named owner signature",
    "actual decode/detector/pose conformance on the target before soak",
    "multi-camera concurrency and shared-runtime fairness",
)

UNMEASURED = "unmeasured"

#: EventOutbox keeps no drop counter, so a drop figure would be invented rather than observed.
OUTBOX_DROPS_REASON = "EventOutbox exposes no drop/reject counter"


def percentiles(values: list[float]) -> dict[str, float]:
    """Return mean/p50/p90/p95/p99/max so tail latency is visible, not just the average."""
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    arr = np.asarray(values, dtype=np.float64)
    return {
        "mean": round(float(np.mean(arr)), 3),
        "p50": round(float(np.percentile(arr, 50)), 3),
        "p90": round(float(np.percentile(arr, 90)), 3),
        "p95": round(float(np.percentile(arr, 95)), 3),
        "p99": round(float(np.percentile(arr, 99)), 3),
        "max": round(float(np.max(arr)), 3),
    }


def gap_totals(gaps: list[list[float]] | list[tuple[float, float]]) -> dict[str, Any]:
    """Count continuity gaps and sum their seconds, so coverage loss is reported not implied."""
    seconds = sum(max(0.0, float(end) - float(start)) for start, end in gaps)
    return {"count": len(gaps), "seconds": round(seconds, 3)}


class _FsyncCounter:
    """Count real os.fsync calls and their time by wrapping the attribute the recorder calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.seconds = 0.0
        self._original: Callable[[int], Any] | None = None

    def __enter__(self) -> "_FsyncCounter":
        self._original = os.fsync

        def counting(fd: int) -> Any:
            began = time.perf_counter()
            try:
                return self._original(fd)  # type: ignore[misc]
            finally:
                self.calls += 1
                self.seconds += time.perf_counter() - began

        os.fsync = counting  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self._original is not None:
            os.fsync = self._original  # type: ignore[assignment]

    def report(self) -> dict[str, Any]:
        return {"calls": self.calls, "seconds": round(self.seconds, 6)}


class _UploadDrainer:
    """Drive caller-supplied upload work on a background thread and account for every attempt."""

    def __init__(self, hook: Callable[[], Any] | None, interval_seconds: float) -> None:
        self._hook = hook
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.drains = 0
        self.failed_drains = 0
        self.last_error: str | None = None

    def __enter__(self) -> "_UploadDrainer":
        if self._hook is not None:
            self._thread = threading.Thread(target=self._run, name="capacity-upload-drain", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        # Narrow once: mypy cannot narrow an Optional across the thread boundary.
        hook = self._hook
        if hook is None:
            return
        # Drain once immediately: waiting first would report zero drains for short profiles.
        while not self._stop.is_set():
            try:
                hook()
            except Exception as exc:  # a failing upload must not abort the profile
                self.failed_drains += 1
                self.last_error = type(exc).__name__
            else:
                self.drains += 1
            if self._stop.wait(self._interval):
                break

    def report(self) -> dict[str, Any]:
        return {"exercised": self._hook is not None, "drains": self.drains,
                "failed_drains": self.failed_drains, "last_error": self.last_error}


def _storage_report(pipeline: Any) -> dict[str, Any]:
    manager = getattr(pipeline, "quota_manager", None)
    breakdown = getattr(manager, "get_storage_breakdown", None)
    if breakdown is None:
        return {"status": UNMEASURED, "reason": "no quota manager on the pipeline"}
    try:
        data = breakdown()
        return {"status": "measured", **data.to_dict(), "headroom_bytes": data.free_bytes}
    except Exception as exc:
        return {"status": UNMEASURED, "reason": type(exc).__name__}


def _wal_report(pipeline: Any) -> dict[str, Any]:
    path = getattr(getattr(pipeline, "outbox", None), "path", None)
    if not path:
        return {"status": UNMEASURED, "reason": "no file-backed outbox"}
    try:
        with sqlite3.connect(str(path), timeout=5) as db:
            mode = db.execute("PRAGMA journal_mode").fetchone()
        wal_path = f"{path}-wal"
        return {"status": "measured", "journal_mode": (mode[0] if mode else None),
                "wal_bytes": os.path.getsize(wal_path) if os.path.exists(wal_path) else 0}
    except Exception as exc:
        return {"status": UNMEASURED, "reason": type(exc).__name__}


def _coverage_report(pipeline: Any, session_id: Any, start_source: float | None,
                     end_source: float) -> dict[str, Any]:
    if not session_id or start_source is None or end_source <= start_source:
        return {"status": UNMEASURED, "reason": "no source-time span to query"}
    try:
        actual = pipeline.recorder.actual_range(session_id, start_source, end_source)
    except Exception as exc:
        return {"status": UNMEASURED, "reason": type(exc).__name__}
    totals = gap_totals(actual.get("gaps") or [])
    return {"status": "measured", "completeness": actual.get("completeness"),
            "reason": actual.get("reason"), "gaps": actual.get("gaps") or [],
            "gap_count": totals["count"], "gap_seconds": totals["seconds"]}


def _pose_report(pipeline: Any) -> dict[str, Any]:
    getter = getattr(pipeline, "get_pose_metrics", None)
    if getter is None:
        return {"status": UNMEASURED, "reason": "pipeline exposes no pose metrics"}
    try:
        metrics = getter() or {}
    except Exception as exc:
        return {"status": UNMEASURED, "reason": type(exc).__name__}
    if not metrics:
        return {"status": UNMEASURED, "reason": "pose manager not configured for this run"}
    return {"status": "measured", "metrics": metrics}


def run_lab(
    pipeline: Any,
    *,
    frames: int,
    frame_factory: Callable[[int], tuple[int, float, Any]],
    detections_factory: Callable[[int], list[dict[str, Any]]] | None = None,
    camera_id: str | None = None,
    upload_hook: Callable[[], Any] | None = None,
    upload_interval_seconds: float = 0.01,
) -> dict[str, Any]:
    """Profile one camera's ingest and durable-commit path under optional upload load."""
    if frames <= 0:
        raise ValueError("frames must be a positive integer")
    camera = camera_id or getattr(pipeline, "camera_id", None) or "default"
    session_id = getattr(pipeline, "stream_session_id", None)

    latencies: list[float] = []
    skipped = 0
    pending_samples: list[int] = []
    start_wall = time.perf_counter()
    start_source: float | None = None
    end_source = 0.0

    with _UploadDrainer(upload_hook, upload_interval_seconds) as drainer, _FsyncCounter() as fsync:
        for index in range(frames):
            frame_id, timestamp, rgb = frame_factory(index)
            detections = detections_factory(index) if detections_factory is not None else []
            if start_source is None:
                start_source = float(timestamp)
            end_source = max(end_source, float(timestamp))
            began = time.perf_counter()
            pipeline.process_frame(rgb, timestamp, frame_id, detections=detections)
            latencies.append((time.perf_counter() - began) * 1000.0)
            observation = getattr(pipeline, "last_observation", None) or {}
            if observation.get("detection_status") not in {None, "ok", "ok_empty"}:
                skipped += 1
            pending_samples.append(len(pipeline.outbox.pending()))

    elapsed = max(time.perf_counter() - start_wall, 1e-9)
    return {
        "kind": "exploratory_capacity_profile",
        "accepted_capacity": False,
        "disclaimer": DISCLAIMER,
        "missing_gates": list(MISSING_GATES),
        "workload": {
            "camera_id": camera,
            "frames": frames,
            "duration_seconds": round(elapsed, 3),
            "ingest_fps": round(frames / elapsed, 3),
            "ingest_fps_scope": "synthetic ingest loop; excludes decode and inference",
            "detections_supplied": detections_factory is not None,
        },
        "per_camera": {
            camera: {
                "frames": frames,
                "skipped_frames": skipped,
                "latency_ms": percentiles(latencies),
                "queue": {
                    "max_pending_events": max(pending_samples) if pending_samples else 0,
                    "samples": len(pending_samples),
                    "drops": None,
                    "drops_reason": OUTBOX_DROPS_REASON,
                },
                "fsync": fsync.report(),
                "storage": _storage_report(pipeline),
                "wal": _wal_report(pipeline),
                "coverage": _coverage_report(pipeline, session_id, start_source, end_source),
            }
        },
        "pose": _pose_report(pipeline),
        "upload": drainer.report(),
    }
