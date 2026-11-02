"""Probe concurrent RTSP stream sessions for camera stream ownership decision."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from apps.edge.rtsp import load_rtsp_config, probe_rtsp_stream, sanitize_probe_output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe concurrent RTSP stream sessions.")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON path")
    parser.add_argument("--duration", type=float, default=20.0, help="Duration in seconds per session")
    parser.add_argument("--max-sessions", type=int, default=3, help="Max concurrent sessions to probe")

    args = parser.parse_args(argv)

    try:
        config = load_rtsp_config()
    except Exception as exc:
        print(f"Error loading RTSP config: {exc}", file=sys.stderr)
        return 1

    try:
        info = probe_rtsp_stream(config.stream_url, timeout_seconds=10.0)
    except Exception as exc:
        sanitized = sanitize_probe_output(str(exc), config.stream_url)
        print(f"Error probing RTSP stream: {sanitized}", file=sys.stderr)
        return 1

    duration = float(args.duration)
    expected_packets = round(info.fps * duration)
    timeout_seconds = duration + 15.0

    levels: list[dict] = []

    for k in range(1, args.max_sessions + 1):
        print(f"[PROBE] Testing level k={k} concurrent session(s)...", file=sys.stderr)
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            config.stream_url,
            "-t",
            str(duration),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-f",
            "framemd5",
            "-",
        ]

        procs: list[subprocess.Popen[str]] = []
        for _ in range(k):
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            procs.append(p)

        results: list[dict] = []
        for p in procs:
            try:
                out, err = p.communicate(timeout=timeout_seconds)
                code: int | None = p.returncode
            except subprocess.TimeoutExpired:
                p.kill()
                out, err = p.communicate()
                code = None

            packets = len([line for line in out.splitlines() if line.strip() and not line.strip().startswith("#")])
            ok = (code == 0) and (packets >= 0.95 * expected_packets)
            sanitized_err = sanitize_probe_output(err, config.stream_url)

            results.append({
                "exit_code": code,
                "packets": packets,
                "expected": expected_packets,
                "ok": ok,
                "stderr": sanitized_err,
            })

        levels.append({
            "sessions": k,
            "results": results,
        })

    report = {
        "redacted_url": config.redacted_url,
        "codec": info.codec,
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
        "duration_seconds": duration,
        "levels": levels,
        "probed_at": datetime.now(timezone.utc).isoformat(),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[PROBE] Probe complete. Output written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
