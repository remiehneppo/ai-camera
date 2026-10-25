"""Integration test suite for Ticket #33: Device lifecycle and site access enforcement."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.server.config import load_server_config
from apps.server.main import create_app
from apps.server.store import EventStore
from domain.device_contract import (
    DeviceRecord,
    ReviewerAccessRecord,
    STATUS_ACTIVE,
    STATUS_QUARANTINED,
    STATUS_REVOKED,
    check_device_access,
    check_reviewer_site_access,
    quarantine_device,
    reactivate_device,
    revoke_device,
    transition_device,
)


def custom_server_env(evidence_dir: str, db_name: str) -> dict[str, str]:
    return {
        "DEVICE_TOKENS": json.dumps({
            "token-edge-site-a": "edge-dev-site-a",
            "token-edge-site-b": "edge-dev-site-b",
            "token-edge-revoked": "edge-dev-revoked",
        }),
        "DEVICE_SITES": json.dumps({
            "edge-dev-site-a": "site-district-1",
            "edge-dev-site-b": "site-district-2",
            "edge-dev-revoked": "site-district-1",
        }),
        "REVIEWER_TOKENS": json.dumps({
            "reviewer_site_a": "token-rev-a",
            "reviewer_site_b": "token-rev-b",
            "reviewer_global": "token-rev-global",
        }),
        "REVIEWER_SITES": json.dumps({
            "reviewer_site_a": ["site-district-1"],
            "reviewer_site_b": ["site-district-2"],
            "reviewer_global": [],
        }),
        "DASHBOARD_TOKEN": "dashboard-secret-admin",
        "MONGO_URI": "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true",
        "MONGO_DATABASE": db_name,
        "EVIDENCE_DIR": evidence_dir,
    }


def make_test_event(device_id: str, camera_id: str = "cam-01") -> dict[str, object]:
    eid = str(uuid4())
    session_id = str(uuid4())
    return {
        "schema_version": 1,
        "message_id": f"msg-{uuid4().hex[:8]}",
        "event_id": eid,
        "revision": 1,
        "device_id": device_id,
        "camera_id": camera_id,
        "stream_session_id": session_id,
        "pipeline_id": "synthetic-pipeline",
        "pipeline_version": "1",
        "origin": "synthetic",
        "event_time": "2026-10-22T00:00:00Z",
        "produced_at": "2026-10-22T00:00:01Z",
        "config_version": "synthetic-v1",
        "model_lineage": [{"role": "fixture", "version": "1"}],
        "model_artifact_hash": "unknown_hash",
        "calibration_version": "uncalibrated",
        "quality_state": "normal",
        "payload": {
            "taxonomy": "person_fall",
            "lifecycle": "candidate",
            "severity": "high",
            "evidence_requests": [
                {
                    "request_id": "req-001",
                    "session_id": session_id,
                    "evidence_anchor_kind": "synthetic",
                    "evidence_anchor_time": 100.0,
                    "requested_start": 90.0,
                    "requested_end": 120.0,
                    "mapping_uncertainty": 0.0,
                    "policy_version": "lab-pre10-post20-v1",
                    "supersedes_request_id": None,
                }
            ],
        },
    }


class TestDeviceLifecycleFlow(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_name = f"test_lifecycle_{uuid4().hex[:8]}"
        self.env = custom_server_env(self.tmp.name, self.db_name)
        self.config = load_server_config(self.env)
        self.app = create_app(self.config)
        self.client = TestClient(self.app)
        self.store: EventStore = self.app.state.event_store
        self.store.ensure_ready()

        # Enroll devices in MongoDB store with initial lifecycle state
        self.dev_a = self.store.enroll_device("edge-dev-site-a", "site-district-1", allowed_cameras=["cam-01", "cam-02"])
        self.dev_b = self.store.enroll_device("edge-dev-site-b", "site-district-2", allowed_cameras=["cam-b1"])
        self.dev_rev = self.store.enroll_device("edge-dev-revoked", "site-district-1")
        self.store.revoke_device("edge-dev-revoked", reason="compromised_key")

    def tearDown(self) -> None:
        self.store.client.drop_database(self.db_name)
        self.store.close()
        self.tmp.cleanup()

    def test_revoked_device_is_denied_on_ingest(self) -> None:
        event = make_test_event("edge-dev-revoked")
        res = self.client.post(
            "/v1/events",
            headers={
                "Authorization": "Bearer token-edge-revoked",
                "Content-Type": "application/json",
                "Idempotency-Key": str(event["message_id"]),
            },
            json=event,
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("device_credential_revoked", res.json()["detail"])

    def test_device_routes_reject_a_non_object_body_without_a_500(self) -> None:
        headers = {"Authorization": "Bearer dashboard-secret-admin", "Content-Type": "application/json"}
        for route in ("quarantine", "reactivate", "revoke"):
            for payload in ([{"reason": "array"}], "string", 5):
                res = self.client.post(
                    f"/v1/devices/edge-dev-site-a/{route}", content=json.dumps(payload), headers=headers
                )
                self.assertEqual(res.status_code, 422, (route, payload))
            empty = self.client.post(
                f"/v1/devices/edge-dev-site-a/{route}",
                content=b"",
                headers={"Authorization": "Bearer dashboard-secret-admin", "Content-Type": "application/json"},
            )
            self.assertIn(empty.status_code, (200, 404), (route, empty.text))

    def test_quarantined_device_is_denied_and_can_be_reactivated(self) -> None:
        # Quarantine device A via admin endpoint
        q_res = self.client.post(
            "/v1/devices/edge-dev-site-a/quarantine",
            headers={"Authorization": "Bearer dashboard-secret-admin"},
            json={"reason": "anomaly_detected"},
        )
        self.assertEqual(q_res.status_code, 200)
        self.assertEqual(q_res.json()["status"], STATUS_QUARANTINED)

        # Ingestion should now be denied
        event = make_test_event("edge-dev-site-a", camera_id="cam-01")
        res = self.client.post(
            "/v1/events",
            headers={
                "Authorization": "Bearer token-edge-site-a",
                "Content-Type": "application/json",
                "Idempotency-Key": str(event["message_id"]),
            },
            json=event,
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("device_quarantined", res.json()["detail"])

        # Reactivate device A
        r_res = self.client.post(
            "/v1/devices/edge-dev-site-a/reactivate",
            headers={"Authorization": "Bearer dashboard-secret-admin"},
            json={"reason": "inspection_cleared"},
        )
        self.assertEqual(r_res.status_code, 200)
        self.assertEqual(r_res.json()["status"], STATUS_ACTIVE)

        # Ingestion should succeed now
        res_ok = self.client.post(
            "/v1/events",
            headers={
                "Authorization": "Bearer token-edge-site-a",
                "Content-Type": "application/json",
                "Idempotency-Key": str(event["message_id"]),
            },
            json=event,
        )
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.json()["accepted"])

    def test_disallowed_camera_for_device_is_denied(self) -> None:
        # device-a only allows cam-01 and cam-02
        event = make_test_event("edge-dev-site-a", camera_id="unauthorized-cam-99")
        res = self.client.post(
            "/v1/events",
            headers={
                "Authorization": "Bearer token-edge-site-a",
                "Content-Type": "application/json",
                "Idempotency-Key": str(event["message_id"]),
            },
            json=event,
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("camera_not_allowed_for_device", res.json()["detail"])

    def test_cross_site_review_access_is_denied(self) -> None:
        # Ingest event from site A (device-a)
        event = make_test_event("edge-dev-site-a", camera_id="cam-01")
        self.client.post(
            "/v1/events",
            headers={
                "Authorization": "Bearer token-edge-site-a",
                "Content-Type": "application/json",
                "Idempotency-Key": str(event["message_id"]),
            },
            json=event,
        )

        review_payload = {
            "action": "confirm",
            "expected_review_version": 0,
            "viewed_event_revision": 1,
            "viewed_event_hash": hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "viewed_evidence_versions": {},
            "reason": "verified on site",
        }

        # Reviewer B is scoped to site-district-2 -> reviewing site A event must be denied 403!
        res_b = self.client.post(
            f"/v1/events/edge-dev-site-a/{event['event_id']}/review",
            headers={"Authorization": "Bearer token-rev-b", "Content-Type": "application/json"},
            json=review_payload,
        )
        self.assertEqual(res_b.status_code, 403)
        self.assertIn("cross-site review access denied", res_b.json()["detail"])

        # Reviewer A is scoped to site-district-1 -> review succeeds
        # First get canonical event hash
        cur = self.client.get("/v1/events", headers={"Authorization": "Bearer dashboard-secret-admin"}).json()["events"][0]
        review_payload["viewed_event_hash"] = cur["event_hash"]

        res_a = self.client.post(
            f"/v1/events/edge-dev-site-a/{event['event_id']}/review",
            headers={"Authorization": "Bearer token-rev-a", "Content-Type": "application/json"},
            json=review_payload,
        )
        self.assertEqual(res_a.status_code, 200)
        self.assertEqual(res_a.json()["decision"], "confirmed")

    def test_cross_site_dataset_export_is_denied(self) -> None:
        # Reviewer A tries to export site B -> 403 denied
        res_denied = self.client.get(
            "/v1/dataset/export?site_id=site-district-2",
            headers={"Authorization": "Bearer token-rev-a"},
        )
        self.assertEqual(res_denied.status_code, 403)
        self.assertIn("cross-site export access denied", res_denied.json()["detail"])

        # Reviewer A exports their allowed site -> 200 OK
        res_ok = self.client.get(
            "/v1/dataset/export?site_id=site-district-1",
            headers={"Authorization": "Bearer token-rev-a"},
        )
        self.assertEqual(res_ok.status_code, 200)

    def test_cross_site_raw_evidence_read_is_denied(self) -> None:
        # Ingest event from site A
        event = make_test_event("edge-dev-site-a", camera_id="cam-01")
        self.client.post(
            "/v1/events",
            headers={
                "Authorization": "Bearer token-edge-site-a",
                "Content-Type": "application/json",
                "Idempotency-Key": str(event["message_id"]),
            },
            json=event,
        )

        # Upload dummy evidence for site A
        dummy_video = b"test-mp4-video-data"
        sha = hashlib.sha256(dummy_video).hexdigest()
        meta = json.dumps({"content_type": "video/mp4", "size_bytes": len(dummy_video), "owner": f"edge-dev-site-a/{event['event_id']}/1"})
        upload_res = self.client.put(
            f"/v1/evidence/edge-dev-site-a/{event['event_id']}/req-001",
            headers={
                "Authorization": "Bearer token-edge-site-a",
                "X-Evidence-Sha256": sha,
                "X-Evidence-Metadata": meta,
            },
            content=dummy_video,
        )
        self.assertEqual(upload_res.status_code, 200)

        # Reviewer B (site 2) tries to read manifest of site 1 -> 403 denied
        manifest_res_b = self.client.get(
            f"/v1/evidence/edge-dev-site-a/{event['event_id']}/req-001",
            headers={"Authorization": "Bearer token-rev-b"},
        )
        self.assertEqual(manifest_res_b.status_code, 403)
        self.assertIn("cross-site evidence access denied", manifest_res_b.json()["detail"])

        # Reviewer B (site 2) tries to read media binary of site 1 -> 403 denied
        media_res_b = self.client.get(
            f"/v1/evidence/edge-dev-site-a/{event['event_id']}/req-001/media",
            headers={"Authorization": "Bearer token-rev-b"},
        )
        self.assertEqual(media_res_b.status_code, 403)
        self.assertIn("cross-site evidence access denied", media_res_b.json()["detail"])

        # Reviewer A (site 1) reads manifest and media -> 200 OK
        manifest_res_a = self.client.get(
            f"/v1/evidence/edge-dev-site-a/{event['event_id']}/req-001",
            headers={"Authorization": "Bearer token-rev-a"},
        )
        self.assertEqual(manifest_res_a.status_code, 200)

        media_res_a = self.client.get(
            f"/v1/evidence/edge-dev-site-a/{event['event_id']}/req-001/media",
            headers={"Authorization": "Bearer token-rev-a"},
        )
        self.assertEqual(media_res_a.status_code, 200)

    def test_rotate_device_token(self) -> None:
        updated = self.store.rotate_device_token("edge-dev-site-a", new_site_id="site-district-new")
        self.assertEqual(updated.site_id, "site-district-new")
        self.assertEqual(self.store.get_device("edge-dev-site-a").site_id, "site-district-new")


if __name__ == "__main__":
    unittest.main()
