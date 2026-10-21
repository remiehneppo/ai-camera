"""Deterministic negative-audit sampling over the recorder ring (ticket #28).

Segments that carry no alert are sampled before the ring expires, using the
inclusion probability of their stratum. Each sampled window becomes a
``pending_review`` audit record in ``<evidence_dir>/audit_samples``; reviewed
records are the denominator of the G2 quality report.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from domain.quality_eval import SamplingPlan, Stratum

SAMPLER_VERSION = "negative-audit-sampler-v1"
MANIFEST_VERSION = 1
DEFAULT_SALT = "negative-audit-v1"


class AuditSamplingError(ValueError):
    """Raised when a sampling request cannot be answered deterministically."""


class NegativeAuditSampler:
    """Sample no-alert ring segments with their stratum's inclusion probability."""

    DIRNAME = "audit_samples"

    def __init__(
        self,
        evidence_dir: str | Path,
        plan: SamplingPlan,
        *,
        rights_cleared: bool = True,
        salt: str = DEFAULT_SALT,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(plan, SamplingPlan):
            raise TypeError("plan must be a domain.quality_eval.SamplingPlan")
        if not isinstance(salt, str) or not salt:
            raise AuditSamplingError("salt must be a non-empty string")
        if not isinstance(rights_cleared, bool):
            raise AuditSamplingError("rights_cleared must be a boolean")
        self.evidence_dir = Path(evidence_dir)
        self.plan = plan
        self.rights_cleared = rights_cleared
        self.salt = salt
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.root = self.evidence_dir / self.DIRNAME
        self._seen: set[str] | None = None

    @property
    def manifest_path(self) -> Path:
        return self.root / "samples.jsonl"

    @property
    def plan_path(self) -> Path:
        return self.root / "plan.json"

    # ---- plan / probability -------------------------------------------------

    def stratum_for(self, camera_id: str, stratum_id: str | None = None) -> Stratum:
        return self.plan.stratum_for(camera_id, stratum_id=stratum_id)

    def inclusion_probability(self, camera_id: str, *, stratum_id: str | None = None) -> float:
        return self.stratum_for(camera_id, stratum_id).inclusion_probability

    def noise(self, camera_id: str, start_time: float, end_time: float, *, stratum_id: str | None = None) -> float:
        """Deterministic uniform value in [0, 1) for one window.

        Stable across processes and runs so a replayed ring yields the same
        audit decisions; no global RNG state is involved.
        """
        stratum = self.stratum_for(camera_id, stratum_id)
        key = "|".join(
            (
                self.salt,
                self.plan.plan_version,
                stratum.stratum_id,
                camera_id,
                f"{start_time:.6f}",
                f"{end_time:.6f}",
            )
        )
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    def should_sample(
        self,
        camera_id: str,
        start_time: float,
        end_time: float,
        *,
        stratum_id: str | None = None,
    ) -> bool:
        start, end = self._window(start_time, end_time)
        stratum = self.stratum_for(camera_id, stratum_id)
        if stratum.inclusion_probability >= 1.0:
            return True
        return self.noise(camera_id, start, end, stratum_id=stratum.stratum_id) < stratum.inclusion_probability

    # ---- sampling -----------------------------------------------------------

    def sample_window(
        self,
        *,
        camera_id: str,
        start_time: float,
        end_time: float,
        alert_count: int = 0,
        stratum_id: str | None = None,
        rights_cleared: bool | None = None,
    ) -> dict[str, Any] | None:
        """Return an audit record for a no-alert window, or None when not sampled.

        Windows with alerts are never audit samples: alerts already enter the
        report as positives, and double counting them would bias recall.
        """
        camera_id = self._camera(camera_id)
        if type(alert_count) is not int or alert_count < 0:
            raise AuditSamplingError("alert_count must be a non-negative integer")
        start, end = self._window(start_time, end_time)
        stratum = self.stratum_for(camera_id, stratum_id)
        if alert_count or not self.should_sample(camera_id, start, end, stratum_id=stratum.stratum_id):
            return None
        rights = self.rights_cleared if rights_cleared is None else rights_cleared
        if not isinstance(rights, bool):
            raise AuditSamplingError("rights_cleared must be a boolean")
        sample_id = self._sample_id(stratum.stratum_id, camera_id, start, end)
        if sample_id in self._sampled_ids():
            return None
        record = {
            "sample_id": sample_id,
            "stratum_id": stratum.stratum_id,
            "inclusion_probability": stratum.inclusion_probability,
            "camera_id": camera_id,
            "start_time": start,
            "end_time": end,
            "duration_seconds": end - start,
            "rights_cleared": rights,
            "status": "pending_review",
            "start_time_iso": self._iso(start),
            "end_time_iso": self._iso(end),
            "sampled_at": self._timestamp(),
            "capability": self.plan.capability,
            "plan_version": self.plan.plan_version,
            "manifest_version": MANIFEST_VERSION,
            "sampler_version": SAMPLER_VERSION,
        }
        self._append(record)
        assert self._seen is not None
        self._seen.add(sample_id)
        return record

    def sample_segment(
        self,
        segment: Any,
        *,
        camera_id: str | None = None,
        alert_count: int = 0,
        stratum_id: str | None = None,
        rights_cleared: bool | None = None,
    ) -> dict[str, Any] | None:
        """Sample a `FileRecorder` segment before the ring reclaims it."""
        start = getattr(segment, "start_seconds", None)
        end = getattr(segment, "end_seconds", None)
        if start is None or end is None:
            raise AuditSamplingError("segment must expose start_seconds and end_seconds")
        camera = str(camera_id or getattr(segment, "camera_id", None) or getattr(segment, "session_id", "default_camera"))
        return self.sample_window(
            camera_id=camera,
            start_time=start,
            end_time=end,
            alert_count=alert_count,
            stratum_id=stratum_id,
            rights_cleared=rights_cleared,
        )

    def _timestamp(self) -> str:
        moment = self._clock()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat()

    # ---- manifest -----------------------------------------------------------

    def samples(self) -> list[dict[str, Any]]:
        if not self.manifest_path.exists():
            return []
        records = []
        with self.manifest_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def summary(self) -> dict[str, Any]:
        records = self.samples()
        by_stratum: dict[str, int] = {}
        for record in records:
            key = str(record.get("stratum_id"))
            by_stratum[key] = by_stratum.get(key, 0) + 1
        return {
            "plan_version": self.plan.plan_version,
            "capability": self.plan.capability,
            "sampler_version": SAMPLER_VERSION,
            "manifest_version": MANIFEST_VERSION,
            "samples": len(records),
            "sampled_seconds": sum(float(record.get("duration_seconds", 0.0)) for record in records),
            "by_stratum": dict(sorted(by_stratum.items())),
            "pending_review": sum(1 for record in records if record.get("status") == "pending_review"),
        }

    def _sample_id(self, stratum_id: str, camera_id: str, start: float, end: float) -> str:
        """Stable UUIDv5 so re-sampling the same window cannot double the denominator."""
        key = "|".join(
            (self.salt, self.plan.plan_version, stratum_id, camera_id, f"{start:.6f}", f"{end:.6f}")
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"negative-audit:{key}"))

    def _sampled_ids(self) -> set[str]:
        if self._seen is None:
            self._seen = {str(record.get("sample_id")) for record in self.samples()}
        return self._seen

    def _append(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_plan_snapshot()
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n"
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def _write_plan_snapshot(self) -> None:
        if self.plan_path.exists():
            return
        payload = {
            "manifest_version": MANIFEST_VERSION,
            "sampler_version": SAMPLER_VERSION,
            "plan_sha256": self.plan.content_hash(),
            "plan": self.plan.to_dict(),
        }
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
        temporary = self.plan_path.with_suffix(".json.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, self.plan_path)

    # ---- validation ---------------------------------------------------------

    @staticmethod
    def _camera(camera_id: Any) -> str:
        if not isinstance(camera_id, str) or not camera_id:
            raise AuditSamplingError("camera_id must be a non-empty string")
        return camera_id

    @staticmethod
    def _window(start_time: Any, end_time: Any) -> tuple[float, float]:
        for value in (start_time, end_time):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise AuditSamplingError("start_time and end_time must be finite numbers")
        start, end = float(start_time), float(end_time)
        if end <= start:
            raise AuditSamplingError("end_time must follow start_time")
        return start, end

    @staticmethod
    def _iso(epoch_seconds: float) -> str:
        return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()
