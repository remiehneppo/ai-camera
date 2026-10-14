"""Storage quota accounting, state reserve protection, and emergency cleanup."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StorageBreakdown:
    ring_bytes: int
    pinned_bytes: int
    temp_bytes: int
    wal_bytes: int
    free_bytes: int
    total_bytes: int
    used_percent: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "ring_bytes": self.ring_bytes,
            "pinned_bytes": self.pinned_bytes,
            "temp_bytes": self.temp_bytes,
            "wal_bytes": self.wal_bytes,
            "free_bytes": self.free_bytes,
            "total_bytes": self.total_bytes,
            "used_percent": self.used_percent,
        }


class StorageQuotaManager:
    """Manages storage quotas, accounts for file types, and enforces reserve protection."""

    DEFAULT_MIN_STATE_RESERVE_BYTES: int = 50 * 1024 * 1024  # 50 MB
    DEFAULT_WARNING_PERCENT: float = 90.0
    DEFAULT_CRITICAL_PERCENT: float = 95.0

    def __init__(
        self,
        *,
        storage_path: str | Path | None = None,
        recorder: Any | None = None,
        outbox: Any | None = None,
        min_state_reserve_bytes: int = DEFAULT_MIN_STATE_RESERVE_BYTES,
        warning_percent: float = DEFAULT_WARNING_PERCENT,
        critical_percent: float = DEFAULT_CRITICAL_PERCENT,
        disk_usage_fn: Callable[[Path], Any] | None = None,
    ) -> None:
        self.recorder = recorder
        self.outbox = outbox
        self.min_state_reserve_bytes = int(min_state_reserve_bytes)
        self.warning_percent = float(warning_percent)
        self.critical_percent = float(critical_percent)
        self.disk_usage_fn = disk_usage_fn or shutil.disk_usage

        if storage_path is not None:
            self.storage_path = Path(storage_path).resolve()
        elif recorder is not None and hasattr(recorder, "root"):
            self.storage_path = Path(recorder.root).resolve()
        elif outbox is not None and hasattr(outbox, "path"):
            self.storage_path = Path(outbox.path).resolve().parent
        else:
            self.storage_path = Path(".").resolve()

    def _get_active_pins(self) -> dict[str, list[tuple[float, float]]]:
        """Return active (unreleased) pin ranges grouped by session_id."""
        pins_db = None
        if self.recorder is not None and hasattr(self.recorder, "_pins"):
            pins_db = Path(self.recorder._pins)
        elif (self.storage_path / "pins.sqlite3").is_file():
            pins_db = self.storage_path / "pins.sqlite3"

        if not pins_db or not pins_db.is_file():
            return {}

        active_pins: dict[str, list[tuple[float, float]]] = {}
        try:
            with sqlite3.connect(pins_db, timeout=5) as db:
                rows = db.execute(
                    "SELECT session_id, start, end FROM pins WHERE released=0"
                ).fetchall()
                for session_id, start, end in rows:
                    active_pins.setdefault(session_id, []).append((float(start), float(end)))
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Failed to query active pins: %s", exc)
        return active_pins

    def get_storage_breakdown(self) -> StorageBreakdown:
        """Accurately accounts for ring, pinned, temp, wal, and disk space."""
        ring_bytes = 0
        pinned_bytes = 0
        temp_bytes = 0
        wal_bytes = 0

        active_pins = self._get_active_pins()
        seen_wal_files: set[Path] = set()

        # 1. Inspect WAL and SQLite DB files
        wal_candidates: list[Path] = []
        if self.recorder is not None and hasattr(self.recorder, "root"):
            root = Path(self.recorder.root)
            wal_candidates.extend(root.glob("*.sqlite3*"))
            wal_candidates.extend(root.glob("*.db*"))
        if self.outbox is not None and hasattr(self.outbox, "path"):
            outbox_p = Path(self.outbox.path)
            parent = outbox_p.parent
            wal_candidates.extend(parent.glob(f"{outbox_p.name}*"))
            wal_candidates.extend(parent.glob("*.db*"))
            wal_candidates.extend(parent.glob("*.sqlite3*"))
        if self.storage_path.is_dir():
            wal_candidates.extend(self.storage_path.glob("*.sqlite3*"))
            wal_candidates.extend(self.storage_path.glob("*.db*"))

        for f in wal_candidates:
            if f.is_file() and f not in seen_wal_files:
                seen_wal_files.add(f)
                try:
                    wal_bytes += f.stat().st_size
                except OSError:
                    pass

        # 2. Inspect Recorder root (sessions and manifests)
        recorder_root = None
        if self.recorder is not None and hasattr(self.recorder, "root"):
            recorder_root = Path(self.recorder.root)
        elif (self.storage_path / "manifests").is_dir():
            recorder_root = self.storage_path

        if recorder_root and recorder_root.is_dir():
            # A. Manifests directory
            manifests_dir = recorder_root / "manifests"
            if manifests_dir.is_dir():
                for entry in manifests_dir.iterdir():
                    if not entry.is_file():
                        continue
                    try:
                        sz = entry.stat().st_size
                    except OSError:
                        continue
                    name = entry.name
                    if name.endswith((".tmp.mkv", ".json.tmp", ".concat", ".tmp")):
                        temp_bytes += sz
                    elif name.endswith(".mkv") or name.endswith(".json"):
                        pinned_bytes += sz

            # B. Session directories
            for sdir in recorder_root.iterdir():
                if not sdir.is_dir() or sdir.name == "manifests" or sdir.name.startswith("."):
                    continue
                session_id = sdir.name
                session_pins = active_pins.get(session_id, [])

                # Map segment name -> is_pinned
                segment_pinned_cache: dict[str, bool] = {}

                for entry in sdir.iterdir():
                    if not entry.is_file():
                        continue
                    try:
                        sz = entry.stat().st_size
                    except OSError:
                        continue
                    name = entry.name
                    # Check temp patterns
                    if (
                        name.startswith(".segment-")
                        or ".part" in name
                        or name.endswith((".tmp", ".tmp.mkv", ".json.tmp", ".concat"))
                    ):
                        temp_bytes += sz
                        continue

                    # Segment JSON sidecar or MKV media
                    if name.endswith(".json"):
                        stem = entry.stem
                        is_pinned = False
                        try:
                            meta = json.loads(entry.read_text())
                            s_start = float(meta.get("start_seconds", 0.0))
                            s_end = float(meta.get("end_seconds", 0.0))
                            is_pinned = any(
                                s_start <= pin_end and s_end >= pin_start
                                for pin_start, pin_end in session_pins
                            )
                        except Exception:
                            is_pinned = False
                        segment_pinned_cache[stem] = is_pinned
                        if is_pinned:
                            pinned_bytes += sz
                        else:
                            ring_bytes += sz
                    elif name.endswith(".mkv"):
                        stem = entry.stem
                        if stem not in segment_pinned_cache:
                            # Try to read companion json
                            json_p = sdir / f"{stem}.json"
                            is_pinned = False
                            if json_p.is_file():
                                try:
                                    meta = json.loads(json_p.read_text())
                                    s_start = float(meta.get("start_seconds", 0.0))
                                    s_end = float(meta.get("end_seconds", 0.0))
                                    is_pinned = any(
                                        s_start <= pin_end and s_end >= pin_start
                                        for pin_start, pin_end in session_pins
                                    )
                                except Exception:
                                    is_pinned = False
                            segment_pinned_cache[stem] = is_pinned
                        else:
                            is_pinned = segment_pinned_cache[stem]

                        if is_pinned:
                            pinned_bytes += sz
                        else:
                            ring_bytes += sz

        # 3. Disk usage metrics
        try:
            usage = self.disk_usage_fn(self.storage_path)
            if hasattr(usage, "total") and hasattr(usage, "free"):
                total_bytes = usage.total
                free_bytes = usage.free
                used_bytes = getattr(usage, "used", total_bytes - free_bytes)
            else:
                total_bytes, used_bytes, free_bytes = usage[:3]
        except Exception as exc:
            logger.warning("Failed to inspect disk usage: %s", exc)
            total_bytes = 0
            free_bytes = 0
            used_bytes = 0

        used_percent = (
            round((used_bytes / total_bytes * 100.0), 2) if total_bytes > 0 else 0.0
        )

        return StorageBreakdown(
            ring_bytes=ring_bytes,
            pinned_bytes=pinned_bytes,
            temp_bytes=temp_bytes,
            wal_bytes=wal_bytes,
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            used_percent=used_percent,
        )

    def is_storage_pressured(self) -> bool:
        """True if disk usage exceeds warning threshold or free space <= state reserve."""
        breakdown = self.get_storage_breakdown()
        return (
            breakdown.used_percent >= self.warning_percent
            or breakdown.free_bytes <= self.min_state_reserve_bytes
        )

    def is_storage_exhausted(self) -> bool:
        """True if disk reaches critical threshold or free space <= state reserve."""
        breakdown = self.get_storage_breakdown()
        return (
            breakdown.used_percent >= self.critical_percent
            or breakdown.free_bytes <= self.min_state_reserve_bytes
        )

    def can_accept_new_evidence(self, estimated_bytes: int = 0) -> bool:
        """Returns False if new evidence would breach critical threshold or state reserve."""
        breakdown = self.get_storage_breakdown()
        if breakdown.free_bytes <= 0 or breakdown.total_bytes <= 0:
            return False
        if (breakdown.free_bytes - estimated_bytes) <= self.min_state_reserve_bytes:
            return False
        projected_used_bytes = (breakdown.total_bytes - breakdown.free_bytes) + estimated_bytes
        if (projected_used_bytes / breakdown.total_bytes * 100.0) >= self.critical_percent:
            return False
        return True

    def cleanup_eligible(self, *, force: bool = False) -> dict[str, Any]:
        """Cleans up orphan temporary files and unpinned ring segments under storage pressure.

        STRICT UNACK PRESERVATION:
        - Pinned segments and unACK finalized clips are NEVER deleted.
        - Outage > 24h does NOT act as a TTL to delete unACK evidence.
        """
        if not force and not self.is_storage_pressured():
            return {"cleaned_bytes": 0, "cleaned_files": []}

        cleaned_files: list[str] = []
        cleaned_bytes: int = 0

        # Step 1: Cleanup temporary scratch files
        if self.recorder is not None and hasattr(self.recorder, "cleanup_evidence_temps"):
            try:
                rec_cleaned = self.recorder.cleanup_evidence_temps()
                cleaned_files.extend(rec_cleaned)
            except Exception as exc:
                logger.warning("Recorder cleanup_evidence_temps error: %s", exc)

        recorder_root = None
        if self.recorder is not None and hasattr(self.recorder, "root"):
            recorder_root = Path(self.recorder.root)
        elif (self.storage_path / "manifests").is_dir():
            recorder_root = self.storage_path

        if recorder_root and recorder_root.is_dir():
            # Clean orphan temp files in manifests/
            manifests_dir = recorder_root / "manifests"
            if manifests_dir.is_dir():
                for entry in manifests_dir.iterdir():
                    if entry.is_file() and entry.name.endswith(
                        (".tmp.mkv", ".json.tmp", ".concat", ".tmp")
                    ):
                        try:
                            sz = entry.stat().st_size
                            entry.unlink(missing_ok=True)
                            cleaned_files.append(str(entry))
                            cleaned_bytes += sz
                        except OSError:
                            pass

            # Step 2: Clean unpinned ring segments
            active_pins = self._get_active_pins()

            for sdir in recorder_root.iterdir():
                if not sdir.is_dir() or sdir.name == "manifests" or sdir.name.startswith("."):
                    continue
                session_id = sdir.name
                session_pins = active_pins.get(session_id, [])

                # Clean any orphan tmp files in session dir (skip active segment parts)
                for entry in sdir.iterdir():
                    if entry.is_file() and entry.name.endswith(
                        (".tmp", ".tmp.mkv", ".json.tmp", ".concat")
                    ):
                        try:
                            sz = entry.stat().st_size
                            entry.unlink(missing_ok=True)
                            cleaned_files.append(str(entry))
                            cleaned_bytes += sz
                        except OSError:
                            pass

                # Find unpinned segments from sidecar json
                eligible_segments: list[tuple[float, Path, Path]] = []
                for entry in sdir.iterdir():
                    if entry.is_file() and entry.name.endswith(".json") and not entry.name.endswith(".json.tmp"):
                        try:
                            meta = json.loads(entry.read_text())
                            s_start = float(meta.get("start_seconds", 0.0))
                            s_end = float(meta.get("end_seconds", 0.0))
                            is_pinned = any(
                                s_start <= pin_end and s_end >= pin_start
                                for pin_start, pin_end in session_pins
                            )
                            if not is_pinned:
                                media_p = sdir / f"{entry.stem}.mkv"
                                eligible_segments.append((s_start, entry, media_p))
                        except Exception:
                            continue

                # Sort oldest first (FIFO)
                eligible_segments.sort(key=lambda x: x[0])
                for _, json_p, media_p in eligible_segments:
                    try:
                        if media_p.is_file():
                            sz = media_p.stat().st_size
                            media_p.unlink(missing_ok=True)
                            cleaned_files.append(str(media_p))
                            cleaned_bytes += sz
                        if json_p.is_file():
                            sz = json_p.stat().st_size
                            json_p.unlink(missing_ok=True)
                            cleaned_files.append(str(json_p))
                            cleaned_bytes += sz
                    except OSError:
                        pass

        return {
            "cleaned_bytes": cleaned_bytes,
            "cleaned_files": cleaned_files,
        }
