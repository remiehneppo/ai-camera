from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.server.config import load_server_config
from apps.server.dataset import (
    export_dataset_records,
    redact_sensitive_data,
    split_dataset,
)
from apps.server.export_dataset import main as cli_main
from apps.server.main import create_app
from apps.server.store import EventStore


def server_env(evidence_dir: str, db_name: str) -> dict[str, str]:
    return {
        "DEVICE_TOKENS": json.dumps({"token-edge-1": "lab-edge-01", "token-edge-2": "lab-edge-02"}),
        "DASHBOARD_TOKEN": "dashboard-secret-token",
        "REVIEWER_TOKENS": json.dumps({"alice": "reviewer-secret-alice", "bob": "reviewer-secret-bob"}),
        "MONGO_URI": "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true",
        "MONGO_DATABASE": db_name,
        "EVIDENCE_DIR": evidence_dir,
    }


def sample_event(
    device_id: str = "lab-edge-01",
    event_id: str | None = None,
    revision: int = 1,
    camera_id: str = "lab-camera-01",
    severity: str = "high",
    evidence_versions: dict[str, str] | None = None,
    stream_session_id: str | None = None,
) -> dict[str, object]:
    eid = event_id or str(uuid4())
    session_id = stream_session_id or str(uuid4())
    return {
        "schema_version": 1,
        "message_id": f"msg-{uuid4().hex[:8]}",
        "event_id": eid,
        "revision": revision,
        "device_id": device_id,
        "camera_id": camera_id,
        "stream_session_id": session_id,
        "pipeline_id": "synthetic-fixture",
        "pipeline_version": "1",
        "origin": "synthetic",
        "event_time": "2026-10-13T00:00:00Z",
        "produced_at": "2026-10-13T00:00:01Z",
        "config_version": "synthetic-v1",
        "model_lineage": [{"role": "fixture", "version": "1"}],
        "model_artifact_hash": "hash_art_12345",
        "calibration_version": "uncalibrated",
        "quality_state": "normal",
        "payload": {
            "taxonomy": "person_fall",
            "lifecycle": "candidate",
            "severity": severity,
            "confidence": 0.88,
            "detections": [{"class": "person", "bbox": [10, 20, 100, 200], "confidence": 0.88}],
            "evidence_versions": evidence_versions or {},
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


class DatasetLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_name = f"test_lineage_{uuid4().hex[:12]}"
        self.store = EventStore(
            "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true",
            self.db_name,
        )
        self.store.ensure_ready()
        self.env = server_env(self.temp_dir.name, self.db_name)
        self.cfg = load_server_config(self.env)
        self.app = create_app(self.cfg)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.store.database.client.drop_database(self.db_name)
        self.store.close()
        if hasattr(self.app.state, "event_store"):
            self.app.state.event_store.close()
        self.temp_dir.cleanup()

    def test_export_lineage_joins_reviewed_revision_not_current(self) -> None:
        event_id = str(uuid4())
        device_id = "lab-edge-01"
        session_id = str(uuid4())

        # 1. Persist revision 1
        ev1 = sample_event(device_id=device_id, event_id=event_id, revision=1, severity="low", stream_session_id=session_id)
        r1 = self.store.persist(ev1)

        # 2. Review revision 1
        review_req = {
            "action": "confirm",
            "reason": "verified person down at rev 1",
            "expected_review_version": 0,
            "viewed_event_revision": 1,
            "viewed_event_hash": r1["event_hash"],
            "viewed_evidence_versions": {},
        }
        self.store.record_review({"device_id": device_id, "event_id": event_id}, review_req, "alice")

        # 3. Persist revision 2 with different payload
        ev2 = sample_event(device_id=device_id, event_id=event_id, revision=2, severity="critical", stream_session_id=session_id)
        ev2["payload"]["confidence"] = 0.99  # type: ignore[index]
        self.store.persist(ev2)

        # 4. Export records
        records = export_dataset_records(self.store, include_ambiguous=True)
        self.assertEqual(len(records), 1)
        rec = records[0]

        # Verify exact lineage connects to revision 1 (what reviewer saw), not revision 2!
        self.assertEqual(rec["event_id"], event_id)
        self.assertEqual(rec["device_id"], device_id)
        self.assertEqual(rec["reviewed_event_revision"], 1)
        self.assertEqual(rec["reviewed_event_hash"], r1["event_hash"])
        self.assertEqual(rec["reviewed_decision"], "confirmed")
        self.assertEqual(rec["actor"], "alice")
        self.assertEqual(rec["reason"], "verified person down at rev 1")

        # Original AI payload must be from revision 1 (low severity, 0.88 confidence), not overwritten
        self.assertEqual(rec["original_ai_payload"]["severity"], "low")
        self.assertEqual(rec["original_ai_payload"]["confidence"], 0.88)

        # Reviewer correction did NOT overwrite the original event or current event
        current = self.store.current.find_one({"device_id": device_id, "event_id": event_id})
        assert current is not None
        self.assertEqual(current["event"]["payload"]["severity"], "critical")

    def test_correction_audit_trail_and_evidence_manifest_captured(self) -> None:
        event_id = str(uuid4())
        device_id = "lab-edge-01"
        ev = sample_event(
            device_id=device_id,
            event_id=event_id,
            revision=1,
            evidence_versions={"req-001": "hash-ev-1"},
        )
        r = self.store.persist(ev)

        # Record evidence manifest
        manifest_data = {
            "actual_range": [10.0, 20.0],
            "completeness": "complete",
            "codec": "h264",
            "sha256": "aabbcc" * 10 + "1234",
            "size_bytes": 2048,
        }
        self.store.record_evidence(device_id, event_id, "req-001", manifest_data, "/tmp/clip_001.mkv")

        # Step 1: Alice marks false_positive
        self.store.record_review(
            {"device_id": device_id, "event_id": event_id},
            {
                "action": "false_positive",
                "reason": "looked like shadow",
                "expected_review_version": 0,
                "viewed_event_revision": 1,
                "viewed_event_hash": r["event_hash"],
                "viewed_evidence_versions": {"req-001": "hash-ev-1"},
            },
            "alice",
        )

        # Step 2: Bob reopens
        self.store.record_review(
            {"device_id": device_id, "event_id": event_id},
            {
                "action": "reopen",
                "reason": "senior review requested",
                "expected_review_version": 1,
                "viewed_event_revision": 1,
                "viewed_event_hash": r["event_hash"],
                "viewed_evidence_versions": {"req-001": "hash-ev-1"},
            },
            "bob",
        )

        # Step 3: Bob confirms
        self.store.record_review(
            {"device_id": device_id, "event_id": event_id},
            {
                "action": "confirm",
                "reason": "confirmed fall on senior check",
                "expected_review_version": 2,
                "viewed_event_revision": 1,
                "viewed_event_hash": r["event_hash"],
                "viewed_evidence_versions": {"req-001": "hash-ev-1"},
            },
            "bob",
        )

        records = export_dataset_records(self.store, include_ambiguous=True)
        self.assertEqual(len(records), 1)
        rec = records[0]

        self.assertEqual(rec["reviewed_decision"], "confirmed")
        self.assertEqual(rec["review_version"], 3)
        self.assertEqual(rec["actor"], "bob")

        # Check audit trail
        self.assertEqual(len(rec["review_audit_trail"]), 3)
        self.assertEqual(rec["review_audit_trail"][0]["action"], "false_positive")
        self.assertEqual(rec["review_audit_trail"][1]["action"], "reopen")
        self.assertEqual(rec["review_audit_trail"][2]["action"], "confirm")

        # Evidence manifest summary
        self.assertIn("evidence_manifests", rec)
        em = rec["evidence_manifests"]
        self.assertEqual(len(em), 1)
        self.assertEqual(em[0]["request_id"], "req-001")
        self.assertEqual(em[0]["sha256"], manifest_data["sha256"])
        self.assertEqual(em[0]["size_bytes"], 2048)
        self.assertEqual(em[0]["completeness"], "complete")
        # Ensure path does not leak internal full temp directory
        self.assertNotIn("/home/", em[0]["location"])

    def test_ambiguous_filter_and_reopen_status(self) -> None:
        event_id1 = str(uuid4())
        device_id = "lab-edge-01"
        ev1 = sample_event(device_id=device_id, event_id=event_id1, revision=1)
        r1 = self.store.persist(ev1)

        # Review as false_positive then reopen (decision becomes reopened)
        self.store.record_review(
            {"device_id": device_id, "event_id": event_id1},
            {
                "action": "false_positive",
                "reason": "initial",
                "expected_review_version": 0,
                "viewed_event_revision": 1,
                "viewed_event_hash": r1["event_hash"],
                "viewed_evidence_versions": {},
            },
            "alice",
        )
        self.store.record_review(
            {"device_id": device_id, "event_id": event_id1},
            {
                "action": "reopen",
                "reason": "disputed",
                "expected_review_version": 1,
                "viewed_event_revision": 1,
                "viewed_event_hash": r1["event_hash"],
                "viewed_evidence_versions": {},
            },
            "bob",
        )

        event_id2 = str(uuid4())
        ev2 = sample_event(device_id=device_id, event_id=event_id2, revision=1)
        r2 = self.store.persist(ev2)
        self.store.record_review(
            {"device_id": device_id, "event_id": event_id2},
            {
                "action": "confirm",
                "reason": "good fall",
                "expected_review_version": 0,
                "viewed_event_revision": 1,
                "viewed_event_hash": r2["event_hash"],
                "viewed_evidence_versions": {},
            },
            "alice",
        )

        # By default include_ambiguous=False -> reopened event is filtered out
        clean_records = export_dataset_records(self.store, include_ambiguous=False)
        self.assertEqual(len(clean_records), 1)
        self.assertEqual(clean_records[0]["event_id"], event_id2)

        # When include_ambiguous=True -> both are returned, event 1 is flagged
        all_records = export_dataset_records(self.store, include_ambiguous=True)
        self.assertEqual(len(all_records), 2)
        rec1 = next(r for r in all_records if r["event_id"] == event_id1)
        self.assertTrue(rec1["is_ambiguous"])
        self.assertEqual(rec1["reviewed_decision"], "reopened")

    def test_sensitive_data_redaction(self) -> None:
        data = {
            "event_id": "ev-1",
            "device_id": "lab-edge-01",
            "token": "secret-device-token",
            "authorization": "Bearer xyz123",
            "nested": {
                "secret_key": "my-secret-key",
                "api_key": "some-key",
                "camera_id": "cam-1",
            },
            "public_field": "safe",
        }
        redacted = redact_sensitive_data(data)
        self.assertEqual(redacted["event_id"], "ev-1")
        self.assertEqual(redacted["public_field"], "safe")
        self.assertNotIn("token", redacted)
        self.assertNotIn("authorization", redacted)
        self.assertNotIn("secret_key", redacted["nested"])
        self.assertNotIn("api_key", redacted["nested"])
        self.assertEqual(redacted["nested"]["camera_id"], "cam-1")

    def test_dataset_splitting_deterministic_and_no_camera_leakage(self) -> None:
        records: list[dict[str, object]] = []
        for i in range(30):
            records.append({
                "event_id": f"ev-{i}",
                "device_id": f"dev-{i % 3}",
                "camera_id": f"cam-0{i % 5}",
                "occurred_at": f"2026-10-13T{i:02d}:00:00Z",
                "reviewed_decision": "confirmed",
            })

        split_records = split_dataset(
            records,
            train_ratio=0.7,
            val_ratio=0.15,
            test_ratio=0.15,
            split_by="camera",
        )

        train_cameras = {r["camera_id"] for r in split_records if r["split"] == "train"}
        val_cameras = {r["camera_id"] for r in split_records if r["split"] == "val"}
        test_cameras = {r["camera_id"] for r in split_records if r["split"] == "test"}

        # No camera leakage across splits
        self.assertTrue(train_cameras.isdisjoint(val_cameras))
        self.assertTrue(train_cameras.isdisjoint(test_cameras))
        self.assertTrue(val_cameras.isdisjoint(test_cameras))

        # Deterministic check: splitting again yields identical split field for all records
        split_records_2 = split_dataset(
            records,
            train_ratio=0.7,
            val_ratio=0.15,
            test_ratio=0.15,
            split_by="camera",
        )
        self.assertEqual(
            [r["split"] for r in split_records],
            [r["split"] for r in split_records_2],
        )

    def test_api_dataset_export_endpoint(self) -> None:
        # Ingest and review an event
        event_id = str(uuid4())
        device_id = "lab-edge-01"
        ev = sample_event(device_id=device_id, event_id=event_id, revision=1)
        r = self.store.persist(ev)
        self.store.record_review(
            {"device_id": device_id, "event_id": event_id},
            {
                "action": "confirm",
                "reason": "api test confirm",
                "expected_review_version": 0,
                "viewed_event_revision": 1,
                "viewed_event_hash": r["event_hash"],
                "viewed_evidence_versions": {},
            },
            "alice",
        )

        # 1. Unauthenticated request -> 401
        res_no_auth = self.client.get("/v1/dataset/export")
        self.assertEqual(res_no_auth.status_code, 401)

        # 2. Reviewer token -> 200 JSONL format
        headers = {"Authorization": "Bearer reviewer-secret-alice"}
        res = self.client.get("/v1/dataset/export", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/x-ndjson", res.headers.get("content-type", ""))
        lines = [json.loads(line) for line in res.text.strip().split("\n") if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["event_id"], event_id)
        self.assertEqual(lines[0]["reviewed_decision"], "confirmed")
        self.assertIn("split", lines[0])

        # 3. Dashboard token with format=json
        headers_dash = {"Authorization": "Bearer dashboard-secret-token"}
        res_json = self.client.get("/v1/dataset/export?format=json", headers=headers_dash)
        self.assertEqual(res_json.status_code, 200)
        data = res_json.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["records"][0]["event_id"], event_id)

        # 4. Filter by decision
        res_fp = self.client.get("/v1/dataset/export?decision=false_positive", headers=headers)
        self.assertEqual(res_fp.status_code, 200)
        self.assertEqual(res_fp.text.strip(), "")

    def test_cli_export_dataset(self) -> None:
        event_id = str(uuid4())
        device_id = "lab-edge-01"
        ev = sample_event(device_id=device_id, event_id=event_id, revision=1)
        r = self.store.persist(ev)
        self.store.record_review(
            {"device_id": device_id, "event_id": event_id},
            {
                "action": "confirm",
                "reason": "cli test",
                "expected_review_version": 0,
                "viewed_event_revision": 1,
                "viewed_event_hash": r["event_hash"],
                "viewed_evidence_versions": {},
            },
            "alice",
        )

        out_file = os.path.join(self.temp_dir.name, "exported.jsonl")
        exit_code = cli_main([
            "--mongo-uri", "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true",
            "--database", self.db_name,
            "--output", out_file,
            "--format", "jsonl",
        ])
        self.assertEqual(exit_code, 0)
        self.assertTrue(os.path.exists(out_file))

        with open(out_file, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["event_id"], event_id)
        self.assertEqual(lines[0]["reviewed_decision"], "confirmed")


if __name__ == "__main__":
    unittest.main()
