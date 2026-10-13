"""Live video stream service with real-time YOLO object detection and graceful fallback."""

from __future__ import annotations

from fractions import Fraction
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterator

import cv2
import numpy as np

from apps.edge.oracle_detector import OracleDetector
from apps.edge.rtsp import load_rtsp_config

logger = logging.getLogger("live_stream")


class LiveStreamService:
    """Isolated live stream engine with detector overlay and fallback."""

    def __init__(
        self,
        rtsp_url: str | None = None,
        fallback_path: str | Path | None = None,
        detector: OracleDetector | None = None,
        manifest_path: str | Path | None = None,
        model_path: str | Path | None = None,
        fps_target: float = 15.0,
        enable_detection: bool = True,
    ) -> None:
        self.fps_target = fps_target
        self.enable_detection = enable_detection

        # 1. Resolve RTSP URL
        if rtsp_url == "":
            self.rtsp_url: str | None = None
        elif rtsp_url is not None:
            self.rtsp_url = rtsp_url
        else:
            try:
                rtsp_cfg = load_rtsp_config()
                self.rtsp_url = rtsp_cfg.stream_url
            except Exception:
                self.rtsp_url = None

        # 2. Resolve fallback video path
        if fallback_path is not None:
            self.fallback_path: Path | None = Path(fallback_path)
        else:
            candidate = Path(".scratch/replay-measurements/h264-10s.mkv")
            self.fallback_path = candidate if candidate.exists() else None

        # 3. Resolve Oracle Detector
        if detector is not None:
            self.detector: OracleDetector | None = detector
        elif enable_detection:
            m_path = (
                Path(manifest_path)
                if manifest_path
                else (
                    Path("data/oracle/yolox_tiny_manifest.json")
                    if Path("data/oracle/yolox_tiny_manifest.json").exists()
                    else Path("models/yolox-tiny/manifest.json")
                )
            )
            if not m_path.exists() and Path("models/yolox-tiny/manifest.json").exists():
                m_path = Path("models/yolox-tiny/manifest.json")

            w_path = Path(model_path) if model_path else Path("data/oracle/yolox_tiny.onnx")
            try:
                self.detector = OracleDetector(m_path, w_path)
            except Exception as exc:
                logger.warning("Could not initialize OracleDetector: %s", exc)
                self.detector = None
        else:
            self.detector = None

        self._rtsp_cap: cv2.VideoCapture | None = None
        self._fallback_cap: cv2.VideoCapture | None = None

        self.current_source: str = "rtsp" if self.rtsp_url else "fallback"
        self.is_running: bool = False
        self.width: int = 1280
        self.height: int = 720
        self.fps: float = 0.0
        self.detections_count: int = 0

        self._frame_counter: int = 0
        self._last_frame_time: float | None = None
        self._lock = threading.Lock()
        self._stopped: bool = False

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
            logger.warning("Failed to open video source %s: %s", source, exc)
            return None

    def read_frame(self) -> tuple[np.ndarray | None, str]:
        with self._lock:
            if self._stopped:
                return None, self.current_source

            # Attempt RTSP source first
            if self.rtsp_url and self.current_source == "rtsp":
                if self._rtsp_cap is None:
                    self._rtsp_cap = self._open_capture(self.rtsp_url)
                if self._rtsp_cap is not None and self._rtsp_cap.isOpened():
                    ret, frame = self._rtsp_cap.read()
                    if ret and frame is not None:
                        return frame, "rtsp"
                    self._rtsp_cap.release()
                    self._rtsp_cap = None
                self.current_source = "fallback"

            # Fallback source
            self.current_source = "fallback"
            if self.fallback_path and self.fallback_path.exists():
                if self._fallback_cap is None:
                    self._fallback_cap = self._open_capture(str(self.fallback_path))
                if self._fallback_cap is not None and self._fallback_cap.isOpened():
                    ret, frame = self._fallback_cap.read()
                    if not ret or frame is None:
                        # Video file hit EOF, loop from start
                        self._fallback_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = self._fallback_cap.read()
                    if ret and frame is not None:
                        return frame, "fallback"

            # Synthetic frame if no video file available
            frame = self._generate_synthetic_frame()
            return frame, "fallback"

    def _generate_synthetic_frame(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (35, 35, 35)
        cv2.putText(
            frame,
            "AI CAMERA OC - FALLBACK VIDEO FEED",
            (50, 100),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (220, 220, 220),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"Frame: {self._frame_counter} | {time.strftime('%Y-%m-%d %H:%M:%S')}",
            (50, 160),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (180, 180, 180),
            1,
            cv2.LINE_AA,
        )
        return frame

    def process_and_annotate(
        self, frame: np.ndarray, source: str
    ) -> tuple[np.ndarray, list[dict[str, Any]]]:
        h, w = frame.shape[:2]
        self.width = w
        self.height = h
        self.current_source = source

        detections: list[dict[str, Any]] = []
        if self.detector is not None:
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self._frame_counter += 1
                frame_meta = {
                    "camera_id": "lab_camera",
                    "stream_session_id": "live_session",
                    "core_epoch": 1,
                    "origin": "replay",
                    "frame_id": self._frame_counter,
                    "pts": self._frame_counter,
                    "time_base": "1/30",
                    "event_time": float(self._frame_counter * Fraction("1/30")),
                }
                res = self.detector.detect(rgb, frame_meta)
                detections = res.get("detections", [])
            except Exception as exc:
                logger.warning("Detection failed on live frame: %s", exc)
                detections = []
        else:
            self._frame_counter += 1

        self.detections_count = len(detections)

        now = time.perf_counter()
        if self._last_frame_time is not None:
            dt = now - self._last_frame_time
            if dt > 0:
                instant_fps = 1.0 / dt
                self.fps = (
                    0.9 * self.fps + 0.1 * instant_fps if self.fps > 0 else instant_fps
                )
        else:
            self.fps = self.fps_target if self.fps_target > 0 else 15.0
        self._last_frame_time = now

        annotated = self.annotate_frame(frame, detections, source, self.fps)
        return annotated, detections

    def annotate_frame(
        self,
        image: np.ndarray,
        detections: list[dict[str, Any]],
        source: str,
        fps: float,
    ) -> np.ndarray:
        annotated = image.copy()
        h, w = annotated.shape[:2]

        # Draw detections
        for det in detections:
            bbox = det.get("bbox_xyxy", [])
            if len(bbox) == 4:
                x1, y1, x2, y2 = [int(round(coord)) for coord in bbox]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                label = str(det.get("label", "object"))
                score = float(det.get("score", 0.0))

                # Draw bounding box rectangle
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)

                # Draw label with confidence percentage
                text = f"{label} {score * 100:.1f}%"
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.5
                thickness = 1
                (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
                tag_y = max(y1, th + 5)
                cv2.rectangle(
                    annotated,
                    (x1, tag_y - th - 4),
                    (x1 + tw + 4, tag_y + baseline - 2),
                    (0, 255, 0),
                    cv2.FILLED,
                )
                cv2.putText(
                    annotated,
                    text,
                    (x1 + 2, tag_y - 2),
                    font,
                    font_scale,
                    (0, 0, 0),
                    thickness,
                    cv2.LINE_AA,
                )

        # Source Badge (top-left)
        src_text = f"SOURCE: {source.upper()}"
        badge_color = (0, 180, 0) if source.lower() == "rtsp" else (0, 140, 255)
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        thickness = 2
        (sw, sh), _ = cv2.getTextSize(src_text, font, font_scale, thickness)
        cv2.rectangle(
            annotated, (10, 10), (10 + sw + 12, 10 + sh + 12), badge_color, cv2.FILLED
        )
        cv2.putText(
            annotated,
            src_text,
            (16, 10 + sh + 4),
            font,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )

        # FPS Badge
        fps_text = f"FPS: {fps:.1f}"
        (fw, fh), _ = cv2.getTextSize(fps_text, font, font_scale, thickness)
        fps_x = 10 + sw + 20
        cv2.rectangle(
            annotated,
            (fps_x, 10),
            (fps_x + fw + 12, 10 + fh + 12),
            (40, 40, 40),
            cv2.FILLED,
        )
        cv2.putText(
            annotated,
            fps_text,
            (fps_x + 6, 10 + fh + 4),
            font,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )

        return annotated

    @staticmethod
    def format_mjpeg_frame(jpeg_bytes: bytes) -> bytes:
        return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"

    def iter_frames(self, max_frames: int | None = None) -> Iterator[bytes]:
        self.is_running = True
        yielded = 0
        try:
            while not self._stopped:
                if max_frames is not None and yielded >= max_frames:
                    break
                frame, source = self.read_frame()
                if frame is None:
                    time.sleep(0.05)
                    continue
                annotated, _ = self.process_and_annotate(frame, source)
                ret, buf = cv2.imencode(
                    ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                )
                if not ret:
                    continue
                jpeg_bytes = buf.tobytes()
                yield self.format_mjpeg_frame(jpeg_bytes)
                yielded += 1
                if source == "fallback" and self.fps_target > 0:
                    time.sleep(1.0 / self.fps_target)
        finally:
            if max_frames is not None:
                pass

    def get_status(self) -> dict[str, Any]:
        return {
            "status": "running" if self.is_running else "idle",
            "source": self.current_source,
            "resolution": [self.width, self.height],
            "fps": round(self.fps, 1),
            "detections_count": self.detections_count,
            "model": "yolox_tiny",
        }

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            self.is_running = False
            if self._rtsp_cap is not None:
                self._rtsp_cap.release()
                self._rtsp_cap = None
            if self._fallback_cap is not None:
                self._fallback_cap.release()
                self._fallback_cap = None
