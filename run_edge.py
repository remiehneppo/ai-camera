"""Run Live Edge Perception Pipeline with Camera RTSP and Server Ingestion."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from uuid import uuid4

from apps.edge.doctor import load_module_registry
from apps.edge.live_pipeline import LivePerceptionRunner
from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder
from apps.edge.rtsp import load_rtsp_config
from apps.edge.rtsp_recorder import RtspRingRecorder
from apps.edge.uploader import EdgeUploader, validate_server_url
from domain.alert_module_config import CameraModuleConfig, ConfigError

os.environ.setdefault("ALLOW_INSECURE_LAB", "1")


def main(argv: list[str] | None = None, stop_event: threading.Event | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Live Edge Perception Pipeline with Camera RTSP and Server Ingestion.")
    parser.add_argument("--module-config", action="append", required=True, help="Path to module x camera configuration document")
    parser.add_argument("--source", choices=["rtsp", "file"], default="rtsp")
    parser.add_argument("--file", type=Path, default=None, help="Fallback or source file path (required when --source file)")
    parser.add_argument("--camera-id", default="lab-camera-01")
    parser.add_argument("--device-id", default="lab-edge-01")
    parser.add_argument("--root", type=Path, default=Path("data/edge"))
    parser.add_argument("--manifest", type=Path, default=Path("models/yolox-tiny/manifest.json"))
    parser.add_argument("--model", type=Path, default=Path("data/oracle/yolox_tiny.onnx"))
    parser.add_argument("--sample-fps", type=float, default=3.0)
    parser.add_argument("--upload-interval", type=float, default=5.0)
    parser.add_argument("--status-log", type=Path, default=None)

    args = parser.parse_args(argv)

    if stop_event is None:
        stop_event = threading.Event()
        def _handle_signal(sig: int, frame: object) -> None:
            stop_event.set()
        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            pass

    server_url_raw = os.environ.get("SERVER_URL")
    if not server_url_raw:
        print(json.dumps({"scope": "startup", "status": "error", "reason": "missing_environment", "field": "SERVER_URL"}))
        return 1

    device_token = os.environ.get("DEVICE_TOKEN")
    if not device_token:
        print(json.dumps({"scope": "startup", "status": "error", "reason": "missing_environment", "field": "DEVICE_TOKEN"}))
        return 1

    try:
        server_url = validate_server_url(server_url_raw)
    except ValueError as e:
        print(json.dumps({"scope": "startup", "status": "error", "reason": "invalid_server_url", "detail": str(e)}))
        return 1

    try:
        loaded = load_module_registry(args.module_config)
    except ConfigError as error:
        print(json.dumps({"scope": "startup", "status": "error", "reason": "invalid module configuration", "error": error.describe()}))
        return 1

    registry = loaded.registry
    camera_id = args.camera_id
    session_id = loaded.session or str(uuid4())

    if loaded.session is None:
        for module in registry.modules():
            cfg = registry.config(module, camera_id)
            if cfg is not None:
                registry.activate(cfg, session_id=session_id)

    switch = registry.activation_for_camera(camera_id, session_id)
    configs: list[CameraModuleConfig] = []
    for m in registry.modules():
        m_cfg = registry.config(m, camera_id)
        if m_cfg is not None:
            configs.append(m_cfg)

    if args.source == "rtsp":
        try:
            rtsp_url = load_rtsp_config().stream_url
        except ValueError as exc:
            print(json.dumps({"scope": "startup", "status": "error", "reason": "invalid_camera_source", "detail": str(exc)}))
            return 1
        fallback_path = None
    elif args.source == "file":
        rtsp_url = ""
        if not args.file or not Path(args.file).is_file():
            print(json.dumps({"scope": "startup", "status": "error", "reason": "invalid_camera_source", "detail": "file not found or missing"}))
            return 1
        fallback_path = Path(args.file)
    else:
        print(json.dumps({"scope": "startup", "status": "error", "reason": "invalid_camera_source", "detail": "unsupported source"}))
        return 1

    root = args.root
    root.mkdir(parents=True, exist_ok=True)

    if not switch["analytics_enabled"]:
        print(
            json.dumps(
                {
                    "scope": "startup",
                    "status": "ok",
                    "camera_id": camera_id,
                    "session_id": session_id,
                    "analytics_enabled": False,
                    "disabled_reason": switch["disabled_reason"],
                    "modules": switch["modules"],
                    "disabled_modules": switch["disabled_modules"],
                }
            )
        )
        with RtspRingRecorder(
            root=root / "ring",
            ring_seconds=600.0,
            rtsp_url=rtsp_url or None,
            fallback_path=fallback_path,
            session_id=session_id,
        ):
            stop_event.wait()
        return 0

    uploader = EdgeUploader(
        outbox=EventOutbox(root / "events.sqlite3"),
        recorder=FileRecorder(root / "ring", ring_seconds=600),
        server_url=server_url,
        device_token=device_token,
    )

    try:
        runner = LivePerceptionRunner(
            root=root,
            rtsp_url=rtsp_url,
            fallback_path=fallback_path,
            sample_fps=args.sample_fps,
            session_id=session_id,
            camera_id=camera_id,
            device_id=args.device_id,
            uploader=uploader,
            upload_interval_seconds=args.upload_interval,
            probe_timeout_seconds=5.0,
            module_configs=configs,
            alert_registry=registry,
            manifest_path=args.manifest,
            model_path=args.model,
        )
    except ConfigError as e:
        print(json.dumps({"scope": "startup", "status": "error", "reason": "invalid module configuration", "error": e.describe()}))
        return 1
    except Exception as e:
        print(json.dumps({"scope": "startup", "status": "error", "reason": "enabled analytics artifact or runtime validation failed", "error_type": type(e).__name__}))
        return 1

    if args.source == "rtsp" and runner.current_source != "rtsp":
        print(json.dumps({"scope": "startup", "status": "error", "reason": "camera_unreachable", "detail": runner.status().get("error")}))
        return 1

    print(
        json.dumps(
            {
                "scope": "startup",
                "status": "ok",
                "camera_id": camera_id,
                "session_id": session_id,
                "analytics_enabled": True,
                "disabled_reason": switch["disabled_reason"],
                "modules": switch["modules"],
                "disabled_modules": switch["disabled_modules"],
            }
        )
    )

    with ExitStack() as stack:
        status_log = None
        if args.status_log:
            args.status_log.parent.mkdir(parents=True, exist_ok=True)
            status_log = stack.enter_context(open(args.status_log, "a", encoding="utf-8"))
        stack.enter_context(runner)
        if status_log is not None:
            status_log.write(json.dumps(runner.status(), sort_keys=True, default=str) + "\n")
            status_log.flush()
        last_status_time = time.monotonic()
        while not stop_event.wait(1.0):
            if status_log is not None:
                now = time.monotonic()
                if now - last_status_time >= 5.0:
                    status_log.write(json.dumps(runner.status(), sort_keys=True, default=str) + "\n")
                    status_log.flush()
                    last_status_time = now
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
