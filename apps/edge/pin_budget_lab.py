"""Reproduce caller-supplied source-time pin delays, not measured runtime maxima."""

from __future__ import annotations

from apps.edge.evidence import EvidenceLifecycle

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder
from apps.edge.send_synthetic import make_event
from domain.evidence_contract import make_evidence_request


def run_lab(source: str | Path, *, ring_seconds: float, anchor_time: float,
            verification_seconds: float, handoff_seconds: float,
            recovery_seconds: float, margin_seconds: float) -> dict[str, Any]:
    config = dict(ring_seconds=ring_seconds, anchor_time=anchor_time,
                  verification_seconds=verification_seconds, handoff_seconds=handoff_seconds,
                  recovery_seconds=recovery_seconds, margin_seconds=margin_seconds)
    for name, value in config.items():
        if isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    if ring_seconds == 0:
        raise ValueError("ring_seconds must be positive")
    if not math.isfinite(anchor_time + verification_seconds + handoff_seconds + recovery_seconds + margin_seconds + 10):
        raise ValueError("scenario timing sum must be finite")
    source = Path(source)
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    delay = verification_seconds + handoff_seconds + recovery_seconds
    pin_time = anchor_time + delay
    with tempfile.TemporaryDirectory(prefix="pin-budget-lab-") as directory:
        root = Path(directory)
        prefix = root / "prefix.mkv"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-copyts", "-i", str(source),
            "-to", str(pin_time), "-map", "0:v:0", "-an", "-c:v", "copy", str(prefix),
        ], check=True, capture_output=True, timeout=30)
        recorder = FileRecorder(root / "ring", ring_seconds=ring_seconds)
        event: dict[str, Any] = make_event("lab-edge-01", "lab-camera-01")
        session = str(event["stream_session_id"])
        request = make_evidence_request("scenario-intent", session, "onset", anchor_time)
        event["payload"]["evidence_requests"] = [request]
        outbox = EventOutbox(root / "events.sqlite3")
        outbox.enqueue(event)
        pending = outbox.evidence_requests()[0]["state"]
        recorder.advance_watermark(session, float("-inf"))
        written = recorder.record_file(prefix, session)
        if not written:
            raise ValueError("scenario has no source frames before pin time")
        recorder.advance_watermark(session, pin_time)
        retained = recorder.actual_range(session, request["requested_start"], request["requested_end"])
        recorder = FileRecorder(root / "ring", ring_seconds=ring_seconds)
        outbox = EventOutbox(root / "events.sqlite3")
        EvidenceLifecycle(outbox, recorder).reconcile( finish_sessions=[session])
        result = outbox.evidence_requests()[0]
        required = delay + 10 + margin_seconds
        return {
            "scope": "software_pin_budget_scenario", "config": config,
            "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
            "source": {"path": str(source.resolve()), "size_bytes": source.stat().st_size,
                       "sha256": digest},
            "versions": {"python": platform.python_version(), "platform": platform.platform(),
                         "ffmpeg": subprocess.run(["ffmpeg", "-version"], check=True,
                                                   capture_output=True, text=True, timeout=5).stdout.splitlines()[0],
                         "ffprobe": subprocess.run(["ffprobe", "-version"], check=True,
                                                    capture_output=True, text=True, timeout=5).stdout.splitlines()[0],
                         "git_revision": subprocess.run(["git", "rev-parse", "HEAD"],
                                                        cwd=Path(__file__).resolve().parents[2], check=True,
                                                        capture_output=True, text=True, timeout=5).stdout.strip(),
                         "working_tree_modified": bool(subprocess.run(["git", "status", "--porcelain"],
                                                                       cwd=Path(__file__).resolve().parents[2], check=True,
                                                                       capture_output=True, text=True, timeout=5).stdout)},
            "schedule": {"basis": "simulated source-time timeline; not actual enqueue/probe/restart timestamps",
                         "event_persist_time": anchor_time + verification_seconds,
                         "handoff_end_time": anchor_time + verification_seconds + handoff_seconds,
                         "pin_time": pin_time,
                         "recorded_end_time": max(item.end_seconds for item in written)},
            "theoretical": {"required_ring_seconds": required,
                            "slack_seconds": ring_seconds - required,
                            "units": "source-event-time seconds",
                            "basis": "caller scenario delay + pre10 + caller mapping/keyframe margin"},
            "pending_before_restart": pending, "retained_before_pin": retained, "result": result,
            "limitations": ["delays are caller-supplied scenarios, not measured verification/handoff/RTO/maxima",
                            "not signed F03 budget or target/hardware capacity/power-cut proof",
                            "prefix fully recorded before pruning/pin; no concurrent ingestion or live RTSP",
                            "source EOF and stream-copy keyframes constrain realized recorded range",
                            "EOF explicitly ends scenario; unavailable post-roll is partial",
                            "temporary artifacts removed after report; no upload or metadata ACK simulated",
                            "margin is theoretical only; actual ranges use recorder coverage policy",
                            "retained_before_pin describes request coverage; missing is not artifact completeness",
                            "result receipt describes artifact completeness: unknown when build failed with no artifact",
                            "no disk quota, bitrate/event-load, unACK autonomy or storage stress proof"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    for name in ("ring_seconds", "anchor_time", "verification_seconds", "handoff_seconds",
                 "recovery_seconds", "margin_seconds"):
        parser.add_argument("--" + name.replace("_", "-"), type=float, required=True)
    args = vars(parser.parse_args())
    try:
        print(json.dumps(run_lab(**args), allow_nan=False, sort_keys=True))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"pin budget lab failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
