"""End-to-end Live RTSP Perception Pipeline with recorder correlation and reconnect handling."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
from uuid import uuid4

import cv2
import numpy as np

from apps.edge.incident import IncidentEngine
from apps.edge.oracle_detector import OnnxDetector
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder
from apps.edge.rtsp import (
    load_rtsp_config,
    probe_rtsp_stream,
    redact_rtsp_url,
    sanitize_probe_output,
)
from apps.edge.rtsp_recorder import RtspRingRecorder
from apps.edge.tracker import ByteTracker
from apps.edge.uploader import EdgeUploader

logger = logging.getLogger(__name__)


class LivePerceptionRunner:
    """Orchestrates concurrent RTSP recording and real-time frame perception under one session."""

    def __init__(
        self,
        root: str | Path,
        *,
        rtsp_url: str | None = None,
        fallback_path: str | Path | None = None,
        sample_fps: float = 3.0,
        session_id: str | None = None,
        ring_seconds: float = 600.0,
        segment_seconds: float = 2.0,
        probe_timeout_seconds: float = 2.0,
        camera_id: str = "lab-camera-01",
        device_id: str = "lab-edge-01",
        detector: OnnxDetector | None = None,
        tracker: ByteTracker | None = None,
        incident_engine: IncidentEngine | None = None,
        uploader: EdgeUploader | None = None,
        pipeline: PerceptionPipeline | None = None,
        ring_recorder: RtspRingRecorder | None = None,
        upload_interval_seconds: float | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.sample_fps = float(sample_fps)
        self.ring_seconds = float(ring_seconds)
        self.segment_seconds = float(segment_seconds)
        self.probe_timeout_seconds = float(probe_timeout_seconds)
        self.camera_id = camera_id
        self.device_id = device_id
        self.upload_interval_seconds = upload_interval_seconds

        # 1. Resolve RTSP URL safely without leaking credentials
        if rtsp_url == "":
            self.rtsp_url: str | None = None
        elif rtsp_url is not None:
            self.rtsp_url = rtsp_url
        else:
            try:
                cfg = load_rtsp_config()
                self.rtsp_url = cfg.stream_url
            except Exception:
                self.rtsp_url = None

        # 2. Resolve fallback video path
        if fallback_path is not None:
            self.fallback_path: Path | None = Path(fallback_path)
        else:
            candidate = Path(".scratch/replay-measurements/h264-10s.mkv")
            self.fallback_path = candidate if candidate.is_file() else None

        # 3. Resolve stream session identity
        if pipeline is not None:
            self.session_id = pipeline.stream_session_id
        elif ring_recorder is not None:
            self.session_id = ring_recorder.session_id
        else:
            self.session_id = session_id or str(uuid4())

        # 4. Probe RTSP source to determine initial source mode
        self._current_source = "fallback"
        self._last_error: str | None = None
        if self.rtsp_url:
            try:
                probe_rtsp_stream(self.rtsp_url, timeout_seconds=self.probe_timeout_seconds)
                self._current_source = "rtsp"
            except Exception as exc:
                self._last_error = sanitize_probe_output(str(exc), self.rtsp_url)
                logger.warning(
                    "RTSP probe failed for %s: %s; falling back to fixture",
                    redact_rtsp_url(self.rtsp_url),
                    self._last_error,
                )
                self._current_source = "fallback"

        # 5. Initialize or bind RtspRingRecorder
        if ring_recorder is not None:
            self.ring_recorder: RtspRingRecorder | None = ring_recorder
            self.recorder: FileRecorder = ring_recorder.recorder
        elif pipeline is not None:
            self.recorder = pipeline.recorder
            self.ring_recorder = RtspRingRecorder(
                root=self.root / "ring",
                ring_seconds=self.ring_seconds,
                rtsp_url=self.rtsp_url,
                fallback_path=self.fallback_path,
                segment_seconds=self.segment_seconds,
                session_id=self.session_id,
                probe_timeout_seconds=self.probe_timeout_seconds,
                recorder=self.recorder,
            )
        else:
            self.ring_recorder = RtspRingRecorder(
                root=self.root / "ring",
                ring_seconds=self.ring_seconds,
                rtsp_url=self.rtsp_url,
                fallback_path=self.fallback_path,
                segment_seconds=self.segment_seconds,
                session_id=self.session_id,
                probe_timeout_seconds=self.probe_timeout_seconds,
            )
            self.recorder = self.ring_recorder.recorder

        # 6. Initialize or bind PerceptionPipeline
        if pipeline is not None:
            self.pipeline = pipeline
            self.outbox = pipeline.outbox
            self.camera_id = pipeline.camera_id
            self.device_id = pipeline.device_id
        else:
            self.outbox = EventOutbox(self.root / "events.sqlite3")
            origin = "live" if self._current_source == "rtsp" else "replay"
            self.pipeline = PerceptionPipeline(
                recorder=self.recorder,
                outbox=self.outbox,
                detector=detector,
                tracker=tracker,
                incident_engine=incident_engine,
                uploader=uploader,
                camera_id=self.camera_id,
                device_id=self.device_id,
                stream_session_id=self.session_id,
                origin=origin,
            )

        # 7. Internal synchronization and telemetry
        self._lock = threading.RLock()
        self._is_running: bool = False
        self.is_connected: bool = True
        self.disconnect_count: int = 0
        self.discontinuity_count: int = 0
        self.last_disconnect_time: float | None = None
        self.last_reconnect_time: float | None = None

        self._frame_counter: int = 0
        self.frames_processed: int = 0
        self.incidents_emitted: int = 0
        self.last_emitted_events: list[dict[str, Any]] = []

        self._stream_start_monotonic: float | None = None
        self.last_frame_time: float | None = None
        self.last_capture_time: float | None = None
        self.last_receive_time: float | None = None

        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._last_upload_time: float = 0.0

    @property
    def current_source(self) -> str:
        with self._lock:
            return self._current_source

    def __repr__(self) -> str:
        redacted = redact_rtsp_url(self.rtsp_url) if self.rtsp_url else None
        return (
            f"LivePerceptionRunner(session_id={self.session_id!r}, "
            f"camera_id={self.camera_id!r}, rtsp_url={redacted!r}, "
            f"source={self._current_source!r}, sample_fps={self.sample_fps})"
        )

    def _open_capture(self, source: str) -> cv2.VideoCapture | None:
        try:
            if source.startswith("rtsp://") or source.startswith("rtsps://"):
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                    "rtsp_transport;tcp|timeout;2000000"
                )
                cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
            else:
                cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                return None
            return cap
        except Exception as exc:
            logger.warning("Failed to open video source %s: %s", redact_rtsp_url(source), exc)
            return None

    def _ensure_capture(self) -> cv2.VideoCapture | None:
        if self._cap is not None and self._cap.isOpened():
            return self._cap

        if self.rtsp_url and self._current_source == "rtsp":
            self._cap = self._open_capture(self.rtsp_url)
            if self._cap is not None:
                self.is_connected = True
                return self._cap
            self._current_source = "fallback"

        # Fallback file capture
        fallback_file = self.fallback_path
        if fallback_file is None or not fallback_file.is_file():
            fallback_file = self._generate_synthetic_fixture()
            self.fallback_path = fallback_file

        self._cap = self._open_capture(str(fallback_file))
        return self._cap

    def _generate_synthetic_fixture(self) -> Path:
        syn_path = self.root / "synthetic-fallback-10s.mkv"
        if syn_path.is_file():
            return syn_path
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x480:rate=15",
            "-t",
            "10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(syn_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return syn_path

    def _generate_synthetic_frame(self) -> np.ndarray:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (35, 35, 35)
        return frame

    def handle_disconnect(self, reason: str = "stream_disconnected") -> None:
        """Mark observation gap on disconnect / frame drop to prevent false velocity or false onset."""
        with self._lock:
            self.is_connected = False
            self.disconnect_count += 1
            self.last_disconnect_time = time.monotonic()
            self._last_error = reason
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            self.pipeline.observation_gap()

    def handle_reconnect(self, new_session_id: str | None = None) -> int:
        """Handle stream reconnect: increment core_epoch and update lineage per contracts.md:24."""
        with self._lock:
            self.is_connected = True
            self.discontinuity_count += 1
            self.last_reconnect_time = time.monotonic()
            new_epoch = self.pipeline.core_epoch + 1
            self.pipeline.set_core_epoch(new_epoch)
            if new_session_id is not None:
                self.pipeline.stream_session_id = str(new_session_id)
                self.session_id = self.pipeline.stream_session_id
            return self.pipeline.core_epoch

    def step(
        self,
        *,
        frame: np.ndarray | None = None,
        timestamp: float | None = None,
        frame_id: int | None = None,
        detections: list[dict[str, Any]] | None = None,
        observation_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Process one frame step through the perception pipeline with honest monotonic tracking."""
        with self._lock:
            now_mono = time.monotonic()
            now_wall = time.time()
            if self._stream_start_monotonic is None:
                self._stream_start_monotonic = now_mono

            if timestamp is not None:
                ts = float(timestamp)
            else:
                ts = round(now_mono - self._stream_start_monotonic, 3)

            if frame_id is not None:
                fid = int(frame_id)
            else:
                self._frame_counter += 1
                fid = self._frame_counter

            if frame is None:
                frame = self._read_next_frame()

            self.last_capture_time = now_mono
            self.last_receive_time = now_wall
            self.last_frame_time = ts

            events = self.pipeline.process_frame(
                frame,
                timestamp=ts,
                frame_id=fid,
                detections=detections,
                observation_status=observation_status,
            )

            self.frames_processed += 1
            if events:
                self.incidents_emitted += len(events)
                self.last_emitted_events.extend(events)

            return events

    def _read_next_frame(self) -> np.ndarray:
        cap = self._ensure_capture()
        if cap is not None and cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                return frame
            if self._current_source == "fallback":
                # Video file reached EOF, loop back to start
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if ret and frame is not None:
                    return frame
            else:
                # RTSP stream dropped
                self.handle_disconnect("rtsp_read_eof")

        return self._generate_synthetic_frame()

    def start(self) -> None:
        """Start concurrent ring buffer recording and frame perception loop in background."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._stop_event.clear()
            self._ready_event.clear()

            if self.ring_recorder is not None:
                self.ring_recorder.start()

            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name=f"live-runner-{self.session_id}",
            )
            self._thread.start()

        self._ready_event.wait(timeout=10.0)

    def _run_loop(self) -> None:
        target_period = 1.0 / self.sample_fps if self.sample_fps > 0 else 0.2
        self._ready_event.set()

        try:
            while not self._stop_event.is_set():
                loop_start = time.monotonic()
                try:
                    self.step()
                except Exception as exc:
                    logger.warning("Error in live perception step: %s", exc)

                # Periodic background evidence upload if enabled
                if self.upload_interval_seconds and self.upload_interval_seconds > 0:
                    if loop_start - self._last_upload_time >= self.upload_interval_seconds:
                        try:
                            self.trigger_upload()
                            self._last_upload_time = loop_start
                        except Exception as up_exc:
                            logger.warning("Periodic upload trigger failed: %s", up_exc)

                elapsed = time.monotonic() - loop_start
                sleep_time = target_period - elapsed
                if sleep_time > 0:
                    self._stop_event.wait(sleep_time)
        finally:
            self._is_running = False

    def stop(self, timeout: float = 5.0) -> None:
        """Stop background execution and cleanly release processes, threads, and captures."""
        with self._lock:
            if not self._is_running and (self._thread is None or not self._thread.is_alive()):
                if self.ring_recorder is not None:
                    self.ring_recorder.stop()
                return

            self._stop_event.set()
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            thread = self._thread

        if thread and thread.is_alive():
            thread.join(timeout=timeout)

        with self._lock:
            if self.ring_recorder is not None:
                self.ring_recorder.stop()

            self._is_running = False

    def trigger_upload(self, *, reconcile: bool = True, finish_sessions=()) -> int:
        """Trigger reconciliation and upload of pending events and evidence clips."""
        return self.pipeline.trigger_upload(reconcile=reconcile, finish_sessions=finish_sessions)

    def status(self) -> dict[str, Any]:
        """Return safe, sanitized live runner status."""
        with self._lock:
            ring_status = self.ring_recorder.status() if self.ring_recorder is not None else None
            return {
                "status": "running" if self._is_running else "stopped",
                "source": self._current_source,
                "is_connected": self.is_connected,
                "camera_id": self.camera_id,
                "device_id": self.device_id,
                "session_id": self.session_id,
                "core_epoch": self.pipeline.core_epoch,
                "discontinuity_count": self.discontinuity_count,
                "disconnect_count": self.disconnect_count,
                "redacted_rtsp_url": redact_rtsp_url(self.rtsp_url) if self.rtsp_url else None,
                "fallback_path": str(self.fallback_path) if self.fallback_path else None,
                "sample_fps": self.sample_fps,
                "frames_processed": self.frames_processed,
                "incidents_emitted": self.incidents_emitted,
                "last_frame_time": self.last_frame_time,
                "last_capture_time": self.last_capture_time,
                "ring_recorder": ring_status,
                "error": self._last_error,
            }

    def __enter__(self) -> LivePerceptionRunner:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
