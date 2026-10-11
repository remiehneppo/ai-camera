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


class EventHashConflict(Exception):
    pass


class EventIdentityConflict(Exception):
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

    def ensure_ready(self) -> None:
        self.client.admin.command("ping")
        self.revisions.create_index(
            [("device_id", 1), ("event_id", 1), ("revision", 1)], unique=True, name="event_revision_identity"
        )
        self.current.create_index([("device_id", 1), ("event_id", 1)], unique=True, name="current_event_identity")
        self.outbox.create_index(
            [("device_id", 1), ("event_id", 1), ("revision", 1)], unique=True, name="downstream_intent_identity"
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
                    {**key, "event": event, "event_hash": event_hash, "updated_at": accepted_at},
                    upsert=True,
                    session=session,
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
        return list(cursor)

    def close(self) -> None:
        self.client.close()
