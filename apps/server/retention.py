"""Central retention sweep, authorized delete/export, and backup/restore reconciliation (Ticket #43).

Implements Tasks E03 and E02 reconciliation:
- CentralRetentionManager: evaluates retention policy against stored evidence records,
  protects open retrieval commands, pinned/legal-hold clips, and unreviewed high/critical
  events, removes expired media files while preserving immutable manifest receipts, and
  records RBAC-checked audit entries for delete/export operations.
- create_backup_bundle & restore_and_reconcile: snapshots central metadata collections
  and evidence files into an isolated backup bundle with SHA-256 inventory, then restores
  into a separate target environment and reconciles every manifest against its restored
  file on disk without assuming a shared DB/filesystem transaction.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Any, Iterable, Mapping, Optional
from uuid import uuid4

from domain.retention_contract import (
    ACTION_CENTRAL_DELETE,
    ACTION_CENTRAL_EXPORT,
    ACTION_RETENTION_EXPIRE,
    IMMUTABLE_RECEIPT_FIELDS,
    POLICY_VERSION,
    RECONCILE_VERIFIED,
    ROLE_OPERATOR,
    RetentionError,
    RetentionPolicy,
    apply_reconcile_outcome_to_manifest,
    apply_retention_expiry_to_manifest,
    authorize_retention_action,
    build_reconciliation_report,
    classify_manifest_and_file,
    evaluate_retention_candidate,
)

__all__ = [
    "BACKUP_COLLECTIONS",
    "CentralRetentionManager",
    "EventContext",
    "create_backup_bundle",
    "restore_and_reconcile",
]


@dataclass(frozen=True)
class EventContext:
    decision: Optional[str] = None
    severity: Optional[str] = None
    site_id: Optional[str] = None

BACKUP_COLLECTIONS: tuple[str, ...] = (
    "event_revisions",
    "current_events",
    "downstream_outbox",
    "event_reviews",
    "event_review_audit",
    "evidence_manifests",
    "devices",
    "retrieval_commands",
    "retention_audit",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _collection_docs(store_or_db: Any, name: str) -> list[dict[str, Any]]:
    if isinstance(store_or_db, Mapping):
        items = store_or_db.get(name, [])
        return [deepcopy(dict(doc)) for doc in items]
    db = getattr(store_or_db, "database", store_or_db)
    if hasattr(db, "get_collection"):
        coll = db.get_collection(name)
        docs: list[dict[str, Any]] = []
        for doc in coll.find({}):
            cleaned = dict(doc)
            if "_id" in cleaned:
                cleaned["_id"] = str(cleaned["_id"])
            docs.append(cleaned)
        return docs
    return []


def _replace_collection_docs(store_or_db: Any, name: str, docs: list[dict[str, Any]]) -> int:
    if isinstance(store_or_db, dict):
        store_or_db[name] = [deepcopy(dict(doc)) for doc in docs]
        return len(docs)
    db = getattr(store_or_db, "database", store_or_db)
    if hasattr(db, "get_collection"):
        coll = db.get_collection(name)
        coll.delete_many({})
        if docs:
            to_insert = []
            for doc in docs:
                item = deepcopy(dict(doc))
                item.pop("_id", None)
                to_insert.append(item)
            coll.insert_many(to_insert)
        return len(docs)
    raise ValueError(f"unsupported target store for collection {name}")


class CentralRetentionManager:
    """Executes central retention sweeps, authorized delete, and export with audit records."""

    def __init__(
        self,
        store_or_db: Any,
        evidence_dir: str | Path,
        *,
        policy: Optional[RetentionPolicy] = None,
    ) -> None:
        self.store = store_or_db
        self.evidence_dir = Path(evidence_dir).resolve()
        self.policy = policy or RetentionPolicy()

    def _manifests(self) -> list[dict[str, Any]]:
        return _collection_docs(self.store, "evidence_manifests")

    def _save_manifest(self, updated_record: dict[str, Any]) -> None:
        key = (
            updated_record.get("device_id"),
            updated_record.get("event_id"),
            updated_record.get("request_id"),
        )
        if isinstance(self.store, dict):
            records = self.store.setdefault("evidence_manifests", [])
            for idx, existing in enumerate(records):
                if (
                    existing.get("device_id"),
                    existing.get("event_id"),
                    existing.get("request_id"),
                ) == key:
                    records[idx] = deepcopy(updated_record)
                    return
            records.append(deepcopy(updated_record))
            return
        db = getattr(self.store, "database", self.store)
        coll = db.get_collection("evidence_manifests")
        doc = deepcopy(updated_record)
        doc.pop("_id", None)
        coll.replace_one(
            {"device_id": key[0], "event_id": key[1], "request_id": key[2]},
            doc,
            upsert=True,
        )

    def _append_audit(self, audit_dict: dict[str, Any]) -> None:
        if isinstance(self.store, dict):
            self.store.setdefault("retention_audit", []).append(deepcopy(audit_dict))
            return
        db = getattr(self.store, "database", self.store)
        coll = db.get_collection("retention_audit")
        coll.insert_one(deepcopy(audit_dict))

    def audit_log(self) -> list[dict[str, Any]]:
        return _collection_docs(self.store, "retention_audit")

    def _has_open_retrieval(self, device_id: str, event_id: str, request_id: str) -> bool:
        for cmd in _collection_docs(self.store, "retrieval_commands"):
            raw_ev = cmd.get("evidence")
            ev: Mapping[str, Any] = raw_ev if isinstance(raw_ev, Mapping) else {}
            if (
                cmd.get("device_id") == device_id
                and ev.get("event_id") == event_id
                and ev.get("request_id") == request_id
                and cmd.get("status") in {"pending", "claimed"}
            ):
                return True
        return False

    def _event_context(self, device_id: str, event_id: str) -> EventContext:
        severity: Optional[str] = None
        site_id: Optional[str] = None
        for ev in _collection_docs(self.store, "current_events"):
            if ev.get("device_id") == device_id and ev.get("event_id") == event_id:
                raw_snap = ev.get("snapshot")
                snap: Mapping[str, Any] = raw_snap if isinstance(raw_snap, Mapping) else ev
                sev = snap.get("severity")
                if isinstance(sev, str):
                    severity = sev
                st = ev.get("site_id") or snap.get("site_id")
                if isinstance(st, str):
                    site_id = st
                break
        decision: Optional[str] = None
        for rev in _collection_docs(self.store, "event_reviews"):
            if rev.get("device_id") == device_id and rev.get("event_id") == event_id:
                dec = rev.get("decision")
                if isinstance(dec, str):
                    decision = dec
                break
        return EventContext(decision=decision, severity=severity, site_id=site_id)

    def run_retention_sweep(
        self,
        *,
        now: Optional[float] = None,
        actor: str = "system-retention",
        role: str = ROLE_OPERATOR,
    ) -> dict[str, Any]:
        """Evaluate all manifests and expire eligible clips while keeping immutable receipts."""
        stamp = time.time() if now is None else float(now)
        expired_items: list[dict[str, Any]] = []
        kept_items: list[dict[str, Any]] = []
        storage_errors: list[dict[str, Any]] = []

        for record in self._manifests():
            device_id = str(record.get("device_id", ""))
            event_id = str(record.get("event_id", ""))
            request_id = str(record.get("request_id", ""))
            has_open = self._has_open_retrieval(device_id, event_id, request_id)
            ctx = self._event_context(device_id, event_id)

            decision = evaluate_retention_candidate(
                record,
                now=stamp,
                policy=self.policy,
                has_open_retrieval=has_open,
                review_decision=ctx.decision,
                event_severity=ctx.severity,
            )
            if not decision.eligible_for_delete:
                kept_items.append(
                    {
                        "device_id": device_id,
                        "event_id": event_id,
                        "request_id": request_id,
                        "reason": decision.reason,
                    }
                )
                continue

            audit = authorize_retention_action(
                action=ACTION_RETENTION_EXPIRE,
                actor=actor,
                role=role,
                reason="retention_policy_sweep",
                timestamp=stamp,
                device_id=device_id,
                event_id=event_id,
                request_id=request_id,
                site_id=ctx.site_id,
                audit_id="audit-" + uuid4().hex[:12],
            )

            file_path_str = record.get("file_path")
            if isinstance(file_path_str, str) and file_path_str:
                file_path = Path(file_path_str)
                try:
                    if file_path.exists():
                        file_path.unlink()
                except OSError as exc:
                    storage_errors.append(
                        {
                            "device_id": device_id,
                            "event_id": event_id,
                            "request_id": request_id,
                            "error": type(exc).__name__,
                        }
                    )
                    continue

            raw_manifest = record.get("manifest")
            manifest_dict = dict(raw_manifest) if isinstance(raw_manifest, Mapping) else {}
            updated_manifest = apply_retention_expiry_to_manifest(
                manifest_dict,
                expired_at=stamp,
                reason="central_retention_expired",
            )
            updated_record = deepcopy(record)
            updated_record["manifest"] = updated_manifest
            updated_record["status"] = "expired"
            updated_record["expired_at"] = stamp
            self._save_manifest(updated_record)
            self._append_audit(audit.as_dict())
            expired_items.append(
                {
                    "device_id": device_id,
                    "event_id": event_id,
                    "request_id": request_id,
                    "age_seconds": decision.age_seconds,
                }
            )

        return {
            "policy_version": POLICY_VERSION,
            "evaluated_at": stamp,
            "expired_count": len(expired_items),
            "kept_count": len(kept_items),
            "storage_error_count": len(storage_errors),
            "expired": expired_items,
            "kept": kept_items,
            "storage_errors": storage_errors,
        }

    def delete_evidence(
        self,
        device_id: str,
        event_id: str,
        request_id: str,
        *,
        actor: str,
        role: str,
        reason: str,
        allowed_sites: Optional[Iterable[str]] = None,
        now: Optional[float] = None,
    ) -> dict[str, Any]:
        """Authorized administrative deletion of clip bytes while keeping immutable manifest receipt."""
        stamp = time.time() if now is None else float(now)
        ctx = self._event_context(device_id, event_id)
        audit = authorize_retention_action(
            action=ACTION_CENTRAL_DELETE,
            actor=actor,
            role=role,
            reason=reason,
            timestamp=stamp,
            device_id=device_id,
            event_id=event_id,
            request_id=request_id,
            site_id=ctx.site_id,
            allowed_sites=allowed_sites,
            audit_id="audit-" + uuid4().hex[:12],
        )
        target_record: Optional[dict[str, Any]] = None
        for rec in self._manifests():
            if (
                rec.get("device_id") == device_id
                and rec.get("event_id") == event_id
                and rec.get("request_id") == request_id
            ):
                target_record = rec
                break
        if target_record is None:
            raise RetentionError("evidence_not_found", "manifest not found for delete")

        raw_manifest = target_record.get("manifest")
        manifest_dict = dict(raw_manifest) if isinstance(raw_manifest, Mapping) else {}
        if (
            bool(target_record.get("legal_hold"))
            or bool(manifest_dict.get("legal_hold"))
            or bool(target_record.get("pinned"))
            or bool(manifest_dict.get("pinned"))
        ):
            raise RetentionError("pinned_or_legal_hold_protected", "cannot delete evidence under pin or legal hold")
        if self._has_open_retrieval(device_id, event_id, request_id):
            raise RetentionError("open_retrieval_protected", "cannot delete evidence with open retrieval command")

        file_path_str = target_record.get("file_path")
        if isinstance(file_path_str, str) and file_path_str:
            fp = Path(file_path_str)
            if fp.exists():
                fp.unlink()

        updated_manifest = apply_retention_expiry_to_manifest(
            manifest_dict,
            expired_at=stamp,
            reason=f"admin_delete:{reason.strip()}",
        )
        updated_record = deepcopy(target_record)
        updated_record["manifest"] = updated_manifest
        updated_record["status"] = "expired"
        updated_record["expired_at"] = stamp
        self._save_manifest(updated_record)
        self._append_audit(audit.as_dict())
        return {"audit": audit.as_dict(), "manifest": updated_manifest}

    def export_evidence(
        self,
        device_id: str,
        event_id: str,
        request_id: str,
        *,
        actor: str,
        role: str,
        reason: str,
        allowed_sites: Optional[Iterable[str]] = None,
        now: Optional[float] = None,
    ) -> dict[str, Any]:
        """Authorized export of evidence metadata + verified file reference with audit trail."""
        stamp = time.time() if now is None else float(now)
        ctx = self._event_context(device_id, event_id)
        audit = authorize_retention_action(
            action=ACTION_CENTRAL_EXPORT,
            actor=actor,
            role=role,
            reason=reason,
            timestamp=stamp,
            device_id=device_id,
            event_id=event_id,
            request_id=request_id,
            site_id=ctx.site_id,
            allowed_sites=allowed_sites,
            audit_id="audit-" + uuid4().hex[:12],
        )
        target_record: Optional[dict[str, Any]] = None
        for rec in self._manifests():
            if (
                rec.get("device_id") == device_id
                and rec.get("event_id") == event_id
                and rec.get("request_id") == request_id
            ):
                target_record = rec
                break
        if target_record is None:
            raise RetentionError("evidence_not_found", "manifest not found for export")

        self._append_audit(audit.as_dict())
        return {
            "audit": audit.as_dict(),
            "device_id": device_id,
            "event_id": event_id,
            "request_id": request_id,
            "manifest": deepcopy(target_record.get("manifest")),
            "file_path": target_record.get("file_path"),
        }


def create_backup_bundle(
    store_or_db: Any,
    evidence_dir: str | Path,
    backup_dir: str | Path,
    *,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Snapshot central metadata collections and evidence media files into an isolated backup bundle."""
    stamp = time.time() if now is None else float(now)
    src_evidence = Path(evidence_dir).resolve()
    dst_root = Path(backup_dir).resolve()
    dst_db_dir = dst_root / "collections"
    dst_media_dir = dst_root / "evidence"
    dst_db_dir.mkdir(parents=True, exist_ok=True)
    dst_media_dir.mkdir(parents=True, exist_ok=True)

    collection_counts: dict[str, int] = {}
    latest_data_ts = 0.0

    for coll_name in BACKUP_COLLECTIONS:
        docs = _collection_docs(store_or_db, coll_name)
        collection_counts[coll_name] = len(docs)
        for doc in docs:
            for ts_field in ("uploaded_at", "updated_at", "created_at", "timestamp", "issued_at"):
                val = doc.get(ts_field)
                if isinstance(val, (int, float)) and float(val) > latest_data_ts:
                    latest_data_ts = float(val)
        (dst_db_dir / f"{coll_name}.json").write_text(
            json.dumps(docs, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if latest_data_ts == 0.0:
        latest_data_ts = stamp

    copied_files: list[dict[str, Any]] = []
    if src_evidence.exists():
        for item in sorted(src_evidence.rglob("*")):
            if not item.is_file() or item.suffix == ".tmp" or ".tmp" in item.name:
                continue
            rel = item.relative_to(src_evidence)
            target = dst_media_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied_files.append(
                {
                    "relative_path": str(rel),
                    "size_bytes": target.stat().st_size,
                    "sha256": _sha256_file(target),
                }
            )

    manifest = {
        "policy_version": POLICY_VERSION,
        "backup_created_at": stamp,
        "latest_data_timestamp": latest_data_ts,
        "collections": collection_counts,
        "files": copied_files,
    }
    (dst_root / "backup_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def restore_and_reconcile(
    backup_dir: str | Path,
    target_store_or_db: Any,
    target_evidence_dir: str | Path,
    *,
    now: Optional[float] = None,
    copy_files: bool = True,
) -> dict[str, Any]:
    """Restore a backup bundle into an isolated target environment and reconcile DB vs filesystem.

    Handles and classifies verified, pending, missing, corrupt, and orphan artifacts without
    assuming a cross-system transaction, and preserves all immutable manifest receipt fields.
    """
    restore_started = time.time() if now is None else float(now)
    src_root = Path(backup_dir).resolve()
    manifest_path = src_root / "backup_manifest.json"
    if not manifest_path.is_file():
        raise RetentionError("invalid_backup_bundle", "backup_manifest.json is missing")

    backup_meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    src_db_dir = src_root / "collections"
    src_media_dir = src_root / "evidence"
    dst_evidence = Path(target_evidence_dir).resolve()
    dst_evidence.mkdir(parents=True, exist_ok=True)

    # Clean any lingering .tmp scratch files in target environment
    for scratch in list(dst_evidence.rglob("*")):
        if scratch.is_file() and (scratch.suffix == ".tmp" or ".tmp" in scratch.name):
            scratch.unlink(missing_ok=True)

    if copy_files and src_media_dir.exists():
        for item in sorted(src_media_dir.rglob("*")):
            if not item.is_file():
                continue
            rel = item.relative_to(src_media_dir)
            dest = dst_evidence / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    collections_restored: dict[str, int] = {}
    for coll_name in BACKUP_COLLECTIONS:
        coll_file = src_db_dir / f"{coll_name}.json"
        docs = json.loads(coll_file.read_text(encoding="utf-8")) if coll_file.is_file() else []
        collections_restored[coll_name] = _replace_collection_docs(target_store_or_db, coll_name, docs)

    # Reconcile every evidence manifest against target_evidence_dir
    manifest_docs = _collection_docs(target_store_or_db, "evidence_manifests")
    referenced_rel_paths: set[str] = set()
    reconciled_items: list[dict[str, Any]] = []
    updated_manifest_docs: list[dict[str, Any]] = []

    for rec in manifest_docs:
        device_id = str(rec.get("device_id", ""))
        event_id = str(rec.get("event_id", ""))
        request_id = str(rec.get("request_id", ""))
        raw_manifest = rec.get("manifest")
        manifest_inner = dict(raw_manifest) if isinstance(raw_manifest, Mapping) else {}

        # Resolve relative path inside target_evidence_dir
        rel_path_str = rec.get("relative_path")
        if not isinstance(rel_path_str, str) or not rel_path_str:
            orig_fp = rec.get("file_path")
            if isinstance(orig_fp, str) and orig_fp:
                p = Path(orig_fp)
                rel_path_str = f"{device_id}/{event_id}/{p.name}"
            else:
                rel_path_str = f"{device_id}/{event_id}/{request_id}.mkv"

        target_file = (dst_evidence / rel_path_str).resolve()
        try:
            rel_norm = str(target_file.relative_to(dst_evidence))
            referenced_rel_paths.add(rel_norm)
        except ValueError:
            rel_norm = rel_path_str

        exists = target_file.is_file()
        actual_size: Optional[int] = None
        actual_sha: Optional[str] = None
        if exists:
            actual_size = target_file.stat().st_size
            actual_sha = _sha256_file(target_file)

        state = classify_manifest_and_file(
            rec,
            file_exists=exists,
            actual_size_bytes=actual_size,
            actual_sha256=actual_sha,
        )
        reconciled_manifest = apply_reconcile_outcome_to_manifest(
            manifest_inner,
            state,
            reconciled_at=restore_started,
        )
        new_rec = deepcopy(rec)
        new_rec["manifest"] = reconciled_manifest
        new_rec["file_path"] = str(target_file) if state != "pending" else rec.get("file_path")
        new_rec["reconcile_state"] = state
        updated_manifest_docs.append(new_rec)

        # Verify immutable receipt fields were preserved intact
        for field_name in IMMUTABLE_RECEIPT_FIELDS:
            if field_name in manifest_inner:
                assert reconciled_manifest.get(field_name) == manifest_inner[field_name]

        reconciled_items.append(
            {
                "device_id": device_id,
                "event_id": event_id,
                "request_id": request_id,
                "state": state,
                "relative_path": rel_norm,
                "sha256": manifest_inner.get("sha256"),
                "size_bytes": manifest_inner.get("size_bytes"),
            }
        )

    _replace_collection_docs(target_store_or_db, "evidence_manifests", updated_manifest_docs)

    # Detect orphan files on disk that have no manifest in DB
    orphan_files: list[str] = []
    for disk_file in sorted(dst_evidence.rglob("*")):
        if not disk_file.is_file():
            continue
        rel_disk = str(disk_file.relative_to(dst_evidence))
        if rel_disk not in referenced_rel_paths:
            orphan_files.append(rel_disk)

    restore_completed = time.time() if now is None else float(now) + 0.05
    return build_reconciliation_report(
        items=reconciled_items,
        orphan_files=orphan_files,
        backup_created_at=float(backup_meta.get("backup_created_at", restore_started)),
        latest_data_timestamp=float(backup_meta.get("latest_data_timestamp", restore_started)),
        restore_started_at=restore_started,
        restore_completed_at=restore_completed,
        collections_restored=collections_restored,
    )
