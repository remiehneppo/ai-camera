"""Raw file replay recorder backed by ffmpeg's stream-copy segment muxer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator, Literal


@dataclass(frozen=True)
class Segment:
    path: str
    session_id: str
    codec: str
    time_base: str
    start_pts: int
    end_pts: int
    start_seconds: float
    end_seconds: float
    keyframe_pts: tuple[int, ...]
    frame_interval_seconds: float


@dataclass(frozen=True)
class ReplayFrame:
    session_id: str
    pts: int
    time_base: str
    event_time: float


class FileRecorder:
    """Record copied, unmodified video packets and expose their raw ring."""

    def __init__(self, root: str | Path, ring_seconds: float = 600) -> None:
        if ring_seconds <= 0:
            raise ValueError("ring_seconds must be positive")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("ffmpeg and ffprobe are required")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ring_seconds = ring_seconds
        self._watermarks: dict[str, float] = {}

    def _session_dir(self, session_id: str) -> Path:
        if not session_id or session_id in {".", ".."} or Path(session_id).name != session_id:
            raise ValueError("session_id must be a non-empty path-safe name")
        return self.root / session_id

    def record_file(self, source: str | Path, session_id: str, segment_seconds: float = 2) -> list[Segment]:
        if segment_seconds <= 0:
            raise ValueError("segment_seconds must be positive")
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(source)
        directory = self._session_dir(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.glob("segment-*.mkv")):
            raise FileExistsError(f"recorder session already exists: {session_id}")
        pattern = directory / ".segment-%05d.part.mkv"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-copyts", "-i", str(source),
            "-map", "0:v:0", "-an", "-c:v", "copy", "-f", "segment",
            "-segment_time", str(segment_seconds), "-reset_timestamps", "0", str(pattern),
        ], check=True, capture_output=True)
        segments: list[Segment] = []
        for part in sorted(directory.glob(".segment-*.part.mkv")):
            metadata = self._probe(part, session_id)
            final = part.with_name(part.name.removeprefix(".").removesuffix(".part.mkv") + ".mkv")
            with part.open("rb") as raw:
                os.fsync(raw.fileno())
            os.replace(part, final)
            segment = Segment(path=str(final), **{k: v for k, v in metadata.items() if k != "path"})
            self._write_metadata(segment)
            segments.append(segment)
        self._prune(session_id)
        return self.segments(session_id)

    def segments(self, session_id: str) -> list[Segment]:
        directory = self._session_dir(session_id)
        result = []
        for meta in sorted(directory.glob("*.json")) if directory.exists() else ():
            data = json.loads(meta.read_text())
            data["keyframe_pts"] = tuple(data["keyframe_pts"])
            if Path(data["path"]).is_file():
                result.append(Segment(**data))
        return result

    def actual_range(self, session_id: str, requested_start: float, requested_end: float) -> dict:
        if requested_end <= requested_start:
            raise ValueError("requested_end must be after requested_start")
        segments = self.segments(session_id)
        if not segments:
            return {
                "actual_start": None, "actual_end": None, "actual_ranges": [], "gaps": [],
                "completeness": "missing", "reason": "no_segments",
            }
        actual_start = segments[0].start_seconds
        actual_end = segments[-1].end_seconds
        tolerance = 1.5 * sorted(item.frame_interval_seconds for item in segments)[len(segments) // 2]
        gaps = [
            (left.end_seconds, right.start_seconds)
            for left, right in zip(segments, segments[1:])
            if right.start_seconds - left.end_seconds > tolerance
        ]
        reason = "missing_preroll" if actual_start > requested_start else (
            "missing_postroll" if actual_end < requested_end else None
        )
        if reason is None and any(start < requested_end and end > requested_start for start, end in gaps):
            reason = "continuity_gap"
        return {
            "actual_start": actual_start, "actual_end": actual_end,
            "actual_ranges": [[item.start_seconds, item.end_seconds] for item in segments],
            "gaps": [[start, end] for start, end in gaps],
            "completeness": "partial" if reason else "complete", "reason": reason,
        }

    def advance_watermark(self, session_id: str, event_time: float) -> None:
        self._session_dir(session_id)
        previous = self._watermarks.get(session_id, float("-inf"))
        if event_time < previous:
            raise ValueError("recorder-consumer watermark cannot move backwards")
        self._watermarks[session_id] = event_time
        self._prune(session_id)

    def replay(
        self,
        source: str | Path,
        session_id: str,
        consumer: Callable[[ReplayFrame], None],
        *,
        sample_fps: float,
        mode: Literal["fast", "realtime"] = "fast",
    ) -> int:
        """Deliver a fixed PTS sampling plan; synchronous calls provide backpressure."""
        if sample_fps <= 0 or mode not in {"fast", "realtime"}:
            raise ValueError("sample_fps must be positive and mode must be fast or realtime")
        frames = self._frames(Path(source))
        if not frames:
            return 0
        time_base = frames[0]["time_base"]
        selected: Iterator[dict] = iter(frames)
        first_pts = frames[0]["pts"]
        first_time = first_pts * frames[0]["time_base_num"] / frames[0]["time_base_den"]
        next_sample = first_time
        interval = 1 / sample_fps
        wall_start = time.monotonic()
        delivered = 0
        for frame in selected:
            event_time = frame["pts"] * frame["time_base_num"] / frame["time_base_den"]
            if event_time + 1e-9 < next_sample:
                continue
            item = ReplayFrame(session_id, frame["pts"], time_base, event_time)
            if mode == "realtime":
                time.sleep(max(0, wall_start + event_time - first_time - time.monotonic()))
            consumer(item)
            delivered += 1
            next_sample = event_time + interval
            self.advance_watermark(session_id, event_time)
        return delivered

    def _probe(self, path: Path, session_id: str) -> dict:
        probe = json.loads(subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_frames", "-of", "json", str(path),
        ], check=True, capture_output=True, text=True).stdout)
        stream = probe["streams"][0]
        frames = probe.get("frames", [])
        if not frames or "pts" not in frames[0]:
            raise ValueError(f"segment has no timestamped video frames: {path.name}")
        pts = [int(frame["pts"]) for frame in frames if "pts" in frame]
        numerator, denominator = map(int, stream["time_base"].split("/"))
        unique_pts = sorted(set(pts))
        intervals = [right - left for left, right in zip(unique_pts, unique_pts[1:]) if right > left]
        frame_interval = (sorted(intervals)[len(intervals) // 2] * numerator / denominator) if intervals else 0
        return {
            "path": str(path), "session_id": session_id, "codec": stream["codec_name"],
            "time_base": stream["time_base"], "start_pts": min(pts), "end_pts": max(pts),
            "start_seconds": min(pts) * numerator / denominator,
            "end_seconds": max(pts) * numerator / denominator,
            "keyframe_pts": tuple(int(frame["pts"]) for frame in frames if frame.get("key_frame") and "pts" in frame),
            "frame_interval_seconds": frame_interval,
        }

    def _frames(self, source: Path) -> list[dict]:
        probe = json.loads(subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_frames",
            "-show_entries", "stream=time_base:frame=pts,best_effort_timestamp", "-of", "json", str(source),
        ], check=True, capture_output=True, text=True).stdout)
        stream = probe["streams"][0]
        numerator, denominator = map(int, stream["time_base"].split("/"))
        return [{"pts": int(f["best_effort_timestamp"] if "best_effort_timestamp" in f else f["pts"]), "time_base": stream["time_base"],
                 "time_base_num": numerator, "time_base_den": denominator} for f in probe.get("frames", [])
                if f.get("pts") is not None or f.get("best_effort_timestamp") is not None]

    def _write_metadata(self, segment: Segment) -> None:
        target = Path(segment.path).with_suffix(".json")
        temp = target.with_suffix(".json.tmp")
        with temp.open("w") as output:
            json.dump(asdict(segment), output, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, target)
        dir_fd = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _prune(self, session_id: str) -> None:
        segments = self.segments(session_id)
        if not segments:
            return
        cutoff = max(item.end_seconds for item in segments) - self.ring_seconds
        watermark = self._watermarks.get(session_id, float("inf"))
        for item in segments:
            if item.end_seconds < cutoff and item.end_seconds < watermark:
                Path(item.path).unlink(missing_ok=True)
                Path(item.path).with_suffix(".json").unlink(missing_ok=True)
