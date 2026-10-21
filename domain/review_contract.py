"""Versioned human review actions independent from AI event snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


class ReviewValidationError(ValueError):
    pass


class ReviewTransitionError(ValueError):
    pass


_ACTIONS = {"confirm", "false_positive", "resolve", "reopen"}
_FIELDS = {
    "action",
    "expected_review_version",
    "viewed_event_revision",
    "viewed_event_hash",
    "viewed_evidence_versions",
    "reason",
}
_HASH = re.compile(r"^[0-9a-f]{64}$")


def validate_review_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewValidationError("review request must be an object")
    missing = _FIELDS - value.keys()
    extra = value.keys() - _FIELDS
    if missing:
        raise ReviewValidationError(f"missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ReviewValidationError(f"unknown fields: {', '.join(sorted(extra))}")
    if not isinstance(value["action"], str) or value["action"] not in _ACTIONS:
        raise ReviewValidationError("action must be confirm, false_positive, resolve, or reopen")
    if type(value["expected_review_version"]) is not int or value["expected_review_version"] < 0:
        raise ReviewValidationError("expected_review_version must be a non-negative integer")
    if type(value["viewed_event_revision"]) is not int or value["viewed_event_revision"] < 1:
        raise ReviewValidationError("viewed_event_revision must be a positive integer")
    if not isinstance(value["viewed_event_hash"], str) or not _HASH.fullmatch(value["viewed_event_hash"]):
        raise ReviewValidationError("viewed_event_hash must be a lowercase SHA-256 hash")
    evidence_versions = value["viewed_evidence_versions"]
    if not isinstance(evidence_versions, dict) or len(evidence_versions) > 64 or any(
        not isinstance(key, str) or not key or len(key) > 128 or type(version) is not int or version < 1
        for key, version in evidence_versions.items()
    ):
        raise ReviewValidationError("viewed_evidence_versions must map evidence IDs to positive versions")
    reason = value["reason"]
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ReviewValidationError("reason must contain 1 to 1000 characters")
    return {
        "action": value["action"],
        "expected_review_version": value["expected_review_version"],
        "viewed_event_revision": value["viewed_event_revision"],
        "viewed_event_hash": value["viewed_event_hash"],
        "viewed_evidence_versions": dict(sorted(evidence_versions.items())),
        "reason": reason.strip(),
    }


def meaningful_content_hash(event: dict[str, Any]) -> str:
    payload = event["payload"]
    content = {
        "taxonomy": payload.get("taxonomy"),
        "severity": payload.get("severity"),
        "evidence_versions": payload.get("evidence_versions", {}),
    }
    encoded = json.dumps(content, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def next_decision(current: str, action: str, needs_re_review: bool = False) -> str:
    if needs_re_review and action != "reopen":
        raise ReviewTransitionError("event needs explicit reopen before a new review")
    if action == "confirm" and current == "unreviewed":
        return "confirmed"
    if action == "false_positive" and current == "unreviewed":
        return "false_positive"
    if action == "resolve" and current == "confirmed":
        return "resolved"
    if action == "reopen" and current != "unreviewed":
        return "unreviewed"
    raise ReviewTransitionError(f"cannot {action} a {current} event")


LOW_PRIORITY_TAXONOMIES = frozenset({"person_on_stationary_vehicle"})
SEVERITY_VALUES = ("low", "medium", "high", "critical")


def review_priority_for(payload: dict[str, Any]) -> str:
    """Return the review-queue priority class for an event payload.

    On-vehicle events lower priority rather than suppress the event, and a low
    severity never becomes an urgent review or notification candidate. An
    explicit high/critical severity still wins: that is the danger override
    (fallen or suddenly stopped vehicle), so an emergency is never hidden.
    """
    severity = payload.get("severity")
    if severity in {"high", "critical"}:
        return "urgent"
    if payload.get("taxonomy") in LOW_PRIORITY_TAXONOMIES or severity == "low":
        return "low"
    return "standard"