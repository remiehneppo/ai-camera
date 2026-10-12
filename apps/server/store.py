"""MongoDB transaction boundary for event snapshots and disabled outbox intent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import MongoClient, ReadPreference
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from domain.event_contract import canonical_event_hash, validate_revision_identity
from domain.review_contract import ReviewTransitionError, meaningful_content_hash, next_decision


class EventHashConflict(Exception):
    pass


class EventIdentityConflict(Exception):
    pass


class ReviewConflict(Exception):
    pass


class ReviewNotFound(Exception):
    pass


class EventStore:
    def __init__(self, uri: str, database_name: str) -> None:
        if "replicaSet=" not in uri:
            raise ValueError("MONGO_URI must name the lab replica set")
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000, retryWrites=True)
        self.database = self.client[database_name]
        self.revisions = self.database.get_collection("event_revisions")
        self.current = self.database.get_collection("current_events")
        self.outbox = self.database.get_collection("downstream_outbox")
        self.reviews = self.database.get_collection("event_reviews")
        self.review_audit = self.database.get_collection("event_review_audit")

    def ensure_ready(self) -> None:
        self.client.admin.command("ping")
        self.revisions.create_index(
            [("device_id", 1), ("event_id", 1), ("revision", 1)], unique=True, name="event_revision_identity"
        )
        self.current.create_index([("device_id", 1), ("event_id", 1)], unique=True, name="current_event_identity")
        self.outbox.create_index(
            [("device_id", 1), ("event_id", 1), ("revision", 1)], unique=True, name="downstream_intent_identity"
        )
        self.reviews.create_index([("device_id", 1), ("event_id", 1)], unique=True, name="event_review_identity")
        self.review_audit.create_index(
            [("device_id", 1), ("event_id", 1), ("review_version", 1)], unique=True, name="event_review_version"
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
                        self.reviews.replace_one(
                            {"device_id": event["device_id"], "event_id": event["event_id"]}, review, session=session
                        )
            reason = "synthetic_or_replay_origin" if event["origin"] in {"synthetic", "replay"} else "lab_notifications_disabled"
            self.outbox.insert_one(
                {
                    **key,
                    "message_id": event["message_id"],
                    "event_hash": event_hash,
                    "origin": event["origin"],
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

    def list_current(self, limit: int) -> list[dict[str, Any]]:
        cursor = self.current.find({}, {"_id": 0, "event": 1, "event_hash": 1, "updated_at": 1}).sort("updated_at", -1).limit(limit)
        rows = list(cursor)
        if not rows:
            return rows
        keys = [{"device_id": row["event"]["device_id"], "event_id": row["event"]["event_id"]} for row in rows]
        selector = {"$or": keys}
        states = {
            (state["device_id"], state["event_id"]): state
            for state in self.reviews.find(selector, {"_id": 0})
        }
        audits: dict[tuple[str, str], list[dict[str, Any]]] = {}
        pipeline = [
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
        for row in rows:
            event = row["event"]
            key = (event["device_id"], event["event_id"])
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
        return rows

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
            expected_evidence = current_event["payload"].get("evidence_versions", {})
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
                "actor": actor,
                "reason": request["reason"],
                "reviewed_event_revision": request["viewed_event_revision"],
                "reviewed_event_hash": request["viewed_event_hash"],
                "viewed_evidence_versions": request["viewed_evidence_versions"],
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

    def close(self) -> None:
        self.client.close()
