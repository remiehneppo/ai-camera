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
