"""Survey-weighted quality evaluation and sampling plan contract (ticket #28).

Pinned protocol (must be approved before a G2 sign-off):

- units: reviewed alert events (census unless a record carries its own
  inclusion probability) and reviewed negative audit samples;
- recall: Horvitz-Thompson ratio estimator, weight ``1 / p_h`` per stratum;
- uncertainty: 95% Wilson interval on the Kish effective sample size;
- FP denominator: HT-estimated camera-hours from the negative audit samples;
- the denominator never adds raw counts across strata with different ``p_h``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import NormalDist
from typing import Any, Iterable

EVAL_VERSION = "g2-quality-eval-v1"
CONFIDENCE_LEVEL = 0.95
DEFAULT_MIN_SAMPLES = 30
BRANCHES = ("person_fall", "person_lying_persistent", "person_on_stationary_vehicle")

_CONFIRMED = {"confirmed", "confirm", "resolved", "resolve", "true_positive", "tp", "positive"}
_FALSE_POSITIVE = {"false_positive", "false-positive", "fp", "negative", "no_event"}
_NEGATIVE_CLEAR = {"clear", "no_event", "negative", "no_target", "pass"}
_NEGATIVE_MISSED = {"missed_event", "missed", "target_present", "positive", "true_positive", "fail"}
_REVIEWED_STATUS = {"reviewed", "complete", "completed", "final", "done"}
_MISSING = object()


class QualityEvalError(ValueError):
    """Raised when a plan, record, or threshold cannot be evaluated."""


# ---- sampling plan ---------------------------------------------------------


@dataclass(frozen=True)
class Stratum:
    """One sampling stratum and its inclusion probability ``p_h``."""

    stratum_id: str
    inclusion_probability: float
    camera_id: str | None = None
    time_band: str | None = None
    weather: str | None = None
    rights_cleared: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.stratum_id, str) or not self.stratum_id.strip():
            raise QualityEvalError("stratum_id must be a non-empty string")
        probability = self.inclusion_probability
        if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 < probability <= 1:
            raise QualityEvalError("inclusion_probability must be a number in (0, 1]")
        if self.camera_id is not None and (not isinstance(self.camera_id, str) or not self.camera_id):
            raise QualityEvalError("camera_id must be a non-empty string when set")
        if self.rights_cleared is not True and self.rights_cleared is not False:
            raise QualityEvalError("rights_cleared must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stratum_id": self.stratum_id,
            "inclusion_probability": float(self.inclusion_probability),
            "camera_id": self.camera_id,
            "time_band": self.time_band,
            "weather": self.weather,
            "rights_cleared": self.rights_cleared,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "Stratum":
        if not isinstance(value, dict):
            raise QualityEvalError("stratum must be an object")
        stratum_id = value.get("stratum_id")
        if not isinstance(stratum_id, str):
            raise QualityEvalError("stratum_id must be a string")
        prob = value.get("inclusion_probability", value.get("p_h"))
        if type(prob) not in (int, float):
            raise QualityEvalError("inclusion_probability must be a number")
        return cls(
            stratum_id=stratum_id,
            inclusion_probability=float(prob),
            camera_id=value.get("camera_id"),
            time_band=value.get("time_band"),
            weather=value.get("weather"),
            rights_cleared=bool(value.get("rights_cleared", True)),
        )


@dataclass(frozen=True)
class SamplingPlan:
    """Versioned sampling plan shared by the edge sampler and the G2 report."""

    plan_version: str
    capability: str
    strata: tuple[Stratum, ...]
    min_samples: int = DEFAULT_MIN_SAMPLES
    site: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan_version, str) or not self.plan_version.strip():
            raise QualityEvalError("plan_version must be a non-empty string")
        if not isinstance(self.capability, str) or not self.capability.strip():
            raise QualityEvalError("capability must be a non-empty string")
        if not isinstance(self.strata, tuple) or not self.strata or not all(
            isinstance(item, Stratum) for item in self.strata
        ):
            raise QualityEvalError("strata must be a non-empty tuple of Stratum")
        identifiers = [item.stratum_id for item in self.strata]
        if len(set(identifiers)) != len(identifiers):
            raise QualityEvalError("stratum_id values must be unique")
        if type(self.min_samples) is not int or self.min_samples < 1:
            raise QualityEvalError("min_samples must be a positive integer")

    def stratum(self, stratum_id: str) -> Stratum:
        for item in self.strata:
            if item.stratum_id == stratum_id:
                return item
        raise QualityEvalError(f"unknown stratum_id: {stratum_id!r}")

    def stratum_for(self, camera_id: str | None, *, stratum_id: str | None = None) -> Stratum:
        if stratum_id is not None:
            return self.stratum(stratum_id)
        if camera_id:
            matches = [item for item in self.strata if item.camera_id == camera_id]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise QualityEvalError(f"multiple strata match camera {camera_id!r}; pass stratum_id")
        wildcards = [item for item in self.strata if item.camera_id is None]
        if len(wildcards) == 1:
            return wildcards[0]
        if len(self.strata) == 1:
            return self.strata[0]
        raise QualityEvalError(f"no unambiguous stratum for camera {camera_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "capability": self.capability,
            "site": self.site,
            "min_samples": self.min_samples,
            "strata": [item.to_dict() for item in self.strata],
        }

    def content_hash(self) -> str:
        encoded = json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: Any) -> "SamplingPlan":
        if not isinstance(value, dict):
            raise QualityEvalError("sampling plan must be an object")
        if "plan" in value and isinstance(value["plan"], dict):
            value = value["plan"]
        strata = value.get("strata")
        if not isinstance(strata, list):
            raise QualityEvalError("sampling plan strata must be a list")
        plan_version = value.get("plan_version", value.get("version"))
        if not isinstance(plan_version, str):
            raise QualityEvalError("plan_version must be a string")
        capability = value.get("capability")
        if not isinstance(capability, str):
            raise QualityEvalError("capability must be a string")
        return cls(
            plan_version=plan_version,
            capability=capability,
            strata=tuple(Stratum.from_dict(item) for item in strata),
            min_samples=int(value.get("min_samples", DEFAULT_MIN_SAMPLES)),
            site=value.get("site"),
        )


# ---- primitives ------------------------------------------------------------


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if type(value) in (int, float) and math.isfinite(value):
        seconds = value / 1000.0 if abs(value) > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(text), tz=timezone.utc)
            except (ValueError, OverflowError, OSError):
                return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    return None


def wilson_interval(estimate: float, sample_size: float, confidence: float = CONFIDENCE_LEVEL) -> tuple[float, float]:
    """Wilson score interval for a proportion evaluated at an effective n."""
    if not 0 < confidence < 1:
        raise QualityEvalError("confidence must be between 0 and 1")
    if sample_size <= 0:
        raise QualityEvalError("sample_size must be positive")
    if not 0 <= estimate <= 1:
        raise QualityEvalError("estimate must be a proportion")
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    denominator = 1 + z * z / sample_size
    centre = (estimate + z * z / (2 * sample_size)) / denominator
    margin = z * math.sqrt(estimate * (1 - estimate) / sample_size + z * z / (4 * sample_size * sample_size)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _kish_effective_size(weights: Iterable[float]) -> float:
    total = 0.0
    squared = 0.0
    for weight in weights:
        total += weight
        squared += weight * weight
    return total * total / squared if squared else 0.0


def _dig(record: dict[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _first(record: dict[str, Any], paths: Iterable[str], default: Any = None) -> Any:
    for path in paths:
        value = _dig(record, path)
        if value is not _MISSING and value is not None:
            return value
    return default


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _number(value: Any) -> float | None:
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _boolean(value: Any) -> bool | None:
    if value is True or value is False:
        return value
    return None


def _reject_non_mapping(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise QualityEvalError("reviewed record must be an object")
    return record


# ---- record normalisation --------------------------------------------------


def _stratum_identity(
    plan: SamplingPlan | None,
    camera_id: str | None,
    record: dict[str, Any],
    *,
    use_plan_probability: bool,
) -> tuple[str | None, float | None, bool, bool]:
    """Return (stratum_id, inclusion_probability, planned).

    Alerts are a census unless the record carries its own ``p_h``; negative
    samples inherit their stratum's probability from the plan.
    """
    explicit = _text(_first(record, ("stratum_id", "stratum", "stratum.id")))
    probability = _number(_first(record, ("inclusion_probability", "p_h", "plan.inclusion_probability")))
    if probability is not None and not 0 < probability <= 1:
        raise QualityEvalError("inclusion_probability must be in (0, 1]")
    if plan is None:
        return explicit, probability, True, False
    try:
        stratum = plan.stratum_for(camera_id, stratum_id=explicit)
    except QualityEvalError:
        return explicit, probability, False, False
    mismatch = probability is not None and abs(probability - stratum.inclusion_probability) > 1e-9
    if use_plan_probability:
        probability = stratum.inclusion_probability
    return stratum.stratum_id, probability, True, mismatch


def _review_minutes(record: dict[str, Any]) -> float | None:
    minutes = _number(_first(record, ("review_minutes", "review.minutes", "review.review_minutes")))
    if minutes is not None:
        return max(0.0, minutes)
    seconds = _number(_first(record, ("review_seconds", "review_duration_seconds", "review.seconds")))
    return None if seconds is None else max(0.0, seconds / 60.0)


def normalize_alert(record: dict[str, Any], plan: SamplingPlan | None, capability: str) -> dict[str, Any]:
    record = _reject_non_mapping(record)
    declared = _text(_first(record, ("capability", "payload.capability")))
    if declared is not None and declared != capability:
        return {"excluded": "other_capability", "camera_id": _text(_first(record, ("camera_id", "device_id")))}
    decision_text = _text(_first(record, ("reviewed_decision", "decision", "review.decision", "review_status", "label")))
    decision = decision_text.lower() if decision_text else None
    branch = _text(_first(record, ("branch", "payload.branch", "taxonomy", "payload.taxonomy"))) or "unassigned"
    camera_id = _text(_first(record, ("camera_id", "device_id", "camera.id")))
    stratum_id, probability, planned, mismatch = _stratum_identity(
        plan, camera_id, record, use_plan_probability=False
    )
    occurred_at = parse_timestamp(_first(record, ("occurred_at", "event_time", "started_at", "start_time", "timestamp")))
    normalized = {
        "camera_id": camera_id,
        "branch": branch,
        "occurred_at": occurred_at,
        "stratum_id": stratum_id,
        "probability": 1.0 if probability is None else probability,
        "planned": planned,
        "probability_mismatch": mismatch,
        "review_minutes": _review_minutes(record),
        "excluded": None,
        "false_positive": False,
        "detected": 0,
    }
    if decision in _CONFIRMED:
        normalized["detected"] = 1
        normalized["outcome"] = "confirmed"
    elif decision in _FALSE_POSITIVE:
        normalized["false_positive"] = True
        normalized["outcome"] = "false_positive"
    else:
        normalized["excluded"] = "unreviewed"
        normalized["outcome"] = decision or "unreviewed"
    return normalized


def normalize_negative(record: dict[str, Any], plan: SamplingPlan | None) -> dict[str, Any]:
    record = _reject_non_mapping(record)
    camera_id = _text(_first(record, ("camera_id", "device_id", "camera.id")))
    stratum_id, probability, planned, mismatch = _stratum_identity(
        plan, camera_id, record, use_plan_probability=True
    )
    start = parse_timestamp(_first(record, ("start_time", "started_at", "start", "segment_start")))
    end = parse_timestamp(_first(record, ("end_time", "ended_at", "end", "segment_end")))
    duration = _number(_first(record, ("duration_seconds", "segment_duration_seconds", "duration")))
    if duration is None and start is not None and end is not None:
        duration = (end - start).total_seconds()
    status = _text(_first(record, ("status", "review_status", "review.status")))
    reviewed_flag = _boolean(_first(record, ("reviewed", "is_reviewed")))
    outcome_text = _text(_first(record, ("outcome", "reviewed_outcome", "review_outcome", "reviewed_decision", "review.decision", "label")))
    missed_value = _first(record, ("missed_instances", "missed_count", "positives_found"))
    target_present = _first(record, ("target_present", "has_target", "contains_target", "missed_event"))
    rights = _boolean(_first(record, ("rights_cleared", "rights.cleared")))

    reviewed = reviewed_flag is True or (status is not None and status.lower() in _REVIEWED_STATUS)
    missed: int | None = None
    outcome: str | None = None
    if missed_value is not None:
        parsed = _number(missed_value)
        if parsed is None or parsed < 0 or parsed != int(parsed):
            raise QualityEvalError("missed_instances must be a non-negative integer")
        missed, reviewed, outcome = int(parsed), True, "reviewed"
    elif target_present is not None:
        truth = _boolean(target_present)
        if truth is None:
            raise QualityEvalError("target_present must be a boolean")
        missed, reviewed, outcome = (1 if truth else 0), True, "reviewed"
    elif outcome_text:
        lowered = outcome_text.lower()
        if lowered in _NEGATIVE_MISSED:
            missed, reviewed, outcome = 1, True, lowered
        elif lowered in _NEGATIVE_CLEAR:
            missed, reviewed, outcome = 0, True, lowered
        else:
            reviewed, outcome = False, lowered
    elif reviewed:
        missed, outcome = 0, "reviewed"

    return {
        "camera_id": camera_id,
        "stratum_id": stratum_id,
        "probability": probability,
        "planned": planned,
        "probability_mismatch": mismatch,
        "start": start,
        "end": end,
        "duration_seconds": max(0.0, duration) if duration is not None else None,
        "reviewed": bool(reviewed) and missed is not None,
        "missed": missed or 0,
        "outcome": outcome,
        "rights_cleared": True if rights is None else rights,
        "review_minutes": _review_minutes(record),
        "branch": _text(_first(record, ("branch", "missed_branch", "payload.branch"))) or "unassigned",
    }


# ---- evaluation ------------------------------------------------------------


def _stratum_entry(
    observed: dict[str, dict[str, Any]],
    stratum_id: str,
    probability: float | None,
    plan: SamplingPlan | None,
) -> dict[str, Any]:
    entry = observed.get(stratum_id)
    if entry is not None:
        return entry
    if plan is not None:
        try:
            probability = plan.stratum(stratum_id).inclusion_probability
        except QualityEvalError:
            pass
    return observed.setdefault(
        stratum_id,
        {
            "inclusion_probability": probability,
            "samples": 0,
            "reviewed_samples": 0,
            "alerts": 0,
            "raw_hours": 0.0,
            "estimated_hours": 0.0,
        },
    )


def _summarize_units(units: list[dict[str, Any]]) -> dict[str, Any]:
    detected_weights = [unit["weight"] for unit in units if unit["detected"]]
    all_weights = [unit["weight"] for unit in units]
    weighted_total = sum(all_weights)
    weighted_detected = sum(detected_weights)
    estimate = weighted_detected / weighted_total if weighted_total else None
    effective = _kish_effective_size(all_weights)
    interval = wilson_interval(estimate, effective) if estimate is not None and effective > 0 else None
    return {
        "estimate": estimate,
        "ci_low": None if interval is None else interval[0],
        "ci_high": None if interval is None else interval[1],
        "usable": True,
        "effective_sample_size": effective,
        "weighted_total_units": weighted_total,
        "weighted_detected_units": weighted_detected,
        "weighted_missed_units": weighted_total - weighted_detected,
        "detected_units": len(detected_weights),
        "missed_units": len(all_weights) - len(detected_weights),
    }


def evaluate_quality_metrics(
    alerts: Iterable[dict[str, Any]] | None,
    negatives: Iterable[dict[str, Any]] | None,
    *,
    plan: SamplingPlan | None = None,
    capability: str = "person_down",
    min_recall: float = 0.90,
    max_fp_per_day: float = 2.0,
    min_samples: int | None = None,
    site: str | None = None,
    confidence: float = CONFIDENCE_LEVEL,
    matching_window_seconds: float | None = None,
) -> dict[str, Any]:
    """Evaluate stratified recall, FP rate, review load and the G2 verdict."""
    if not isinstance(capability, str) or not capability:
        raise QualityEvalError("capability must be a non-empty string")
    if type(min_recall) not in (int, float) or not math.isfinite(min_recall) or not 0 < min_recall <= 1:
        raise QualityEvalError("min_recall must be in (0, 1]")
    if type(max_fp_per_day) not in (int, float) or not math.isfinite(max_fp_per_day) or max_fp_per_day < 0:
        raise QualityEvalError("max_fp_per_day must be finite and non-negative")
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 < confidence < 1:
        raise QualityEvalError("confidence must be between 0 and 1")
    required = DEFAULT_MIN_SAMPLES if min_samples is None else min_samples
    if plan is not None and min_samples is None:
        required = plan.min_samples
    if type(required) is not int or required < 1:
        raise QualityEvalError("min_samples must be a positive integer")

    alert_records = [normalize_alert(record, plan, capability) for record in (alerts or [])]
    negative_records = [normalize_negative(record, plan) for record in (negatives or [])]

    warnings: list[str] = []
    blocking: list[str] = []
    if plan is None:
        warnings.append("sampling_plan_not_provided")
    if matching_window_seconds is None:
        warnings.append("matching_window_not_pinned")
    elif (
        type(matching_window_seconds) not in (int, float)
        or not math.isfinite(matching_window_seconds)
        or matching_window_seconds <= 0
    ):
        raise QualityEvalError("matching_window_seconds must be finite and positive")

    counts = {
        "alerts_total": len(alert_records),
        "alerts_confirmed": 0,
        "alerts_false_positive": 0,
        "alerts_unreviewed": 0,
        "alerts_other_capability": 0,
        "negative_samples_total": len(negative_records),
        "negative_samples_reviewed": 0,
        "negative_samples_pending_review": 0,
        "negative_samples_with_missed_events": 0,
        "negative_positives_found": 0,
    }
    units: list[dict[str, Any]] = []
    branch_units: dict[str, list[dict[str, Any]]] = {}
    branch_false_positives: dict[str, int] = {}
    unplanned = 0
    rights_gap = 0
    missing_probability = 0
    missing_duration = 0
    probability_mismatch = 0
    missing_strata: set[str] = set()
    observed_strata: dict[str, dict[str, Any]] = {}
    alert_review_minutes = 0.0
    negative_review_minutes = 0.0
    false_positive_weight = 0.0
    estimated_hours = 0.0
    raw_hours = 0.0
    reviewed_raw_hours = 0.0

    for alert in alert_records:
        if alert["excluded"] == "other_capability":
            counts["alerts_other_capability"] += 1
            continue
        if alert["excluded"]:
            counts["alerts_unreviewed"] += 1
            continue
        if alert["probability"] is None:
            missing_probability += 1
            continue
        if not alert["planned"]:
            unplanned += 1
            continue
        if alert["probability_mismatch"]:
            probability_mismatch += 1
        weight = 1.0 / alert["probability"]
        if alert["review_minutes"] is not None:
            alert_review_minutes += alert["review_minutes"]
        if alert["false_positive"]:
            counts["alerts_false_positive"] += 1
            false_positive_weight += weight
            branch_false_positives[alert["branch"]] = branch_false_positives.get(alert["branch"], 0) + 1
            continue
        counts["alerts_confirmed"] += 1
        unit = {"weight": weight, "detected": True, "branch": alert["branch"]}
        units.append(unit)
        branch_units.setdefault(alert["branch"], []).append(unit)
        if alert["stratum_id"]:
            _stratum_entry(observed_strata, alert["stratum_id"], alert["probability"], plan)["alerts"] += 1

    for sample in negative_records:
        if not sample["planned"]:
            unplanned += 1
            continue
        if not sample["rights_cleared"]:
            rights_gap += 1
            continue
        if sample["probability"] is None:
            missing_probability += 1
            continue
        if sample["probability_mismatch"]:
            probability_mismatch += 1
        weight = 1.0 / sample["probability"]
        duration = sample["duration_seconds"]
        if duration is None or duration <= 0:
            missing_duration += 1
        else:
            hours = duration / 3600.0
            raw_hours += hours
            estimated_hours += hours / sample["probability"]
        if sample["stratum_id"]:
            entries = _stratum_entry(observed_strata, sample["stratum_id"], sample["probability"], plan)
            entries["samples"] += 1
            if duration:
                entries["raw_hours"] += duration / 3600.0
                entries["estimated_hours"] += duration / 3600.0 / sample["probability"]
        if not sample["reviewed"]:
            counts["negative_samples_pending_review"] += 1
            continue
        counts["negative_samples_reviewed"] += 1
        if sample["stratum_id"]:
            _stratum_entry(observed_strata, sample["stratum_id"], sample["probability"], plan)["reviewed_samples"] += 1
        if duration:
            reviewed_raw_hours += duration / 3600.0
        if sample["review_minutes"] is not None:
            negative_review_minutes += sample["review_minutes"]
        if sample["missed"]:
            counts["negative_samples_with_missed_events"] += 1
            counts["negative_positives_found"] += sample["missed"]
            for _ in range(sample["missed"]):
                unit = {"weight": weight, "detected": False, "branch": sample["branch"]}
                units.append(unit)
                branch_units.setdefault(sample["branch"], []).append(unit)

    if plan is not None:
        for stratum in plan.strata:
            if stratum.stratum_id not in observed_strata:
                missing_strata.add(stratum.stratum_id)
        if plan.capability != capability:
            warnings.append(f"plan_capability_mismatch:{plan.capability}")

    if counts["negative_samples_reviewed"] == 0:
        blocking.append("alerts_only")
    if unplanned:
        blocking.append(f"unplanned_samples:{unplanned}")
    if rights_gap:
        blocking.append(f"rights_not_cleared:{rights_gap}")
    if missing_probability:
        blocking.append(f"missing_inclusion_probability:{missing_probability}")
    if probability_mismatch:
        blocking.append(f"inclusion_probability_mismatch:{probability_mismatch}")
    if missing_strata:
        blocking.append("missing_strata:" + ",".join(sorted(missing_strata)))
    if counts["alerts_unreviewed"]:
        blocking.append(f"unreviewed_alerts:{counts['alerts_unreviewed']}")
    if missing_duration:
        warnings.append(f"missing_duration_samples:{missing_duration}")

    recall = _summarize_units(units)
    branches: dict[str, Any] = {}
    for branch in sorted(set(BRANCHES) | set(branch_units) | set(branch_false_positives)):
        summary = _summarize_units(branch_units.get(branch, []))
        summary["false_positives"] = branch_false_positives.get(branch, 0)
        if plan is not None and branch not in BRANCHES:
            warnings.append(f"unlisted_branch:{branch}")
        branches[branch] = summary

    if counts["negative_samples_reviewed"] == 0:
        # Alerts alone are not a denominator: never expose a recall figure
        # without reviewed negative samples behind it.
        for block in (recall, *branches.values()):
            block.update({"estimate": None, "ci_low": None, "ci_high": None, "usable": False})

    negative_weights = [
        1.0 / sample["probability"]
        for sample in negative_records
        if sample["planned"] and sample["rights_cleared"] and sample["probability"] is not None
    ]
    negative_effective = _kish_effective_size(negative_weights)

    fp_per_hour = false_positive_weight / estimated_hours if estimated_hours > 0 else None
    observation_days = estimated_hours / 24.0 if estimated_hours > 0 else 0.0
    false_positives = {
        "count": counts["alerts_false_positive"],
        "weighted_count": false_positive_weight,
        "camera_hours_raw": raw_hours,
        "camera_hours_estimated": estimated_hours,
        "per_camera_hour": fp_per_hour,
        "per_camera_day": None if fp_per_hour is None else fp_per_hour * 24.0,
    }

    reviewed_units = (
        counts["alerts_confirmed"] + counts["alerts_false_positive"] + counts["negative_samples_reviewed"]
    )
    review_minutes_total = alert_review_minutes + negative_review_minutes
    review_load = {
        "reviewed_alerts": counts["alerts_confirmed"] + counts["alerts_false_positive"],
        "reviewed_negatives": counts["negative_samples_reviewed"],
        "review_minutes_total": review_minutes_total,
        "review_minutes_per_alert": (
            alert_review_minutes / (counts["alerts_confirmed"] + counts["alerts_false_positive"])
            if counts["alerts_confirmed"] + counts["alerts_false_positive"]
            else None
        ),
        "review_minutes_per_negative": (
            negative_review_minutes / counts["negative_samples_reviewed"] if counts["negative_samples_reviewed"] else None
        ),
        "review_minutes_per_camera_day": (
            review_minutes_total / observation_days if observation_days > 0 else None
        ),
        "reviewed_units": reviewed_units,
    }

    sufficiency_reasons: list[str] = []
    if counts["negative_samples_reviewed"] < 1:
        sufficiency_reasons.append("no_reviewed_negative_samples")
    if negative_effective < required:
        sufficiency_reasons.append(f"effective_negative_samples={negative_effective:.2f} < min_samples={required}")
    if missing_probability:
        sufficiency_reasons.append("missing_inclusion_probability")
    sufficient = not sufficiency_reasons

    coverage = {
        "strata": [
            {"stratum_id": stratum_id, **entries}
            for stratum_id, entries in sorted(observed_strata.items())
        ],
        "missing_strata": sorted(missing_strata),
        "unplanned_samples": unplanned,
        "rights_not_cleared": rights_gap,
        "missing_inclusion_probability": missing_probability,
        "inclusion_probability_mismatch": probability_mismatch,
        "missing_duration_samples": missing_duration,
        "unreviewed_alerts": counts["alerts_unreviewed"],
        "other_capability_alerts": counts["alerts_other_capability"],
        "reviewed_negative_hours_raw": reviewed_raw_hours,
        "warnings": sorted(set(warnings)),
    }

    gaps = list(dict.fromkeys(blocking))
    verdict = "PASS"
    reasons: list[str] = []
    if counts["alerts_total"] == 0 and counts["negative_samples_total"] == 0:
        verdict, reasons = "BLOCKED", ["no_reviewed_data", *gaps]
    elif counts["alerts_total"] == 0:
        verdict, reasons = "BLOCKED", ["no_reviewed_alerts", *gaps]
    elif counts["negative_samples_reviewed"] == 0:
        verdict, reasons = "BLOCKED", ["alerts_only", *gaps]
    elif recall["estimate"] is None:
        verdict, reasons = "BLOCKED", ["no_recall_units", *gaps]
    elif not sufficient:
        verdict, reasons = "BLOCKED", ["insufficient_sample", *sufficiency_reasons, *gaps]
    elif gaps:
        verdict, reasons = "BLOCKED", ["coverage_incomplete", *gaps]
    elif recall["estimate"] < min_recall:
        verdict, reasons = "FAIL", [f"recall_below_target:{recall['estimate']:.4f} < {min_recall}"]
    elif fp_per_hour is None:
        verdict, reasons = "BLOCKED", ["missing_coverage_hours"]
    elif false_positives["per_camera_day"] is not None and false_positives["per_camera_day"] > max_fp_per_day:
        verdict, reasons = "FAIL", [f"fp_per_day_above_target:{false_positives['per_camera_day']:.4f} > {max_fp_per_day}"]
    elif recall["ci_low"] is not None and recall["ci_low"] < min_recall:
        verdict, reasons = "BLOCKED", [
            f"uncertainty_below_target:ci_low={recall['ci_low']:.4f} < {min_recall}"
        ]

    reasons = list(dict.fromkeys(reasons))
    return {
        "capability": capability,
        "site": site,
        "eval_version": EVAL_VERSION,
        "protocol": {
            "confidence_level": confidence,
            "min_recall": float(min_recall),
            "max_fp_per_day": float(max_fp_per_day),
            "min_samples": required,
            "denominator_unit": "estimated_camera_hours",
            "recall_estimator": "horvitz_thompson_ratio",
            "interval_method": "wilson_on_kish_effective_n",
            "matching_window_seconds": matching_window_seconds,
            "plan_version": None if plan is None else plan.plan_version,
            "plan_sha256": None if plan is None else plan.content_hash(),
        },
        "counts": counts,
        "workload": {
            "cameras": len(
                {record["camera_id"] for record in alert_records if record.get("camera_id")}
                | {record["camera_id"] for record in negative_records if record.get("camera_id")}
            ),
            "strata": len(observed_strata),
            "camera_hours_estimated": estimated_hours,
            "observation_days_estimated": observation_days,
            "reviewed_negative_hours_raw": reviewed_raw_hours,
        },
        "recall": recall,
        "branches": branches,
        "false_positives": false_positives,
        "review_load": review_load,
        "coverage": coverage,
        "sample_sufficiency": {
            "sufficient": sufficient,
            "reasons": sufficiency_reasons,
            "min_samples": required,
            "effective_negative_samples": negative_effective,
            "reviewed_negatives": counts["negative_samples_reviewed"],
        },
        "verdict": verdict,
        "verdict_reasons": reasons,
        "blocking_gaps": blocking,
    }
