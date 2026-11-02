"""Harness for G1 X19 latency measurement (edge durable commit to dashboard DOM render)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from apps.edge.capacity_lab import percentiles
from apps.edge.live_pipeline import MetadataDeliveryWorker
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder
from apps.edge.send_synthetic import make_event
from apps.edge.uploader import EdgeUploader, validate_server_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure G1 X19 latency (edge commit to browser render).")
    parser.add_argument("--server-url", required=True, help="Server base URL (e.g. https://HOST:PORT or http://127.0.0.1:PORT)")
    parser.add_argument("--output", required=True, type=Path, help="Output JSON path")
    parser.add_argument("--events", type=int, default=50, help="Number of events to generate")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between events")
    parser.add_argument("--device-id", default="lab-edge-01", help="Edge device ID")
    parser.add_argument("--camera-id", default="lab-camera-01", help="Camera ID")
    parser.add_argument("--work-dir", type=Path, default=None, help="Working directory for sqlite outbox and ring buffer")

    args = parser.parse_args(argv)

    device_token = os.environ.get("DEVICE_TOKEN")
    if not device_token:
        print("Missing required environment variable: DEVICE_TOKEN", file=sys.stderr)
        return 2

    dashboard_token = os.environ.get("DASHBOARD_TOKEN")
    if not dashboard_token:
        print("Missing required environment variable: DASHBOARD_TOKEN", file=sys.stderr)
        return 2

    try:
        server_url = validate_server_url(args.server_url)
    except ValueError as exc:
        print(f"Invalid server_url: {exc}", file=sys.stderr)
        return 2

    parsed_url = urlparse(server_url)
    server_is_loopback = parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}
    if server_is_loopback:
        os.environ.setdefault("ALLOW_INSECURE_LAB", "1")

    temp_dir_obj = None
    if args.work_dir is not None:
        work_dir = args.work_dir
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        temp_dir_obj = tempfile.TemporaryDirectory(prefix="g1-x19-")
        work_dir = Path(temp_dir_obj.name)

    print(f"[X19] Work directory: {work_dir}", file=sys.stderr)

    outbox = EventOutbox(work_dir / "events.sqlite3")
    recorder = FileRecorder(work_dir / "ring", ring_seconds=600.0)
    uploader = EdgeUploader(
        outbox=outbox,
        recorder=recorder,
        server_url=server_url,
        device_token=device_token,
    )

    pipeline = PerceptionPipeline(
        recorder=recorder,
        outbox=outbox,
        uploader=uploader,
        camera_id=args.camera_id,
        device_id=args.device_id,
        origin="synthetic",
    )

    worker = MetadataDeliveryWorker(pipeline.trigger_upload, interval_seconds=5.0, name="x19-delivery")
    worker.start()

    init_script = """
    window.__g1RenderTimes = {};
    new MutationObserver(() => {
      for (const card of document.querySelectorAll("article.event")) {
        const key = card.dataset.eventKey;
        if (key && !(key in window.__g1RenderTimes)) {
          window.__g1RenderTimes[key] = Date.now();
        }
      }
    }).observe(document, {childList: true, subtree: true});
    """

    pw_version = version("playwright")

    try:
        git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        git_head = "unknown"

    samples: list[dict] = []
    missing_event_ids: list[str] = []

    try:
        with sync_playwright() as p, p.firefox.launch(headless=True) as browser:
            context = browser.new_context(ignore_https_errors=True)
            context.add_init_script(init_script)
            page = context.new_page()

            print(f"[X19] Navigating to dashboard: {server_url}/", file=sys.stderr)
            page.goto(server_url + "/")
            page.once("dialog", lambda dialog: dialog.accept(dashboard_token))
            with page.expect_response(
                lambda response: urlparse(response.url).path == "/v1/events"
                and response.request.method == "GET"
            ) as authentication:
                page.click("#auth")
            if not authentication.value.ok:
                raise RuntimeError("dashboard authentication failed")
            if page.locator("#filter-limit").count():
                page.select_option("#filter-limit", "100")

            time.sleep(1.5)
            # Record keys already on dashboard to ignore baseline cards
            baseline_keys: set[str] = set(page.evaluate("Object.keys(window.__g1RenderTimes || {})"))
            print(f"[X19] Baseline cards already present: {len(baseline_keys)}", file=sys.stderr)

            # Generate and commit events
            event_commit_times: dict[str, float] = {}  # key -> commit_unix
            event_id_map: dict[str, str] = {}  # key -> event_id

            for i in range(args.events):
                event = make_event(args.device_id, args.camera_id)
                event_id = event["event_id"]
                key = json.dumps([args.device_id, event_id], separators=(",", ":"))
                event_id_map[key] = event_id

                pipeline.evidence.persist(event)
                t_commit = time.time()
                event_commit_times[key] = t_commit

                worker.wake()

                if (i + 1) % 10 == 0 or i == args.events - 1:
                    print(f"[X19] Sent event {i + 1}/{args.events} (id={event_id})", file=sys.stderr)

                if i < args.events - 1 and args.interval > 0:
                    time.sleep(args.interval)

            print(f"[X19] Waiting for events to render in dashboard DOM...", file=sys.stderr)
            deadline = time.time() + 25.0
            render_times: dict[str, float] = {}

            while time.time() < deadline:
                current_renders: dict[str, float] = page.evaluate("window.__g1RenderTimes || {}")
                for k in event_commit_times:
                    if k in current_renders and k not in baseline_keys:
                        render_times[k] = current_renders[k]

                if len(render_times) >= len(event_commit_times):
                    break
                time.sleep(0.5)

        # Compute latencies
        latency_values: list[float] = []
        for key, t_commit in event_commit_times.items():
            ev_id = event_id_map[key]
            if key in render_times:
                t_render = render_times[key] / 1000.0
                lat = max(0.0, t_render - t_commit)
                latency_values.append(lat)
                samples.append({
                    "event_id": ev_id,
                    "commit_unix": t_commit,
                    "render_unix": t_render,
                    "latency_seconds": lat,
                })
            else:
                missing_event_ids.append(ev_id)

    finally:
        worker.stop()
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()

    latency_stats = percentiles(latency_values)
    events_sent = args.events
    events_rendered = len(latency_values)
    p95 = latency_stats.get("p95", 999.0)
    passed = (events_rendered == events_sent) and (p95 <= 5.0)

    report = {
        "scope": "g1_x19_latency",
        "server_origin": f"{parsed_url.scheme}://{parsed_url.netloc}",
        "server_is_loopback": server_is_loopback,
        "events_sent": events_sent,
        "events_rendered": events_rendered,
        "missing_event_ids": missing_event_ids,
        "latency_seconds": latency_stats,
        "samples": samples,
        "clock_basis": "single host: edge commit time.time() and Firefox Date.now() on the same machine",
        "clock_uncertainty_ms": 17,
        "render_definition": "first insertion of the event card into the dashboard DOM",
        "dashboard_poll_seconds": 3.0,
        "p95_target_seconds": 5.0,
        "pass": passed,
        "versions": {
            "python": sys.version.split()[0],
            "playwright": pw_version,
            "git_head": git_head,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[X19] Report written to {args.output}. Pass={passed}, P95={p95:.3f}s", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
