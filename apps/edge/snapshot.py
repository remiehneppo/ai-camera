"""Stateless full-snapshot construction for Suspected incidents (ADR-0005).

Feature modules decide the situation and return ``SnapshotFacts``; the caller supplies the
current runtime ``SnapshotContext`` and the active ``FeatureContext``. This module owns the
event envelope, Evidence request and identity minting. It holds no state and does no I/O:
persistence stays with EvidenceLifecycle/EventOutbox, which receive the returned snapshot.
"""

from collections.abc import Mapping, Sequence
import copy
from datetime import datetime, timezone
import math
from typing import Any, NotRequired, TypedDict
from uuid import uuid4

from domain.event_contract import _FIELDS as _ENVELOPE_FIELDS
from domain.event_contract import SCHEMA_VERSION, validate_event
from domain.evidence_contract import make_evidence_request


class SnapshotFacts(TypedDict):
    """Scenario facts from a feature module; anchor_kind is an evidence-contract anchor kind."""

    anchor_kind: str
    payload: dict[str, Any]


class SnapshotContext(TypedDict):
    """Runtime context of the current frame; quality is already evaluated (scoped or fallback)."""

    camera_id: str
    device_id: str
    stream_session_id: str
    origin: str
    model_lineage: list[dict[str, Any]]
    model_artifact_hash: str
    calibration_version: str
    quality: dict[str, Any]
    capability_scope: NotRequired[dict[str, Any] | None]


class FeatureContext(TypedDict):
    """Producer binding of the active feature."""

    pipeline_id: str
    pipeline_version: str
    config_version: str
    rule_lineage: list[dict[str, Any]]


_FACTS_KEYS = SnapshotFacts.__required_keys__
_CONTEXT_REQUIRED = SnapshotContext.__required_keys__
_CONTEXT_OPTIONAL = SnapshotContext.__optional_keys__
_FEATURE_KEYS = FeatureContext.__required_keys__

# Semantic fields every payload must carry; none is defaulted, so missing input is never masked.
_REQUIRED_PAYLOAD = ("taxonomy", "severity", "confidence", "anchor_time", "detection_time")
# Owned by the snapshot module: facts may not supply or override them.
_RESERVED_PAYLOAD = frozenset({"quality", "evidence_requests", "capability_scope"}) | _ENVELOPE_FIELDS
# Detector provenance comes from the runtime context, never from a feature's rule lineage.
_DETECTOR_ROLES = frozenset({"detector", "person_detector", "vehicle_detector", "crowd_detector"})


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def _exact_keys(value: Mapping[str, Any], name: str, required: frozenset[str],
                optional: frozenset[str] = frozenset()) -> None:
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise ValueError(f"{name} is missing required keys: {', '.join(sorted(map(str, missing)))}")
    if extra:
        raise ValueError(f"{name} has unsupported keys: {', '.join(sorted(map(str, extra)))}")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _lineage(value: Any, name: str) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence of role entries")
    entries = []
    for entry in value:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("role"), str) or not entry["role"]:
            raise ValueError(f"{name} entries must be mappings with a non-empty role")
        entries.append(copy.deepcopy(dict(entry)))
    return entries


def build_incident_snapshot(
    facts: SnapshotFacts | Mapping[str, Any],
    *,
    context: SnapshotContext | Mapping[str, Any],
    feature: FeatureContext | Mapping[str, Any],
) -> dict[str, Any]:
    """Return a new validated revision-1 full snapshot; inputs are neither mutated nor aliased.

    Every call mints new event/message/request identity and UTC times, so the result is not
    idempotent per facts: a retry must resend the persisted snapshot, not call this again.

    Raises ValueError for malformed facts/context/feature or anchors, and EventValidationError
    (a ValueError) when the assembled snapshot violates the event contract. Nothing is stored.
    """
    facts = _mapping(facts, "facts")
    context = _mapping(context, "context")
    feature = _mapping(feature, "feature")
    _exact_keys(facts, "facts", _FACTS_KEYS)
    _exact_keys(context, "context", _CONTEXT_REQUIRED, _CONTEXT_OPTIONAL)
    _exact_keys(feature, "feature", _FEATURE_KEYS)

    payload = _mapping(facts["payload"], "facts.payload")
    missing = [key for key in _REQUIRED_PAYLOAD if key not in payload]
    if missing:
        raise ValueError(f"facts.payload is missing required fields: {', '.join(missing)}")
    reserved = _RESERVED_PAYLOAD.intersection(payload)
    if reserved:
        raise ValueError(f"facts.payload must not supply snapshot-owned fields: {', '.join(sorted(reserved))}")
    for key in ("taxonomy", "severity"):
        if not isinstance(payload[key], str) or not payload[key]:
            raise ValueError(f"facts.payload.{key} must be a non-empty string")
    for key in ("confidence", "anchor_time", "detection_time"):
        if not _finite_number(payload[key]):
            raise ValueError(f"facts.payload.{key} must be a finite number")

    quality = _mapping(context["quality"], "context.quality")
    if not isinstance(quality.get("state"), str) or not quality["state"]:
        raise ValueError("context.quality.state must be a non-empty string")
    scope = context.get("capability_scope")
    if scope is not None:
        _mapping(scope, "context.capability_scope")

    runtime_lineage = _lineage(context["model_lineage"], "context.model_lineage")
    runtime_roles = {entry["role"] for entry in runtime_lineage}
    # Runtime detector/pose provenance wins over conflicting feature lineage roles.
    rule_lineage = [
        entry for entry in _lineage(feature["rule_lineage"], "feature.rule_lineage")
        if entry["role"] not in _DETECTOR_ROLES and entry["role"] not in runtime_roles
    ]

    session_id = context["stream_session_id"]
    request = make_evidence_request(
        request_id=f"req-{uuid4().hex[:12]}",
        session_id=session_id,
        anchor_kind=facts["anchor_kind"],
        anchor_time=payload["anchor_time"],
    )

    snapshot_payload = copy.deepcopy(dict(payload))
    snapshot_payload["quality"] = copy.deepcopy(dict(quality))
    snapshot_payload["evidence_requests"] = [request]
    if scope is not None:
        snapshot_payload["capability_scope"] = copy.deepcopy(dict(scope))

    now_iso = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return validate_event({
        "schema_version": SCHEMA_VERSION,
        "message_id": f"msg-{uuid4().hex[:12]}",
        "event_id": str(uuid4()),
        "revision": 1,
        "device_id": context["device_id"],
        "camera_id": context["camera_id"],
        "stream_session_id": session_id,
        "pipeline_id": feature["pipeline_id"],
        "pipeline_version": feature["pipeline_version"],
        "origin": context["origin"],
        "event_time": now_iso,
        "produced_at": now_iso,
        "config_version": feature["config_version"],
        "model_lineage": runtime_lineage + rule_lineage,
        "model_artifact_hash": context["model_artifact_hash"],
        "calibration_version": context["calibration_version"],
        "quality_state": quality["state"],
        "payload": snapshot_payload,
    })
