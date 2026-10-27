"""Edge WAN outage resilience coordinator, metadata priority, and backlog drain (Ticket #36).

Coordinates edge delivery outbox and evidence uploads across WAN outages:
1. Tracks WAN connectivity state (online, offline/outage) and outage duration.
2. Enforces metadata prioritization: flushes all pending event outbox messages
   before uploading video clips during recovery.
3. Handles network failures gracefully with bounded backoff and jitter without
   dropping any pending events or evidence intents (zero unACKed data loss).
4. Integrates with StorageQuotaManager and EdgeHealthMonitor to surface
   wan_outage_degraded when outage duration exceeds the 24h autonomy budget,
   while preserving state reserve.
5. Resumes and drains backlog cleanly when WAN connection is restored,
   verifying the B / (U - G) drain trajectory.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import math
import os
import random
import ssl
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from apps.edge.outbox import EventOutbox
from domain.wan_outage import (
    DEFAULT_AUTONOMY_BUDGET_SECONDS,
    DEFAULT_MIN_STATE_RESERVE_BYTES,
    ITEM_TYPE_EVIDENCE_CLIP,
    ITEM_TYPE_METADATA,
    POLICY_VERSION,
    REASON_OUTAGE_BUDGET_EXCEEDED,
    REASON_RECOVERY_IMPOSSIBLE_RATE,
    REASON_STORAGE_EXHAUSTED,
    STATUS_DEGRADED,
    STATUS_HEALTHY,
    STATUS_UNAVAILABLE,
    AutonomySizingModel,
    BacklogDrainModel,
    DrainVerificationResult,
    MetadataPriorityPolicy,
    OutageAssessment,
    RpoRtoAssessment,
)

logger = logging.getLogger(__name__)


def _api_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (local_http and os.getenv("ALLOW_INSECURE_LAB") == "1"):
        raise ValueError("API_URL must use HTTPS; loopback HTTP requires ALLOW_INSECURE_LAB=1")
    if not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("API_URL must be an origin without credentials, path, query, or fragment")
    return base_url.rstrip("/") + "/v1/events"


def _validate_event_receipt(receipt: Any, item: dict[str, Any]) -> dict[str, Any]:
    event = item["event"]
    expected = {
        "device_id": event["device_id"],
        "event_id": event["event_id"],
        "revision": event["revision"],
        "message_id": item["message_id"],
        "event_hash": item["event_hash"],
        "accepted": True,
        "canonicalization": "canonical-json-python-v1",
    }
    if not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in expected.items()) or not isinstance(receipt.get("accepted_at"), str):
        raise ValueError("server receipt does not match the pending event")
    return receipt


class WanOutageCoordinator:
    """Coordinates outbox deliveries and evidence uploads across WAN outages."""

    def __init__(
        self,
        *,
        outbox: EventOutbox,
        uploader: Any | None = None,
        quota_manager: Any | None = None,
        health_monitor: Any | None = None,
        sizing_model: AutonomySizingModel | None = None,
        autonomy_budget_seconds: float = DEFAULT_AUTONOMY_BUDGET_SECONDS,
        event_sender: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        base_url: str | None = None,
        token: str | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        max_backoff: float = 8.0,
        jitter: bool = True,
        clock_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        rng_fn: Callable[[float, float], float] | None = None,
    ) -> None:
        self.outbox = outbox
        self.uploader = uploader
        self.quota_manager = quota_manager
        self.health_monitor = health_monitor
        self.autonomy_budget_seconds = float(autonomy_budget_seconds)
        self.sizing_model = sizing_model or AutonomySizingModel(
            autonomy_budget_seconds=self.autonomy_budget_seconds
        )
        self.event_sender = event_sender
        self.base_url = base_url
        self.token = token
        self.max_retries = max(0, int(max_retries))
        self.backoff_base = max(0.0, float(backoff_base))
        self.max_backoff = max(0.0, float(max_backoff))
        self.jitter = bool(jitter)

        self.clock_fn: Callable[[], float] = clock_fn if clock_fn is not None else time.time
        self.sleep_fn: Callable[[float], None] = sleep_fn if sleep_fn is not None else time.sleep
        self.rng_fn: Callable[[float, float], float] = rng_fn if rng_fn is not None else random.uniform

        # Connectivity tracking state
        self._is_online: bool = True
        self._outage_start_time: float | None = None
        self._last_online_time: float | None = self.clock_fn()
        self._total_outage_seconds: float = 0.0
        self._outage_count: int = 0
        self._ssl_context = ssl.create_default_context()

    @property
    def is_online(self) -> bool:
        """True if edge WAN connection is currently active."""
        return self._is_online

    @property
    def is_reachable(self) -> bool:
        """Compatibility property for EdgeHealthMonitor backend_checker."""
        return self._is_online

    def is_backend_reachable(self) -> bool:
        """Callable checker for EdgeHealthMonitor backend_checker."""
        return self._is_online

    @property
    def outage_start_time(self) -> float | None:
        return self._outage_start_time

    @property
    def last_online_time(self) -> float | None:
        return self._last_online_time

    @property
    def total_outage_seconds(self) -> float:
        return self._total_outage_seconds

    @property
    def outage_count(self) -> int:
        return self._outage_count

    def outage_duration(self, now: float | None = None) -> float:
        """Calculate elapsed seconds of current outage, or 0.0 if online."""
        if self._is_online or self._outage_start_time is None:
            return 0.0
        current = self.clock_fn() if now is None else float(now)
        return max(0.0, current - self._outage_start_time)

    def is_outage_budget_exceeded(self, now: float | None = None) -> bool:
        """True if current outage has exceeded the autonomy budget."""
        return self.outage_duration(now=now) > self.autonomy_budget_seconds

    def record_connectivity(self, is_online: bool, *, now: float | None = None) -> None:
        """Update WAN connectivity state and update metrics and health."""
        current = self.clock_fn() if now is None else float(now)
        new_online = bool(is_online)

        if self._is_online and not new_online:
            # Transition online -> offline
            self._is_online = False
            self._outage_start_time = current
            self._outage_count += 1
            logger.warning(
                "WAN outage detected (outage #%d) at timestamp %.2f",
                self._outage_count,
                current,
            )
        elif not self._is_online and new_online:
            # Transition offline -> online
            self._is_online = True
            if self._outage_start_time is not None:
                duration = max(0.0, current - self._outage_start_time)
                self._total_outage_seconds += duration
                logger.info(
                    "WAN connection restored after %.2fs outage (total outages: %d)",
                    duration,
                    self._outage_count,
                )
            self._outage_start_time = None
            self._last_online_time = current

        self.sync_health_and_quota(now=current)

    def sync_health_and_quota(self, *, now: float | None = None) -> OutageAssessment:
        """Evaluate autonomy and state reserve, updating health monitor and quota manager."""
        current = self.clock_fn() if now is None else float(now)
        duration = self.outage_duration(now=current)

        avail_bytes: int | None = None
        if self.quota_manager is not None:
            try:
                breakdown = self.quota_manager.get_storage_breakdown()
                avail_bytes = int(breakdown.free_bytes)
            except Exception as exc:
                logger.warning("Failed to obtain storage breakdown: %s", exc)

        assessment = self.sizing_model.evaluate_outage(duration, available_bytes=avail_bytes)

        # Update StorageQuotaManager degraded state
        if self.quota_manager is not None:
            if assessment.is_budget_exceeded:
                self.quota_manager.degraded = True
                self.quota_manager.degraded_reason = REASON_OUTAGE_BUDGET_EXCEEDED
            elif self.quota_manager.degraded_reason == REASON_OUTAGE_BUDGET_EXCEEDED:
                self.quota_manager.degraded = False
                self.quota_manager.degraded_reason = None

        # Update EdgeHealthMonitor
        if self.health_monitor is not None:
            if assessment.is_budget_exceeded:
                self.health_monitor.record_probe_faults(
                    [
                        {
                            "code": "wan_outage_degraded",
                            "message": (
                                f"WAN outage duration ({duration:.1f}s) exceeded "
                                f"autonomy budget ({self.autonomy_budget_seconds:.1f}s)"
                            ),
                        }
                    ]
                )
                self.health_monitor.set_component_capability("backend", "unreachable")
            else:
                if not self._is_online:
                    self.health_monitor.set_component_capability("backend", "unreachable")
                else:
                    self.health_monitor.set_component_capability("backend", "reachable")
                    # Clear our probe fault if it was set
                    existing = getattr(self.health_monitor, "_probe_faults", [])
                    remaining = [f for f in existing if f.get("code") != "wan_outage_degraded"]
                    self.health_monitor.record_probe_faults(remaining)

        return assessment

    def get_pending_metadata_bytes(self) -> int:
        """Calculate total byte size of pending outbox events."""
        total = 0
        try:
            for item in self.outbox.pending():
                encoded = json.dumps(
                    item["event"],
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                total += len(encoded)
        except Exception as exc:
            logger.warning("Error calculating pending metadata bytes: %s", exc)
        return total

    def get_pending_clip_bytes(self) -> int:
        """Calculate total byte size of pending evidence clips awaiting upload."""
        total = 0
        try:
            for req in self.outbox.evidence_requests():
                if req.get("state") in {"fulfilled", "partial"}:
                    receipt = req.get("receipt") or {}
                    artifact = receipt.get("artifact") or {}
                    size = int(artifact.get("size_bytes") or req.get("estimated_bytes") or 0)
                    total += size
        except Exception as exc:
            logger.warning("Error calculating pending clip bytes: %s", exc)
        return total

    def get_total_backlog_bytes(self) -> int:
        """Total backlog bytes B = metadata bytes + clip bytes."""
        return self.get_pending_metadata_bytes() + self.get_pending_clip_bytes()

    def get_pending_counts(self) -> tuple[int, int]:
        """Return (pending_metadata_count, pending_clip_count)."""
        pending_meta = len(self.outbox.pending())
        pending_clips = 0
        for req in self.outbox.evidence_requests():
            if req.get("state") in {"fulfilled", "partial"}:
                pending_clips += 1
        return pending_meta, pending_clips

    def _deliver_single_event(self, item: dict[str, Any]) -> dict[str, Any]:
        """Deliver one event outbox item with validation and retry."""
        if self.event_sender is not None:
            return self.event_sender(item)

        if not self.base_url or not self.token:
            raise ValueError("No event_sender or base_url/token configured for delivery")

        endpoint = _api_url(self.base_url)
        body = json.dumps(
            item["event"],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        req = Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Idempotency-Key": item["message_id"],
            },
            method="POST",
        )
        with urlopen(req, timeout=5, context=self._ssl_context) as response:
            receipt = json.load(response)
        return _validate_event_receipt(receipt, item)

    def flush_pending_metadata(self, max_batch: int | None = None) -> int:
        """Flush pending metadata events from outbox with bounded backoff.

        Never drops or deletes unACKed events on network failure.
        """
        if not self._is_online:
            logger.debug("flush_pending_metadata called while offline; skipping")
            return 0

        pending_items = self.outbox.pending()
        if max_batch is not None:
            pending_items = pending_items[:max_batch]

        delivered_count = 0

        for item in pending_items:
            message_id = item["message_id"]
            delivered = False

            for attempt in range(self.max_retries + 1):
                if attempt > 0 and self.backoff_base > 0:
                    raw_delay = min(self.max_backoff, self.backoff_base * (2.0 ** (attempt - 1)))
                    delay = self.rng_fn(0.0, raw_delay) if self.jitter else raw_delay
                    self.sleep_fn(delay)

                try:
                    receipt = self._deliver_single_event(item)
                    self.outbox.record_attempt(message_id)
                    self.outbox.mark_delivered(message_id, receipt)
                    delivered_count += 1
                    delivered = True
                    break

                except HTTPError as exc:
                    self.outbox.record_attempt(message_id, type(exc).__name__)
                    # 429 and 5xx are retryable
                    if (exc.code == 429 or exc.code in {500, 502, 503, 504}) and attempt < self.max_retries:
                        continue
                    # Non-retryable HTTP error: stop batch but do NOT delete event
                    logger.error("Non-retryable HTTP error %d delivering %s: %s", exc.code, message_id, exc)
                    return delivered_count

                except (URLError, TimeoutError, ConnectionError, OSError) as exc:
                    self.outbox.record_attempt(message_id, type(exc).__name__)
                    if attempt < self.max_retries:
                        continue
                    # Retries exhausted: mark offline and break without data loss
                    logger.warning("Network failure during metadata delivery (%s): %s", message_id, exc)
                    self.record_connectivity(False)
                    return delivered_count

                except ValueError as exc:
                    # Receipt verification failure: record attempt, do not delete event
                    self.outbox.record_attempt(message_id, type(exc).__name__)
                    logger.error("Receipt validation error on %s: %s", message_id, exc)
                    return delivered_count

            if not delivered and not self._is_online:
                break

        return delivered_count

    def upload_pending_clips(self, batch_size: int = 10, *, reconcile: bool = False) -> int:
        """Upload pending evidence clips, STRICTLY prioritizing metadata first.

        Metadata Priority Policy (Ticket #36):
        If any metadata events are pending in the outbox, clip uploads are deferred.
        """
        if not self._is_online:
            return 0

        pending_meta = len(self.outbox.pending())
        if MetadataPriorityPolicy.should_defer_clip_upload(pending_meta):
            logger.info(
                "Metadata priority policy: deferring clip uploads (%d metadata events pending)",
                pending_meta,
            )
            return 0

        if self.uploader is None:
            return 0

        try:
            if hasattr(self.uploader, "upload_pending"):
                result = self.uploader.upload_pending(batch_size=batch_size, reconcile=reconcile)
                return int(result) if result is not None else 0
            return 0
        except (URLError, TimeoutError, ConnectionError, OSError) as exc:
            logger.warning("Network failure during evidence clip upload: %s", exc)
            self.record_connectivity(False)
            return 0
        except Exception as exc:
            logger.error("Unexpected error during clip upload: %s", exc)
            return 0

    def drain_step(self, *, metadata_batch: int | None = None, clip_batch: int = 10) -> dict[str, Any]:
        """Perform one coordinated backlog drain step.

        1. If offline, evaluates autonomy and returns offline status.
        2. Flushes metadata events first.
        3. If no metadata pending and still online, uploads evidence clips.
        """
        current = self.clock_fn()
        self.sync_health_and_quota(now=current)

        if not self._is_online:
            meta_count, clip_count = self.get_pending_counts()
            return {
                "online": False,
                "metadata_delivered": 0,
                "clips_uploaded": 0,
                "pending_metadata": meta_count,
                "pending_clips": clip_count,
                "backlog_bytes": self.get_total_backlog_bytes(),
            }

        # Step 1: Metadata delivery
        delivered_meta = self.flush_pending_metadata(max_batch=metadata_batch)

        # Step 2: Evidence clip upload (only if online and all metadata cleared)
        uploaded_clips = 0
        if self._is_online and len(self.outbox.pending()) == 0:
            uploaded_clips = self.upload_pending_clips(batch_size=clip_batch)

        pending_meta, pending_clips = self.get_pending_counts()
        return {
            "online": self._is_online,
            "metadata_delivered": delivered_meta,
            "clips_uploaded": uploaded_clips,
            "pending_metadata": pending_meta,
            "pending_clips": pending_clips,
            "backlog_bytes": self.get_total_backlog_bytes(),
        }

    def drain_all(self, *, max_iterations: int = 1000) -> dict[str, Any]:
        """Drain complete backlog across iterations until empty or network disconnects."""
        total_meta = 0
        total_clips = 0
        start_time = self.clock_fn()
        initial_backlog = self.get_total_backlog_bytes()

        for _ in range(max_iterations):
            if not self._is_online:
                break
            step_res = self.drain_step()
            total_meta += step_res["metadata_delivered"]
            total_clips += step_res["clips_uploaded"]
            if step_res["pending_metadata"] == 0 and step_res["pending_clips"] == 0:
                break

        elapsed = max(0.001, self.clock_fn() - start_time)
        final_backlog = self.get_total_backlog_bytes()
        drained_bytes = max(0, initial_backlog - final_backlog)

        return {
            "online": self._is_online,
            "total_metadata_delivered": total_meta,
            "total_clips_uploaded": total_clips,
            "initial_backlog_bytes": initial_backlog,
            "final_backlog_bytes": final_backlog,
            "drained_bytes": drained_bytes,
            "elapsed_seconds": elapsed,
            "drain_rate_bytes_per_second": drained_bytes / elapsed,
        }

    def assess_rpo_rto(
        self,
        upload_rate_bytes_per_second: float,
        generation_rate_bytes_per_second: float = 0.0,
    ) -> RpoRtoAssessment:
        """Report RPO and RTO within scope per contracts §3."""
        model = BacklogDrainModel(
            backlog_bytes=self.get_total_backlog_bytes(),
            upload_rate_bytes_per_second=upload_rate_bytes_per_second,
            generation_rate_bytes_per_second=generation_rate_bytes_per_second,
        )
        return model.assess_rpo_rto()

    def verify_drain_trajectory(
        self,
        *,
        upload_rate: float,
        generation_rate: float,
        start_backlog_bytes: int,
        measured_drain_time: float,
        tolerance_fraction: float = 0.15,
    ) -> DrainVerificationResult:
        """Verify measured drain against mathematical model B / (U - G)."""
        model = BacklogDrainModel(
            backlog_bytes=start_backlog_bytes,
            upload_rate_bytes_per_second=upload_rate,
            generation_rate_bytes_per_second=generation_rate,
        )
        return model.verify_drain(
            measured_drain_time,
            tolerance_fraction=tolerance_fraction,
        )
