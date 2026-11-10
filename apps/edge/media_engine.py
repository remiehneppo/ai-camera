"""Tier-1 Media & Evidence Stream Engine Adapter (go2rtc / MediaMTX) for CiviWatch v2.

Provides a zero-plumbing interface to `go2rtc` / `MediaMTX` for:
- Single-pull RTSP stream ingestion with WebRTC / MSE / MP4 / MJPEG fan-out.
- Low-latency keyframe snapshot retrieval (`/api/frame.jpeg`).
- Stream-copy fMP4 / MKV evidence clip extraction without CPU transcoding.
- Graceful local FileRecorder fallback when running standalone without a go2rtc daemon.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
import urllib.parse
import urllib.request

if TYPE_CHECKING:
    from apps.edge.recorder import FileRecorder


@dataclass(frozen=True)
class StreamEndpointInfo:
    """Resolved media endpoints for a camera stream managed by CiviWatch Media Engine."""

    camera_id: str
    rtsp_relay_url: str
    webrtc_url: str
    mjpeg_url: str
    mp4_clip_url: str
    snapshot_url: str
    provider: str = "go2rtc"

    def to_dict(self) -> dict[str, str]:
        return {
            "camera_id": self.camera_id,
            "rtsp_relay_url": self.rtsp_relay_url,
            "webrtc_url": self.webrtc_url,
            "mjpeg_url": self.mjpeg_url,
            "mp4_clip_url": self.mp4_clip_url,
            "snapshot_url": self.snapshot_url,
            "provider": self.provider,
        }


class Go2RtcMediaEngine:
    """Adapter for go2rtc REST & streaming endpoints with local fallback."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        rtsp_port: int = 8554,
        timeout_seconds: float = 2.0,
        http_getter: Callable[[str, float], bytes] | None = None,
        fallback_recorder: "FileRecorder | None" = None,
    ) -> None:
        raw_url = base_url if base_url is not None else os.environ.get("CIVIWATCH_GO2RTC_URL", "http://127.0.0.1:1984")
        self.base_url = raw_url.rstrip("/")
        self.rtsp_port = int(rtsp_port)
        self.timeout_seconds = float(timeout_seconds)
        self._http_getter = http_getter
        self.fallback_recorder = fallback_recorder

    def endpoints_for_camera(self, camera_id: str) -> StreamEndpointInfo:
        """Return canonical WebRTC, MJPEG, RTSP, and MP4 URLs for a camera stream."""
        safe_cam = urllib.parse.quote(str(camera_id), safe="")
        parsed = urllib.parse.urlsplit(self.base_url)
        host = parsed.hostname or "127.0.0.1"
        return StreamEndpointInfo(
            camera_id=camera_id,
            rtsp_relay_url=f"rtsp://{host}:{self.rtsp_port}/{safe_cam}",
            webrtc_url=f"{self.base_url}/api/ws?src={safe_cam}",
            mjpeg_url=f"{self.base_url}/api/stream.mjpeg?src={safe_cam}",
            mp4_clip_url=f"{self.base_url}/api/stream.mp4?src={safe_cam}",
            snapshot_url=f"{self.base_url}/api/frame.jpeg?src={safe_cam}",
        )

    def probe_streams(self) -> dict[str, Any]:
        """Query active streams from go2rtc `/api/streams`; returns status dict without raising."""
        url = f"{self.base_url}/api/streams"
        try:
            raw = self._fetch(url)
            streams = json.loads(raw.decode("utf-8"))
            return {
                "status": "available",
                "provider": "go2rtc",
                "base_url": self.base_url,
                "stream_count": len(streams) if isinstance(streams, dict) else 0,
                "streams": list(streams.keys()) if isinstance(streams, dict) else [],
            }
        except Exception as exc:
            return {
                "status": "standalone_fallback",
                "provider": "ffmpeg_local",
                "base_url": self.base_url,
                "reason": type(exc).__name__,
            }

    def fetch_snapshot_jpeg(self, camera_id: str, output_path: str | Path | None = None) -> bytes:
        """Fetch an instant JPEG keyframe snapshot from go2rtc for the given camera."""
        info = self.endpoints_for_camera(camera_id)
        data = self._fetch(info.snapshot_url)
        if output_path is not None:
            dst = Path(output_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
        return data

    def extract_evidence_clip(
        self,
        camera_id: str,
        *,
        request_id: str,
        session_id: str,
        start_seconds: float,
        end_seconds: float,
        owner: str = "civiwatch-edge",
        output_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Extract an evidence clip via go2rtc MP4 stream or fallback to local FileRecorder pin/finalize."""
        duration = max(1.0, float(end_seconds) - float(start_seconds))
        info = self.endpoints_for_camera(camera_id)
        clip_url = f"{info.mp4_clip_url}&duration={int(round(duration))}"
        try:
            clip_bytes = self._fetch(clip_url)
            if output_path is not None:
                dst = Path(output_path)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(clip_bytes)
            return {
                "status": "complete",
                "provider": "go2rtc",
                "request_id": request_id,
                "session_id": session_id,
                "requested_start": float(start_seconds),
                "requested_end": float(end_seconds),
                "size_bytes": len(clip_bytes),
                "location": str(output_path) if output_path is not None else clip_url,
            }
        except Exception as exc:
            if self.fallback_recorder is not None:
                pin_receipt = self.fallback_recorder.pin(
                    request_id=request_id,
                    session_id=session_id,
                    start=float(start_seconds),
                    end=float(end_seconds),
                    owner=owner,
                )
                return {
                    **pin_receipt,
                    "provider": "file_recorder_fallback",
                }
            return {
                "status": "unavailable",
                "provider": "none",
                "request_id": request_id,
                "session_id": session_id,
                "reason": type(exc).__name__,
            }

    def _fetch(self, url: str) -> bytes:
        if self._http_getter is not None:
            return self._http_getter(url, self.timeout_seconds)
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            return resp.read()
