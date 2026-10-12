"""Measure file replay metadata semantics, not analytics or realtime stress."""

import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal

from apps.edge.recorder import FileRecorder


def run_lab(source: str | Path, *, sample_fps: float = 2,
            slow_callback_seconds: float = 0.1) -> dict:
    if not math.isfinite(sample_fps) or sample_fps <= 0:
        raise ValueError("sample_fps must be finite and positive")
    if not math.isfinite(slow_callback_seconds) or slow_callback_seconds < 0:
        raise ValueError("slow_callback_seconds must be finite and nonnegative")
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    with tempfile.TemporaryDirectory(prefix="replay-lab-") as directory:
        root = Path(directory)
        raw = FileRecorder(root / "raw")
        segments = raw.record_file(source, "raw")
        if not segments:
            raise ValueError("source has no recorded video segments")
        start = min(item.start_seconds for item in segments)
        end = max(item.end_seconds for item in segments)
        if end <= start:
            raise ValueError("source needs at least two distinct video timestamps for raw coverage")
        coverage = raw.actual_range("raw", start, end)
        runs = {}
        runs_to_execute: tuple[tuple[str, Literal["fast", "realtime"], float], ...] = (
            ("fast", "fast", 0), ("realtime", "realtime", 0),
            ("slow_realtime", "realtime", slow_callback_seconds),
        )
        for name, mode, delay in runs_to_execute:
            recorder = FileRecorder(root / name)
            trace = []
            queries = 0
            unchanged = True
            first_arrival = None
            max_lag = 0

            def consume(frame):
                nonlocal queries, unchanged, first_arrival, max_lag
                if first_arrival is None:
                    first_arrival = time.monotonic()
                trace.append({"pts": frame.pts, "time_base": frame.time_base,
                              "event_time": frame.event_time})
                time.sleep(delay)
                unchanged = (raw.actual_range("raw", start, end) == coverage) and unchanged
                queries += 1
                max_lag = max(max_lag, time.monotonic() - first_arrival
                              - (frame.event_time - trace[0]["event_time"]))

            began = time.monotonic()
            count = recorder.replay(source, name, consume, sample_fps=sample_fps, mode=mode)
            runs[name] = {
                "mode": mode, "callback_delay_seconds": delay,
                "delivered_count": count, "trace": trace,
                "elapsed_seconds": time.monotonic() - began,
                "max_callback_completion_lag_seconds": max_lag,
                "last_consumer_event_time": trace[-1]["event_time"] if trace else None,
                "raw_query_count": queries, "raw_coverage_unchanged": unchanged,
            }
        return {
            "scope": "software_semantic_replay", "source": str(source.resolve()),
            "sample_fps": sample_fps,
            "raw": {"segment_count": len(segments), "coverage": coverage},
            "runs": runs,
            "trace_parity": all(run["trace"] == runs["fast"]["trace"] for run in runs.values()),
            "limitations": ["not analytics/domain parity", "not realtime queue/drop stress",
                            "raw recorded completely before replay; this lab does not measure concurrent ingestion",
                            "lag relative to first callback; excludes initial probe startup",
                            "last_consumer_event_time is observed callback progress, not a queried recorder watermark",
                            "temporary artifacts removed after report; input metadata/traces are materialized"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="cleared video file; use small lab fixtures")
    parser.add_argument("--sample-fps", type=float, default=2)
    parser.add_argument("--slow-callback-seconds", type=float, default=0.1)
    args = parser.parse_args()
    try:
        report = run_lab(args.source, sample_fps=args.sample_fps,
                         slow_callback_seconds=args.slow_callback_seconds)
        output = json.dumps(report, allow_nan=False, sort_keys=True)
        print(output)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"replay lab failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
