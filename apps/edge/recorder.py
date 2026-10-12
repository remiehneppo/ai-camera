"""Raw file replay recorder backed by ffmpeg's stream-copy segment muxer."""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import json
import math
import os
import select
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Generator, Iterator, Literal


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


class IncompleteSegment(Exception):
    """A `.part` ffmpeg never finished writing, so it is not ring data."""


class FileRecorder:
    """Record copied, unmodified video packets and expose their raw ring."""

    # ffmpeg's segment muxer opens the next part only after closing the previous one,
    # so every part but the highest-numbered one is closed while the producer runs.
    PART_GLOB = ".segment-*.part.mkv"
    PART_PATTERN = ".segment-%05d.part.mkv"
    # Grace before SIGKILL when a caller abandons ingest mid-stream.
    STOP_GRACE_SECONDS = 0.5

    def __init__(self, root: str | Path, ring_seconds: float = 600,
                 *, probe_timeout_seconds: float = 30) -> None:
        if ring_seconds <= 0:
            raise ValueError("ring_seconds must be positive")
        if not math.isfinite(probe_timeout_seconds) or probe_timeout_seconds <= 0:
            raise ValueError("probe_timeout_seconds must be finite and positive")
        self.probe_timeout_seconds = probe_timeout_seconds
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("ffmpeg and ffprobe are required")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ring_seconds = ring_seconds
        self._watermarks: dict[str, float] = {}
        self._pins = self.root / "pins.sqlite3"
        with sqlite3.connect(self._pins) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE IF NOT EXISTS transfers (request_id TEXT PRIMARY KEY, receipt TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS pins (request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, owner TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL, released INTEGER NOT NULL DEFAULT 0, receipt TEXT NOT NULL)")

    def pin(self, request_id: str, session_id: str, start: float, end: float, owner: str) -> dict:
        """Durably hold the requested ring interval and return an idempotent receipt."""
        self._session_dir(session_id)
        if not request_id or not owner or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (start, end)) or end <= start:
            raise ValueError("request_id and owner are required and end must follow start")
        with sqlite3.connect(self._pins, timeout=30, isolation_level="IMMEDIATE") as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT session_id, owner, start, end, receipt FROM pins WHERE request_id=?", (request_id,)).fetchone()
            if prior:
                if prior[:4] != (session_id, owner, start, end):
                    raise ValueError("pin request ID already has different content")
                return json.loads(prior[4])
            coverage = self.actual_range(session_id, start, end)
            receipt = {"request_id": request_id, "session_id": session_id, "owner": owner,
                       "requested_start": start, "requested_end": end, **coverage,
                       "build_state": "pending",
                       "state": "collecting" if coverage["actual_end"] is None or coverage["actual_end"] < end else "held"}
            db.execute("INSERT INTO pins(request_id,session_id,owner,start,end,receipt) VALUES(?,?,?,?,?,?)",
                       (request_id, session_id, owner, start, end, json.dumps(receipt, separators=(",", ":"))))
            return receipt

    def release_pin(self, request_id: str) -> bool:
        with sqlite3.connect(self._pins, timeout=30, isolation_level="IMMEDIATE") as db:
            changed = db.execute("UPDATE pins SET released=1 WHERE request_id=? AND released=0", (request_id,)).rowcount
        if changed:
            with sqlite3.connect(self._pins) as db:
                row = db.execute("SELECT session_id FROM pins WHERE request_id=?", (request_id,)).fetchone()
            if row:
                self._prune(row[0])
        return bool(changed)

    def pin_status(self, request_id: str) -> dict | None:
        with sqlite3.connect(self._pins) as db:
            row = db.execute("SELECT session_id, owner, start, end, released, receipt FROM pins WHERE request_id=?", (request_id,)).fetchone()
        if not row:
            return None
        session_id, owner, start, end, released, saved_receipt = row
        saved_receipt = json.loads(saved_receipt)
        if saved_receipt.get("manifest"):
            artifact = saved_receipt.get("artifact")
            location = {"availability": "missing", "integrity": "unverified"}
            if artifact and Path(artifact["path"]).is_file():
                location = {"availability": "available", "integrity": "verified"}
                if not self._verify_artifact(artifact):
                    location = {"availability": "quarantined", "integrity": "corrupt"}
            with sqlite3.connect(self._pins) as db:
                transfer = db.execute("SELECT receipt FROM transfers WHERE request_id=?", (request_id,)).fetchone()
            return {**saved_receipt, **location, "state": "released" if released else "held",
                    "transfer_state": "acknowledged" if transfer else "not_started",
                    "transfer_receipt": json.loads(transfer[0]) if transfer else None}
        coverage = self.actual_range(session_id, start, end)
        latest = max((item.end_seconds for item in self.segments(session_id)), default=float("-inf"))
        state = "released" if released else ("collecting" if latest < end else "held")
        return {"request_id": request_id, "session_id": session_id, "owner": owner,
                "requested_start": start, "requested_end": end, **coverage, "state": state}

    def acknowledge_transfer(self, request_id: str, receipt: dict) -> None:
        status = self.pin_status(request_id)
        if not status or not status.get("artifact"):
            raise ValueError("finalized artifact required")
        expected = {"request_id": request_id, "sha256": status["artifact"]["sha256"],
                    "size_bytes": status["artifact"]["size_bytes"]}
        if any(receipt.get(key) != value for key, value in expected.items()) or not isinstance(receipt.get("location"), str) or not receipt["location"]:
            raise ValueError("transfer receipt does not match artifact")
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(self._pins) as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT receipt FROM transfers WHERE request_id=?", (request_id,)).fetchone()
            if prior and prior[0] != encoded:
                raise ValueError("transfer receipt conflict")
            db.execute("INSERT OR IGNORE INTO transfers VALUES(?,?)", (request_id, encoded))

    @staticmethod
    def _verify_artifact(artifact: dict) -> bool:
        path = Path(artifact["path"])
        if not path.is_file() or path.stat().st_size != artifact["size_bytes"]:
            return False
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest() == artifact["sha256"]

    @staticmethod
    def _sync_dir(directory: Path) -> None:
        fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def finalize_pin(self, request_id: str, *, allow_partial: bool = False, request_metadata: dict | None = None) -> dict:
        """Materialize immutable stream-copy evidence; retry reconciles file/DB commits."""
        if request_metadata and request_metadata.keys() - {"evidence_anchor_kind", "evidence_anchor_time", "mapping_uncertainty", "policy_version", "supersedes_request_id"}:
            raise ValueError("invalid request metadata")
        with sqlite3.connect(self._pins, timeout=30, isolation_level="IMMEDIATE") as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT session_id, owner, start, end, released, receipt FROM pins WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise KeyError(request_id)
            session_id, owner, start, end, released, receipt_json = row
            receipt = json.loads(receipt_json)
            if receipt.get("manifest"):
                return receipt
            if released:
                raise ValueError("cannot finalize a released pin")
            directory = self.root / "manifests"
            directory.mkdir(exist_ok=True)
            self._sync_dir(self.root)
            name = hashlib.sha256(request_id.encode()).hexdigest()
            target = directory / (name + ".json")
            # Renamed manifest survives rollback of the SQLite finalize receipt.
            if target.exists():
                manifest = json.loads(target.read_text())
                if (manifest["request_id"], manifest["session_id"], manifest["owner"],
                    manifest["requested_start"], manifest["requested_end"]) != (request_id, session_id, owner, start, end):
                    raise ValueError("orphan manifest identity conflict")
                if manifest.get("artifact") and not self._verify_artifact(manifest["artifact"]):
                    raise ValueError("orphan artifact missing or corrupt")
                receipt = {**manifest, "manifest": str(target)}
                db.execute("UPDATE pins SET receipt=? WHERE request_id=?",
                           (json.dumps(receipt, separators=(",", ":")), request_id))
                return receipt
            coverage = self.actual_range(session_id, start, end)
            latest = max((item.end_seconds for item in self.segments(session_id)), default=float("-inf"))
            if latest < end:
                if not allow_partial:
                    raise ValueError("pin is still collecting post-roll")
                coverage["reason"] = coverage["reason"] or "incomplete_postroll"
            segments = [item for item in self.segments(session_id)
                        if item.end_seconds >= start and item.start_seconds <= end]
            artifact = None
            if segments:
                clip = directory / (name + ".mkv")
                clip_temp = directory / (name + ".tmp.mkv")
                playlist = directory / (name + ".concat")
                playlist.write_text("".join("file '" + str(Path(item.path).resolve()).replace("'", "'\\''") + "'\nduration " + str(item.end_seconds - item.start_seconds + item.frame_interval_seconds) + "\n" for item in segments))
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                    "-safe", "0", "-i", str(playlist), "-map", "0:v:0", "-c:v", "copy", str(clip_temp),
                ], check=True, capture_output=True, timeout=20)
                with clip_temp.open("rb") as source:
                    os.fsync(source.fileno())
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                artifact = {"path": str(clip), "size_bytes": clip_temp.stat().st_size,
                            "sha256": digest, "content_type": "video/x-matroska", "codec": segments[0].codec}
                os.replace(clip_temp, clip)
                self._sync_dir(directory)
                playlist.unlink(missing_ok=True)
            artifacts = []
            for item in segments:
                path = Path(item.path)
                with path.open("rb") as source:
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                artifacts.append({"path": str(path), "size_bytes": path.stat().st_size, "sha256": digest})
            if not artifact:
                coverage["completeness"] = "unknown"
            manifest = {
                "request_id": request_id, "session_id": session_id, "owner": owner,
                "requested_start": start, "requested_end": end, **coverage,
                "build_state": "finalized" if artifact else "failed", "state": "held", "segments": artifacts,
                "artifact": artifact, "transfer_state": "not_started",
                **(request_metadata or {}),
            }
            temp = target.with_suffix(".json.tmp")
            with temp.open("w") as output:
                json.dump(manifest, output, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, target)
            dir_fd = os.open(directory, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            receipt = {**manifest, "manifest": str(target)}
            db.execute("UPDATE pins SET receipt=? WHERE request_id=?",
                       (json.dumps(receipt, separators=(",", ":")), request_id))
            return receipt

    def _session_dir(self, session_id: str) -> Path:
        if not session_id or session_id in {".", ".."} or Path(session_id).name != session_id:
            raise ValueError("session_id must be a non-empty path-safe name")
        return self.root / session_id

    @staticmethod
    def _local_source(source: str | Path) -> Path:
        """Accept only an existing local path; reject a remote URL without echoing it.

        A URL is refused before any subprocess is built, so the credential it may embed
        reaches neither ffmpeg's argv nor an exception raised by this module.
        """
        location = os.fspath(source)
        if "://" in location:
            raise ValueError("recorder source must be a local file or FIFO, not a remote URL")
        path = Path(location)
        if not path.exists():
            raise FileNotFoundError(location)
        return path

    def record_file(self, source: str | Path, session_id: str, segment_seconds: float = 2) -> list[Segment]:
        if segment_seconds <= 0:
            raise ValueError("segment_seconds must be positive")
        source = self._local_source(source)
        if not source.is_file():
            raise FileNotFoundError(source)
        with self.ingest(source, session_id, segment_seconds):
            pass
        return self.segments(session_id)

    @contextlib.contextmanager
    def ingest(self, source: str | Path, session_id: str, segment_seconds: float = 2,
               *, poll_seconds: float = 0.05) -> Iterator[FileRecorder]:
        """Segment `source`, publishing each closed segment while ingest continues.

        Unlike file replay, `source` may be a named pipe, so a supervisor can query
        `segments()`/`actual_range()` and pin coverage before the producer reaches EOF.
        Only an existing local path is accepted: a remote URL may embed credentials and is
        rejected before any subprocess starts. The in-flight part is published only once
        ffmpeg closes it; a producer that dies without a trailer leaves its part unpublished
        and the caller sees `CalledProcessError`.
        """
        if segment_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("segment_seconds and poll_seconds must be positive")
        source = self._local_source(source)
        directory = self._session_dir(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        # A death between a segment's media rename and its sidecar commit leaves a whole file
        # that `segments()` cannot see and that a new ingest would refuse over forever. Adopt or
        # drop those files first, so the existence check below only refuses a real ring.
        self.reconcile(session_id)
        if any(directory.glob("segment-*.mkv")):
            raise FileExistsError(f"recorder session already exists: {session_id}")
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-copyts", "-i", str(source),
            "-map", "0:v:0", "-an", "-c:v", "copy", "-f", "segment",
            "-segment_time", str(segment_seconds), "-reset_timestamps", "0", str(directory / self.PART_PATTERN),
        ]
        failures: list[BaseException] = []
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors)
            publisher = threading.Thread(target=self._publish_closed,
                                         args=(directory, session_id, process, poll_seconds, failures),
                                         name=f"recorder-publisher-{session_id}", daemon=True)
            publisher.start()
            try:
                yield self
            except BaseException:
                self._stop(process)
                raise
            finally:
                returncode = self._reap(process, publisher, poll_seconds)
                # Allow each remaining part its own probe budget, not a whole-ingest deadline.
                remaining = len(list(directory.glob(self.PART_GLOB)))
                publisher.join((remaining + 1) * self.probe_timeout_seconds
                               + 2 * self.STOP_GRACE_SECONDS + poll_seconds)
                if publisher.is_alive():
                    raise TimeoutError("recorder publisher did not stop after producer exit")
                if failures:
                    # The publisher died before it could classify what was left, so re-run the
                    # same probe gate here: a part that is still provably complete is published,
                    # and one that cannot be published with the publisher down is kept for the
                    # next reconcile -- the session is reported as failed either way, when
                    # `ingest` re-raises `failures`.
                    self._publish_parts(directory, session_id)
                self._prune(session_id)
            if failures:
                raise failures[0]
            if returncode:
                errors.seek(0)
                raise subprocess.CalledProcessError(returncode, command,
                                                    stderr=errors.read().decode(errors="replace"))

    def _reap(self, process: subprocess.Popen, publisher: threading.Thread, poll_seconds: float) -> int:
        """Reap the producer, aborting it once nothing publishes for it any more.

        Without this, a publisher that has already stopped would leave the caller blocked in
        `process.wait()` for as long as the producer keeps writing to a ring nobody reads.
        """
        while True:
            try:
                return process.wait(timeout=poll_seconds)
            except subprocess.TimeoutExpired:
                if publisher.is_alive():
                    continue
                self._stop(process)

    def _stop(self, process: subprocess.Popen) -> None:
        """Bounded abort; ffmpeg blocked on a non-seekable input can ignore SIGTERM."""
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=self.STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=self.STOP_GRACE_SECONDS)

    def _publish_closed(self, directory: Path, session_id: str, process: subprocess.Popen,
                        poll_seconds: float, failures: list[BaseException]) -> None:
        """Publish every part ffmpeg has finished; `ingest` re-raises what breaks here.

        While the producer runs, every part but the newest one is closed by construction and
        becomes a candidate. The newest part becomes a candidate once the producer has exited,
        whatever its exit status: a kill can land just after a segment close, so the status
        cannot decide that part's fate -- it is probed like any other candidate, and only a
        part that probes as a whole segment is published.
        """
        probed: set[Path] = set()
        try:
            while True:
                returncode = process.poll()
                parts = sorted(directory.glob(self.PART_GLOB))
                if returncode is None and parts:
                    # The newest part may still be open: renaming it would move a file the
                    # producer keeps writing into.
                    parts = parts[:-1]
                # Bounded: a part is probed at most once, so a leftover cannot spin the loop.
                for part in [candidate for candidate in parts if candidate not in probed]:
                    probed.add(part)
                    self._publish_part(part, session_id)
                if returncode is not None:
                    return
                time.sleep(poll_seconds)
        except BaseException as exc:
            failures.append(exc)
            # Publishing can no longer progress, so the producer must stop with it rather
            # than keep writing to a ring that nothing will ever publish.
            self._stop(process)

    def _publish_part(self, part: Path, session_id: str) -> None:
        """Publish `part` when it is a whole segment, drop it when it is not.

        Completeness is decided by the probe alone -- never by the producer's exit status,
        which says nothing about a segment ffmpeg closed just before dying. A part that fails
        the probe is unfinished by definition, so it is discarded here and can never become
        ring data.

        The media file is renamed before its sidecar is written, and not the other way round:
        two files cannot be replaced atomically together, so visibility is gated by the sidecar
        instead -- `segments()` lists committed `.json` metadata only, which `_write_metadata`
        installs atomically (temp file + fsync + `os.replace`). Between the rename and that
        commit the finalized media exists but stays invisible, so a segment is never exposed
        while its metadata is missing or half-written.
        """
        if not part.is_file():
            return
        final = part.with_name(part.name.removeprefix(".").removesuffix(".part.mkv") + ".mkv")
        if final.exists():
            return
        try:
            segment = self._probe_segment(part, session_id)
        except IncompleteSegment:
            # Rejected by the probe, so it is an unfinished part: drop it rather than rename it.
            part.unlink(missing_ok=True)
            return
        with part.open("rb") as raw:
            os.fsync(raw.fileno())
        os.replace(part, final)
        self._write_metadata(replace(segment, path=str(final)))

    def _publish_parts(self, directory: Path, session_id: str) -> list[BaseException]:
        """Run the publish gate over every leftover `.part` and return what it could not classify.

        `_publish_part` is the only authority on a part: one that probes as a whole segment is
        published, one the probe rejects as unfinished is dropped. Any other error is not a
        verdict on the file, so the part is left in place and handed back to the caller, which
        must surface it rather than delete possibly-whole evidence over a transient IO error.
        """
        undecided: list[BaseException] = []
        for part in sorted(directory.glob(self.PART_GLOB)):
            try:
                self._publish_part(part, session_id)
            except IncompleteSegment:
                # `_publish_part` drops a rejected part itself; this covers a substituted
                # publisher that raises before its own removal.
                part.unlink(missing_ok=True)
            except Exception as exc:
                undecided.append(exc)
        return undecided

    def reconcile(self, session_id: str) -> list[Segment]:
        """Repair what a death between a segment's media rename and its sidecar commit left behind.

        `_publish_part` renames a finished segment into place and commits its sidecar after, so a
        crash in between leaves a whole `segment-*.mkv` that `segments()` hides and that a later
        `ingest` refuses to record over. Every media file without a sidecar is probed here: a whole
        segment gets its sidecar rebuilt (a committed sidecar is never rewritten) and one the probe
        proves unfinished is removed, while a probe that fails for any other reason leaves the file
        alone and is raised to the caller. Leftover `.part` files go through the same gate.
        Returns the visible ring after the repair, so running it again is a no-op.
        """
        directory = self._session_dir(session_id)
        if not directory.is_dir():
            return []
        for media in sorted(directory.glob("segment-*.mkv")):
            if media.with_suffix(".json").exists():
                continue
            try:
                self._write_metadata(self._probe_segment(media, session_id))
            except IncompleteSegment:
                media.unlink(missing_ok=True)
        undecided = self._publish_parts(directory, session_id)
        if undecided:
            raise undecided[0]
        return self.segments(session_id)

    def segments(self, session_id: str) -> list[Segment]:
        """Published ring segments, listed from committed sidecars.

        A segment is visible only once its `.json` metadata exists, so the pair of files that
        makes up a segment is committed by the sidecar write rather than by the media rename.
        """
        directory = self._session_dir(session_id)
        result = []
        for meta in sorted(directory.glob("*.json")) if directory.exists() else ():
            try:
                data = json.loads(meta.read_text())
            except FileNotFoundError:  # pruned between listing and reading
                continue
            data["keyframe_pts"] = tuple(data["keyframe_pts"])
            if Path(data["path"]).is_file():
                result.append(Segment(**data))
        return result

    def actual_range(self, session_id: str, requested_start: float, requested_end: float) -> dict:
        if requested_end <= requested_start:
            raise ValueError("requested_end must be after requested_start")
        segments = [item for item in self.segments(session_id)
                    if item.end_seconds >= requested_start and item.start_seconds <= requested_end]
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
        """Deliver a fixed PTS sampling plan one frame at a time; synchronous calls provide backpressure."""
        if sample_fps <= 0 or mode not in {"fast", "realtime"}:
            raise ValueError("sample_fps must be positive and mode must be fast or realtime")
        frames = self._iter_frames(Path(source))
        try:
            first = next(frames, None)
            if first is None:
                return 0
            time_base = first["time_base"]
            first_time = first["pts"] * first["time_base_num"] / first["time_base_den"]
            next_sample = first_time
            interval = 1 / sample_fps
            wall_start = time.monotonic()
            delivered = 0
            for frame in itertools.chain((first,), frames):
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
        finally:
            frames.close()

    def _probe(self, path: Path, session_id: str) -> dict:
        """Read metadata from a segment ffmpeg has finished writing.

        ffprobe reads an unterminated part up to its last complete cluster and then reports
        `File ended prematurely` on stderr, while a part ffmpeg closed cleanly probes without any
        error output -- and `-v error` prints nothing but errors. That trailer is the only
        reliable completeness signal: a producer killed mid-segment leaves a readable part whose
        timestamp range looks plausible, so its metadata cannot tell it apart from a closed one.
        Known premature-EOF, malformed EBML-header and invalid-input diagnostics prove
        incomplete or corrupt media. Unknown diagnostics, IO failures and killed probes
        are not a verdict on the media.
        """
        command = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
                   "-show_frames", "-of", "json", str(path)]
        probe = subprocess.run(command, capture_output=True, text=True,
                               timeout=self.probe_timeout_seconds)
        if probe.returncode or probe.stderr.strip():
            diagnostics = probe.stderr.strip().splitlines()
            if probe.returncode >= 0 and diagnostics and all(
                line.endswith(("File ended prematurely", "EBML header parsing failed",
                               "Invalid data found when processing input")) for line in diagnostics
            ):
                raise IncompleteSegment(f"segment is not closed: {path.name}")
            raise subprocess.CalledProcessError(probe.returncode, command,
                                                output=probe.stdout, stderr=probe.stderr)
        result = json.loads(probe.stdout)
        stream = result["streams"][0]
        frames = result.get("frames", [])
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

    def _probe_segment(self, media: Path, session_id: str) -> Segment:
        """Describe whole `media` as the segment it already is, stored at that path."""
        metadata = self._probe(media, session_id)
        return Segment(path=str(media), **{k: v for k, v in metadata.items() if k != "path"})

    def _iter_frames(self, source: Path) -> Generator[dict, None, None]:
        """Stream one frame's PTS metadata at a time, so replay holds a constant-size window."""
        time_base = self._stream_time_base(source)
        numerator, denominator = map(int, time_base.split("/"))
        command = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "frame=pts,best_effort_timestamp", "-of", "csv=p=0", str(source)]
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            stdout = process.stdout
            if stdout is None:
                self._stop(process)
                raise RuntimeError("ffprobe stdout pipe unavailable")
            try:
                pending = b""
                while True:
                    if not select.select([stdout], [], [], self.probe_timeout_seconds)[0]:
                        raise subprocess.TimeoutExpired(command, self.probe_timeout_seconds)
                    chunk = os.read(stdout.fileno(), 4096)
                    if not chunk:
                        break
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        pts = self._frame_timestamp(line.decode())
                        if pts is not None:
                            yield {"pts": pts, "time_base": time_base,
                                   "time_base_num": numerator, "time_base_den": denominator}
                    if len(pending) > 4096:
                        raise ValueError("ffprobe frame timestamp line is too long")
                if pending:
                    pts = self._frame_timestamp(pending.decode())
                    if pts is not None:
                        yield {"pts": pts, "time_base": time_base,
                               "time_base_num": numerator, "time_base_den": denominator}
                returncode = process.wait(timeout=self.probe_timeout_seconds)
            finally:
                self._stop(process)
                stdout.close()
            if returncode:
                errors.seek(0)
                raise subprocess.CalledProcessError(returncode, command,
                                                    stderr=errors.read().decode(errors="replace"))

    def _stream_time_base(self, source: Path) -> str:
        probe = json.loads(subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=time_base",
            "-of", "json", str(source),
        ], check=True, capture_output=True, text=True, timeout=self.probe_timeout_seconds).stdout)
        return probe["streams"][0]["time_base"]

    @staticmethod
    def _frame_timestamp(line: str) -> int | None:
        """Prefer `best_effort_timestamp` over `pts`; skip fields ffprobe reports as unset."""
        fields = line.strip().split(",")
        for candidate in (fields[1] if len(fields) > 1 else "", fields[0]):
            if candidate and candidate != "N/A":
                return int(candidate)
        return None

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
        # Hold SQLite's write lock while deleting, so a concurrent pin cannot ACK
        # ownership after cleanup has decided the same segment is unowned.
        with sqlite3.connect(self._pins, timeout=30, isolation_level="IMMEDIATE") as db:
            db.execute("BEGIN IMMEDIATE")
            pins = db.execute("SELECT start, end FROM pins WHERE session_id=? AND released=0", (session_id,)).fetchall()
            for item in segments:
                pinned = any(item.start_seconds <= end and item.end_seconds >= start for start, end in pins)
                if item.end_seconds < cutoff and item.end_seconds < watermark and not pinned:
                    Path(item.path).unlink(missing_ok=True)
                    Path(item.path).with_suffix(".json").unlink(missing_ok=True)
