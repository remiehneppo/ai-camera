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
            db.execute(
                "INSERT INTO event_revisions VALUES (?, ?, ?, ?, ?, ?)",
                (*identity, event["message_id"], digest, event_json),
            )
            db.execute(
                "INSERT INTO delivery_outbox (message_id, device_id, event_id, revision, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (event["message_id"], *identity, datetime.now(timezone.utc).isoformat()),
            )
        return event["message_id"]

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
