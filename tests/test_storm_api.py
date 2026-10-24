"""Ticket #41: malformed storm does not consume the state reserve (HTTP level)."""

import json
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.server.config import load_server_config
from apps.server.main import create_app
from domain.event_contract import MAX_EVENT_BYTES
from domain.storm_guard import StormGuard, StormGuardPolicy
from tests.test_server_evidence import sample_event, server_env

DEVICE = {"Authorization": "Bearer token-edge-1", "Content-Type": "application/json"}
DASHBOARD = {"Authorization": "Bearer dashboard-secret-token"}


class StormApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = "storm_api_" + uuid4().hex
        config = load_server_config(server_env(self.temp.name + "/evidence", self.database))
        self.app = create_app(config)
        self.store = self.app.state.event_store
        self.store.ensure_ready()
        self.addCleanup(self.store.close)
        self.addCleanup(self.store.database.client.drop_database, self.database)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.replace_guard(malformed_budget=3, forensic_samples=2)

    def replace_guard(self, *, malformed_budget=3, forensic_samples=2, now=None):
        clock = now or (lambda: 1_000.0)
        self.guard = StormGuard(
            StormGuardPolicy(window_seconds=60.0, malformed_budget=malformed_budget,
                             forensic_samples=forensic_samples, sample_text_bytes=120),
            _now=clock,
        )
        self.app.state.ingest_guard = self.guard
        return self.guard

    def post_raw(self, body, headers=None):
        return self.client.post("/v1/events", content=body, headers=headers or DEVICE)

    def post_event(self, event, headers=None):
        merged = dict(headers or DEVICE)
        merged["Idempotency-Key"] = event["message_id"]
        return self.client.post("/v1/events", content=json.dumps(event).encode(), headers=merged)

    def guard_state(self):
        return self.client.get("/v1/ingest/guard", headers=DASHBOARD).json()

    def test_malformed_flood_is_bounded_then_refused_and_stays_observable(self):
        for expected in (400, 400, 400):
            self.assertEqual(self.post_raw(b"{not json").status_code, expected)
        refused = self.post_raw(b"{not json")
        self.assertEqual(refused.status_code, 429)
        self.assertIn("retry-after", {key.lower(): value for key, value in refused.headers.items()})
        state = self.guard_state()
        self.assertEqual(state["counts"]["malformed"], 3)
        self.assertEqual(state["counts"]["rate_limited"], 1)
        self.assertEqual((state["budget_spent"], state["budget_remaining"]), (4, 0))
        self.assertTrue(state["degraded"])
        self.assertTrue(state["truncated"])
        self.assertEqual(len(state["forensics"]), 2)
        self.assertGreater(state["dropped_samples"], 0)

    def test_duplicate_delivery_is_compact_and_never_spends_the_budget(self):
        event = sample_event()
        first = self.post_event(event)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(first.json()["duplicate"])
        second = self.post_event(event)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()["duplicate"])
        state = self.guard_state()
        self.assertEqual((state["counts"]["accepted"], state["counts"]["duplicate"]), (1, 1))
        self.assertEqual(state["budget_spent"], 0)
        self.assertEqual(state["forensics"], [], "a duplicate revision must not create forensic noise")
        self.assertFalse(state["degraded"])

    def test_unique_valid_events_are_not_refused_by_the_guard(self):
        self.replace_guard(malformed_budget=2)
        for _ in range(6):
            event = sample_event()
            response = self.post_event(event)
            self.assertEqual(response.status_code, 200, response.text)
        state = self.guard_state()
        self.assertEqual(state["counts"]["accepted"], 6)
        self.assertEqual((state["budget_spent"], state["counts"]["rate_limited"]), (0, 0))
        self.assertFalse(state["degraded"])

    def test_validation_failures_and_wrong_content_type_are_counted_as_malformed(self):
        self.assertEqual(self.post_raw(b"{}", headers={"Authorization": "Bearer token-edge-1"}).status_code, 415)
        self.assertEqual(self.post_raw(b"{}").status_code, 422)
        state = self.guard_state()
        self.assertEqual(state["counts"]["malformed"], 2)
        self.assertEqual(state["budget_spent"], 2)
        details = [sample["detail"] for sample in state["forensics"]]
        self.assertTrue(all("detail" in detail and "status" in detail for detail in details))

    def test_oversized_event_is_counted_without_being_parsed(self):
        oversized = b"{" + b"x" * (MAX_EVENT_BYTES + 1024)
        response = self.post_raw(oversized)
        self.assertEqual(response.status_code, 413)
        state = self.guard_state()
        self.assertEqual(state["counts"]["too_large"], 1)
        self.assertEqual(state["forensics"][-1]["size_bytes"], MAX_EVENT_BYTES + 1025)

    def test_healthz_reports_degradation_without_failing_readiness(self):
        for _ in range(4):
            self.post_raw(b"{not json")
        health = self.client.get("/healthz")
        self.assertEqual(health.status_code, 200)
        body = health.json()
        self.assertEqual(body["status"], "degraded")
        self.assertTrue(body["ingest_guard"]["degraded"])
        self.assertEqual(body["ingest_guard"]["budget_remaining"], 0)

    def test_guard_endpoint_requires_credentials(self):
        self.assertEqual(self.client.get("/v1/ingest/guard").status_code, 401)
        self.assertEqual(self.client.get("/v1/ingest/guard", headers=DEVICE).status_code, 401)
        self.assertEqual(self.client.get("/v1/ingest/guard", headers=DASHBOARD).status_code, 200)

    def test_window_rollover_restores_admission(self):
        clock = {"now": 1_000.0}
        self.replace_guard(malformed_budget=2, now=lambda: clock["now"])
        for _ in range(2):
            self.assertEqual(self.post_raw(b"{not json").status_code, 400)
        self.assertEqual(self.post_raw(b"{not json").status_code, 429)
        clock["now"] += 61.0
        self.assertEqual(self.post_raw(b"{not json").status_code, 400)
        state = self.guard_state()
        self.assertEqual(state["counts"]["malformed"], 1)
        self.assertFalse(state["degraded"])


if __name__ == "__main__":
    unittest.main()
