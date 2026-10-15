"""End-to-end Live RTSP Perception Pipeline with recorder correlation and reconnect handling."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable
from uuid import uuid4

import cv2
import numpy as np

from apps.edge.health import EdgeHealthMonitor
from apps.edge.incident import IncidentEngine
from apps.edge.oracle_detector import OnnxDetector
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder
from apps.edge.rtsp import (
    ExponentialBackoff,
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
        health: EdgeHealthMonitor | None = None,
        drain_frames: bool = False,
        reconnect_initial_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
        reconnect_backoff: ExponentialBackoff | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] | None = None,
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
        self.drain_frames = drain_frames
        self.clock = clock
        self.sleeper = sleeper
        self.reconnect_backoff = (
            reconnect_backoff
            if reconnect_backoff is not None
            else ExponentialBackoff(
                initial_delay=reconnect_initial_delay,
                max_delay=reconnect_max_delay,
                clock=clock,
                sleeper=sleeper,
            )
        )

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
            if getattr(self.ring_recorder, "on_source_change", None) is None:
                self.ring_recorder.on_source_change = self._on_recorder_source_change
            self.ring_recorder.session_id = self.session_id
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
                on_source_change=self._on_recorder_source_change,
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
                on_source_change=self._on_recorder_source_change,
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
                health=health,
            )

        # 7. Health monitor
        self.health = health or getattr(self.pipeline, "health", None) or EdgeHealthMonitor(
            recorder=self.recorder,
            recorder_session_id=self.session_id,
            outbox=self.outbox,
            backend_checker=uploader,
        )
        if hasattr(self.pipeline, "health") and self.health is not None:
            self.pipeline.health = self.health
            self.health.quota_manager = self.pipeline.quota_manager

        # 7. Internal synchronization and telemetry
        self._lock = threading.RLock()
        self._is_running: bool = False
        self.is_connected: bool = (self._current_source == "rtsp") if self.rtsp_url else True
        if self.rtsp_url and self._current_source != "rtsp":
            if self.health is not None:
                self.health.set_component_capability("camera", "disconnected")
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
        self._reconnect_thread: threading.Thread | None = None
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
                    "rtsp_transport;tcp|fflags;nobuffer|max_delay;500000|timeout;2000000"
                )
                cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
                if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
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
            self.handle_disconnect("rtsp_open_failed")
            return None

        # Fallback file capture
        if not self.rtsp_url or self._current_source == "fallback":
            fallback_file = self.fallback_path
            if fallback_file is None or not fallback_file.is_file():
                fallback_file = self._generate_synthetic_fixture()
                self.fallback_path = fallback_file

            self._cap = self._open_capture(str(fallback_file))
            return self._cap

        return None

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
            self.last_disconnect_time = self.clock() if hasattr(self, "clock") else time.monotonic()
            self._last_error = reason
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            if self.health is not None:
                self.health.set_component_capability("camera", "disconnected")
                self.health.set_component_capability("analytics", "failed")
                self.health.record_frame_drop()
            self.pipeline.observation_gap()

    def _on_recorder_source_change(self, source: str, session_id: str) -> None:
        """Handle source change reported by RtspRingRecorder."""
        needs_reconnect = False
        with self._lock:
            if source == "fallback":
                self.session_id = session_id
                self.pipeline.stream_session_id = session_id
                if self.health is not None:
                    self.health.recorder_session_id = session_id
                if self.is_connected:
                    self.handle_disconnect("recorder_fallback")
            elif source == "rtsp":
                needs_reconnect = not self.is_connected
        if needs_reconnect:
            # reconnect() does blocking probe/open I/O and takes self._lock itself where needed;
            # running it outside the lock keeps step() and stop() responsive.
            self.reconnect()

    def handle_reconnect(self, new_session_id: str | None = None) -> int:
        """Handle stream reconnect: increment core_epoch and update lineage per contracts.md:24."""
        with self._lock:
            self.is_connected = True
            self.discontinuity_count += 1
            self.last_reconnect_time = self.clock() if hasattr(self, "clock") else time.monotonic()
            new_epoch = self.pipeline.core_epoch + 1
            self.pipeline.set_core_epoch(new_epoch)
            session = str(new_session_id) if new_session_id is not None else str(uuid4())
            self.pipeline.stream_session_id = session
            self.session_id = session
            if self.ring_recorder is not None:
                self.ring_recorder.rollover_session(session)
                self.ring_recorder._current_source = "rtsp"
            if self.health is not None:
                self.health.recorder_session_id = session
                self.health.set_component_capability("camera", "active")
                self.health.set_component_capability("analytics", "active")
            if hasattr(self, "reconnect_backoff"):
                self.reconnect_backoff.reset()
            self._stream_start_monotonic = None
            self.last_frame_time = None
            self._frame_counter = 0
            return self.pipeline.core_epoch

    def reconnect(self) -> bool:
        """Attempt to probe and reconnect to RTSP stream.

        Returns True if reconnection succeeded, False otherwise.
        """
        if not self.rtsp_url:
            return False

        with self._lock:
            if self.is_connected and self._current_source == "rtsp":
                return True

        try:
            probe_rtsp_stream(self.rtsp_url, timeout_seconds=self.probe_timeout_seconds)
            new_cap = self._open_capture(self.rtsp_url)
            if new_cap is None or not new_cap.isOpened():
                return False

            with self._lock:
                if self.is_connected and self._current_source == "rtsp":
                    new_cap.release()
                    return True
                if self._cap is not None:
                    self._cap.release()
                self._cap = new_cap
                self._current_source = "rtsp"
                self.handle_reconnect()
                return True
        except Exception as exc:
            with self._lock:
                self._last_error = sanitize_probe_output(str(exc), self.rtsp_url)
                if self.health is not None:
                    self.health.set_component_capability("camera", "disconnected")
            return False

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
            now_mono = self.clock() if hasattr(self, "clock") else time.monotonic()
            now_wall = time.time()
            if self._stream_start_monotonic is None:
                self._stream_start_monotonic = now_mono

            if timestamp is not None:
                ts = float(timestamp)
                if self.last_frame_time is not None and ts <= self.last_frame_time:
                    ts = self.last_frame_time + 1e-6
            else:
                raw_ts = now_mono - self._stream_start_monotonic
                if self.last_frame_time is not None and raw_ts <= self.last_frame_time:
                    ts = self.last_frame_time + 1e-6
                else:
                    ts = max(0.0, raw_ts)

            if frame_id is not None:
                fid = int(frame_id)
            else:
                self._frame_counter += 1
                fid = self._frame_counter

            if frame is None:
                read_frame, read_status = self._read_next_frame()
                if read_frame is not None:
                    frame = read_frame
                else:
                    frame = np.zeros((0, 0, 3), dtype=np.uint8)
                if observation_status is None and read_status is not None:
                    observation_status = read_status

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

            if not self.is_connected and self.health is not None:
                self.health.set_component_capability("camera", "disconnected")

            self.frames_processed += 1
            if events:
                self.incidents_emitted += len(events)
                self.last_emitted_events.extend(events)

            return events

    def _read_next_frame(self) -> tuple[np.ndarray | None, str | None]:
        was_connected = self.is_connected
        cap = self._ensure_capture()
        if cap is not None and cap.isOpened():
            if self._current_source == "rtsp" and getattr(self, "drain_frames", False):
                cap.grab()
                ret, bgr_frame = cap.retrieve()
            else:
                ret, bgr_frame = cap.read()

            if ret and bgr_frame is not None:
                rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
                return rgb_frame, None

            if self._current_source == "fallback":
                # Video file reached EOF, loop back to start
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, bgr_frame = cap.read()
                if ret and bgr_frame is not None:
                    rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
                    return rgb_frame, None
                return None, "missing"
            else:
                # RTSP stream dropped / EOF
                self.handle_disconnect("rtsp_read_eof")
                return None, "missing"

        # Stream missing / capture unavailable. _ensure_capture() already records the disconnect when an
        # RTSP open fails; only record it here if that path did not (avoids double-counting drops/gaps).
        if self.rtsp_url and was_connected and self.is_connected:
            self.handle_disconnect("rtsp_unavailable")
        return None, "missing"

    def start(self) -> None:
        """Start concurrent ring buffer recording and frame perception loop in background."""
        with self._lock:
            if self._is_running:
                return
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("previous perception loop is still stopping")
            self.health.mark_starting()
            self._is_running = True
            self._stop_event.clear()
            self._ready_event.clear()

            try:
                if self.ring_recorder is not None:
                    self.ring_recorder.start()

                if self.rtsp_url:
                    self._reconnect_thread = threading.Thread(
                        target=self._reconnect_loop,
                        daemon=True,
                        name=f"live-reconnect-{self.session_id}",
                    )
                    self._reconnect_thread.start()

                self._thread = threading.Thread(
                    target=self._run_loop,
                    daemon=True,
                    name=f"live-runner-{self.session_id}",
                )
                self._thread.start()
            except Exception:
                self._is_running = False
                self._stop_event.set()
                self.health.mark_stopped()
                if self.ring_recorder is not None:
                    self.ring_recorder.stop()
                raise

        self._ready_event.wait(timeout=10.0)

    def _reconnect_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self.is_connected and self.rtsp_url:
                self.reconnect_backoff.wait(self._stop_event)
                if self._stop_event.is_set():
                    break
                try:
                    self.reconnect()
                except Exception as exc:
                    logger.debug("LivePerceptionRunner background reconnect attempt failed: %s", exc)
            else:
                self._stop_event.wait(0.5)

    def _run_loop(self) -> None:
        target_period = 1.0 / self.sample_fps if self.sample_fps > 0 else 0.2
        self.health.mark_started()
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
            self.health.mark_stopped()
            self._is_running = False

    def stop(self, timeout: float = 5.0) -> None:
        """Stop background execution and cleanly release processes, threads, and captures."""
        with self._lock:
            self.health.mark_stopped()
            recon_alive = self._reconnect_thread is not None and self._reconnect_thread.is_alive()
            if not self._is_running and not recon_alive and (self._thread is None or not self._thread.is_alive()):
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

        recon_thread = self._reconnect_thread
        if recon_thread and recon_thread.is_alive():
            recon_thread.join(timeout=timeout)

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
                "health": self.health.get_health_snapshot() if self.health is not None else None,
            }

    def __enter__(self) -> LivePerceptionRunner:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
