"""RTSP rolling ring buffer recorder with graceful fallback and credential sanitization."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import threading
from typing import Any
from uuid import uuid4

from apps.edge.recorder import FileRecorder
from apps.edge.rtsp import load_rtsp_config, probe_rtsp_stream, redact_rtsp_url, sanitize_probe_output

logger = logging.getLogger(__name__)


class RtspRingRecorder:
    """Manages continuous rolling ring buffer recording from RTSP with fixture fallback."""

    def __init__(
        self,
        root: str | Path,
        ring_seconds: float = 600.0,
        *,
        rtsp_url: str | None = None,
        fallback_path: str | Path | None = None,
        segment_seconds: float = 2.0,
        session_id: str | None = None,
        probe_timeout_seconds: float = 2.0,
        recorder: FileRecorder | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ring_seconds = float(ring_seconds)
        self.segment_seconds = float(segment_seconds)
        self.probe_timeout_seconds = float(probe_timeout_seconds)
        self.session_id = session_id or str(uuid4())
        self.recorder = recorder if recorder is not None else FileRecorder(self.root, ring_seconds=self.ring_seconds)

        # 1. Resolve RTSP URL (secrets must never be leaked)
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

        self._is_running: bool = False
        self._current_source: str = "rtsp" if self.rtsp_url else "fallback"
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._ffmpeg_process: subprocess.Popen[Any] | None = None
        self._last_error: str | None = None
        self._lock = threading.Lock()
        self._fifo_path: Path | None = None

    def __repr__(self) -> str:
        redacted = redact_rtsp_url(self.rtsp_url) if self.rtsp_url else None
        return (
            f"RtspRingRecorder(root={self.root!r}, ring_seconds={self.ring_seconds}, "
            f"rtsp_url={redacted!r}, session_id={self.session_id!r}, source={self._current_source!r})"
        )

    def start(self) -> None:
        """Start background ring buffer recording."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._stop_event.clear()
            self._ready_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name=f"rtsp-recorder-{self.session_id}",
            )
            self._thread.start()

        # Block until stream connection or fallback recording has initialized
        self._ready_event.wait(timeout=10.0)

    def _run_loop(self) -> None:
        try:
            # 1. Attempt RTSP if configured
            if self.rtsp_url:
                try:
                    probe_rtsp_stream(self.rtsp_url, timeout_seconds=self.probe_timeout_seconds)
                    self._current_source = "rtsp"
                    self._record_rtsp_stream()
                    return
                except Exception as exc:
                    self._last_error = sanitize_probe_output(str(exc), self.rtsp_url)
                    logger.warning(
                        "RTSP probe/stream failed for %s: %s; falling back to fixture",
                        redact_rtsp_url(self.rtsp_url),
                        self._last_error,
                    )
                    self._current_source = "fallback"

            # 2. Fallback to fixture or synthetic
            self._record_fallback()
        except Exception as exc:
            self._last_error = str(exc)
            logger.error("RtspRingRecorder background loop error: %s", exc)
        finally:
            self._ready_event.set()

    def _record_rtsp_stream(self) -> None:
        assert self.rtsp_url is not None
        fifo_path = self.root / f".feed-{self.session_id}.mkv"
        self._fifo_path = fifo_path
        if fifo_path.exists():
            fifo_path.unlink()
        os.mkfifo(fifo_path)

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            self.rtsp_url,
            "-c:v",
            "copy",
            "-f",
            "matroska",
            "-y",
            str(fifo_path),
        ]

        self._ffmpeg_process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        self._ready_event.set()

        try:
            with self.recorder.ingest(fifo_path, self.session_id, segment_seconds=self.segment_seconds):
                while not self._stop_event.is_set():
                    if self._ffmpeg_process.poll() is not None:
                        stderr_out = (
                            self._ffmpeg_process.stderr.read().decode(errors="replace")
                            if self._ffmpeg_process.stderr
                            else ""
                        )
                        sanitized = sanitize_probe_output(stderr_out, self.rtsp_url)
                        raise RuntimeError(f"RTSP ffmpeg producer exited: {sanitized}")
                    self._stop_event.wait(0.2)
        finally:
            if self._ffmpeg_process and self._ffmpeg_process.poll() is None:
                self._ffmpeg_process.terminate()
                try:
                    self._ffmpeg_process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._ffmpeg_process.kill()
            if fifo_path.exists():
                fifo_path.unlink(missing_ok=True)

    def _record_fallback(self) -> None:
        self._current_source = "fallback"
        fallback_file = self.fallback_path
        if fallback_file is None or not fallback_file.is_file():
            fallback_file = self._generate_synthetic_fixture()
            self.fallback_path = fallback_file

        try:
            self.recorder.record_file(fallback_file, self.session_id, segment_seconds=self.segment_seconds)
        except Exception as exc:
            self._last_error = f"Fallback recording failed: {exc}"
            logger.error("Failed to record fallback file %s: %s", fallback_file, exc)
        finally:
            self._ready_event.set()

        while not self._stop_event.is_set():
            self._stop_event.wait(0.5)

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

    def stop(self) -> None:
        """Stop background recording and clean up child processes and pipes."""
        with self._lock:
            if not self._is_running:
                return
            self._stop_event.set()
            if self._ffmpeg_process and self._ffmpeg_process.poll() is None:
                self._ffmpeg_process.terminate()
                try:
                    self._ffmpeg_process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._ffmpeg_process.kill()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5.0)
            if self._fifo_path and self._fifo_path.exists():
                self._fifo_path.unlink(missing_ok=True)
            self._is_running = False

    def status(self) -> dict[str, Any]:
        """Return sanitized recorder status."""
        segments_count = 0
        try:
            segments_count = len(self.recorder.segments(self.session_id))
        except Exception:
            pass

        return {
            "status": "running" if self._is_running else "stopped",
            "source": self._current_source,
            "session_id": self.session_id,
            "redacted_rtsp_url": redact_rtsp_url(self.rtsp_url) if self.rtsp_url else None,
            "fallback_path": str(self.fallback_path) if self.fallback_path else None,
            "segments_count": segments_count,
            "error": self._last_error,
        }

    def __enter__(self) -> RtspRingRecorder:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
