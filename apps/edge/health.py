"""Edge health observation monitor.

Provides truthful edge runtime health states, metrics, and fault/degradation detection.
Masks secrets, enforces bounded label cardinality, and bounds telemetry history.
"""

from __future__ import annotations

import collections
import enum
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder
from apps.edge.rtsp import redact_rtsp_url
from domain.storm_guard import OUTCOME_MALFORMED, OUTCOMES, StormGuard, StormGuardPolicy

logger = logging.getLogger(__name__)


class HealthStatus(str, enum.Enum):
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


ALLOWED_STATUSES = {
    HealthStatus.STARTING.value,
    HealthStatus.HEALTHY.value,
    HealthStatus.DEGRADED.value,
    HealthStatus.UNAVAILABLE.value,
}

# Strictly bounded labels to prevent high-cardinality label explosion
ALLOWED_METRIC_LABELS = frozenset({"component", "status", "reason"})


class EdgeHealthMonitor:
    """Monitors edge runtime components and provides a truthful health observation snapshot."""

    def __init__(
        self,
        *,
        recorder: FileRecorder | None = None,
        recorder_session_id: str | None = None,
        outbox: EventOutbox | None = None,
        storage_path: str | Path | None = None,
        quota_manager: Any | None = None,
        backend_checker: Any | None = None,
        analytics_stall_timeout: float = 5.0,
        recorder_gap_threshold: float = 3.0,
        disk_warning_percent: float = 90.0,
        disk_critical_percent: float = 98.0,
        spool_max_len: int = 100,
        storm_guard: StormGuard | None = None,
        forensic_sink: Any | None = None,
    ) -> None:
        self.recorder = recorder
        self.recorder_session_id = recorder_session_id
        self.outbox = outbox
        self.storage_path = Path(storage_path).resolve() if storage_path else None
        self.quota_manager = quota_manager
        self.backend_checker = backend_checker
        self.analytics_stall_timeout = float(analytics_stall_timeout)
        self.recorder_gap_threshold = float(recorder_gap_threshold)
        self.disk_warning_percent = float(disk_warning_percent)
        self.disk_critical_percent = float(disk_critical_percent)
        self.spool_max_len = int(spool_max_len)

        if storm_guard is not None:
            self.storm_guard = storm_guard
            if self.storm_guard.storage_available is None:
                self.storm_guard.storage_available = self._is_storage_available
            if forensic_sink is not None and self.storm_guard.forensic_sink is None:
                self.storm_guard.forensic_sink = forensic_sink
        else:
            self.storm_guard = StormGuard(
                storage_available=self._is_storage_available,
                forensic_sink=forensic_sink,
            )

        self._lock = threading.RLock()
        self._is_started: bool = False
        self._is_stopped: bool = False

        # Frame observation state
        self._last_receive_time: float | None = None
        self._last_capture_time: float | None = None
        self._clock_mapping_valid: bool = False
        self._frame_drop_count: int = 0
        self._total_frames_received: int = 0

        # Component capabilities
        self._capabilities: dict[str, Any] = {
            "camera": "unknown",
            "analytics": "unknown",
            "recorder": "unknown",
            "outbox": "unknown",
            "backend": "unknown",
            "storm_guard": "active",
        }

        # Bounded telemetry event spool (FIFO)
        self._telemetry_spool: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=self.spool_max_len
        )

        # Synthetic-probe faults (Ticket #40): operational signal, never an incident.
        self._probe_faults: list[dict[str, Any]] = []

    def mark_started(self) -> None:
        """Mark system as transitioned past startup."""
        with self._lock:
            if not self._is_stopped:
                self._is_started = True

    def mark_starting(self) -> None:
        """Begin a new runtime session without reusing old frame liveness."""
        with self._lock:
            self._is_started = False
            self._is_stopped = False
            self._last_receive_time = None
            self._last_capture_time = None
            self._clock_mapping_valid = False
            self._capabilities["camera"] = "unknown"

    def mark_stopped(self) -> None:
        """Keep shutdown unavailable even if an in-flight frame completes."""
        with self._lock:
            self._is_stopped = True
            self._is_started = False

    def record_frame_received(
        self,
        *,
        receive_time: float | None = None,
        capture_time: float | None = None,
        clock_mapping_valid: bool = False,
    ) -> None:
        """Record receipt of a frame from camera source."""
        now = time.time() if receive_time is None else float(receive_time)
        with self._lock:
            self._last_receive_time = now
            self._total_frames_received += 1
            if capture_time is not None and clock_mapping_valid:
                self._last_capture_time = float(capture_time)
                self._clock_mapping_valid = True
            else:
                self._last_capture_time = None
                self._clock_mapping_valid = False
            self._capabilities["camera"] = "active"

    def record_frame_drop(self, count: int = 1) -> None:
        """Record dropped or stale frames."""
        with self._lock:
            self._frame_drop_count += count

    def set_component_capability(self, component: str, state: str) -> None:
        """Set capability state for a component (e.g. active, degraded, unavailable)."""
        with self._lock:
            self._capabilities[component] = state

    def record_probe_faults(self, faults: Any) -> None:
        """Hold the latest synthetic-probe faults; bounded so a flap cannot grow the snapshot."""
        with self._lock:
            self._probe_faults = [dict(fault) for fault in list(faults)[:8]]

    def record_ingest_outcome(
        self,
        outcome: str,
        *,
        device_id: str = "",
        detail: Mapping[str, Any] | None = None,
        size_bytes: int | None = None,
        now: float | None = None,
    ) -> None:
        """Record an inbound or edge ingest outcome into edge storm guard."""
        masked_detail = self._mask_secrets_in_obj(dict(detail)) if detail else None
        with self._lock:
            self.storm_guard.record(
                outcome,
                device_id=device_id,
                detail=masked_detail,
                size_bytes=size_bytes,
                now=now,
            )

    def record_malformed_payload(
        self,
        detail_or_reason: Mapping[str, Any] | str | None = None,
        *,
        device_id: str = "",
        detail: Mapping[str, Any] | None = None,
        size_bytes: int | None = None,
        now: float | None = None,
    ) -> None:
        """Record a malformed payload or command received at edge."""
        merged_detail: dict[str, Any] = {}
        if isinstance(detail_or_reason, str):
            merged_detail["reason"] = detail_or_reason
        elif isinstance(detail_or_reason, Mapping):
            merged_detail.update(detail_or_reason)
        if detail:
            merged_detail.update(detail)
        self.record_ingest_outcome(
            OUTCOME_MALFORMED,
            device_id=device_id,
            detail=merged_detail if merged_detail else None,
            size_bytes=size_bytes,
            now=now,
        )

    def record_media_failure(self, count: int = 1) -> None:
        """Record media or forensic write failure at edge."""
        with self._lock:
            self.storm_guard.record_sink_failure(count=count)

    def record_sink_failure(self, count: int = 1) -> None:
        """Alias for record_media_failure."""
        self.record_media_failure(count=count)

    def record_telemetry_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Record a telemetry event in bounded FIFO spool, masking any sensitive fields."""
        masked_data = self._mask_secrets_in_obj(data)
        with self._lock:
            entry = {
                "timestamp": time.time(),
                "event_type": event_type,
                "data": masked_data,
            }
            self._telemetry_spool.append(entry)

    def get_telemetry_events(self) -> list[dict[str, Any]]:
        """Return shallow copy of current bounded telemetry spool."""
        with self._lock:
            return list(self._telemetry_spool)

    def _mask_secrets_in_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            if "rtsp://" in obj or "rtsps://" in obj:
                return redact_rtsp_url(obj)
            return obj
        elif isinstance(obj, dict):
            masked = {}
            for k, v in obj.items():
                key_str = str(k).lower()
                is_secret = (
                    any(secret_key in key_str for secret_key in ("password", "token", "secret", "auth"))
                    or key_str == "key"
                    or key_str.endswith("_key")
                    or key_str.startswith("key_")
                )
                if is_secret:
                    masked[k] = "<redacted>"
                else:
                    masked[k] = self._mask_secrets_in_obj(v)
            return masked
        elif isinstance(obj, list):
            return [self._mask_secrets_in_obj(item) for item in obj]
        return obj

    def _measure_disk(self) -> tuple[float, int, int]:
        """Return (disk_usage_percent, disk_free_bytes, disk_total_bytes)."""
        if self.quota_manager is not None:
            try:
                breakdown = self.quota_manager.get_storage_breakdown()
                return (breakdown.used_percent, breakdown.free_bytes, breakdown.total_bytes)
            except Exception as exc:
                logger.warning("Failed to inspect disk usage via quota manager: %s", exc)

        path_to_check = self.storage_path
        if path_to_check is None and self.recorder is not None:
            path_to_check = self.recorder.root
        if path_to_check is None:
            path_to_check = Path(".")

        try:
            usage = shutil.disk_usage(path_to_check)
            total = usage.total
            free = usage.free
            used = usage.used
            percent = (used / total * 100.0) if total > 0 else 0.0
            return (round(percent, 2), free, total)
        except Exception as exc:
            logger.warning("Failed to inspect disk usage: %s", exc)
            return (0.0, 0, 0)

    def _is_storage_available(self) -> bool:
        """Check if storage is available (not full and reserve intact)."""
        disk_percent, disk_free, _ = self._measure_disk()
        if self.quota_manager is not None:
            min_reserve = getattr(self.quota_manager, "min_state_reserve_bytes", 0)
            crit_pct = getattr(self.quota_manager, "critical_percent", self.disk_critical_percent)
            if disk_free <= min_reserve or disk_percent >= crit_pct:
                return False
        else:
            if disk_percent >= self.disk_critical_percent:
                return False
        return True

    def _measure_recorder_gap(self) -> float:
        """Measure maximum gap in seconds between segments in active ring."""
        if self.recorder is None or not self.recorder_session_id:
            return 0.0
        try:
            raw_segments = self.recorder.segments(self.recorder_session_id)
            if len(raw_segments) < 2:
                return 0.0
            segments = sorted(raw_segments, key=lambda s: getattr(s, "start_seconds", 0.0))
            max_gap = 0.0
            for left, right in zip(segments, segments[1:]):
                gap = right.start_seconds - left.end_seconds
                if gap > max_gap:
                    max_gap = gap
            return max(0.0, round(max_gap, 3))
        except Exception as exc:
            logger.warning("Failed to inspect recorder segments: %s", exc)
            return 0.0

    def _measure_outbox_pending(self) -> int:
        """Return count of undelivered pending messages in outbox."""
        if self.outbox is None:
            return 0
        try:
            return len(self.outbox.pending())
        except Exception as exc:
            logger.warning("Failed to query outbox pending count: %s", exc)
            return 0

    def _measure_operational_faults(self) -> list[str]:
        """Return distinct operational fault reasons from outbox evidence requests."""
        if self.outbox is None:
            return []
        try:
            reqs_fn = getattr(self.outbox, "evidence_requests", None)
            if callable(reqs_fn):
                faults: list[str] = []
                for req in reqs_fn():
                    receipt = req.get("receipt") or {}
                    fault = receipt.get("operational_fault")
                    if fault and str(fault) not in faults:
                        faults.append(str(fault))
                return faults
            return []
        except Exception as exc:
            logger.warning("Failed to query operational faults: %s", exc)
            return []

    def _check_backend_reachable(self) -> bool:
        """Check if backend is reachable."""
        if self.backend_checker is None:
            return True
        try:
            if callable(self.backend_checker):
                return bool(self.backend_checker())
            return bool(getattr(self.backend_checker, "is_reachable", True))
        except Exception:
            return False

    def get_health_snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        """Produce a complete, truthful health snapshot."""
        current_time = time.time() if now is None else float(now)
        disk_percent, disk_free, disk_total = self._measure_disk()
        recorder_gap = self._measure_recorder_gap()
        outbox_pending = self._measure_outbox_pending()
        operational_faults = self._measure_operational_faults()
        backend_ok = self._check_backend_reachable()

        with self._lock:
            # 1. Evaluate metrics
            # Frame age
            if self._last_receive_time is not None:
                receive_age = max(0.0, current_time - self._last_receive_time)
            else:
                receive_age = None

            if self._clock_mapping_valid and self._last_capture_time is not None:
                capture_age: float | None = max(0.0, current_time - self._last_capture_time)
            else:
                capture_age = None

            # Copy capabilities
            capabilities = dict(self._capabilities)

            # 2. Fault and status determination
            status = HealthStatus.HEALTHY
            reasons: list[str] = []

            if not self._is_started:
                status = HealthStatus.STARTING
                reasons.append("system_starting")

            # Check camera / frame stall
            if self._is_started:
                if self._last_receive_time is None:
                    status = HealthStatus.UNAVAILABLE
                    reasons.append("no_frames_received")
                    capabilities["camera"] = "unavailable"
                elif receive_age is not None and receive_age > self.analytics_stall_timeout:
                    status = HealthStatus.DEGRADED
                    reasons.append("queue_stall")
                    capabilities["camera"] = "stalled"

            # Check analytics capability
            analytics_cap = capabilities.get("analytics")
            if analytics_cap in ("hung", "stalled"):
                if status not in (HealthStatus.UNAVAILABLE, HealthStatus.STARTING):
                    status = HealthStatus.DEGRADED
                reasons.append("analytics_hung")
            elif analytics_cap in ("failed", "crash", "unavailable"):
                if status not in (HealthStatus.UNAVAILABLE, HealthStatus.STARTING):
                    status = HealthStatus.DEGRADED
                reasons.append("analytics_failed")

            # Check recorder capability
            recorder_cap = capabilities.get("recorder")
            if recorder_cap in ("failed", "unavailable"):
                if status not in (HealthStatus.UNAVAILABLE, HealthStatus.STARTING):
                    status = HealthStatus.DEGRADED
                reasons.append("recorder_failed")

            # Check recorder gap
            if recorder_gap > self.recorder_gap_threshold:
                if status not in (HealthStatus.UNAVAILABLE, HealthStatus.STARTING):
                    status = HealthStatus.DEGRADED
                reasons.append("recorder_gap_exceeded")
                capabilities["recorder"] = "gap_detected"

            # Check disk
            if self.quota_manager is not None:
                if disk_free <= self.quota_manager.min_state_reserve_bytes or disk_percent >= self.quota_manager.critical_percent:
                    status = HealthStatus.UNAVAILABLE
                    reasons.append("storage_exhausted")
                elif disk_percent >= self.quota_manager.warning_percent:
                    if status == HealthStatus.HEALTHY:
                        status = HealthStatus.DEGRADED
                    reasons.append("disk_near_capacity")
            else:
                if disk_percent >= self.disk_critical_percent:
                    status = HealthStatus.UNAVAILABLE
                    reasons.append("disk_full")
                elif disk_percent >= self.disk_warning_percent:
                    if status == HealthStatus.HEALTHY:
                        status = HealthStatus.DEGRADED
                    reasons.append("disk_near_capacity")

            # Check backend
            if not backend_ok:
                if status == HealthStatus.HEALTHY:
                    status = HealthStatus.DEGRADED
                reasons.append("backend_unreachable")
                capabilities["backend"] = "unreachable"
            else:
                capabilities["backend"] = "reachable"

            # Synthetic-probe faults are operational: they degrade health, they never open an incident.
            with self._lock:
                probe_faults = [dict(fault) for fault in self._probe_faults]
            for probe_fault in probe_faults:
                code = probe_fault.get("code")
                if isinstance(code, str) and code and code not in operational_faults:
                    operational_faults.append(code)

            # Check operational faults
            if operational_faults:
                if status == HealthStatus.HEALTHY:
                    status = HealthStatus.DEGRADED
                for fault in operational_faults:
                    if fault not in reasons:
                        reasons.append(fault)

            # Check edge storm guard
            storm_snapshot = self.storm_guard.snapshot(now=current_time)
            storm_degraded = (
                storm_snapshot.get("degraded", False)
                or storm_snapshot.get("truncated", False)
                or storm_snapshot.get("forensic_storage_degraded", False)
                or storm_snapshot.get("budget_spent", 0) >= storm_snapshot.get("malformed_budget", 1)
            )
            if storm_degraded:
                if status == HealthStatus.HEALTHY:
                    status = HealthStatus.DEGRADED
                if "malformed_storm_detected" not in reasons:
                    reasons.append("malformed_storm_detected")
                capabilities["storm_guard"] = "degraded"
            else:
                capabilities["storm_guard"] = "active"

            if self._is_stopped:
                status = HealthStatus.UNAVAILABLE
                reasons.insert(0, "system_stopped")
                capabilities["camera"] = "stopped"
                if "system_starting" in reasons:
                    reasons.remove("system_starting")

            UNAVAILABLE_REASONS = {"system_stopped", "storage_exhausted", "disk_full", "no_frames_received"}
            DEGRADED_REASONS = {
                "queue_stall", "analytics_hung", "analytics_failed",
                "recorder_gap_exceeded", "recorder_failed", "disk_near_capacity",
                "backend_unreachable", "upload_413_payload_too_large",
                "malformed_storm_detected",
            }

            if status == HealthStatus.UNAVAILABLE:
                primary_reason = next((r for r in reasons if r in UNAVAILABLE_REASONS), reasons[0] if reasons else None)
            elif status == HealthStatus.DEGRADED:
                primary_reason = next((r for r in reasons if r in DEGRADED_REASONS), reasons[0] if reasons else None)
            elif status == HealthStatus.STARTING:
                primary_reason = "system_starting"
            else:
                primary_reason = None

            metrics = {
                "frame_age_seconds": receive_age if capture_age is None else capture_age,
                "receive_age_seconds": receive_age,
                "capture_age_seconds": capture_age,
                "clock_mapping_valid": self._clock_mapping_valid,
                "frame_drop_count": self._frame_drop_count,
                "total_frames_received": self._total_frames_received,
                "recorder_gap_seconds": recorder_gap,
                "disk_usage_percent": disk_percent,
                "disk_free_bytes": disk_free,
                "disk_total_bytes": disk_total,
                "outbox_pending_count": outbox_pending,
                "operational_fault_count": len(operational_faults),
                "operational_faults": operational_faults,
                "probe_fault_count": len(probe_faults),
                "probe_faults": probe_faults,
                "backend_reachable": backend_ok,
                "storm_guard": storm_snapshot,
                "media_write_failures": storm_snapshot.get("media_write_failures", 0),
            }

            snapshot: dict[str, Any] = {
                "status": status.value,
                "reason": primary_reason,
                "all_reasons": reasons,
                "capabilities": capabilities,
                "metrics": metrics,
                "storm_guard": storm_snapshot,
                "timestamp": current_time,
            }
            return snapshot
