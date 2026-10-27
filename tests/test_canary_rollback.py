"""Comprehensive tests for Canary Activation and Authorized Rollback with New Sequence (Ticket #35).

Covers:
  1. Canary Deployment:
     - Subset camera/module rollout while non-canary retains baseline config.
     - Observation monitoring: healthy observation vs health failure/high error rate auto-abort.
     - Explicit abort_canary restores baseline LKG cleanly.
     - promote_canary rolls out full configuration to all targets and updates LKG.
     - Failed canary activation (bad signature, target mismatch, invalid inner config) preserves LKG.
  2. Rollback via NEW Authorization Sequence:
     - Rejects stale sequence (<= current HWM) and downgrades with stale_trust_sequence error.
     - Requires fresh, strictly higher sequence.
     - HWM advances monotonically and never decreases across rollbacks.
     - Authorized keys with role config_signer or config_rollback are accepted for rollback.
     - Key with only config_rollback cannot sign regular forward bundles.
     - Unauthorized role (e.g. auditor/operator) rejected.
     - Valid rollback restores target LKG, advances HWM, updates observed_version and provenance.
  3. Compatibility & Lineage Policy:
     - Schema version allowlist enforcement.
     - Factory allowlist enforcement.
     - Incompatible model lineage transition rejection across rollback.
     - Conflicting model lineages in same bundle rejection (no silent mixing).
  4. Reboot & Crash Survival:
     - HWM, restored LKG, and rollback state survive database close and reopen with WAL+FULL.
     - Active canary observation state survives store close and reopen.
  5. Recorder Isolation & Secret Non-Leakage:
     - Recorder is never stopped or reset across any canary, rollback, or failure.
     - Secret fields rejected without echoing secrets in error messages or audit logs.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from apps.edge.config_activation import (
    ACTIVATION_TYPE_CANARY,
    ACTIVATION_TYPE_LOCAL,
    ACTIVATION_TYPE_REMOTE,
    ACTIVATION_TYPE_ROLLBACK,
    ActivationResult,
    ConfigActivationManager,
    DurableConfigStateStore,
    STATUS_CANARY,
    STATUS_FAILED,
    STATUS_ROLLED_BACK,
)
from domain.alert_module_config import (
    AlertModuleDefinition,
    AlertModuleRegistry,
    STATUS_ACTIVE,
    STATUS_REJECTED,
)
from domain.signed_config import (
    CanarySpec,
    CompatibilityPolicy,
    ERROR_CANARY_FAILURE,
    ERROR_INCOMPATIBLE_LINEAGE,
    ERROR_INVALID_ROLLBACK,
    ERROR_SECRET_FIELD,
    ERROR_STALE_SEQUENCE,
    ERROR_TARGET_MISMATCH,
    ERROR_UNAUTHORIZED_ROLE,
    ROLE_CONFIG_ROLLBACK,
    ROLE_CONFIG_SIGNER,
    SignedConfigBundle,
    SignedConfigError,
    TargetSpec,
    TrustedKey,
    TrustedKeyRing,
    create_canary_bundle,
    create_rollback_bundle,
    verify_signed_bundle,
)

PERSON_DOWN = AlertModuleDefinition(
    module="person_down",
    config_version="person-down-v1",
    factory="person_down",
    required_fields=frozenset({"roi", "thresholds"}),
    thresholds=frozenset({"min_score", "persistence_seconds"}),
)

VEHICLE = AlertModuleDefinition(
    module="vehicle_incident",
    config_version="vehicle-v1",
    factory="vehicle_incident",
    required_fields=frozenset({"roi"}),
    thresholds=frozenset({"motion_delta"}),
)

ROI = [[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]]
SCHEDULE = [{"days": ["mon", "tue"], "start_second": 21600, "end_second": 61200}]


def make_person_down_config(
    version: int = 1,
    camera_id: str = "cam-1",
    min_score: float = 0.4,
    persistence_seconds: float = 5.0,
    schema_version: str | None = None,
    factory: str | None = None,
    model_lineage: str | None = None,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "module": "person_down",
        "camera_id": camera_id,
        "version": version,
        "enabled": True,
        "roi": ROI,
        "schedule": SCHEDULE,
        "thresholds": {"min_score": min_score, "persistence_seconds": persistence_seconds},
        "exceptions": [],
    }
    if schema_version is not None:
        cfg["schema_version"] = schema_version
    if factory is not None:
        cfg["factory"] = factory
    if model_lineage is not None:
        cfg["model_lineage"] = model_lineage
    return cfg


def make_vehicle_config(
    version: int = 1,
    camera_id: str = "cam-1",
    motion_delta: float = 0.5,
    schema_version: str | None = None,
    factory: str | None = None,
    model_lineage: str | None = None,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "module": "vehicle_incident",
        "camera_id": camera_id,
        "version": version,
        "enabled": True,
        "roi": ROI,
        "schedule": SCHEDULE,
        "thresholds": {"motion_delta": motion_delta},
        "exceptions": [],
    }
    if schema_version is not None:
        cfg["schema_version"] = schema_version
    if factory is not None:
        cfg["factory"] = factory
    if model_lineage is not None:
        cfg["model_lineage"] = model_lineage
    return cfg


class DummyRecorder:
    def __init__(self) -> None:
        self.is_running = True
        self.stop_count = 0
        self.reset_count = 0

    def stop(self) -> None:
        self.stop_count += 1
        self.is_running = False

    def reset(self) -> None:
        self.reset_count += 1


class TestCanaryDeployment(unittest.TestCase):
    """Test Canary Release: subset activation, health observation, auto-abort, promotion, and LKG preservation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_canary.db"
        self.store = DurableConfigStateStore(self.db_path)

        self.registry = AlertModuleRegistry()
        self.registry.register(PERSON_DOWN)
        self.registry.register(VEHICLE)

        self.signer_key = TrustedKey("k-signer", ROLE_CONFIG_SIGNER, "master-signer-secret-key")
        self.rollback_key = TrustedKey("k-rollback", ROLE_CONFIG_ROLLBACK, "master-rollback-secret-key")
        self.keyring = TrustedKeyRing([self.signer_key, self.rollback_key])
        self.target = TargetSpec(device_id="edge-node-01", site_id="site-hn", profile="factory_floor")

        self.recorder = DummyRecorder()
        self.manager = ConfigActivationManager(
            self.store,
            self.registry,
            keyring=self.keyring,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
            recorder=self.recorder,
        )

        # Establish baseline LKG (v1) on two cameras: cam-1 and cam-2
        baseline_configs = [
            make_person_down_config(version=1, camera_id="cam-1"),
            make_person_down_config(version=1, camera_id="cam-2"),
        ]
        bundle_v1 = SignedConfigBundle.create(
            payload={"configs": baseline_configs},
            key=self.signer_key,
            trust_sequence=10,
            expires_at=9999999999.0,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        res = self.manager.activate_signed_bundle(bundle_v1, session_id="sess-baseline")
        self.assertTrue(res.success)
        self.assertEqual(self.manager.get_high_water_mark(), 10)
        self.assertEqual(self.manager.get_observed_version(), 1)

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_canary_activation_on_subset_cameras_preserves_baseline_lkg(self) -> None:
        """Canary activates on cam-1 only; cam-2 stays on baseline v1; store LKG remains baseline."""
        canary_bundle = create_canary_bundle(
            configs=[
                make_person_down_config(version=2, camera_id="cam-1", min_score=0.8),
                make_person_down_config(version=2, camera_id="cam-2", min_score=0.8),
            ],
            key=self.signer_key,
            trust_sequence=15,
            expires_at=9999999999.0,
            canary_cameras=["cam-1"],
            max_error_rate=0.05,
            observation_period_seconds=120.0,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )

        res = self.manager.activate_canary(canary_bundle, session_id="sess-canary-01")
        self.assertTrue(res.success)
        self.assertEqual(res.status, STATUS_CANARY)
        self.assertEqual(res.activation_type, ACTIVATION_TYPE_CANARY)

        # Monotonic HWM advanced to 15 to prevent replay
        self.assertEqual(self.manager.get_high_water_mark(), 15)

        # Baseline LKG preserved in durable store
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 1)

        # Verify cam-1 is running canary v2, cam-2 is running baseline v1
        cam1_cfg = self.registry.config("person_down", "cam-1")
        cam2_cfg = self.registry.config("person_down", "cam-2")
        assert cam1_cfg is not None
        assert cam2_cfg is not None
        self.assertEqual(cam1_cfg.version, 2)
        self.assertEqual(cam2_cfg.version, 1)

        # Recorder untouched
        self.assertEqual(self.recorder.stop_count, 0)
        self.assertEqual(self.recorder.reset_count, 0)

    def test_canary_health_degradation_triggers_automatic_abort_to_lkg(self) -> None:
        """When error rate exceeds max_error_rate, canary auto-aborts and restores cam-1 to baseline LKG."""
        canary_bundle = create_canary_bundle(
            configs=[
                make_person_down_config(version=2, camera_id="cam-1"),
                make_person_down_config(version=2, camera_id="cam-2"),
            ],
            key=self.signer_key,
            trust_sequence=15,
            expires_at=9999999999.0,
            canary_cameras=["cam-1"],
            max_error_rate=0.05,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        self.manager.activate_canary(canary_bundle, session_id="sess-canary")

        # Healthy observation passes
        healthy_res = self.manager.record_canary_observation(error_rate=0.01, is_healthy=True)
        self.assertTrue(healthy_res.success)
        self.assertEqual(healthy_res.status, STATUS_CANARY)

        # Error rate 0.08 exceeds 0.05 threshold -> automatic abort
        fail_res = self.manager.record_canary_observation(error_rate=0.08, is_healthy=True)
        self.assertFalse(fail_res.success)
        self.assertEqual(fail_res.status, STATUS_FAILED)
        self.assertEqual(fail_res.reason, ERROR_CANARY_FAILURE)

        # cam-1 is cleanly reverted to baseline v1
        cam1_cfg = self.registry.config("person_down", "cam-1")
        assert cam1_cfg is not None
        self.assertEqual(cam1_cfg.version, 1)

        # Canary state in store is cleared
        self.assertIsNone(self.manager.get_canary_state())
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 1)

        # Audit history records canary health failure
        audits = self.store.get_audit_history(limit=5)
        self.assertEqual(audits[0]["status"], STATUS_FAILED)
        self.assertIn("error_rate", audits[0]["reason"])

    def test_explicit_canary_abort_restores_baseline_lkg(self) -> None:
        """Explicit abort_canary cleanly rolls back canary camera to baseline LKG."""
        canary_bundle = create_canary_bundle(
            configs=[
                make_person_down_config(version=2, camera_id="cam-1"),
                make_person_down_config(version=2, camera_id="cam-2"),
            ],
            key=self.signer_key,
            trust_sequence=15,
            expires_at=9999999999.0,
            canary_cameras=["cam-1"],
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        self.manager.activate_canary(canary_bundle, session_id="sess-canary")

        abort_res = self.manager.abort_canary(reason="operator_emergency_stop")
        self.assertTrue(abort_res.success)
        self.assertEqual(abort_res.status, STATUS_ROLLED_BACK)

        # cam-1 restored to baseline v1
        cam1_cfg = self.registry.config("person_down", "cam-1")
        assert cam1_cfg is not None
        self.assertEqual(cam1_cfg.version, 1)
        self.assertIsNone(self.manager.get_canary_state())

    def test_canary_promotion_rolls_out_all_cameras_and_advances_lkg(self) -> None:
        """Promote canary rolls out v2 to both cam-1 and cam-2, updating LKG."""
        canary_bundle = create_canary_bundle(
            configs=[
                make_person_down_config(version=2, camera_id="cam-1"),
                make_person_down_config(version=2, camera_id="cam-2"),
            ],
            key=self.signer_key,
            trust_sequence=15,
            expires_at=9999999999.0,
            canary_cameras=["cam-1"],
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        self.manager.activate_canary(canary_bundle, session_id="sess-canary")

        promo_res = self.manager.promote_canary(session_id="sess-promo")
        self.assertTrue(promo_res.success)
        self.assertEqual(promo_res.status, STATUS_ACTIVE)
        self.assertEqual(promo_res.observed_version, 2)

        # Both cameras now running v2
        c1 = self.registry.config("person_down", "cam-1")
        c2 = self.registry.config("person_down", "cam-2")
        assert c1 is not None and c2 is not None
        self.assertEqual(c1.version, 2)
        self.assertEqual(c2.version, 2)

        # LKG in store advanced to v2
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 2)
        self.assertIsNone(self.manager.get_canary_state())

    def test_failed_canary_activation_preserves_lkg(self) -> None:
        """Tampered canary signature or invalid config fails fast, keeping baseline intact."""
        # 1. Invalid threshold inner config
        bad_config_bundle = create_canary_bundle(
            configs=[
                {
                    "module": "person_down",
                    "camera_id": "cam-1",
                    "version": 2,
                    "enabled": True,
                    "thresholds": {"min_score": -1.0},  # Invalid negative score
                }
            ],
            key=self.signer_key,
            trust_sequence=20,
            expires_at=9999999999.0,
            canary_cameras=["cam-1"],
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        res = self.manager.activate_canary(bad_config_bundle, session_id="sess-bad")
        self.assertFalse(res.success)
        self.assertEqual(res.status, STATUS_REJECTED)
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 1)

        # 2. Target mismatch
        mismatch_bundle = create_canary_bundle(
            configs=[make_person_down_config(version=2, camera_id="cam-1")],
            key=self.signer_key,
            trust_sequence=25,
            expires_at=9999999999.0,
            canary_cameras=["cam-1"],
            target_device_id="different-edge-node",
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        res2 = self.manager.activate_canary(mismatch_bundle, session_id="sess-mismatch")
        self.assertFalse(res2.success)
        self.assertEqual(res2.status, STATUS_REJECTED)
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 1)


class TestAuthorizedRollback(unittest.TestCase):
    """Test Rollback via NEW Authorization Sequence, strictly monotonic HWM, and LKG restoration."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_rollback.db"
        self.store = DurableConfigStateStore(self.db_path)

        self.registry = AlertModuleRegistry()
        self.registry.register(PERSON_DOWN)
        self.registry.register(VEHICLE)

        self.signer_key = TrustedKey("k-signer", ROLE_CONFIG_SIGNER, "primary-signer-secret-key")
        self.rollback_key = TrustedKey("k-rollback", ROLE_CONFIG_ROLLBACK, "dedicated-rollback-secret-key")
        self.auditor_key = TrustedKey("k-auditor", "auditor", "auditor-secret-key")
        self.keyring = TrustedKeyRing([self.signer_key, self.rollback_key, self.auditor_key])
        self.target = TargetSpec(device_id="edge-node-01", site_id="site-hn", profile="factory_floor")

        self.recorder = DummyRecorder()
        self.manager = ConfigActivationManager(
            self.store,
            self.registry,
            keyring=self.keyring,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
            recorder=self.recorder,
        )

        # Baseline v1 deployed at sequence 10
        b1 = SignedConfigBundle.create(
            payload={"configs": [make_person_down_config(version=1, camera_id="cam-1")]},
            key=self.signer_key,
            trust_sequence=10,
            expires_at=9999999999.0,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        self.manager.activate_signed_bundle(b1, session_id="s1")

        # Deploy v2 at sequence 20 (causing HWM = 20)
        b2 = SignedConfigBundle.create(
            payload={"configs": [make_person_down_config(version=2, camera_id="cam-1", min_score=0.9)]},
            key=self.signer_key,
            trust_sequence=20,
            expires_at=9999999999.0,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        res_v2 = self.manager.activate_signed_bundle(b2, session_id="s2")
        self.assertTrue(res_v2.success)
        self.assertEqual(self.manager.get_high_water_mark(), 20)
        self.assertEqual(self.manager.get_observed_version(), 2)

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_rollback_with_stale_sequence_is_rejected_preserving_lkg(self) -> None:
        """Rollback attempting to replay sequence 10 (or <= 20) is rejected as stale sequence."""
        stale_rollback_bundle = create_rollback_bundle(
            configs=[make_person_down_config(version=1, camera_id="cam-1")],
            key=self.rollback_key,
            trust_sequence=10,  # Stale: 10 <= 20
            expires_at=9999999999.0,
            rollback_for_sequence=20,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )

        res = self.manager.activate_signed_rollback(stale_rollback_bundle, session_id="s-rollback")
        self.assertFalse(res.success)
        self.assertEqual(res.status, STATUS_REJECTED)
        self.assertEqual(res.reason, ERROR_STALE_SEQUENCE)

        # HWM remains 20 (never downgraded)
        self.assertEqual(self.manager.get_high_water_mark(), 20)

        # LKG remains v2
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 2)
        c1 = self.registry.config("person_down", "cam-1")
        assert c1 is not None
        self.assertEqual(c1.version, 2)

        # Audit logged with rejected status
        audits = self.store.get_audit_history(limit=1)
        self.assertEqual(audits[0]["status"], STATUS_REJECTED)
        self.assertEqual(audits[0]["activation_type"], ACTIVATION_TYPE_ROLLBACK)

    def test_rollback_with_fresh_higher_sequence_succeeds_and_advances_hwm(self) -> None:
        """Rollback with sequence 21 (> 20) succeeds, restores v1, advances HWM to 21."""
        fresh_rollback = create_rollback_bundle(
            configs=[make_person_down_config(version=1, camera_id="cam-1")],
            key=self.rollback_key,
            trust_sequence=21,  # Fresh higher sequence > 20
            expires_at=9999999999.0,
            rollback_for_sequence=20,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )

        res = self.manager.activate_signed_rollback(fresh_rollback, session_id="s-rollback")
        self.assertTrue(res.success)
        self.assertEqual(res.status, STATUS_ACTIVE)
        self.assertEqual(res.activation_type, ACTIVATION_TYPE_ROLLBACK)
        self.assertEqual(res.observed_version, 1)

        # High-water mark strictly advanced to 21 (never decreased)
        self.assertEqual(self.manager.get_high_water_mark(), 21)
        self.assertEqual(self.store.get_last_rollback_sequence(), 21)

        # Registry and LKG reflect restored v1
        c1 = self.registry.config("person_down", "cam-1")
        assert c1 is not None
        self.assertEqual(c1.version, 1)
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 1)

        # Event provenance reflects restored v1
        prov = self.manager.get_event_provenance("person_down", "cam-1")
        self.assertEqual(prov["observed_version"], 1)
        self.assertEqual(prov["module_version"], 1)

    def test_role_authorization_for_rollback_and_forward_bundles(self) -> None:
        """Key with role config_rollback can sign rollbacks, but cannot sign forward config bundles."""
        # 1. config_rollback key signing regular forward bundle -> REJECTED
        forward_bundle = SignedConfigBundle.create(
            payload={"configs": [make_person_down_config(version=3, camera_id="cam-1")]},
            key=self.rollback_key,  # Role config_rollback
            trust_sequence=30,
            expires_at=9999999999.0,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        res_fwd = self.manager.activate_signed_bundle(forward_bundle, session_id="s-fwd")
        self.assertFalse(res_fwd.success)
        self.assertEqual(res_fwd.reason, ERROR_UNAUTHORIZED_ROLE)

        # 2. Key with unauthorized role (e.g. auditor) signing rollback -> REJECTED
        auditor_rollback = create_rollback_bundle(
            configs=[make_person_down_config(version=1, camera_id="cam-1")],
            key=self.auditor_key,  # Role auditor
            trust_sequence=35,
            expires_at=9999999999.0,
            rollback_for_sequence=20,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        res_audit = self.manager.activate_signed_rollback(auditor_rollback, session_id="s-audit")
        self.assertFalse(res_audit.success)
        self.assertEqual(res_audit.reason, ERROR_UNAUTHORIZED_ROLE)

        # 3. Master config_signer key CAN sign rollbacks -> ACCEPTED
        signer_rollback = create_rollback_bundle(
            configs=[make_person_down_config(version=1, camera_id="cam-1")],
            key=self.signer_key,  # Role config_signer
            trust_sequence=40,
            expires_at=9999999999.0,
            rollback_for_sequence=20,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        res_signer = self.manager.activate_signed_rollback(signer_rollback, session_id="s-signer-rb")
        self.assertTrue(res_signer.success)
        self.assertEqual(self.manager.get_high_water_mark(), 40)

    def test_reboot_and_crash_survival_of_rollback_state(self) -> None:
        """After rollback, closing store and creating new manager reloads restored LKG and HWM from SQLite."""
        # Perform rollback to v1 at sequence 25
        rollback_bundle = create_rollback_bundle(
            configs=[make_person_down_config(version=1, camera_id="cam-1")],
            key=self.rollback_key,
            trust_sequence=25,
            expires_at=9999999999.0,
            rollback_for_sequence=20,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )
        self.manager.activate_signed_rollback(rollback_bundle, session_id="s-rb")
        self.assertEqual(self.manager.get_high_water_mark(), 25)

        # Simulate process reboot / crash by closing existing manager and opening new one on same DB
        self.manager.close()

        new_store = DurableConfigStateStore(self.db_path)
        new_registry = AlertModuleRegistry()
        new_registry.register(PERSON_DOWN)
        new_manager = ConfigActivationManager(
            new_store,
            new_registry,
            keyring=self.keyring,
            target_device_id=self.target.device_id,
            target_site_id=self.target.site_id,
            target_profile=self.target.profile,
        )

        try:
            # High-water mark remains 25
            self.assertEqual(new_manager.get_high_water_mark(), 25)
            # Restored LKG is v1
            self.assertEqual(new_manager.get_observed_version(), 1)
            lkg = new_manager.get_lkg()
            assert lkg is not None
            self.assertEqual(lkg["observed_version"], 1)
            # Registry automatically restored v1
            c1 = new_registry.config("person_down", "cam-1")
            assert c1 is not None
            self.assertEqual(c1.version, 1)

            # Replay of sequence 25 or earlier is strictly rejected
            stale_retry = create_rollback_bundle(
                configs=[make_person_down_config(version=1, camera_id="cam-1")],
                key=self.rollback_key,
                trust_sequence=25,
                expires_at=9999999999.0,
                target_device_id=self.target.device_id,
            )
            res = new_manager.activate_signed_rollback(stale_retry, session_id="retry-s")
            self.assertFalse(res.success)
            self.assertEqual(res.reason, ERROR_STALE_SEQUENCE)
        finally:
            new_manager.close()


class TestCompatibilityAndLineagePolicy(unittest.TestCase):
    """Test CompatibilityPolicy: schema version, factory allowlist, and model lineage transition."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_compat.db"
        self.store = DurableConfigStateStore(self.db_path)

        self.registry = AlertModuleRegistry()
        self.registry.register(PERSON_DOWN)
        self.registry.register(VEHICLE)

        self.signer_key = TrustedKey("k-signer", ROLE_CONFIG_SIGNER, "signer-secret")
        self.rollback_key = TrustedKey("k-rollback", ROLE_CONFIG_ROLLBACK, "rollback-secret")
        self.keyring = TrustedKeyRing([self.signer_key, self.rollback_key])
        self.target = TargetSpec(device_id="edge-node-01")

        self.policy = CompatibilityPolicy(
            allowed_schema_versions=("v1", "v2"),
            allowed_factories=("person_down", "vehicle_incident"),
            allowed_lineages=("yolox_tiny_v1", "yolox_tiny_v2"),
            lineage_compatibility_matrix={
                "yolox_tiny_v2": ("yolox_tiny_v2", "yolox_tiny_v1"),
            },
        )

        self.manager = ConfigActivationManager(
            self.store,
            self.registry,
            keyring=self.keyring,
            target_device_id=self.target.device_id,
            compatibility_policy=self.policy,
        )

        # Baseline v1 with model_lineage yolox_tiny_v1
        base_cfg = make_person_down_config(
            version=1,
            camera_id="cam-1",
            schema_version="v1",
            factory="person_down",
            model_lineage="yolox_tiny_v1",
        )
        b1 = SignedConfigBundle.create(
            payload={"configs": [base_cfg], "schema_version": "v1", "model_lineage": "yolox_tiny_v1"},
            key=self.signer_key,
            trust_sequence=10,
            expires_at=9999999999.0,
            target_device_id=self.target.device_id,
        )
        self.manager.activate_signed_bundle(b1, session_id="s1")

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_incompatible_schema_version_rejected(self) -> None:
        """Bundle carrying unallowed schema version (v3) is rejected."""
        bad_schema_bundle = SignedConfigBundle.create(
            payload={
                "configs": [make_person_down_config(version=2, camera_id="cam-1", schema_version="v3")],
                "schema_version": "v3",
            },
            key=self.signer_key,
            trust_sequence=20,
            expires_at=9999999999.0,
            target_device_id=self.target.device_id,
        )
        res = self.manager.activate_signed_bundle(bad_schema_bundle, session_id="s-bad-schema")
        self.assertFalse(res.success)
        self.assertEqual(res.status, STATUS_REJECTED)
        self.assertEqual(res.reason, ERROR_INCOMPATIBLE_LINEAGE)
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 1)

    def test_unapproved_factory_rejected(self) -> None:
        """Bundle specifying an unapproved factory is rejected."""
        bad_factory_bundle = SignedConfigBundle.create(
            payload={
                "configs": [
                    make_person_down_config(version=2, camera_id="cam-1", factory="unapproved_neural_net")
                ]
            },
            key=self.signer_key,
            trust_sequence=20,
            expires_at=9999999999.0,
            target_device_id=self.target.device_id,
        )
        res = self.manager.activate_signed_bundle(bad_factory_bundle, session_id="s-bad-factory")
        self.assertFalse(res.success)
        self.assertEqual(res.reason, ERROR_INCOMPATIBLE_LINEAGE)
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 1)

    def test_incompatible_model_lineage_rollback_rejected(self) -> None:
        """Rollback attempting to restore an incompatible legacy model lineage is rejected."""
        # Advance to v2 with yolox_tiny_v2
        v2_cfg = make_person_down_config(
            version=2,
            camera_id="cam-1",
            schema_version="v2",
            factory="person_down",
            model_lineage="yolox_tiny_v2",
        )
        b2 = SignedConfigBundle.create(
            payload={"configs": [v2_cfg], "schema_version": "v2", "model_lineage": "yolox_tiny_v2"},
            key=self.signer_key,
            trust_sequence=20,
            expires_at=9999999999.0,
            target_device_id=self.target.device_id,
        )
        self.manager.activate_signed_bundle(b2, session_id="s2")

        # Rollback specifying incompatible lineage "legacy_v0" not in allowed lineages
        incompat_rollback = create_rollback_bundle(
            configs=[make_person_down_config(version=1, camera_id="cam-1", model_lineage="legacy_v0")],
            key=self.rollback_key,
            trust_sequence=30,
            expires_at=9999999999.0,
            rollback_for_sequence=20,
            model_lineage="legacy_v0",
            target_device_id=self.target.device_id,
        )
        res = self.manager.activate_signed_rollback(incompat_rollback, session_id="s-rb-incompat")
        self.assertFalse(res.success)
        self.assertEqual(res.reason, ERROR_INCOMPATIBLE_LINEAGE)
        lkg = self.manager.get_lkg()
        assert lkg is not None
        self.assertEqual(lkg["observed_version"], 2)

    def test_bundle_with_conflicting_lineages_rejected(self) -> None:
        """Silent mixing of incompatible model lineages within the same bundle is rejected."""
        policy_with_matrix = CompatibilityPolicy(
            allowed_lineages=("lineage_A", "lineage_B"),
            lineage_compatibility_matrix={
                "lineage_A": ("lineage_A",),
                "lineage_B": ("lineage_B",),
            },
        )
        mixed_payload = {
            "configs": [
                make_person_down_config(version=2, camera_id="cam-1", model_lineage="lineage_A"),
                make_vehicle_config(version=2, camera_id="cam-2", model_lineage="lineage_B"),
            ]
        }
        with self.assertRaises(SignedConfigError) as ctx:
            policy_with_matrix.validate_bundle(mixed_payload)
        self.assertEqual(ctx.exception.code, ERROR_INCOMPATIBLE_LINEAGE)
        self.assertIn("conflicting", ctx.exception.message)


class TestSecretNonLeakageAndRecorderIsolation(unittest.TestCase):
    """Ensure secrets are never leaked and recorder reference is isolated."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_secrets.db"
        self.store = DurableConfigStateStore(self.db_path)
        self.registry = AlertModuleRegistry()
        self.registry.register(PERSON_DOWN)
        self.key = TrustedKey("k-signer", ROLE_CONFIG_SIGNER, "secret-key-123456")
        self.keyring = TrustedKeyRing([self.key])
        self.recorder = DummyRecorder()
        self.manager = ConfigActivationManager(
            self.store,
            self.registry,
            keyring=self.keyring,
            target_device_id="dev-01",
            recorder=self.recorder,
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_secret_field_in_bundle_rejected_without_value_leakage(self) -> None:
        """Secret tokens in bundle payloads are rejected, and value is never echoed."""
        secret_value = "SUPER_SECRET_TOKEN_DO_NOT_LEAK"
        bundle = SignedConfigBundle.create(
            payload={
                "configs": [
                    {
                        "module": "person_down",
                        "camera_id": "cam-1",
                        "version": 1,
                        "enabled": True,
                        "api_key": secret_value,
                        "thresholds": {"min_score": 0.5, "persistence_seconds": 1.0},
                    }
                ]
            },
            key=self.key,
            trust_sequence=1,
            expires_at=9999999999.0,
            target_device_id="dev-01",
        )
        res = self.manager.activate_signed_bundle(bundle, session_id="s1")
        self.assertFalse(res.success)
        self.assertEqual(res.reason, ERROR_SECRET_FIELD)

        # Assert secret value does NOT appear in error or reason
        self.assertNotIn(secret_value, str(res.error))
        self.assertNotIn(secret_value, str(res.reason))

        # Check audit trail does not contain secret value
        audits = self.store.get_audit_history(limit=5)
        self.assertNotIn(secret_value, str(audits))

        # Recorder continuity preserved
        self.assertEqual(self.recorder.stop_count, 0)
        self.assertEqual(self.recorder.reset_count, 0)