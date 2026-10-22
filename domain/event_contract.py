"""Version 1 full-snapshot contract shared by edge and server."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID

from domain.evidence_contract import validate_evidence_request

SCHEMA_VERSION = 1
CANONICALIZATION = "canonical-json-python-v1"
MAX_EVENT_BYTES = 256 * 1024
MAX_PAYLOAD_BYTES = 64 * 1024

PERSON_DOWN_TAXONOMIES = (
    "person_fall",
    "person_lying_persistent",
    "person_on_stationary_vehicle",
)

_FIELDS = {
    "schema_version",
    "message_id",
    "event_id",
    "revision",
    "device_id",
    "camera_id",
    "stream_session_id",
    "pipeline_id",
    "pipeline_version",
    "origin",
    "event_time",
    "produced_at",
    "config_version",
    "model_lineage",
    "model_artifact_hash",
    "calibration_version",
    "quality_state",
    "payload",
}
_STRING_LIMITS = {
    "message_id": 128,
    "device_id": 128,
    "camera_id": 128,
    "stream_session_id": 128,
    "pipeline_id": 128,
    "pipeline_version": 64,
    "config_version": 128,
    "model_artifact_hash": 128,
    "calibration_version": 128,
    "quality_state": 64,
}
_ORIGINS = {"live", "replay", "synthetic"}


class EventValidationError(ValueError):
    pass


_IMMUTABLE_REVISION_FIELDS = ("device_id", "event_id", "camera_id", "stream_session_id", "pipeline_id", "pipeline_version", "origin")


def validate_revision_identity(first: dict[str, Any], next_event: dict[str, Any]) -> None:
    for field in _IMMUTABLE_REVISION_FIELDS:
        if first[field] != next_event[field]:
            raise EventValidationError(f"{field} is immutable across event revisions")


def _canonical_uuid(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise EventValidationError(f"{name} must be a UUID string")
    try:
        parsed = str(UUID(value))
    except ValueError as exc:
        raise EventValidationError(f"{name} must be a UUID string") from exc
    if parsed != value:
        raise EventValidationError(f"{name} must use lowercase canonical UUID form")
    return parsed


def _timestamp(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise EventValidationError(f"{name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventValidationError(f"{name} must be an ISO-8601 string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventValidationError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_quality(quality: Any) -> None:
    """Optional payload.quality: odd_supported is tri-state and must agree with state."""
    if quality is None:
        return
    if not isinstance(quality, dict):
        raise EventValidationError("payload.quality must be an object")
    state, supported = quality.get("state"), quality.get("odd_supported")
    if not isinstance(state, str) or not state or len(state) > 64:
        raise EventValidationError("payload.quality.state must be a non-empty string")
    if supported is not None and type(supported) is not bool:
        raise EventValidationError("payload.quality.odd_supported must be true, false or null")
    if (supported is True and state != "normal") or (supported is False and state == "normal"):
        raise EventValidationError("payload.quality.odd_supported contradicts state")


_POSE_STATUSES = {"none", "ok", "skipped", "failed", "cancelled"}


def _validate_pose_evidence(pose_evidence: Any) -> None:
    """Optional payload.pose_evidence: validates status, reason, branch, and keypoints."""
    if pose_evidence is None:
        return
    if not isinstance(pose_evidence, dict):
        raise EventValidationError("payload.pose_evidence must be an object")
    status = pose_evidence.get("status")
    if not isinstance(status, str) or status not in _POSE_STATUSES:
        raise EventValidationError(f"payload.pose_evidence.status must be one of: {', '.join(sorted(_POSE_STATUSES))}")
    keypoints = pose_evidence.get("keypoints")
    if not isinstance(keypoints, list):
        raise EventValidationError("payload.pose_evidence.keypoints must be an array")
    if status == "ok" and not keypoints:
        raise EventValidationError("payload.pose_evidence with status 'ok' must have non-empty keypoints")
    if status != "ok" and keypoints:
        raise EventValidationError("payload.pose_evidence with non-ok status must have empty keypoints")
    if len(keypoints) > 32:
        raise EventValidationError("payload.pose_evidence.keypoints exceeds 32 items")


def validate_event(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EventValidationError("event must be a JSON object")
    missing = _FIELDS - value.keys()
    extra = value.keys() - _FIELDS
    if missing:
        raise EventValidationError(f"missing required fields: {', '.join(sorted(missing))}")
    if extra:
        raise EventValidationError(f"unknown fields: {', '.join(sorted(extra))}")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise EventValidationError(f"schema_version must be {SCHEMA_VERSION}")
    if type(value["revision"]) is not int or value["revision"] < 1:
        raise EventValidationError("revision must be a positive integer")
    if type(value["pipeline_version"]) is not str or not value["pipeline_version"]:
        raise EventValidationError("pipeline_version must be a non-empty string")
    for field, limit in _STRING_LIMITS.items():
        text = value[field]
        if not isinstance(text, str) or not text or len(text) > limit:
            raise EventValidationError(f"{field} must be a non-empty string of at most {limit} characters")
    if not isinstance(value["origin"], str) or value["origin"] not in _ORIGINS:
        raise EventValidationError("origin must be live, replay, or synthetic")
    for field in ("event_id", "stream_session_id"):
        _canonical_uuid(value[field], field)
    if not isinstance(value["model_lineage"], list) or len(value["model_lineage"]) > 16:
        raise EventValidationError("model_lineage must be an array with at most 16 entries")
    if not isinstance(value["payload"], dict):
        raise EventValidationError("payload must be a JSON object")

    _validate_quality(value["payload"].get("quality"))
    _validate_pose_evidence(value["payload"].get("pose_evidence"))
    requests = value["payload"].get("evidence_requests", [])
    if not isinstance(requests, list) or len(requests) > 16:
        raise EventValidationError("evidence_requests must be an array of at most 16 requests")
    try:
        for request in requests:
            checked = validate_evidence_request(request)
            if checked["session_id"] != value["stream_session_id"]:
                raise ValueError("evidence request session must match event")
    except ValueError as exc:
        raise EventValidationError(str(exc)) from exc

    normalized = dict(value)
    normalized["event_time"] = _timestamp(value["event_time"], "event_time")
    normalized["produced_at"] = _timestamp(value["produced_at"], "produced_at")
    try:
        encoded = json.dumps(normalized, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        payload_bytes = json.dumps(value["payload"], ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EventValidationError("event must contain finite JSON values only") from exc
    if len(payload_bytes) > MAX_PAYLOAD_BYTES:
        raise EventValidationError("payload exceeds 65536 bytes")
    if len(encoded) > MAX_EVENT_BYTES:
        raise EventValidationError("event exceeds 262144 bytes")
    return normalized


def canonical_event_bytes(event: dict[str, Any]) -> bytes:
    """Canonical JSON v1: UTF-8, sorted keys, compact separators, finite numbers."""
    return json.dumps(event, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_event_hash(event: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_event_bytes(event)).hexdigest()
