"""Dataset export and lineage utilities for reviewed events."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any

from apps.server.store import EventStore
from domain.review_contract import review_priority_for

SENSITIVE_KEY_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "credential",
    "api_key",
    "authorization",
)


def redact_sensitive_data(item: Any) -> Any:
    """Recursively strip sensitive authentication, credential, or secret fields."""
    if isinstance(item, dict):
        cleaned: dict[str, Any] = {}
        for key, value in item.items():
            key_lower = str(key).lower()
            if key_lower == "file_path" or any(substring in key_lower for substring in SENSITIVE_KEY_SUBSTRINGS):
                continue
            cleaned[key] = redact_sensitive_data(value)
        return cleaned
    if isinstance(item, list):
        return [redact_sensitive_data(elem) for elem in item]
    if isinstance(item, str):
        if item.startswith("Bearer "):
            return "[REDACTED_BEARER_TOKEN]"
        return item
    return item


def split_dataset(
    records: list[dict[str, Any]],
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    split_by: str = "camera",
) -> list[dict[str, Any]]:
    """Deterministically assign records to train, val, or test split without data leakage."""
    total = train_ratio + val_ratio + test_ratio
    if total <= 0:
        raise ValueError("split ratios must sum to a positive number")

    norm_train = train_ratio / total
    norm_val = (train_ratio + val_ratio) / total

    results: list[dict[str, Any]] = []
    for record in records:
        rec_copy = copy.deepcopy(record)
        if split_by == "camera":
            group_key = str(rec_copy.get("camera_id") or rec_copy.get("device_id") or rec_copy.get("event_id") or "")
        elif split_by == "site_camera_time":
            cam = str(rec_copy.get("camera_id") or rec_copy.get("device_id") or "unknown")
            occurred = str(rec_copy.get("occurred_at") or rec_copy.get("event_time") or "")
            time_window = occurred[:13] if len(occurred) >= 13 else occurred
            group_key = f"{cam}:{time_window}"
        elif split_by == "time":
            occurred = str(rec_copy.get("occurred_at") or rec_copy.get("event_time") or "")
            group_key = occurred[:13] if len(occurred) >= 13 else occurred
        else:
            group_key = str(rec_copy.get("event_id") or "")

        hash_int = int(hashlib.sha256(f"ai_cam_split:{group_key}".encode("utf-8")).hexdigest(), 16)
        hash_ratio = (hash_int % 10000) / 10000.0

        if hash_ratio < norm_train:
            rec_copy["split"] = "train"
        elif hash_ratio < norm_val:
            rec_copy["split"] = "val"
        else:
            rec_copy["split"] = "test"

        results.append(rec_copy)

    return results


def export_dataset_records(
    store: EventStore,
    split: str = "all",
    decision: str = "all",
    include_ambiguous: bool = False,
    split_by: str = "camera",
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    severity: str | None = None,
    taxonomy: str | None = None,
    site_id: str | None = None,
    allowed_sites: tuple[str, ...] | list[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Extract reviewed event records with exact lineage, evidence manifest, and dataset split."""
    query_decision = decision if decision != "all" else None
    items = store.query_reviewed_dataset(decision=query_decision, include_ambiguous=include_ambiguous)

    records: list[dict[str, Any]] = []
    for item in items:
        review = item["review"]
        event = item["event"]
        audits = item.get("audits", [])
        manifests = item.get("manifests", [])

        # Clean evidence manifests: sanitize internal paths and include verification digests
        evidence_summaries: list[dict[str, Any]] = []
        for m in manifests:
            raw_path = m.get("file_path", "")
            sanitized_location = f"evidence/{os.path.basename(raw_path)}" if raw_path else None
            manifest_details = m.get("manifest", {})
            evidence_summaries.append({
                "request_id": m.get("request_id"),
                "manifest_version": m.get("manifest_version", 1),
                "location": sanitized_location,
                "sha256": manifest_details.get("sha256"),
                "size_bytes": manifest_details.get("size_bytes"),
                "actual_range": manifest_details.get("actual_range"),
                "completeness": manifest_details.get("completeness"),
            })

        # Capture original AI payload untouched from the exact reviewed revision
        original_ai_payload = copy.deepcopy(event.get("payload", {}))

        # Determine effective decision label
        raw_decision = review.get("decision")
        if raw_decision == "unreviewed" and review.get("review_version", 0) > 0:
            effective_decision = "reopened"
        else:
            effective_decision = raw_decision

        # Flag ambiguous records (unreviewed, reopened, or content modified requiring re-review)
        is_ambiguous = bool(
            review.get("needs_re_review", False)
            or effective_decision in {"unreviewed", "reopened"}
        )

        device_doc = store.get_device(event["device_id"])
        record_site_id = device_doc.site_id if device_doc else event.get("site_id", "default_site")

        record: dict[str, Any] = {
            "event_id": event["event_id"],
            "device_id": event["device_id"],
            "site_id": record_site_id,
            "camera_id": event.get("camera_id"),
            "occurred_at": event.get("event_time"),
            "taxonomy": event["payload"].get("taxonomy"),
            "severity": event["payload"].get("severity"),
            "review_priority": review_priority_for(event["payload"]),
            "reviewed_decision": effective_decision,
            "review_version": review.get("review_version"),
            "actor": review.get("actor"),
            "reason": review.get("reason"),
            "reviewed_event_revision": review.get("reviewed_event_revision"),
            "reviewed_event_hash": review.get("reviewed_event_hash"),
            "viewed_evidence_versions": review.get("viewed_evidence_versions", {}),
            "evidence_manifests": evidence_summaries,
            "original_ai_payload": original_ai_payload,
            "model_lineage": event.get("model_lineage", []),
            "model_artifact_hash": event.get("model_artifact_hash"),
            "config_version": event.get("config_version"),
            "review_audit_trail": audits,
            "is_ambiguous": is_ambiguous,
        }

        # Redact secrets / tokens before adding to dataset
        clean_record = redact_sensitive_data(record)
        records.append(clean_record)

    # Perform split assignment
    assigned_records = split_dataset(
        records,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        test_ratio=test_ratio,
        split_by=split_by,
    )

    if split != "all":
        assigned_records = [r for r in assigned_records if r.get("split") == split]

    if decision != "all":
        assigned_records = [r for r in assigned_records if r.get("reviewed_decision") == decision]

    if taxonomy is not None:
        assigned_records = [r for r in assigned_records if r.get("taxonomy") == taxonomy]

    if severity is not None:
        assigned_records = [r for r in assigned_records if r.get("severity") == severity]

    if site_id is not None:
        assigned_records = [r for r in assigned_records if r.get("site_id") == site_id]
    elif allowed_sites is not None:
        allowed_set = set(allowed_sites)
        assigned_records = [r for r in assigned_records if r.get("site_id") in allowed_set]

    return assigned_records


def records_to_jsonl(records: list[dict[str, Any]]) -> str:
    """Format records into newline-delimited JSON."""
    if not records:
        return ""
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
