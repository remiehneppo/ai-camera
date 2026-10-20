"""HTTP-level acceptance for ticket #04: versioned review, 409 conflicts, audit, re-review reasons."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.server.config import load_server_config
from apps.server.main import create_app
from tests.test_server_evidence import sample_event, server_env

ALICE = {"Authorization": "Bearer reviewer-secret-alice"}


class ReviewApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = "review_api_" + uuid4().hex
        config = load_server_config(server_env(self.temp.name + "/evidence", self.database))
        self.app = create_app(config)
        self.store = self.app.state.event_store
        self.store.ensure_ready()
        self.addCleanup(self.store.close)
        self.addCleanup(self.store.database.client.drop_database, self.database)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.event = sample_event()
        self.receipt = self.store.persist(self.event)
        self.url = f"/v1/events/{self.event['device_id']}/{self.event['event_id']}/review"

    def body(self, action="confirm", expected=0, versions=None, revision=1, event_hash=None, reason="ok"):
        return {
            "action": action, "expected_review_version": expected, "viewed_event_revision": revision,
            "viewed_event_hash": event_hash or self.receipt["event_hash"],
            "viewed_evidence_versions": versions or {}, "reason": reason,
        }

    def post(self, body, headers=ALICE, url=None):
        return self.client.post(url or self.url, json=body, headers=headers)

    def revision2(self, **payload):
        event = copy.deepcopy(self.event)
        event["revision"] = 2
        event["message_id"] = "msg-" + uuid4().hex[:8]
        event["payload"].update(payload)
        return self.store.persist(event)

    def state(self):
        return self.store.reviews.find_one({k: self.event[k] for k in ("device_id", "event_id")})

    def test_auth_and_validation_rejects(self):
        self.assertEqual(self.post(self.body(), headers={}).status_code, 401)
        self.assertEqual(self.post(self.body(), headers={"Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(self.post(self.body(), headers={"Authorization": "Bearer dashboard-secret-token"}).status_code, 401)
        self.assertEqual(self.post(self.body(action="delete")).status_code, 422)
        self.assertEqual(self.post(self.body(reason="  ")).status_code, 422)
        self.assertEqual(self.post(self.body(), url="/v1/events/lab-edge-01/missing/review").status_code, 404)
        self.assertIsNone(self.state())

    def test_confirm_resolve_audit_and_invalid_transitions(self):
        self.assertEqual(self.post(self.body("resolve")).status_code, 409)  # resolve needs confirmed
        first = self.post(self.body("confirm"))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["decision"], "confirmed")
        self.assertEqual(self.post(self.body("false_positive", expected=1)).status_code, 409)
        resolved = self.post(self.body("resolve", expected=1))
        self.assertEqual(resolved.json()["decision"], "resolved")
        audits = list(self.store.review_audit.find({"event_id": self.event["event_id"]}).sort("review_version", 1))
        self.assertEqual([(a["review_version"], a["action"], a["actor"]) for a in audits],
                         [(1, "confirm", "alice"), (2, "resolve", "alice")])

    def test_false_positive_allowed_and_two_reviewers_same_version_one_conflict(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted(r.status_code for r in pool.map(
                lambda a: self.post(self.body(a)), ("confirm", "false_positive")))
        self.assertEqual(codes, [200, 409])
        self.assertEqual(self.state()["review_version"], 1)

    def test_stale_expected_version_and_stale_viewed_hash_conflict(self):
        self.assertEqual(self.post(self.body(expected=3)).status_code, 409)
        self.assertEqual(self.post(self.body(event_hash="0" * 64)).status_code, 409)

    def test_stale_meaningful_content_conflicts_but_ai_confidence_revision_does_not(self):
        self.revision2(confidence=0.1)  # harmless AI revision
        harmless = self.post(self.body())
        self.assertEqual(harmless.status_code, 200)
        self.assertEqual(self.store.current.find_one({"event_id": self.event["event_id"]})["event"]["payload"]["confidence"], 0.1)

    def test_stale_severity_revision_blocks_action_on_old_view(self):
        self.revision2(severity="critical")
        self.assertEqual(self.post(self.body()).status_code, 409)

    def test_needs_re_review_requires_reopen_keeps_decision_and_states_reason(self):
        self.assertEqual(self.post(self.body("false_positive")).status_code, 200)
        receipt2 = self.revision2(severity="critical")
        state = self.state()
        self.assertTrue(state["needs_re_review"])
        self.assertEqual(state["decision"], "false_positive")
        self.assertIn("event_content_changed", state["re_review_reasons"])
        rev2 = dict(event_hash=receipt2["event_hash"], revision=2)
        self.assertEqual(self.post(self.body("confirm", expected=1, **rev2)).status_code, 409)
        self.assertEqual(self.state()["decision"], "false_positive")
        reopened = self.post(self.body("reopen", expected=1, reason="severity rose", **rev2))
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.json()["decision"], "unreviewed")
        self.assertFalse(reopened.json()["needs_re_review"])
        self.assertEqual(self.post(self.body("confirm", expected=2, **rev2)).status_code, 200)
        resp = self.client.get("/v1/events", headers={"Authorization": "Bearer dashboard-secret-token"})
        self.assertEqual(resp.status_code, 200)
        events = resp.json().get("events", [])
        audit = [a["action"] for a in sorted(events[0]["review"]["audit"], key=lambda a: a["review_version"])]
        self.assertEqual(audit, ["false_positive", "reopen", "confirm"])

    def test_evidence_pending_to_complete_flags_with_reason_and_stale_evidence_view_conflicts(self):
        def upload(meta):
            data = b"clip"
            return self.client.put(
                f"/v1/evidence/{self.event['device_id']}/{self.event['event_id']}/req-001", content=data,
                headers={"Authorization": "Bearer token-edge-1", "X-Evidence-Sha256": hashlib.sha256(data).hexdigest(),
                         "X-Evidence-Metadata": json.dumps(meta)})
        self.assertEqual(upload({"completeness": "partial"}).status_code, 200)
        self.assertEqual(self.post(self.body("false_positive", versions={"req-001": 1})).status_code, 200)
        self.assertEqual(upload({"completeness": "complete"}).status_code, 200)
        state = self.state()
        self.assertTrue(state["needs_re_review"])
        self.assertIn("evidence_changed", state["re_review_reasons"])
        # viewing old manifest version 1 is stale now
        self.assertEqual(self.post(self.body("reopen", expected=1, versions={"req-001": 1})).status_code, 409)
        self.assertEqual(self.post(self.body("reopen", expected=1, versions={"req-001": 2})).status_code, 200)
