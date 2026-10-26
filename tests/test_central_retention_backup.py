"""Tests for Central Retention Policy and Backup/Restore Reconciliation Proof (Ticket #43)."""

from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from typing import Any

from apps.server.retention import (
    CentralRetentionManager,
    create_backup_bundle,
    restore_and_reconcile,
)
from domain.retention_contract import (
    ACTION_CENTRAL_DELETE,
    ACTION_CENTRAL_EXPORT,
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_EXPIRED,
    AVAILABILITY_MISSING,
    AVAILABILITY_PENDING,
    AVAILABILITY_QUARANTINED,
    DEFAULT_CENTRAL_RETENTION_SECONDS,
    HA_DISCLAIMER,
    IMMUTABLE_RECEIPT_FIELDS,
    INTEGRITY_CORRUPT,
    INTEGRITY_VERIFIED,
    RECONCILE_CORRUPT,
    RECONCILE_MISSING,
    RECONCILE_ORPHAN,
    RECONCILE_PENDING,
    RECONCILE_VERIFIED,
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_REVIEWER,
    RetentionError,
    RetentionPolicy,
    authorize_retention_action,
    evaluate_retention_candidate,
)


def _make_clip_file(base_dir: Path, device_id: str, event_id: str, request_id: str, content: bytes) -> tuple[Path, str, int]:
    clip_dir = base_dir / device_id / event_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    clip_path = clip_dir / f"{request_id}.mkv"
    clip_path.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    return clip_path, sha, len(content)


def _make_manifest_record(
    device_id: str,
    event_id: str,
    request_id: str,
    *,
    file_path: Path | None,
    sha256: str | None,
    size_bytes: int | None,
    uploaded_at: float,
    build_state: str = "finalized",
    legal_hold: bool = False,
    pinned: bool = False,
) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "event_id": event_id,
        "request_id": request_id,
        "uploaded_at": uploaded_at,
        "status": "available" if build_state == "finalized" else "pending",
        "legal_hold": legal_hold,
        "pinned": pinned,
        "file_path": str(file_path) if file_path is not None else None,
        "manifest": {
            "device_id": device_id,
            "event_id": event_id,
            "request_id": request_id,
            "build_state": build_state,
            "completeness": "complete",
            "transfer_state": "acknowledged" if build_state == "finalized" else "uploading",
            "sha256": sha256,
            "size_bytes": size_bytes,
            "requested_start": 100.0,
            "requested_end": 130.0,
            "actual_start": 99.5,
            "actual_end": 130.5,
            "file_status": "available" if build_state == "finalized" else "pending",
            "locations": {
                "server": {
                    "availability": "available" if build_state == "finalized" else "pending",
                    "integrity": "verified" if build_state == "finalized" else "unverified",
                }
            },
        },
    }


class TestCentralRetentionPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.evidence_dir = Path(self.temp_dir.name) / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_retention_protects_unexpired_open_retrieval_legal_hold_and_unreviewed_critical(self) -> None:
        now = 1_000_000.0
        old_ts = now - DEFAULT_CENTRAL_RETENTION_SECONDS - 3600.0
        fresh_ts = now - 3600.0

        p_fresh, sha_fresh, sz_fresh = _make_clip_file(self.evidence_dir, "dev-1", "ev-fresh", "req-1", b"fresh-clip")
        p_retr, sha_retr, sz_retr = _make_clip_file(self.evidence_dir, "dev-1", "ev-retr", "req-2", b"retrieval-clip")
        p_hold, sha_hold, sz_hold = _make_clip_file(self.evidence_dir, "dev-1", "ev-hold", "req-3", b"legal-hold-clip")
        p_crit, sha_crit, sz_crit = _make_clip_file(self.evidence_dir, "dev-1", "ev-crit", "req-4", b"unreviewed-crit")
        p_exp, sha_exp, sz_exp = _make_clip_file(self.evidence_dir, "dev-1", "ev-exp", "req-5", b"expired-eligible")

        store: dict[str, list[dict[str, Any]]] = {
            "evidence_manifests": [
                _make_manifest_record("dev-1", "ev-fresh", "req-1", file_path=p_fresh, sha256=sha_fresh, size_bytes=sz_fresh, uploaded_at=fresh_ts),
                _make_manifest_record("dev-1", "ev-retr", "req-2", file_path=p_retr, sha256=sha_retr, size_bytes=sz_retr, uploaded_at=old_ts),
                _make_manifest_record("dev-1", "ev-hold", "req-3", file_path=p_hold, sha256=sha_hold, size_bytes=sz_hold, uploaded_at=old_ts, legal_hold=True),
                _make_manifest_record("dev-1", "ev-crit", "req-4", file_path=p_crit, sha256=sha_crit, size_bytes=sz_crit, uploaded_at=old_ts),
                _make_manifest_record("dev-1", "ev-exp", "req-5", file_path=p_exp, sha256=sha_exp, size_bytes=sz_exp, uploaded_at=old_ts),
            ],
            "retrieval_commands": [
                {
                    "command_id": "cmd-open-1",
                    "device_id": "dev-1",
                    "status": "claimed",
                    "evidence": {"device_id": "dev-1", "event_id": "ev-retr", "request_id": "req-2"},
                }
            ],
            "current_events": [
                {"device_id": "dev-1", "event_id": "ev-crit", "site_id": "site-a", "snapshot": {"severity": "critical"}},
                {"device_id": "dev-1", "event_id": "ev-exp", "site_id": "site-a", "snapshot": {"severity": "low"}},
            ],
            "event_reviews": [
                {"device_id": "dev-1", "event_id": "ev-crit", "decision": "unreviewed"},
                {"device_id": "dev-1", "event_id": "ev-exp", "decision": "false_positive"},
            ],
        }

        mgr = CentralRetentionManager(store, self.evidence_dir)
        report = mgr.run_retention_sweep(now=now)

        self.assertEqual(report["expired_count"], 1)
        self.assertEqual(report["kept_count"], 4)
        self.assertFalse(p_exp.exists())
        self.assertTrue(p_fresh.exists())
        self.assertTrue(p_retr.exists())
        self.assertTrue(p_hold.exists())
        self.assertTrue(p_crit.exists())

        # Verify immutable receipt fields survived on expired manifest
        expired_rec = [m for m in store["evidence_manifests"] if m["event_id"] == "ev-exp"][0]
        exp_manifest = expired_rec["manifest"]
        self.assertEqual(exp_manifest["file_status"], AVAILABILITY_EXPIRED)
        self.assertEqual(exp_manifest["locations"]["server"]["availability"], AVAILABILITY_EXPIRED)
        self.assertEqual(exp_manifest["sha256"], sha_exp)
        self.assertEqual(exp_manifest["size_bytes"], sz_exp)
        self.assertEqual(exp_manifest["requested_start"], 100.0)
        self.assertEqual(exp_manifest["requested_end"], 130.0)

    def test_rbac_and_audit_on_delete_and_export(self) -> None:
        now = 2_000_000.0
        p_clip, sha_clip, sz_clip = _make_clip_file(self.evidence_dir, "dev-1", "ev-1", "req-1", b"clip-bytes")
        store: dict[str, list[dict[str, Any]]] = {
            "evidence_manifests": [
                _make_manifest_record("dev-1", "ev-1", "req-1", file_path=p_clip, sha256=sha_clip, size_bytes=sz_clip, uploaded_at=now - 100),
            ],
            "current_events": [
                {"device_id": "dev-1", "event_id": "ev-1", "site_id": "site-hcm", "snapshot": {"severity": "medium"}},
            ],
        }
        mgr = CentralRetentionManager(store, self.evidence_dir)

        # Reviewer can export within allowed site, but cannot delete
        exported = mgr.export_evidence(
            "dev-1",
            "ev-1",
            "req-1",
            actor="reviewer-01",
            role=ROLE_REVIEWER,
            reason="incident verification packet",
            allowed_sites=["site-hcm"],
            now=now,
        )
        self.assertEqual(exported["audit"]["action"], ACTION_CENTRAL_EXPORT)
        self.assertEqual(exported["manifest"]["sha256"], sha_clip)

        # Cross-site export denied
        with self.assertRaises(RetentionError) as ctx_site:
            mgr.export_evidence(
                "dev-1",
                "ev-1",
                "req-1",
                actor="reviewer-02",
                role=ROLE_REVIEWER,
                reason="cross site attempt",
                allowed_sites=["site-hanoi"],
                now=now,
            )
        self.assertEqual(ctx_site.exception.code, "site_access_denied")

        # Reviewer cannot delete (admin only)
        with self.assertRaises(RetentionError) as ctx_role:
            mgr.delete_evidence(
                "dev-1",
                "ev-1",
                "req-1",
                actor="reviewer-01",
                role=ROLE_REVIEWER,
                reason="unauthorized delete",
                now=now,
            )
        self.assertEqual(ctx_role.exception.code, "unauthorized_role")
        self.assertTrue(p_clip.exists())

        # Admin delete succeeds, removes file, keeps immutable receipt, appends audit
        del_res = mgr.delete_evidence(
            "dev-1",
            "ev-1",
            "req-1",
            actor="admin-01",
            role=ROLE_ADMIN,
            reason="privacy redaction order",
            allowed_sites=["site-hcm"],
            now=now,
        )
        self.assertFalse(p_clip.exists())
        self.assertEqual(del_res["manifest"]["file_status"], AVAILABILITY_EXPIRED)
        self.assertEqual(del_res["manifest"]["sha256"], sha_clip)
        self.assertEqual(len(mgr.audit_log()), 2)


class TestBackupRestoreAndReconciliationProof(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.src_evidence = self.root / "src_evidence"
        self.backup_dir = self.root / "backup_bundle"
        self.dst_evidence = self.root / "dst_evidence"
        self.src_evidence.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_clean_backup_and_isolated_restore_proof(self) -> None:
        p1, sha1, sz1 = _make_clip_file(self.src_evidence, "dev-01", "ev-101", "req-1", b"valid-clip-content-1")
        p2, sha2, sz2 = _make_clip_file(self.src_evidence, "dev-01", "ev-102", "req-2", b"valid-clip-content-2")
        # Unfinished .tmp file on source disk must not be backed up as valid evidence
        tmp_scratch = self.src_evidence / "dev-01" / "ev-102" / "req-2.mkv.tmp"
        tmp_scratch.write_bytes(b"partial-scratch")

        src_store: dict[str, list[dict[str, Any]]] = {
            "event_revisions": [
                {"device_id": "dev-01", "event_id": "ev-101", "revision": 1, "created_at": 1000.0},
                {"device_id": "dev-01", "event_id": "ev-102", "revision": 1, "created_at": 1010.0},
            ],
            "current_events": [
                {"device_id": "dev-01", "event_id": "ev-101", "revision": 1, "updated_at": 1000.0},
                {"device_id": "dev-01", "event_id": "ev-102", "revision": 1, "updated_at": 1010.0},
            ],
            "event_reviews": [
                {"device_id": "dev-01", "event_id": "ev-101", "decision": "confirmed", "review_version": 1},
            ],
            "evidence_manifests": [
                _make_manifest_record("dev-01", "ev-101", "req-1", file_path=p1, sha256=sha1, size_bytes=sz1, uploaded_at=1005.0),
                _make_manifest_record("dev-01", "ev-102", "req-2", file_path=p2, sha256=sha2, size_bytes=sz2, uploaded_at=1015.0),
            ],
        }

        backup_meta = create_backup_bundle(src_store, self.src_evidence, self.backup_dir, now=1020.0)
        self.assertEqual(len(backup_meta["files"]), 2)
        self.assertEqual(backup_meta["latest_data_timestamp"], 1015.0)

        target_store: dict[str, list[dict[str, Any]]] = {}
        report = restore_and_reconcile(self.backup_dir, target_store, self.dst_evidence, now=1025.0)

        self.assertTrue(report["clean"])
        self.assertEqual(report["ha_disclaimer"], HA_DISCLAIMER)
        self.assertFalse(report["production_ha_signed_off"])
        self.assertAlmostEqual(report["rpo_seconds"], 5.0, places=3)
        self.assertGreaterEqual(report["rto_seconds"], 0.0)
        self.assertEqual(report["counts"][RECONCILE_VERIFIED], 2)
        self.assertEqual(report["counts"][RECONCILE_MISSING], 0)
        self.assertEqual(report["counts"][RECONCILE_CORRUPT], 0)
        self.assertEqual(report["counts"][RECONCILE_ORPHAN], 0)
        self.assertEqual(len(target_store["event_revisions"]), 2)
        self.assertEqual(len(target_store["event_reviews"]), 1)

    def test_reconcile_detects_pending_missing_corrupt_and_orphan_while_preserving_receipts(self) -> None:
        p_ok, sha_ok, sz_ok = _make_clip_file(self.src_evidence, "dev-01", "ev-ok", "req-ok", b"intact-bytes")
        p_miss, sha_miss, sz_miss = _make_clip_file(self.src_evidence, "dev-01", "ev-miss", "req-miss", b"will-be-deleted")
        p_corr, sha_corr, sz_corr = _make_clip_file(self.src_evidence, "dev-01", "ev-corr", "req-corr", b"will-be-tampered")

        src_store: dict[str, list[dict[str, Any]]] = {
            "evidence_manifests": [
                _make_manifest_record("dev-01", "ev-ok", "req-ok", file_path=p_ok, sha256=sha_ok, size_bytes=sz_ok, uploaded_at=500.0),
                _make_manifest_record("dev-01", "ev-miss", "req-miss", file_path=p_miss, sha256=sha_miss, size_bytes=sz_miss, uploaded_at=501.0),
                _make_manifest_record("dev-01", "ev-corr", "req-corr", file_path=p_corr, sha256=sha_corr, size_bytes=sz_corr, uploaded_at=502.0),
                _make_manifest_record("dev-01", "ev-pend", "req-pend", file_path=None, sha256=None, size_bytes=None, uploaded_at=503.0, build_state="pending"),
            ],
        }

        create_backup_bundle(src_store, self.src_evidence, self.backup_dir, now=510.0)

        # Inject faults into the backup media directory before restore_and_reconcile:
        # 1. Remove ev-miss clip from backup
        (self.backup_dir / "evidence" / "dev-01" / "ev-miss" / "req-miss.mkv").unlink()
        # 2. Tamper with ev-corr clip bytes
        (self.backup_dir / "evidence" / "dev-01" / "ev-corr" / "req-corr.mkv").write_bytes(b"corrupted-payload!!")
        # 3. Plant an untracked orphan file and a .tmp file in target_evidence_dir
        orphan_path = self.dst_evidence / "dev-01" / "ev-orphan" / "untracked.mkv"
        orphan_path.parent.mkdir(parents=True, exist_ok=True)
        orphan_path.write_bytes(b"orphan-bytes")
        linger_tmp = self.dst_evidence / "dev-01" / "ev-orphan" / "partial.mkv.tmp"
        linger_tmp.write_bytes(b"temp-bytes")

        target_store: dict[str, list[dict[str, Any]]] = {}
        report = restore_and_reconcile(self.backup_dir, target_store, self.dst_evidence, now=520.0)

        self.assertFalse(report["clean"])
        self.assertFalse(linger_tmp.exists())
        self.assertEqual(
            report["counts"],
            {
                RECONCILE_VERIFIED: 1,
                RECONCILE_PENDING: 1,
                RECONCILE_MISSING: 1,
                RECONCILE_CORRUPT: 1,
                RECONCILE_ORPHAN: 1,
            },
        )
        self.assertEqual(report["orphan_files"], ["dev-01/ev-orphan/untracked.mkv"])

        by_event = {rec["event_id"]: rec["manifest"] for rec in target_store["evidence_manifests"]}
        self.assertEqual(by_event["ev-ok"]["locations"]["server"]["availability"], AVAILABILITY_AVAILABLE)
        self.assertEqual(by_event["ev-ok"]["locations"]["server"]["integrity"], INTEGRITY_VERIFIED)

        self.assertEqual(by_event["ev-pend"]["locations"]["server"]["availability"], AVAILABILITY_PENDING)

        self.assertEqual(by_event["ev-miss"]["locations"]["server"]["availability"], AVAILABILITY_MISSING)
        # Original receipt hash and size are still preserved on missing clip!
        self.assertEqual(by_event["ev-miss"]["sha256"], sha_miss)
        self.assertEqual(by_event["ev-miss"]["size_bytes"], sz_miss)

        self.assertEqual(by_event["ev-corr"]["locations"]["server"]["availability"], AVAILABILITY_QUARANTINED)
        self.assertEqual(by_event["ev-corr"]["locations"]["server"]["integrity"], INTEGRITY_CORRUPT)
        # Original receipt hash and size are still preserved on corrupt clip!
        self.assertEqual(by_event["ev-corr"]["sha256"], sha_corr)
        self.assertEqual(by_event["ev-corr"]["size_bytes"], sz_corr)


if __name__ == "__main__":
    unittest.main()
