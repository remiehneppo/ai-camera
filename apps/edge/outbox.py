"""Durable SQLite event journal and delivery outbox."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from domain.event_contract import canonical_event_hash, validate_event, validate_revision_identity


class EventConflict(ValueError):
    pass


class EventOutbox:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("the durable edge outbox requires a file-backed SQLite database")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS ended_recorder_sessions (session_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS evidence_requests (
                    request_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'requested',
                    receipt_json TEXT,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS event_revisions (
                    device_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    message_id TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY (device_id, event_id, revision)
                );
                CREATE TABLE IF NOT EXISTS delivery_outbox (
                    message_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'delivered')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    receipt_json TEXT,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    UNIQUE (device_id, event_id, revision)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def enqueue(self, raw_event: dict[str, Any]) -> str:
        event = validate_event(raw_event)
        requests = event["payload"].get("evidence_requests", [])
        digest = canonical_event_hash(event)
        event_json = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        identity = (event["device_id"], event["event_id"], event["revision"])
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT event_hash, message_id FROM event_revisions WHERE device_id=? AND event_id=? AND revision=?",
                identity,
            ).fetchone()
            if prior:
                if prior["event_hash"] != digest:
                    raise EventConflict("same event revision was already stored with different content")
                return prior["message_id"]
            first = db.execute(
                "SELECT snapshot_json FROM event_revisions WHERE device_id=? AND event_id=? ORDER BY revision LIMIT 1",
                identity[:2],
            ).fetchone()
            if first:
                validate_revision_identity(json.loads(first["snapshot_json"]), event)
            for request in requests:
                encoded = json.dumps(request, sort_keys=True, separators=(",", ":"))
                saved = db.execute("SELECT device_id,event_id,request_json FROM evidence_requests WHERE request_id=?",
                                   (request["request_id"],)).fetchone()
                if saved and tuple(saved) != (*identity[:2], encoded):
                    raise EventConflict("evidence request ID already has different content or owner")
                supersedes = request["supersedes_request_id"]
                if supersedes:
                    parent = db.execute("SELECT device_id,event_id FROM evidence_requests WHERE request_id=?", (supersedes,)).fetchone()
                    if parent is None or tuple(parent) != identity[:2]:
                        raise EventConflict("superseded request must belong to the same event")
                db.execute("INSERT OR IGNORE INTO evidence_requests(request_id,device_id,event_id,revision,request_json) VALUES(?,?,?,?,?)",
                           (request["request_id"], *identity, encoded))
            db.execute(
                "INSERT INTO event_revisions VALUES (?, ?, ?, ?, ?, ?)",
                (*identity, event["message_id"], digest, event_json),
            )
            db.execute(
                "INSERT INTO delivery_outbox (message_id, device_id, event_id, revision, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (event["message_id"], *identity, datetime.now(timezone.utc).isoformat()),
            )
        return event["message_id"]

    def evidence_requests(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM evidence_requests ORDER BY rowid").fetchall()
        return [{**json.loads(row["request_json"]), "device_id": row["device_id"],
                 "event_id": row["event_id"], "revision": row["revision"], "state": row["state"],
                 "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None,
                 "last_error": row["last_error"]} for row in rows]

    def update_evidence(self, request_id, *, state=None, receipt=None, error=None):
        with self._connect() as db:
            if state is None:
                db.execute("UPDATE evidence_requests SET last_error=? WHERE request_id=?",
                           (str(error)[:512] if error else None, request_id))
            else:
                db.execute("UPDATE evidence_requests SET state=?, receipt_json=COALESCE(?,receipt_json), last_error=? WHERE request_id=?",
                           (state, json.dumps(receipt) if receipt is not None else None,
                            str(error)[:512] if error else None, request_id))

    def ended_sessions(self, finish_sessions=()):
        with self._connect() as db:
            db.executemany("INSERT OR IGNORE INTO ended_recorder_sessions VALUES(?)",
                           [(session,) for session in finish_sessions])
            return {row[0] for row in db.execute("SELECT session_id FROM ended_recorder_sessions")}

    def reconcile_evidence(self, recorder, *, finish_sessions=()) -> int:
        from apps.edge.evidence import EvidenceLifecycle
        return EvidenceLifecycle(self, recorder).reconcile(finish_sessions=finish_sessions)["recovered_fulfilled"]

    def reconcile_and_cleanup(self, recorder: Any) -> dict[str, Any]:
        from apps.edge.evidence import EvidenceLifecycle
        return EvidenceLifecycle(self, recorder).reconcile()

    def pending(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT o.message_id, o.attempts, r.event_hash, r.snapshot_json FROM delivery_outbox o "
                "JOIN event_revisions r USING (device_id, event_id, revision) "
                "WHERE o.status='pending' ORDER BY o.created_at, o.message_id"
            ).fetchall()
        return [
            {"message_id": row["message_id"], "attempts": row["attempts"], "event_hash": row["event_hash"], "event": json.loads(row["snapshot_json"])}
            for row in rows
        ]

    def has_revision(self, device_id: str, event_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM event_revisions WHERE device_id=? AND event_id=? LIMIT 1",
                (device_id, event_id),
            ).fetchone()
        return row is not None

    def record_attempt(self, message_id: str, error: str | None = None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE delivery_outbox SET attempts=attempts+1, last_error=? WHERE message_id=? AND status='pending'",
                (error[:512] if error else None, message_id),
            )

    def mark_delivered(self, message_id: str, receipt: dict[str, Any]) -> None:
        receipt_json = json.dumps(receipt, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM delivery_outbox WHERE message_id=?", (message_id,)).fetchone()
            if row is None:
                raise KeyError(message_id)
            db.execute(
                "UPDATE delivery_outbox SET status='delivered', receipt_json=?, delivered_at=?, last_error=NULL WHERE message_id=?",
                (receipt_json, datetime.now(timezone.utc).isoformat(), message_id),
            )
