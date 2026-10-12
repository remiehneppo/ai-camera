from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from apps.edge.outbox import EventConflict, EventOutbox
from domain.event_contract import EventValidationError, canonical_event_hash, validate_event, validate_revision_identity


def event_fixture() -> dict[str, object]:
    return {
        "schema_version": 1,
        "message_id": "msg-1",
        "event_id": "00000000-0000-4000-8000-000000000001",
        "revision": 1,
        "device_id": "lab-edge-01",
        "camera_id": "lab-camera-01",
        "stream_session_id": "00000000-0000-4000-8000-000000000002",
        "pipeline_id": "synthetic-fixture",
        "pipeline_version": "1",
        "origin": "synthetic",
        "event_time": "2026-10-12T00:00:00Z",
        "produced_at": "2026-10-12T00:00:01+00:00",
        "config_version": "synthetic-fixture-v1",
        "model_lineage": [{"role": "fixture", "version": "1"}],
        "model_artifact_hash": "unknown_artifact",
        "calibration_version": "uncalibrated",
        "quality_state": "unknown",
        "payload": {"taxonomy": "synthetic_demo", "lifecycle": "candidate", "severity": "low", "score": 0.0},
    }


class EventContractTests(unittest.TestCase):
    def test_timestamps_normalize_and_hash_is_key_order_independent(self) -> None:
        event = validate_event(event_fixture())
        self.assertEqual(event["event_time"], "2026-10-12T00:00:00.000000Z")
        self.assertEqual(event["produced_at"], "2026-10-12T00:00:01.000000Z")
        self.assertEqual(canonical_event_hash(event), "8a9004f5813f81e8300918dd3b7629f02ed88e8c877c004aa2a05caa7b658150")
        reverse_order = dict(reversed(list(event.items())))
        self.assertEqual(canonical_event_hash(event), canonical_event_hash(reverse_order))

    def test_requires_timezone_and_rejects_bool_revision(self) -> None:
        event = event_fixture()
        event["event_time"] = "2026-10-12T00:00:00"
        with self.assertRaisesRegex(EventValidationError, "timezone"):
            validate_event(event)
        event = event_fixture()
        event["revision"] = True
        with self.assertRaisesRegex(EventValidationError, "positive integer"):
            validate_event(event)

    def test_rejects_unknown_origin_and_non_finite_payload(self) -> None:
        event = event_fixture()
        event["origin"] = {"synthetic": True}
        with self.assertRaisesRegex(EventValidationError, "origin"):
            validate_event(event)
        event = event_fixture()
        event["payload"] = {"score": float("nan")}
        with self.assertRaisesRegex(EventValidationError, "finite JSON"):
            validate_event(event)

    def test_origin_and_source_identity_cannot_change_between_revisions(self) -> None:
        first = validate_event(event_fixture())
        next_event = event_fixture()
        next_event["revision"] = 2
        next_event["message_id"] = "msg-2"
        next_event["produced_at"] = "2026-10-12T00:00:02Z"
        next_event["origin"] = "live"
        with self.assertRaisesRegex(EventValidationError, "origin is immutable"):
            validate_revision_identity(first, validate_event(next_event))


class EdgeOutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "edge.sqlite3"
        self.outbox = EventOutbox(self.db_path)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_evidence_intent_is_atomic_and_anchored_not_triggered(self):
        from domain.evidence_contract import make_evidence_request

        event = event_fixture()
        request = make_evidence_request("request-1", event["stream_session_id"], "onset", 0)
        event["payload"]["evidence_requests"] = [request]
        self.outbox.enqueue(event)
        restarted = EventOutbox(self.db_path)
        intent = restarted.evidence_requests()[0]
        self.assertEqual((intent["requested_start"], intent["requested_end"]), (-10, 20))
        self.assertEqual(intent["state"], "requested")
        self.assertEqual(restarted.pending()[0]["event"]["payload"]["evidence_requests"], [request])
        changed = event_fixture()
        changed.update(revision=2, message_id="msg-2")
        changed["payload"]["evidence_requests"] = [{**request, "requested_end": 21}]
        with self.assertRaises(ValueError):
            restarted.enqueue(changed)
        self.assertEqual(len(restarted.pending()), 1)
        self.assertEqual(restarted.evidence_requests()[0], intent)

    def test_evidence_failure_rolls_back_event_and_metadata_delivery(self):
        from domain.evidence_contract import make_evidence_request
        event = event_fixture()
        event["payload"]["evidence_requests"] = [make_evidence_request("intent", event["stream_session_id"], "synthetic", 0)]
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TRIGGER reject_evidence BEFORE INSERT ON evidence_requests BEGIN SELECT RAISE(ABORT, 'intent failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.outbox.enqueue(event)
        self.assertFalse(self.outbox.has_revision(event["device_id"], event["event_id"]))
        self.assertEqual(self.outbox.pending(), [])
        self.assertEqual(self.outbox.evidence_requests(), [])

    def test_memory_database_is_rejected_to_preserve_durability(self) -> None:
        with self.assertRaisesRegex(ValueError, "file-backed"):
            EventOutbox(":memory:")

    def test_enqueue_is_idempotent_and_revision_conflicts_are_rejected(self) -> None:
        event = event_fixture()
        self.assertEqual(self.outbox.enqueue(event), "msg-1")
        self.assertEqual(self.outbox.enqueue(event), "msg-1")
        self.assertEqual(len(self.outbox.pending()), 1)
        changed = dict(event)
        changed["payload"] = {"taxonomy": "different"}
        with self.assertRaises(EventConflict):
            self.outbox.enqueue(changed)

    def test_retry_keeps_the_same_snapshot_and_message_identity(self) -> None:
        event = event_fixture()
        self.outbox.enqueue(event)
        initial = self.outbox.pending()[0]

        self.outbox.record_attempt(initial["message_id"], "TimeoutError")
        retried = self.outbox.pending()[0]

        self.assertEqual(retried["message_id"], initial["message_id"])
        self.assertEqual(retried["event_hash"], initial["event_hash"])
        self.assertEqual(retried["event"], initial["event"])
        self.assertEqual(retried["attempts"], 1)

    def test_event_and_delivery_intent_rollback_together(self) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "CREATE TRIGGER reject_delivery BEFORE INSERT ON delivery_outbox "
                "BEGIN SELECT RAISE(ABORT, 'injected outbox failure'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.outbox.enqueue(event_fixture())
        with sqlite3.connect(self.db_path) as db:
            event_count = db.execute("SELECT COUNT(*) FROM event_revisions").fetchone()[0]
            outbox_count = db.execute("SELECT COUNT(*) FROM delivery_outbox").fetchone()[0]
        self.assertEqual((event_count, outbox_count), (0, 0))

    def test_successful_delivery_receipt_removes_entry_from_pending(self) -> None:
        self.outbox.enqueue(event_fixture())
        self.outbox.record_attempt("msg-1")
        self.outbox.mark_delivered("msg-1", {"accepted": True})
        self.assertEqual(self.outbox.pending(), [])
        with sqlite3.connect(self.db_path) as db:
            status, attempts, receipt = db.execute(
                "SELECT status, attempts, receipt_json FROM delivery_outbox WHERE message_id='msg-1'"
            ).fetchone()
        self.assertEqual((status, attempts), ("delivered", 1))
        self.assertEqual(json.loads(receipt), {"accepted": True})

    def test_wrong_receipt_does_not_mark_outbox_delivered(self) -> None:
        self.outbox.enqueue(event_fixture())
        item = self.outbox.pending()[0]
        from apps.edge.send_synthetic import _validate_receipt

        with self.assertRaisesRegex(ValueError, "does not match"):
            _validate_receipt({"accepted": True}, item)
        self.assertEqual(len(self.outbox.pending()), 1)

    def test_source_identity_cannot_change_on_a_later_revision(self) -> None:
        first = event_fixture()
        self.outbox.enqueue(first)
        for field, value in (
            ("camera_id", "other-camera"),
            ("stream_session_id", "00000000-0000-4000-8000-000000000003"),
            ("origin", "live"),
        ):
            next_event = dict(first)
            next_event.update(revision=2, message_id="msg-2", produced_at="2026-10-12T00:00:02Z", **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(EventValidationError, f"{field} is immutable"):
                self.outbox.enqueue(next_event)

    def test_out_of_order_revisions_are_durable_and_identity_checked(self) -> None:
        for revision in (3, 1, 2):
            event = event_fixture()
            event.update(revision=revision, message_id=f"msg-{revision}")
            self.outbox.enqueue(event)

        with sqlite3.connect(self.db_path) as db:
            revisions = db.execute("SELECT revision FROM event_revisions ORDER BY revision").fetchall()
        self.assertEqual([row[0] for row in revisions], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
