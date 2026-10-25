"""Ticket #32: retained-evidence retrieval command API."""

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.server.config import load_server_config
from apps.server.main import create_app
from tests.test_server_evidence import server_env

ALICE = {"Authorization": "Bearer reviewer-secret-alice"}
DEVICE_1 = {"Authorization": "Bearer token-edge-1"}
DEVICE_2 = {"Authorization": "Bearer token-edge-2"}
DASHBOARD = {"Authorization": "Bearer dashboard-secret-token"}


class RetrievalApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = "retrieval_api_" + uuid4().hex
        config = load_server_config(server_env(self.temp.name + "/evidence", self.database))
        self.app = create_app(config)
        self.store = self.app.state.event_store
        self.store.ensure_ready()
        self.addCleanup(self.store.close)
        self.addCleanup(self.store.database.client.drop_database, self.database)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    # -- helpers ---------------------------------------------------------

    def evidence(self, device_id="lab-edge-01", request_id="req-001", event_id=None):
        event_id = event_id or str(uuid4())
        path = Path(self.temp.name) / f"{request_id}-{uuid4().hex[:6]}.mkv"
        path.write_bytes(b"clip-bytes-for-retrieval")
        manifest = {
            "request_id": request_id,
            "session_id": "sess-1",
            "owner": f"{device_id}/{event_id}/1",
            "requested_start": 90.0,
            "requested_end": 120.0,
            "evidence_anchor_kind": "onset",
            "evidence_anchor_time": 100.0,
            "mapping_uncertainty": 0.0,
            "policy_version": "lab-pre10-post20-v1",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
            "completeness": "complete",
        }
        self.store.record_evidence(device_id, event_id, request_id, manifest, str(path))
        return device_id, event_id, request_id, path, manifest

    def issue(self, evidence, *, target="edge", headers=ALICE, **overrides):
        device_id, event_id, request_id, _, _ = evidence
        body = {"target": target, **overrides}
        return self.client.post(f"/v1/evidence/{device_id}/{event_id}/{request_id}/retrieval",
                                json=body, headers=headers)

    def poll(self, device_id="lab-edge-01", headers=DEVICE_1, wait="0"):
        return self.client.get(f"/v1/devices/{device_id}/commands?wait={wait}", headers=headers)

    def ack(self, command_id, payload, device_id="lab-edge-01", headers=DEVICE_1):
        return self.client.post(f"/v1/devices/{device_id}/commands/{command_id}/ack", json=payload, headers=headers)

    def view(self, command_id, headers=ALICE):
        return self.client.get(f"/v1/retrieval/{command_id}", headers=headers)

    def issued_command(self, *, target="edge", **kwargs):
        evidence = self.evidence(**kwargs)
        response = self.issue(evidence, target=target)
        self.assertEqual(response.status_code, 200, response.text)
        return evidence, response.json()

    # -- issuing ---------------------------------------------------------

    def test_only_a_reviewer_may_issue_a_retrieval(self):
        evidence = self.evidence()
        device_id, event_id, request_id, _, _ = evidence
        url = f"/v1/evidence/{device_id}/{event_id}/{request_id}/retrieval"
        self.assertEqual(self.client.post(url, json={"target": "edge"}).status_code, 401)
        self.assertEqual(self.client.post(url, json={"target": "edge"}, headers=DEVICE_1).status_code, 401)
        self.assertEqual(self.client.post(url, json={"target": "edge"}, headers=DASHBOARD).status_code, 401)
        allowed = self.client.post(url, json={"target": "edge"}, headers=ALICE)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.json()["status"], "offline")  # the device has never polled yet
        self.assertEqual(allowed.json()["issued_by"], "alice")
        self.assertEqual(allowed.json()["retention_scope"], "clip")

    def test_issue_validates_fields_targets_and_unknown_evidence(self):
        evidence = self.evidence()
        self.assertEqual(self.issue(evidence, argv=["ffmpeg"]).status_code, 422)
        self.assertEqual(self.issue(evidence, target="s3").status_code, 422)
        self.assertEqual(self.issue(evidence, ttl_seconds=10_000).status_code, 422)
        self.assertEqual(self.issue(evidence, retention_scope="everything").status_code, 422)
        unsupported = self.issue(evidence, retention_scope="metadata")
        self.assertEqual(unsupported.status_code, 422)
        self.assertIn("retention_scope", unsupported.text)
        device_id, event_id, request_id, _, _ = evidence
        missing = self.client.post(f"/v1/evidence/{device_id}/{event_id}/req-missing/retrieval",
                                   json={"target": "edge"}, headers=ALICE)
        self.assertEqual(missing.status_code, 404)
        malformed = self.client.post(f"/v1/evidence/{device_id}/{event_id}/{request_id}/retrieval",
                                     content=b"{not json", headers={**ALICE, "Content-Type": "application/json"})
        self.assertEqual(malformed.status_code, 400)

    def test_reissue_while_open_returns_the_same_command(self):
        evidence, first = self.issued_command()
        again = self.issue(evidence).json()
        self.assertEqual(again["command_id"], first["command_id"])

    def test_reviewer_site_scope_is_enforced(self):
        database = "retrieval_site_" + uuid4().hex
        env = {
            **server_env(self.temp.name + "/evidence", database),
            "DEVICE_SITES": json.dumps({"lab-edge-01": "site-a"}),
            "REVIEWER_SITES": json.dumps({"alice": ["site-b"]}),
        }
        app = create_app(load_server_config(env))
        store = app.state.event_store
        store.ensure_ready()
        self.addCleanup(store.database.client.drop_database, database)
        client = TestClient(app)
        self.addCleanup(client.close)
        path = Path(self.temp.name) / "scoped.mkv"
        path.write_bytes(b"scoped")
        manifest = {"request_id": "req-001", "sha256": hashlib.sha256(b"scoped").hexdigest(),
                    "size_bytes": path.stat().st_size, "completeness": "complete"}
        store.record_evidence("lab-edge-01", "evt-1", "req-001", manifest, str(path))
        denied = client.post("/v1/evidence/lab-edge-01/evt-1/req-001/retrieval",
                             json={"target": "edge"}, headers=ALICE)
        self.assertEqual(denied.status_code, 403)

    # -- device channel --------------------------------------------------

    def test_device_claims_and_completes_with_an_artifact(self):
        _, command = self.issued_command()
        polled = self.poll()
        self.assertEqual(polled.status_code, 200, polled.text)
        commands = polled.json()["commands"]
        self.assertEqual(len(commands), 1)
        wire = commands[0]
        self.assertEqual(wire["command_id"], command["command_id"])
        self.assertEqual(wire["status"], "claimed")
        self.assertIsInstance(wire["lease_id"], str)
        self.assertEqual(set(wire), {"command_id", "device_id", "target", "action", "evidence", "issued_at",
                                     "expires_at", "retention_scope", "status", "lease_id", "expires_in_seconds"})

        acked = self.ack(command["command_id"], {
            "lease_id": wire["lease_id"], "kind": "artifact",
            "sha256": "c" * 64, "size_bytes": 4096, "actual_ranges": [[90.0, 120.0]],
        })
        self.assertEqual(acked.status_code, 200, acked.text)
        self.assertEqual(acked.json()["status"], "completed")
        self.assertEqual(acked.json()["artifact"], {"sha256": "c" * 64, "size_bytes": 4096,
                                                    "actual_ranges": [[90.0, 120.0]]})
        self.assertEqual(self.view(command["command_id"]).json()["status"], "completed")
        self.assertEqual(self.poll().json()["commands"], [])
        replay = self.ack(command["command_id"], {"lease_id": wire["lease_id"], "kind": "artifact",
                                                  "sha256": "c" * 64, "size_bytes": 4096,
                                                  "actual_ranges": [[90.0, 120.0]]})
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["status"], "completed")

    def test_metadata_ack_never_releases_the_clip_or_closes_the_command(self):
        evidence, command = self.issued_command()
        wire = self.poll().json()["commands"][0]
        acked = self.ack(command["command_id"], {"lease_id": wire["lease_id"], "kind": "metadata"})
        self.assertEqual(acked.status_code, 200, acked.text)
        self.assertEqual(acked.json()["status"], "pending")
        self.assertTrue(acked.json()["metadata_acknowledged"])
        self.assertEqual(self.store.get_evidence(*evidence[:3]).get("manifest", {}).get("sha256"),
                         evidence[4]["sha256"])
        self.assertTrue(evidence[3].is_file())
        done = self.ack(command["command_id"], {"lease_id": wire["lease_id"], "kind": "artifact",
                                                "sha256": evidence[4]["sha256"],
                                                "size_bytes": evidence[4]["size_bytes"]})
        self.assertEqual(done.json()["status"], "completed")
        self.assertTrue(evidence[3].is_file())

    def test_offline_until_the_device_polls(self):
        _, command = self.issued_command()
        self.assertEqual(self.view(command["command_id"]).json()["status"], "offline")
        self.poll()
        self.assertEqual(self.view(command["command_id"]).json()["status"], "pending")

    def test_expired_command_is_never_delivered(self):
        evidence = self.evidence()
        device_id, event_id, request_id, _, _ = evidence
        issued = self.store.issue_retrieval(device_id, event_id, request_id, target="edge",
                                           issued_by="alice", ttl_seconds=10, now=time.time() - 60)
        self.assertEqual(self.poll().json()["commands"], [])
        self.assertEqual(self.view(issued["command_id"]).json()["status"], "expired")

    def test_stale_lease_foreign_device_and_unknown_command_are_refused(self):
        _, command = self.issued_command()
        wire = self.poll().json()["commands"][0]
        stale = self.ack(command["command_id"], {"lease_id": "not-the-lease", "kind": "metadata"})
        self.assertEqual(stale.status_code, 409, stale.text)
        foreign = self.ack(command["command_id"], {"lease_id": wire["lease_id"], "kind": "metadata"},
                           device_id="lab-edge-02", headers=DEVICE_2)
        self.assertEqual(foreign.status_code, 404)
        unknown = self.ack("cmd-does-not-exist", {"lease_id": wire["lease_id"], "kind": "metadata"})
        self.assertEqual(unknown.status_code, 404)
        bad_kind = self.ack(command["command_id"], {"lease_id": wire["lease_id"], "kind": "execute"})
        self.assertEqual(bad_kind.status_code, 422)

    def test_poll_requires_a_matching_device_token_and_bounded_wait(self):
        self.assertEqual(self.poll(headers=ALICE).status_code, 401)
        self.assertEqual(self.poll(device_id="lab-edge-02").status_code, 403)
        self.assertEqual(self.poll(headers=DEVICE_2, device_id="lab-edge-02").status_code, 200)
        self.assertEqual(self.poll(wait="99").status_code, 422)
        self.assertEqual(self.poll(wait="soon").status_code, 422)

    def test_long_poll_waits_then_returns_no_commands(self):
        started = time.monotonic()
        response = self.poll(wait="0.15")
        elapsed = time.monotonic() - started
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commands"], [])
        self.assertGreaterEqual(elapsed, 0.1)

    def test_quarantined_device_cannot_poll_or_acknowledge(self):
        _, command = self.issued_command()
        self.store.enroll_device("lab-edge-01", "site-a")
        self.store.quarantine_device("lab-edge-01", reason="maintenance")
        self.assertEqual(self.poll().status_code, 403)
        self.assertEqual(self.ack(command["command_id"], {"lease_id": "x", "kind": "metadata"}).status_code, 403)

    # -- server target and the cleanup race ------------------------------

    def test_server_target_settles_from_availability_and_survives_metadata_only(self):
        evidence, command = self.issued_command(target="server")
        settled = self.view(command["command_id"])
        self.assertEqual(settled.status_code, 200, settled.text)
        self.assertEqual(settled.json()["status"], "completed")
        self.assertEqual(settled.json()["artifact"]["size_bytes"], evidence[4]["size_bytes"])
        self.assertTrue(evidence[3].is_file())

    def test_cleanup_that_removes_the_clip_is_reported_as_a_failure(self):
        evidence, first = self.issued_command(target="server")
        self.assertEqual(self.view(first["command_id"]).json()["status"], "completed")
        evidence[3].unlink()
        device_id, event_id, request_id, _, _ = evidence
        second = self.store.issue_retrieval(device_id, event_id, request_id, target="server", issued_by="alice")
        view = self.view(second["command_id"]).json()
        self.assertEqual((view["status"], view["reason"]), ("failed", "evidence_unavailable"))
        self.assertIsNotNone(self.store.get_evidence(device_id, event_id, request_id),
                             "the manifest receipt must survive even when the clip was cleaned")


if __name__ == "__main__":
    unittest.main()
