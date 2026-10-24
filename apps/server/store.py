"""MongoDB transaction boundary for event snapshots and disabled outbox intent."""

from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from bson import ObjectId
from pymongo import MongoClient, ReadPreference
from pymongo.errors import AutoReconnect, DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from domain.event_contract import canonical_event_hash, validate_revision_identity
from domain.device_contract import (
    DeviceLifecycleError,
    DeviceRecord,
    STATUS_ACTIVE,
    STATUS_ENROLLED,
    STATUS_QUARANTINED,
    STATUS_REVOKED,
    quarantine_device,
    reactivate_device,
    revoke_device,
    transition_device,
)
from domain.retrieval_contract import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_OFFLINE_AFTER_SECONDS,
    STATUS_CLAIMED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    EvidenceRef,
    RetrievalCommand,
    RetrievalState,
    acknowledge,
    claim,
    issue_command,
    requester_status,
    settle_target,
)
from domain.review_contract import (
    LOW_PRIORITY_TAXONOMIES,
    SEVERITY_VALUES,
    ReviewTransitionError,
    meaningful_content_hash,
    next_decision,
    review_priority_for,
    validate_review_request,
)


class EventHashConflict(Exception):
    pass


class EventIdentityConflict(Exception):
    pass


class ReviewConflict(Exception):
    pass


class ReviewNotFound(Exception):
    pass



def cleanup_temp_evidence(evidence_dir: str | Path) -> list[str]:
    cleaned: list[str] = []
    base = Path(evidence_dir)
    if not base.exists():
        return cleaned
    for item in list(base.rglob("*")):
        if item.is_file() and (".tmp" in item.name or item.suffix == ".tmp"):
            try:
                item.unlink(missing_ok=True)
                cleaned.append(str(item))
            except OSError:
                pass
    return cleaned


class PaginatedEvents(list):
    def __init__(self, items: list[dict[str, Any]], next_cursor: str | None = None) -> None:
        super().__init__(items)
        self.next_cursor = next_cursor


def encode_cursor(updated_at: str, doc_id: Any) -> str:
    raw = json.dumps({"u": updated_at, "i": str(doc_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor_str: str) -> tuple[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
        u = data["u"]
        i_str = data["i"]
        if not isinstance(u, str) or not isinstance(i_str, str):
            raise ValueError
        try:
            doc_id = ObjectId(i_str)
        except Exception:
            doc_id = i_str
        return u, doc_id
    except Exception as exc:
        raise ValueError(f"invalid cursor: {cursor_str}") from exc


class EventStore:
    def __init__(self, uri: str, database_name: str) -> None:
        if "replicaSet=" not in uri:
            raise ValueError("MONGO_URI must name the lab replica set")
        self.client: MongoClient[Any] = MongoClient(uri, serverSelectionTimeoutMS=5000, retryWrites=True)
        self.database = self.client[database_name]
        self.revisions = self.database.get_collection("event_revisions")
        self.current = self.database.get_collection("current_events")
        self.outbox = self.database.get_collection("downstream_outbox")
        self.reviews = self.database.get_collection("event_reviews")
        self.review_audit = self.database.get_collection("event_review_audit")
        self.evidence_manifests = self.database.get_collection("evidence_manifests")
        self.devices = self.database.get_collection("devices")
        self.retrieval_commands = self.database.get_collection("retrieval_commands")
        self.device_activity = self.database.get_collection("device_activity")

    def ensure_ready(self) -> None:
        for attempt in range(3):
            try:
                self.client.admin.command("ping")
                self.revisions.create_index(
                    [("device_id", 1), ("event_id", 1), ("revision", 1)], unique=True, name="event_revision_identity"
                )
                self.current.create_index([("device_id", 1), ("event_id", 1)], unique=True, name="current_event_identity")
                self.current.create_index([("updated_at", -1), ("_id", -1)], name="current_event_cursor")
                self.outbox.create_index(
                    [("device_id", 1), ("event_id", 1), ("revision", 1)], unique=True, name="downstream_intent_identity"
                )
                self.reviews.create_index([("device_id", 1), ("event_id", 1)], unique=True, name="event_review_identity")
                self.review_audit.create_index(
                    [("device_id", 1), ("event_id", 1), ("review_version", 1)], unique=True, name="event_review_version"
                )
                self.evidence_manifests.create_index(
                    [("device_id", 1), ("event_id", 1), ("request_id", 1)], unique=True, name="evidence_manifest_identity"
                )
                self.devices.create_index(
                    [("device_id", 1)], unique=True, name="device_identity"
                )
                self.retrieval_commands.create_index(
                    [("command_id", 1)], unique=True, name="retrieval_command_identity"
                )
                self.retrieval_commands.create_index(
                    [("device_id", 1), ("status", 1), ("issued_at", 1)], name="retrieval_command_poll"
                )
                with self.client.start_session() as session:
                    def probe(active: Any) -> None:
                        probes = self.database.get_collection("readiness_probes")
                        probe_id = str(uuid4())
                        probes.insert_one({"_id": probe_id, "created_at": datetime.now(timezone.utc)}, session=active)
                        probes.delete_one({"_id": probe_id}, session=active)

                    session.with_transaction(
                        probe,
                        read_concern=ReadConcern("snapshot"),
                        write_concern=WriteConcern(w="majority", j=True),
                        read_preference=ReadPreference.PRIMARY,
                    )
                break
            except AutoReconnect:
                if attempt == 2:
                    raise
                time.sleep(0.1)

    @staticmethod
    def _key(event: dict[str, Any]) -> dict[str, Any]:
        return {"device_id": event["device_id"], "event_id": event["event_id"], "revision": event["revision"]}

    def persist(self, event: dict[str, Any]) -> dict[str, Any]:
        key = self._key(event)
        event_hash = canonical_event_hash(event)
        accepted_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        receipt = {
            **key,
            "message_id": event["message_id"],
            "event_hash": event_hash,
            "accepted": True,
            "accepted_at": accepted_at,
            "canonicalization": "canonical-json-python-v1",
        }

        def commit(session: Any) -> dict[str, Any]:
            existing = self.revisions.find_one(key, session=session)
            if existing:
                if existing["event_hash"] != event_hash:
                    raise EventHashConflict("event revision already exists with different content")
                return existing["receipt"]

            current = self.current.find_one({"device_id": event["device_id"], "event_id": event["event_id"]}, session=session)
            first = self.revisions.find_one(
                {"device_id": event["device_id"], "event_id": event["event_id"]},
                sort=[("revision", 1)],
                session=session,
            )
            if first:
                try:
                    validate_revision_identity(first["event"], event)
                except ValueError as exc:
                    raise EventIdentityConflict(str(exc)) from exc
            self.revisions.insert_one({**key, "event": event, "event_hash": event_hash, "receipt": receipt}, session=session)
            if current is None or event["revision"] > current["revision"]:
                self.current.replace_one(
                    {"device_id": event["device_id"], "event_id": event["event_id"]},
                    {
                        **key,
                        "event": event,
                        "event_hash": event_hash,
                        "updated_at": accepted_at,
                        "review_guard": 1 if current is None else current.get("review_guard", 0) + 1,
                    },
                    upsert=True,
                    session=session,
                )
                if current is not None and meaningful_content_hash(current["event"]) != meaningful_content_hash(event):
                    review = self.reviews.find_one({"device_id": event["device_id"], "event_id": event["event_id"]}, session=session)
                    if review and review["decision"] != "unreviewed":
                        review["needs_re_review"] = True
                        review["re_review_reasons"] = sorted({*review.get("re_review_reasons", []), "event_content_changed"})
                        self.reviews.replace_one(
                            {"device_id": event["device_id"], "event_id": event["event_id"]}, review, session=session
                        )
            reason = "synthetic_or_replay_origin" if event["origin"] in {"synthetic", "replay"} else "lab_notifications_disabled"
            payload = event["payload"]
            self.outbox.insert_one(
                {
                    **key,
                    "message_id": event["message_id"],
                    "event_hash": event_hash,
                    "origin": event["origin"],
                    "taxonomy": payload.get("taxonomy"),
                    "severity": payload.get("severity"),
                    "review_priority": review_priority_for(payload),
                    "policy_version": "lab-disabled-v1",
                    "eligibility": "ineligible",
                    "reason": reason,
                    "created_at": accepted_at,
                },
                session=session,
            )
            return receipt

        with self.client.start_session() as session:
            try:
                return session.with_transaction(
                    commit,
                    read_concern=ReadConcern("snapshot"),
                    write_concern=WriteConcern(w="majority", j=True),
                    read_preference=ReadPreference.PRIMARY,
                )
            except DuplicateKeyError:
                existing = self.revisions.find_one(key)
                if existing and existing["event_hash"] == event_hash:
                    return existing["receipt"]
                if existing:
                    raise EventHashConflict("event revision already exists with different content")
                raise

    def list_current(
        self,
        limit: int,
        cursor: str | None = None,
        severity: str | None = None,
        taxonomy: str | None = None,
    ) -> PaginatedEvents:
        query: dict[str, Any] = {}
        if severity is not None:
            query["event.payload.severity"] = severity
        if taxonomy is not None:
            query["event.payload.taxonomy"] = taxonomy
        if cursor:
            cursor_updated_at, cursor_id = decode_cursor(cursor)
            query["$or"] = [
                {"updated_at": {"$lt": cursor_updated_at}},
                {"updated_at": cursor_updated_at, "_id": {"$lt": cursor_id}},
            ]

        mongo_cursor = (
            self.current.find(query, {"_id": 1, "event": 1, "event_hash": 1, "updated_at": 1})
            .sort([("updated_at", -1), ("_id", -1)])
            .limit(limit + 1)
        )
        raw_rows = list(mongo_cursor)
        has_next = len(raw_rows) > limit
        rows = raw_rows[:limit]
        next_cursor: str | None = None
        if has_next and rows:
            last = rows[-1]
            next_cursor = encode_cursor(last["updated_at"], last["_id"])

        for row in rows:
            row.pop("_id", None)

        if not rows:
            return PaginatedEvents([], next_cursor=None)
        keys = [{"device_id": row["event"]["device_id"], "event_id": row["event"]["event_id"]} for row in rows]
        selector = {"$or": keys}
        states = {
            (state["device_id"], state["event_id"]): state
            for state in self.reviews.find(selector, {"_id": 0})
        }
        audits: dict[tuple[str, str], list[dict[str, Any]]] = {}
        pipeline: list[dict[str, Any]] = [
            {"$match": selector},
            {
                "$setWindowFields": {
                    "partitionBy": {"device_id": "$device_id", "event_id": "$event_id"},
                    "sortBy": {"review_version": -1},
                    "output": {"rank": {"$documentNumber": {}}},
                }
            },
            {"$match": {"rank": {"$lte": 20}}},
            {"$sort": {"device_id": 1, "event_id": 1, "review_version": -1}},
            {"$project": {"_id": 0, "rank": 0}},
        ]
        for audit in self.review_audit.aggregate(pipeline):
            key = (audit["device_id"], audit["event_id"])
            audits.setdefault(key, []).append(audit)
        evidences: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in self.evidence_manifests.find(selector, {"_id": 0}):
            evidences.setdefault((item["device_id"], item["event_id"]), []).append(item)
        for row in rows:
            event = row["event"]
            key = (event["device_id"], event["event_id"])
            row["taxonomy"] = event["payload"].get("taxonomy")
            row["severity"] = event["payload"].get("severity")
            row["review_priority"] = review_priority_for(event["payload"])
            row["review"] = states.get(key, {
                "device_id": key[0],
                "event_id": key[1],
                "review_version": 0,
                "decision": "unreviewed",
                "needs_re_review": False,
                "reviewed_event_revision": None,
                "reviewed_event_hash": None,
                "viewed_evidence_versions": {},
            })
            row["review"]["audit"] = audits.get(key, [])
            row["evidence"] = evidences.get(key, [])
            row["evidence_versions"] = {
                **event["payload"].get("evidence_versions", {}),
                **{item["request_id"]: item.get("manifest_version", 1) for item in row["evidence"]},
            }
        return PaginatedEvents(rows, next_cursor=next_cursor)

    def record_review(self, key: dict[str, str], request: dict[str, Any], actor: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

        def commit(session: Any) -> dict[str, Any]:
            current = self.current.find_one(key, session=session)
            if current is None:
                raise ReviewNotFound("event not found")
            self.current.update_one(key, {"$inc": {"review_guard": 1}}, session=session)
            state = self.reviews.find_one(key, session=session) or {
                **key,
                "review_version": 0,
                "decision": "unreviewed",
                "needs_re_review": False,
            }
            state.pop("_id", None)
            if state["review_version"] != request["expected_review_version"]:
                raise ReviewConflict("review version changed; refetch before reviewing")
            viewed = self.revisions.find_one(
                {**key, "revision": request["viewed_event_revision"]}, {"event": 1, "event_hash": 1}, session=session
            )
            if viewed is None or viewed["event_hash"] != request["viewed_event_hash"]:
                raise ReviewConflict("viewed event revision is unavailable or changed")
            current_event = current["event"]
            viewed_event = viewed["event"]
            if meaningful_content_hash(viewed_event) != meaningful_content_hash(current_event):
                raise ReviewConflict("event content changed; refetch before reviewing")
            manifests = list(self.evidence_manifests.find(key, {"_id": 0}, session=session))
            expected_evidence = {
                **current_event["payload"].get("evidence_versions", {}),
                **{item["request_id"]: item.get("manifest_version", 1) for item in manifests},
            }
            if request["viewed_evidence_versions"] != expected_evidence:
                raise ReviewConflict("evidence version changed; refetch before reviewing")
            try:
                decision = next_decision(state["decision"], request["action"], state.get("needs_re_review", False))
            except ReviewTransitionError as exc:
                raise ReviewConflict(str(exc)) from exc
            version = state["review_version"] + 1
            updated = {
                **state,
                "review_version": version,
                "decision": decision,
                "needs_re_review": False,
                "re_review_reasons": [],
                "actor": actor,
                "reason": request["reason"],
                "reviewed_event_revision": request["viewed_event_revision"],
                "reviewed_event_hash": request["viewed_event_hash"],
                "viewed_evidence_versions": request["viewed_evidence_versions"],
                "reviewed_evidence_manifests": deepcopy(manifests),
                "reviewed_taxonomy": viewed_event["payload"].get("taxonomy"),
                "reviewed_severity": viewed_event["payload"].get("severity"),
                "reviewed_review_priority": review_priority_for(viewed_event["payload"]),
                "updated_at": now,
            }
            updated.pop("audit", None)
            audit = {
                **key,
                "review_version": version,
                "action": request["action"],
                "decision": decision,
                "actor": actor,
                "reason": request["reason"],
                "viewed_event_revision": request["viewed_event_revision"],
                "viewed_event_hash": request["viewed_event_hash"],
                "viewed_evidence_versions": request["viewed_evidence_versions"],
                "reviewed_evidence_manifests": deepcopy(manifests),
                "reviewed_taxonomy": viewed_event["payload"].get("taxonomy"),
                "reviewed_severity": viewed_event["payload"].get("severity"),
                "reviewed_review_priority": review_priority_for(viewed_event["payload"]),
                "created_at": now,
            }
            self.reviews.replace_one(key, updated, upsert=True, session=session)
            self.review_audit.insert_one(audit, session=session)
            updated.pop("_id", None)
            audit.pop("_id", None)
            return {**updated, "audit": [audit]}

        with self.client.start_session() as session:
            return session.with_transaction(
                commit,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern(w="majority", j=True),
                read_preference=ReadPreference.PRIMARY,
            )

    def evidence_request(self, device_id: str, event_id: str, request_id: str,
                         metadata: dict[str, Any]) -> dict[str, Any]:
        selector: dict[str, Any] = {
            "device_id": device_id, "event_id": event_id,
            "event.payload.evidence_requests.request_id": request_id,
        }
        owner = metadata.get("owner")
        if owner is not None:
            prefix = f"{device_id}/{event_id}/"
            if not isinstance(owner, str) or not owner.startswith(prefix) or not owner[len(prefix):].isdigit():
                raise ValueError("evidence owner does not match event")
            selector["revision"] = int(owner[len(prefix):])
        row = self.revisions.find_one(selector, sort=[("revision", 1)])
        if row is None:
            raise ReviewNotFound("declared event evidence request not found")
        declared = next(item for item in row["event"]["payload"]["evidence_requests"]
                        if item["request_id"] == request_id)
        for name, value in declared.items():
            if name in metadata and metadata[name] != value:
                raise ValueError(f"evidence {name} does not match declared request")
        return {**declared, "owner": f"{device_id}/{event_id}/{row['revision']}"}

    def record_evidence(
        self, device_id: str, event_id: str, request_id: str, manifest_data: dict[str, Any], file_path: str
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        key = {"device_id": device_id, "event_id": event_id, "request_id": request_id}
        doc: dict[str, Any] = {
            "device_id": device_id,
            "event_id": event_id,
            "request_id": request_id,
            "manifest": manifest_data,
            "file_path": file_path,
            "stored_at": now,
        }

        def commit(session: Any) -> dict[str, Any]:
            existing = self.evidence_manifests.find_one(key, {"_id": 0}, session=session)
            if existing:
                for field in ("sha256", "size_bytes"):
                    if existing["manifest"].get(field) != manifest_data.get(field):
                        raise EventHashConflict("finalized evidence bytes are immutable")
                for field in ("session_id", "owner", "requested_start", "requested_end",
                              "evidence_anchor_kind", "evidence_anchor_time", "mapping_uncertainty",
                              "policy_version", "supersedes_request_id"):
                    if field in existing["manifest"] and existing["manifest"][field] != manifest_data.get(field):
                        raise EventHashConflict("evidence request identity and interval are immutable")
                if existing["manifest"] == manifest_data and existing["file_path"] == file_path:
                    return existing
            doc["manifest_version"] = existing.get("manifest_version", 1) + 1 if existing else 1
            event_key = {"device_id": device_id, "event_id": event_id}
            # Review, event updates and evidence publication share a transaction write guard.
            self.current.update_one(event_key, {"$inc": {"review_guard": 1}}, session=session)
            self.evidence_manifests.replace_one(key, doc, upsert=True, session=session)
            review = self.reviews.find_one({"device_id": device_id, "event_id": event_id}, session=session)
            meaningful = ("completeness", "actual_range", "actual_ranges", "file_status")
            changed = existing is None or any(existing["manifest"].get(k) != manifest_data.get(k) for k in meaningful)
            if review and review.get("decision") != "unreviewed" and changed:
                review["needs_re_review"] = True
                review["re_review_reasons"] = sorted({*review.get("re_review_reasons", []), "evidence_changed"})
                self.reviews.replace_one(
                    {"device_id": device_id, "event_id": event_id}, review, session=session
                )
            result = dict(doc)
            result.pop("_id", None)
            return result

        with self.client.start_session() as session:
            return session.with_transaction(
                commit,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern(w="majority", j=True),
                read_preference=ReadPreference.PRIMARY,
            )

    def get_evidence(
        self,
        device_id: str,
        event_id: str,
        request_id: str,
        *,
        verify_file: bool = False,
    ) -> dict[str, Any] | None:
        doc = self.evidence_manifests.find_one(
            {"device_id": device_id, "event_id": event_id, "request_id": request_id},
            {"_id": 0},
        )
        if not doc or not verify_file:
            return doc

        file_path_val = doc.get("file_path")
        file_path = Path(file_path_val) if file_path_val else None
        manifest = doc.get("manifest")
        if not isinstance(manifest, dict):
            return doc

        if not file_path or not file_path.is_file():
            manifest["completeness"] = "missing"
            manifest["file_status"] = "missing"
            return self.record_evidence(device_id, event_id, request_id, manifest, doc["file_path"])

        expected_size = manifest.get("size_bytes")
        expected_sha256 = manifest.get("sha256")
        actual_size = file_path.stat().st_size

        if expected_size is not None and actual_size != int(expected_size):
            manifest["completeness"] = "corrupt"
            manifest["file_status"] = "corrupt"
            return self.record_evidence(device_id, event_id, request_id, manifest, doc["file_path"])

        if expected_sha256:
            with open(file_path, "rb") as stream:
                actual_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual_sha256 != str(expected_sha256).lower():
                manifest["completeness"] = "corrupt"
                manifest["file_status"] = "corrupt"
                return self.record_evidence(device_id, event_id, request_id, manifest, doc["file_path"])

        return doc

    def query_reviewed_dataset(
        self,
        decision: str | None = None,
        include_ambiguous: bool = False,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"review_version": {"$gt": 0}}
        if not include_ambiguous:
            query["needs_re_review"] = False
            query["decision"] = {"$nin": ["unreviewed"]}
            if decision and decision != "all":
                query["decision"] = decision
        else:
            if decision and decision != "all":
                if decision == "reopened":
                    query["decision"] = "unreviewed"
                else:
                    query["decision"] = decision

        reviews = list(self.reviews.find(query, {"_id": 0}))
        results: list[dict[str, Any]] = []

        for review in reviews:
            device_id = review["device_id"]
            event_id = review["event_id"]
            reviewed_rev = review.get("reviewed_event_revision")
            reviewed_hash = review.get("reviewed_event_hash")

            rev_doc = self.revisions.find_one(
                {"device_id": device_id, "event_id": event_id, "revision": reviewed_rev},
                {"_id": 0},
            )
            if not rev_doc:
                continue

            # Verify reviewed event hash matches revision event hash
            if rev_doc.get("event_hash") != reviewed_hash:
                continue

            event = rev_doc["event"]
            audits = list(
                self.review_audit.find(
                    {"device_id": device_id, "event_id": event_id},
                    {"_id": 0},
                ).sort("review_version", 1)
            )

            manifests = review.get("reviewed_evidence_manifests")
            if manifests is None:
                # Legacy reviews have no snapshot: include only exactly matching stored versions.
                viewed_versions = review.get("viewed_evidence_versions", {})
                manifests = [item for item in self.evidence_manifests.find(
                    {"device_id": device_id, "event_id": event_id}, {"_id": 0})
                    if viewed_versions.get(item["request_id"]) == item.get("manifest_version", 1)]
                if set(viewed_versions) != {item["request_id"] for item in manifests}:
                    if not include_ambiguous:
                        continue
                    review = {**review, "needs_re_review": True}

            results.append({
                "review": review,
                "event": event,
                "event_hash": rev_doc["event_hash"],
                "audits": audits,
                "manifests": manifests,
            })

        return results

    # ---- Device lifecycle management (Ticket #33) -------------------------

    def get_device(self, device_id: str) -> DeviceRecord | None:
        doc = self.devices.find_one({"device_id": device_id}, {"_id": 0})
        if not doc:
            return None
        return DeviceRecord.from_dict(doc)

    def enroll_device(
        self,
        device_id: str,
        site_id: str,
        allowed_cameras: list[str] | tuple[str, ...] | None = None,
    ) -> DeviceRecord:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_device(device_id)
        if existing:
            return existing
        record = DeviceRecord(
            device_id=device_id,
            site_id=site_id,
            status=STATUS_ACTIVE,
            enrolled_at=now,
            updated_at=now,
            allowed_cameras=tuple(allowed_cameras or ()),
        )
        self.devices.replace_one({"device_id": device_id}, record.to_dict(), upsert=True)
        return record

    def quarantine_device(self, device_id: str, reason: str) -> DeviceRecord:
        record = self.get_device(device_id)
        if not record:
            raise ReviewNotFound(f"device {device_id!r} not found")
        updated = quarantine_device(record, reason=reason)
        self.devices.replace_one({"device_id": device_id}, updated.to_dict(), upsert=True)
        return updated

    def reactivate_device(self, device_id: str, reason: str | None = None) -> DeviceRecord:
        record = self.get_device(device_id)
        if not record:
            raise ReviewNotFound(f"device {device_id!r} not found")
        updated = reactivate_device(record, reason=reason)
        self.devices.replace_one({"device_id": device_id}, updated.to_dict(), upsert=True)
        return updated

    def revoke_device(self, device_id: str, reason: str) -> DeviceRecord:
        record = self.get_device(device_id)
        if not record:
            raise ReviewNotFound(f"device {device_id!r} not found")
        updated = revoke_device(record, reason=reason)
        self.devices.replace_one({"device_id": device_id}, updated.to_dict(), upsert=True)
        return updated

    def rotate_device_token(
        self, device_id: str, *, new_site_id: str | None = None, reason: str | None = None
    ) -> DeviceRecord:
        record = self.get_device(device_id)
        if not record:
            raise ReviewNotFound(f"device {device_id!r} not found")
        if record.is_revoked:
            raise DeviceLifecycleError("revoked_device_is_terminal", f"device {device_id!r} is revoked")
        now = datetime.now(timezone.utc).isoformat()
        updated_dict = record.to_dict()
        updated_dict["updated_at"] = now
        if new_site_id is not None:
            updated_dict["site_id"] = new_site_id
        updated = DeviceRecord.from_dict(updated_dict)
        self.devices.replace_one({"device_id": device_id}, updated.to_dict(), upsert=True)
        return updated

    # ---- Retained-evidence retrieval commands (Ticket #32) -----------------

    @staticmethod
    def retrieval_state(doc: dict[str, Any]) -> RetrievalState:
        """Rebuild the pure contract state from a stored command document."""
        command = RetrievalCommand(
            command_id=doc["command_id"],
            device_id=doc["device_id"],
            target=doc["target"],
            action=doc["action"],
            evidence=EvidenceRef(**doc["evidence"]),
            issued_by=doc["issued_by"],
            issued_at=doc["issued_at"],
            expires_at=doc["expires_at"],
            retention_scope=doc["retention_scope"],
        )
        return RetrievalState(
            command=command,
            status=doc["status"],
            lease_id=doc.get("lease_id"),
            claimed_at=doc.get("claimed_at"),
            attempts=doc.get("attempts", 0),
            metadata_acknowledged=doc.get("metadata_acknowledged", False),
            artifact=doc.get("artifact"),
            reason=doc.get("reason"),
        )

    @staticmethod
    def _retrieval_doc(state: RetrievalState, base: dict[str, Any] | None = None) -> dict[str, Any]:
        doc = dict(base or {})
        doc.update(
            {
                "command_id": state.command.command_id,
                "device_id": state.command.device_id,
                "target": state.command.target,
                "action": state.command.action,
                "evidence": state.command.evidence.as_dict(),
                "issued_by": state.command.issued_by,
                "issued_at": state.command.issued_at,
                "expires_at": state.command.expires_at,
                "retention_scope": state.command.retention_scope,
                "status": state.status,
                "lease_id": state.lease_id,
                "claimed_at": state.claimed_at,
                "attempts": state.attempts,
                "metadata_acknowledged": state.metadata_acknowledged,
                "artifact": dict(state.artifact) if state.artifact is not None else None,
                "reason": state.reason,
            }
        )
        return doc

    def touch_device_activity(self, device_id: str, *, now: float | None = None) -> float:
        now = time.time() if now is None else float(now)
        self.device_activity.update_one(
            {"_id": device_id},
            {"$set": {"last_seen": now}, "$setOnInsert": {"device_id": device_id}},
            upsert=True,
        )
        return now

    def device_last_seen(self, device_id: str) -> float | None:
        doc = self.device_activity.find_one({"_id": device_id}, {"last_seen": 1})
        if not doc or "last_seen" not in doc:
            return None
        return float(doc["last_seen"])

    def issue_retrieval(
        self,
        device_id: str,
        event_id: str,
        request_id: str,
        *,
        target: str,
        issued_by: str,
        ttl_seconds: float = 300.0,
        retention_scope: str = "clip",
        now: float | None = None,
    ) -> dict[str, Any]:
        """Issue one retrieval command for retained evidence an owner already asked for.

        Re-issuing the same target for the same evidence while it is still open returns the
        live command instead of piling up duplicates.
        """
        now = time.time() if now is None else float(now)
        if self.get_evidence(device_id, event_id, request_id) is None:
            raise ReviewNotFound("retained evidence not found for device/event/request")
        existing = self.retrieval_commands.find_one(
            {
                "device_id": device_id,
                "target": target,
                "evidence.event_id": event_id,
                "evidence.request_id": request_id,
                "status": {"$in": [STATUS_PENDING, STATUS_CLAIMED]},
            },
            {"_id": 0},
        )
        if existing is not None:
            return existing
        state = issue_command(
            command_id="cmd-" + uuid4().hex,
            device_id=device_id,
            target=target,
            evidence=EvidenceRef(device_id=device_id, event_id=event_id, request_id=request_id),
            issued_by=issued_by,
            issued_at=now,
            ttl_seconds=ttl_seconds,
            retention_scope=retention_scope,
        )
        doc = self._retrieval_doc(state, {"created_at": now})
        self.retrieval_commands.replace_one({"command_id": doc["command_id"]}, doc, upsert=True)
        doc.pop("_id", None)
        return doc

    def claim_retrieval(
        self, device_id: str, *, now: float | None = None, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> dict[str, Any] | None:
        """Atomically lease the oldest open command for this device; None when there is none.

        The compare-and-set keeps two concurrent polls from both creating a fresh attempt:
        the loser re-reads and returns the same lease.
        """
        now = self.touch_device_activity(device_id, now=now)
        for _ in range(5):
            doc = self.retrieval_commands.find_one(
                {
                    "device_id": device_id,
                    # A device only executes edge targets; a server target is settled by the server.
                    "target": "edge",
                    "status": {"$in": [STATUS_PENDING, STATUS_CLAIMED]},
                },
                sort=[("issued_at", 1)],
            )
            if doc is None:
                return None
            claimed = claim(self.retrieval_state(doc), now=now, lease_seconds=lease_seconds)
            new_doc = self._retrieval_doc(claimed, doc)
            result = self.retrieval_commands.replace_one(
                {"_id": doc["_id"], "status": doc["status"], "lease_id": doc.get("lease_id")}, new_doc
            )
            if result.matched_count != 1:
                continue
            if claimed.status == STATUS_EXPIRED:
                continue
            new_doc.pop("_id", None)
            return new_doc
        return None

    def acknowledge_retrieval(
        self,
        command_id: str,
        device_id: str,
        *,
        lease_id: str | None,
        ack: dict[str, Any],
        now: float | None = None,
    ) -> dict[str, Any]:
        now = self.touch_device_activity(device_id, now=now)
        doc = self.retrieval_commands.find_one({"command_id": command_id})
        if doc is None or doc["device_id"] != device_id:
            raise ReviewNotFound("retrieval command not found for this device")
        state = acknowledge(self.retrieval_state(doc), now=now, lease_id=lease_id, ack=ack)
        new_doc = self._retrieval_doc(state, doc)
        if new_doc == doc:
            doc.pop("_id", None)
            return doc
        result = self.retrieval_commands.replace_one(
            {"_id": doc["_id"], "status": doc["status"], "lease_id": doc.get("lease_id")}, new_doc
        )
        if result.matched_count != 1:
            raise ReviewConflict("retrieval command changed concurrently; retry with the live lease")
        new_doc.pop("_id", None)
        return new_doc

    def get_retrieval(self, command_id: str) -> dict[str, Any] | None:
        return self.retrieval_commands.find_one({"command_id": command_id}, {"_id": 0})

    def settle_server_retrieval(self, command_id: str, *, now: float | None = None) -> dict[str, Any]:
        """Close a command whose target is the server itself by probing stored availability.

        The probe runs against the live file, so retention cleanup that removed the artifact
        after the request ends as `failed: evidence_unavailable` rather than a false completion.
        Recording the outcome never releases the clip.
        """
        now = time.time() if now is None else float(now)
        doc = self.retrieval_commands.find_one({"command_id": command_id})
        if doc is None:
            raise ReviewNotFound("retrieval command not found")
        state = self.retrieval_state(doc)
        if state.terminal or state.command.target != "server":
            doc.pop("_id", None)
            return doc
        evidence = state.command.evidence
        record = self.get_evidence(evidence.device_id, evidence.event_id, evidence.request_id, verify_file=True)
        manifest = dict((record or {}).get("manifest") or {})
        available = (
            record is not None
            and manifest.get("file_status") not in {"missing", "corrupt"}
            and manifest.get("completeness") not in {"missing", "corrupt"}
            and isinstance(manifest.get("sha256"), str)
            and isinstance(manifest.get("size_bytes"), int)
        )
        artifact = (
            {"sha256": manifest["sha256"], "size_bytes": manifest["size_bytes"]}
            if available
            else None
        )
        settled = settle_target(state, now=now, available=available, artifact=artifact)
        new_doc = self._retrieval_doc(settled, doc)
        result = self.retrieval_commands.replace_one(
            {"_id": doc["_id"], "status": doc["status"], "lease_id": doc.get("lease_id")}, new_doc
        )
        if result.matched_count != 1:
            # Another reader settled it first; the outcome is already durable.
            current = self.retrieval_commands.find_one({"command_id": command_id}, {"_id": 0})
            return current or new_doc
        new_doc.pop("_id", None)
        return new_doc

    def retrieval_view(
        self, command_id: str, *, now: float | None = None, offline_after: float = DEFAULT_OFFLINE_AFTER_SECONDS
    ) -> dict[str, Any]:
        """What the requesting reviewer sees: pending/offline/expired/completed/failed."""
        now = time.time() if now is None else float(now)
        doc = self.get_retrieval(command_id)
        if doc is None:
            raise ReviewNotFound("retrieval command not found")
        state = self.retrieval_state(doc)
        # A server target is fulfilled by the server, so device liveness is irrelevant to its status.
        last_seen = self.device_last_seen(state.command.device_id) if state.command.target == "edge" else now
        status = requester_status(state, now=now, device_last_seen=last_seen, offline_after=offline_after)
        return {
            "command_id": state.command.command_id,
            "device_id": state.command.device_id,
            "status": status,
            "target": state.command.target,
            "action": state.command.action,
            "evidence": state.command.evidence.as_dict(),
            "issued_by": state.command.issued_by,
            "issued_at": state.command.issued_at,
            "expires_at": state.command.expires_at,
            "retention_scope": state.command.retention_scope,
            "attempts": state.attempts,
            "metadata_acknowledged": state.metadata_acknowledged,
            "artifact": dict(state.artifact) if state.artifact is not None else None,
            "reason": state.reason,
        }

    def close(self) -> None:
        self.client.close()
