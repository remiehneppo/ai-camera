"""Run Live Edge Perception Pipeline with Camera RTSP and Server Ingestion."""
import os
import signal
import threading
from pathlib import Path

from apps.edge.live_pipeline import LivePerceptionRunner
from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder
from apps.edge.uploader import EdgeUploader

os.environ.setdefault("ALLOW_INSECURE_LAB", "1")

stop_event = threading.Event()


def _handle_signal(sig, frame):
    stop_event.set()


def _build_uploader(root: Path) -> EdgeUploader:
    outbox = EventOutbox(root / "events.sqlite3")
    recorder = FileRecorder(root / "ring", ring_seconds=600)
    return EdgeUploader(
        outbox=outbox,
        recorder=recorder,
        server_url=os.environ.get("SERVER_URL", "http://[IP]:8000"),
        device_token=os.environ.get("DEVICE_TOKEN", "fixture-device-token"),
    )


if __name__ == "__main__":
    root = Path("data/edge")
    root.mkdir(parents=True, exist_ok=True)
    uploader = _build_uploader(root)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    with LivePerceptionRunner(
        root=root,
        uploader=uploader,
        probe_timeout_seconds=5.0,
        upload_interval_seconds=5.0,
    ) as runner:
        print(f"[EDGE] Started. Source mode: {runner.current_source}, Session: {runner.session_id}")
        while not stop_event.wait(1.0):
            pass
        print("[EDGE] Stopping...")
