"""Storage quota accounting, state reserve protection, and emergency cleanup."""
from __future__ import annotations

from dataclasses import dataclass
import contextlib
import json
import logging
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
    degraded: bool = False
    degraded_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ring_bytes": self.ring_bytes,
            "pinned_bytes": self.pinned_bytes,
            "temp_bytes": self.temp_bytes,
            "wal_bytes": self.wal_bytes,
            "free_bytes": self.free_bytes,
            "total_bytes": self.total_bytes,
            "used_percent": self.used_percent,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
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
        self.degraded: bool = False
        self.degraded_reason: str | None = None

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
            with contextlib.closing(sqlite3.connect(pins_db, timeout=5)) as db:
                rows = db.execute(
                    "SELECT session_id, start, end FROM pins WHERE released=0"
                ).fetchall()
                for session_id, start, end in rows:
                    active_pins.setdefault(session_id, []).append((float(start), float(end)))
            self.degraded = False
            self.degraded_reason = None
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Failed to query active pins: %s", exc)
            self.degraded = True
            self.degraded_reason = f"active_pins_query_failed: {exc}"
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
            try:
                resolved = f.resolve()
            except OSError:
                resolved = f
            if resolved.is_file() and resolved not in seen_wal_files:
                seen_wal_files.add(resolved)
                try:
                    wal_bytes += resolved.stat().st_size
                except OSError:
                    pass

        # 2. Inspect Recorder root (sessions and manifests)
        recorder_root = None
        if self.recorder is not None and hasattr(self.recorder, "root"):
            recorder_root = Path(self.recorder.root)
        elif (self.storage_path / "pins.sqlite3").is_file() or (self.storage_path / "manifests").is_dir() or self.storage_path.is_dir():
            recorder_root = self.storage_path

        released_acked_hashes: set[str] = set()
        pins_db = None
        if self.recorder is not None and hasattr(self.recorder, "_pins"):
            pins_db = Path(self.recorder._pins)
        elif (self.storage_path / "pins.sqlite3").is_file():
            pins_db = self.storage_path / "pins.sqlite3"

        if pins_db and pins_db.is_file():
            try:
                import hashlib
                with contextlib.closing(sqlite3.connect(pins_db, timeout=5)) as db:
                    rows = db.execute(
                        "SELECT p.request_id FROM pins p JOIN transfers t ON p.request_id = t.request_id WHERE p.released = 1"
                    ).fetchall()
                    for (req_id,) in rows:
                        released_acked_hashes.add(hashlib.sha256(req_id.encode()).hexdigest())
            except (sqlite3.Error, OSError) as exc:
                logger.warning("Failed to query released acked pins: %s", exc)
                self.degraded = True
                self.degraded_reason = self.degraded_reason or f"released_pins_query_failed: {exc}"

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
                        stem = entry.name.removesuffix(".mkv").removesuffix(".json")
                        if stem in released_acked_hashes:
                            ring_bytes += sz
                        else:
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
            degraded=self.degraded,
            degraded_reason=self.degraded_reason,
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
        baseline_used_bytes = breakdown.total_bytes * (breakdown.used_percent / 100.0)
        projected_used_bytes = baseline_used_bytes + estimated_bytes
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

        if self.recorder is None or not hasattr(self.recorder, "cleanup_storage"):
            return {"cleaned_bytes": 0, "cleaned_files": []}

        target_bytes_to_reclaim = None
        if not force:
            breakdown = self.get_storage_breakdown()
            needed_for_percent = 0
            if breakdown.used_percent >= self.warning_percent and breakdown.total_bytes > 0:
                target_used = breakdown.total_bytes * (max(0.0, self.warning_percent - 2.0) / 100.0)
                current_used = breakdown.total_bytes * (breakdown.used_percent / 100.0)
                needed_for_percent = int(max(0.0, current_used - target_used))
            needed_for_reserve = 0
            if breakdown.free_bytes <= self.min_state_reserve_bytes:
                target_free = int(self.min_state_reserve_bytes * 1.2)
                needed_for_reserve = max(0, target_free - breakdown.free_bytes)
            target_bytes_to_reclaim = max(needed_for_percent, needed_for_reserve)

        try:
            return self.recorder.cleanup_storage(target_bytes=target_bytes_to_reclaim)
        except Exception as exc:
            logger.warning("Recorder storage cleanup failed: %s", exc)
            return {"cleaned_bytes": 0, "cleaned_files": []}
