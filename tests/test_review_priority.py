"""Acceptance for ticket #27: on-vehicle events stay reviewable at low priority."""
from __future__ import annotations

import copy
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.server.config import load_server_config
from apps.server.dataset import export_dataset_records
from apps.server.main import create_app
from apps.server.store import review_priority_for
from tests.test_server_evidence import sample_event, server_env

DASHBOARD = {"Authorization": "Bearer dashboard-secret-token"}
ALICE = {"Authorization": "Bearer reviewer-secret-alice"}


def on_vehicle_event() -> dict[str, object]:
    event = copy.deepcopy(sample_event())
    event["payload"].update({"taxonomy": "person_on_stationary_vehicle", "severity": "low"})  # type: ignore[union-attr]
    return event


class ReviewPriorityUnitTests(unittest.TestCase):
    def test_priority_classes(self) -> None:
        self.assertEqual(review_priority_for({"taxonomy": "person_on_stationary_vehicle", "severity": "low"}), "low")
        # Explicit danger override (high/critical) beats the on-vehicle low default.
        self.assertEqual(review_priority_for({"taxonomy": "person_on_stationary_vehicle", "severity": "critical"}), "urgent")
        self.assertEqual(review_priority_for({"taxonomy": "person_fall", "severity": "critical"}), "urgent")
        self.assertEqual(review_priority_for({"taxonomy": "person_lying_persistent", "severity": "high"}), "urgent")
        self.assertEqual(review_priority_for({"taxonomy": "person_fall", "severity": "low"}), "low")
        self.assertEqual(review_priority_for({"taxonomy": "other", "severity": "medium"}), "standard")


class ReviewPriorityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = "review_priority_" + uuid4().hex
        config = load_server_config(server_env(self.temp.name + "/evidence", self.database))
        self.app = create_app(config)
        self.store = self.app.state.event_store
        self.store.ensure_ready()
        self.addCleanup(self.store.close)
        self.addCleanup(self.store.database.client.drop_database, self.database)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

        self.fall = sample_event()
        self.fall_receipt = self.store.persist(self.fall)
        self.on_vehicle = on_vehicle_event()
        self.on_vehicle_receipt = self.store.persist(self.on_vehicle)

    def event_keys(self, **filters):
        return [row["event"]["event_id"] for row in self.store.list_current(50, **filters)]

    def test_list_current_tags_and_filters_queue(self) -> None:
        rows = {row["event"]["event_id"]: row for row in self.store.list_current(50)}
        self.assertEqual(rows[self.fall["event_id"]]["review_priority"], "urgent")
        self.assertEqual(rows[self.fall["event_id"]]["severity"], "high")
        low = rows[self.on_vehicle["event_id"]]
        self.assertEqual(low["review_priority"], "low")
        self.assertEqual(low["severity"], "low")
        self.assertEqual(low["taxonomy"], "person_on_stationary_vehicle")

        self.assertEqual(self.event_keys(taxonomy="person_on_stationary_vehicle"), [self.on_vehicle["event_id"]])
        self.assertEqual(self.event_keys(severity="high"), [self.fall["event_id"]])
        self.assertEqual(self.event_keys(severity="low", taxonomy="person_on_stationary_vehicle"),
                         [self.on_vehicle["event_id"]])
        self.assertEqual(self.event_keys(severity="critical"), [])

    def test_lab_outbox_never_marks_urgent_candidates(self) -> None:
        outbox = {doc["event_id"]: doc for doc in self.store.outbox.find({}, {"_id": 0})}
        low = outbox[self.on_vehicle["event_id"]]
        self.assertEqual(low["eligibility"], "ineligible")
        self.assertEqual(low["review_priority"], "low")
        self.assertEqual(low["taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(low["severity"], "low")
        self.assertEqual(outbox[self.fall["event_id"]]["eligibility"], "ineligible")

    def test_events_api_filters_and_rejects_invalid_values(self) -> None:
        res = self.client.get("/v1/events?taxonomy=person_on_stationary_vehicle&limit=50", headers=DASHBOARD)
        self.assertEqual(res.status_code, 200)
        events = res.json()["events"]
        self.assertEqual([row["event"]["event_id"] for row in events], [self.on_vehicle["event_id"]])
        self.assertEqual(events[0]["review_priority"], "low")

        res = self.client.get("/v1/events?severity=high", headers=DASHBOARD)
        self.assertEqual([row["event"]["event_id"] for row in res.json()["events"]], [self.fall["event_id"]])

        self.assertEqual(self.client.get("/v1/events?severity=urgent", headers=DASHBOARD).status_code, 422)
        self.assertEqual(self.client.get("/v1/events?taxonomy=", headers=DASHBOARD).status_code, 422)

    def test_review_audit_records_taxonomy_severity_and_priority(self) -> None:
        res = self.client.post(
            f"/v1/events/{self.on_vehicle['device_id']}/{self.on_vehicle['event_id']}/review",
            json={
                "action": "confirm",
                "expected_review_version": 0,
                "viewed_event_revision": 1,
                "viewed_event_hash": self.on_vehicle_receipt["event_hash"],
                "viewed_evidence_versions": {},
                "reason": "on-vehicle posture reviewed",
            },
            headers=ALICE,
        )
        self.assertEqual(res.status_code, 200)
        state = res.json()
        self.assertEqual(state["reviewed_taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(state["reviewed_severity"], "low")
        self.assertEqual(state["reviewed_review_priority"], "low")
        self.assertEqual(state["audit"][0]["reviewed_review_priority"], "low")
        self.assertEqual(state["audit"][0]["reviewed_taxonomy"], "person_on_stationary_vehicle")

    def test_dataset_export_keeps_lineage_and_review_decision_for_on_vehicle(self) -> None:
        self.client.post(
            f"/v1/events/{self.on_vehicle['device_id']}/{self.on_vehicle['event_id']}/review",
            json={
                "action": "confirm",
                "expected_review_version": 0,
                "viewed_event_revision": 1,
                "viewed_event_hash": self.on_vehicle_receipt["event_hash"],
                "viewed_evidence_versions": {},
                "reason": "reviewed low priority queue",
            },
            headers=ALICE,
        )

        records = export_dataset_records(self.store, taxonomy="person_on_stationary_vehicle")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["event_id"], self.on_vehicle["event_id"])
        self.assertEqual(record["taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(record["severity"], "low")
        self.assertEqual(record["review_priority"], "low")
        self.assertEqual(record["reviewed_decision"], "confirmed")
        self.assertEqual(record["reviewed_event_revision"], 1)
        self.assertEqual(record["reviewed_event_hash"], self.on_vehicle_receipt["event_hash"])
        self.assertEqual(record["original_ai_payload"]["taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(record["review_audit_trail"][0]["action"], "confirm")

        self.assertEqual(export_dataset_records(self.store, taxonomy="person_fall"), [])

        res = self.client.get("/v1/dataset/export?format=json&taxonomy=person_on_stationary_vehicle", headers=DASHBOARD)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["records"][0]["review_priority"], "low")
        self.assertEqual(self.client.get("/v1/dataset/export?severity=urgent", headers=DASHBOARD).status_code, 422)


if __name__ == "__main__":
    unittest.main()
