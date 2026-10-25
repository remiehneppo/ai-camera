"""Ticket #40: a synthetic probe can never reach the notification path.

Covers the guard, not the probe internals: every revision of a synthetic event is recorded
as ineligible before the outbox, a revision cannot rewrite the origin, and a probe report is
not a valid event at all -- so the fault route has no way to become an incident.
"""

import copy
import tempfile
import time
import unittest
from uuid import uuid4

from apps.server.config import load_server_config
from apps.server.main import create_app
from apps.server.store import EventIdentityConflict
from apps.edge.send_synthetic import make_event
from domain.event_contract import EventValidationError, validate_event
from domain.probe_contract import OPERATIONAL_FAULT_TAXONOMY, ProbeLedger, ProbePolicy
from apps.edge.probe import SyntheticProbe
from domain.probe_contract import STAGES
from tests.test_server_evidence import sample_event, server_env


class SyntheticGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = "probe_guard_" + uuid4().hex
        self.app = create_app(load_server_config(server_env(self.temp.name + "/evidence", self.database)))
        self.store = self.app.state.event_store
        self.store.ensure_ready()
        self.addCleanup(self.store.close)
        self.addCleanup(self.store.database.client.drop_database, self.database)

    def outbox(self, event):
        return list(self.store.outbox.find(
            {"device_id": event["device_id"], "event_id": event["event_id"]}, {"_id": 0}
        ).sort("revision", 1))

    def test_every_revision_of_a_synthetic_event_is_ineligible(self):
        event = sample_event()
        self.assertEqual(event["origin"], "synthetic")
        self.store.persist(event)
        second = copy.deepcopy(event)
        second["revision"] = 2
        second["message_id"] = "msg-" + uuid4().hex[:8]
        second["payload"].update({"severity": "medium"})
        self.store.persist(second)
        rows = self.outbox(event)
        self.assertEqual([row["revision"] for row in rows], [1, 2])
        for row in rows:
            self.assertEqual(row["eligibility"], "ineligible", row)
            self.assertEqual(row["reason"], "synthetic_or_replay_origin")
            self.assertEqual(row["policy_version"], "lab-disabled-v1")

    def test_a_revision_cannot_rewrite_the_origin_to_escape_the_guard(self):
        event = sample_event()
        self.store.persist(event)
        escaped = copy.deepcopy(event)
        escaped["revision"] = 2
        escaped["message_id"] = "msg-" + uuid4().hex[:8]
        escaped["origin"] = "live"
        with self.assertRaises(EventIdentityConflict):
            self.store.persist(escaped)
        self.assertEqual(len(self.outbox(event)), 1)

    def test_live_origin_is_still_ineligible_in_the_lab_for_a_different_reason(self):
        event = sample_event()
        event["origin"] = "live"
        event["pipeline_id"] = "perception-pipeline-v1"
        self.store.persist(event)
        row = self.outbox(event)[0]
        self.assertEqual((row["eligibility"], row["reason"]), ("ineligible", "lab_notifications_disabled"))

    def test_probe_report_is_not_a_valid_event_and_cannot_be_ingested(self):
        clock = time.time
        report = SyntheticProbe(
            ProbeLedger(ProbePolicy(), now=clock), {stage: (lambda: None) for stage in STAGES}, now=clock
        ).run("probe-guard")
        self.assertEqual(report["taxonomy"], OPERATIONAL_FAULT_TAXONOMY)
        with self.assertRaises(EventValidationError):
            validate_event(report)
        with self.assertRaises(EventValidationError):
            validate_event({"event": report})

    def test_synthetic_fixture_keeps_its_own_business_taxonomy(self):
        event = make_event("lab-edge-01", "lab-camera-01")
        self.assertEqual(event["origin"], "synthetic")
        self.assertEqual(event["payload"]["taxonomy"], "synthetic_demo")
        self.assertNotEqual(event["payload"]["taxonomy"], OPERATIONAL_FAULT_TAXONOMY)
        validate_event(event)
        self.store.persist(event)
        self.assertEqual(self.outbox(event)[0]["taxonomy"], "synthetic_demo")


if __name__ == "__main__":
    unittest.main()
