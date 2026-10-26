"""Comprehensive tests for Local & Signed Config Activation with Durable High-Water Mark and LKG (Ticket #34)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from apps.edge.config_activation import (
    ACTIVATION_TYPE_LOCAL,
    ACTIVATION_TYPE_REMOTE,
    ActivationResult,
    ConfigActivationManager,
    DurableConfigStateStore,
)
from domain.alert_module_config import (
    AlertModuleDefinition,
    AlertModuleRegistry,
    STATUS_ACTIVE,
    STATUS_REJECTED,
)
from domain.signed_config import (
    ERROR_EXPIRED_BUNDLE,
    ERROR_HASH_MISMATCH,
    ERROR_INVALID_SIGNATURE,
    ERROR_LENGTH_MISMATCH,
    ERROR_REVOKED_KEY,
    ERROR_SECRET_FIELD,
    ERROR_STALE_SEQUENCE,
    ERROR_TARGET_MISMATCH,
    ERROR_UNCERTAIN_CLOCK,
    ERROR_UNAUTHORIZED_ROLE,
    ERROR_UNKNOWN_KEY,
    ROLE_CONFIG_SIGNER,
    SignedConfigBundle,
    SignedConfigError,
    TargetSpec,
    TrustedKey,
    TrustedKeyRing,
    canonical_bundle_bytes,
    canonical_bundle_hash,
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


def valid_person_down_payload(version: int = 1, camera_id: str = "cam-1") -> dict[str, Any]:
    return {
        "module": "person_down",
        "camera_id": camera_id,
        "version": version,
        "enabled": True,
        "roi": ROI,
        "schedule": SCHEDULE,
        "thresholds": {"min_score": 0.4, "persistence_seconds": 5.0},
        "exceptions": [],
    }


class DummyRecorder:
    """Mock recorder to verify isolation across activations."""

    def __init__(self) -> None:
        self.is_running = True
        self.stop_count = 0
        self.reset_count = 0

    def stop(self) -> None:
        self.stop_count += 1
        self.is_running = False

    def reset(self) -> None:
        self.reset_count += 1


class TestSignedConfigPureDomain(unittest.TestCase):
    """1. Pure domain tests: canonical bytes, target mismatch, crypto, HWM, clock certainty."""

    def setUp(self) -> None:
        self.key = TrustedKey(key_id="k-primary", role=ROLE_CONFIG_SIGNER, secret="master-secret-key-123")
        self.keyring = TrustedKeyRing([self.key])
        self.target = TargetSpec(device_id="edge-dev-01", site_id="site-hcm", profile="danger_zone")

    def test_canonical_bundle_bytes_determinism(self) -> None:
        d1 = {"b": 2, "a": 1, "nested": {"z": 10, "y": 20}}
        d2 = {"a": 1, "nested": {"y": 20, "z": 10}, "b": 2}
        b1 = canonical_bundle_bytes(d1)
        b2 = canonical_bundle_bytes(d2)
        self.assertEqual(b1, b2)
        self.assertEqual(b1.decode("utf-8"), '{"a":1,"b":2,"nested":{"y":20,"z":10}}')
        self.assertEqual(canonical_bundle_hash(d1), canonical_bundle_hash(d2))

    def test_valid_bundle_verification(self) -> None:
        payload = {"configs": [valid_person_down_payload(version=1)]}
        bundle = SignedConfigBundle.create(
            payload=payload,
            key=self.key,
            trust_sequence=5,
            expires_at=2000.0,
            target_device_id="edge-dev-01",
            target_site_id="site-hcm",
            target_profile="danger_zone",
        )
        verified = verify_signed_bundle(
            bundle,
            keyring=self.keyring,
            high_water_mark=4,
            expected_target=self.target,
            current_time=1500.0,
            clock_synchronized=True,
        )
        self.assertEqual(verified.trust_sequence, 5)
        self.assertEqual(verified.payload, payload)

    def test_length_and_hash_tamper_rejection(self) -> None:
        payload = {"configs": [valid_person_down_payload(version=1)]}
        bundle = SignedConfigBundle.create(
            payload=payload,
            key=self.key,
            trust_sequence=5,
            expires_at=2000.0,
            target_device_id="edge-dev-01",
        )
        # Length tamper
        bad_len = SignedConfigBundle(
            payload=bundle.payload,
            length=bundle.length + 10,
            sha256=bundle.sha256,
            key_id=bundle.key_id,
            signature=bundle.signature,
            trust_sequence=bundle.trust_sequence,
            expires_at=bundle.expires_at,
            target_device_id=bundle.target_device_id,
        )
        with self.assertRaises(SignedConfigError) as ctx:
            verify_signed_bundle(bad_len, keyring=self.keyring, high_water_mark=0)
        self.assertEqual(ctx.exception.code, ERROR_LENGTH_MISMATCH)

        # Hash tamper
        bad_hash = SignedConfigBundle(
            payload=bundle.payload,
            length=bundle.length,
            sha256="0" * 64,
            key_id=bundle.key_id,
            signature=bundle.signature,
            trust_sequence=bundle.trust_sequence,
            expires_at=bundle.expires_at,
            target_device_id=bundle.target_device_id,
        )
        with self.assertRaises(SignedConfigError) as ctx2:
            verify_signed_bundle(bad_hash, keyring=self.keyring, high_water_mark=0)
        self.assertEqual(ctx2.exception.code, ERROR_HASH_MISMATCH)

    def test_target_mismatch_rejection(self) -> None:
        payload = {"configs": [valid_person_down_payload(version=1)]}
        bundle = SignedConfigBundle.create(
            payload=payload,
            key=self.key,
            trust_sequence=5,
            expires_at=2000.0,
            target_device_id="edge-dev-99",  # Wrong device
            target_site_id="site-hcm",
        )
        with self.assertRaises(SignedConfigError) as ctx:
            verify_signed_bundle(
                bundle,
                keyring=self.keyring,
                high_water_mark=0,
                expected_target=self.target,
            )
        self.assertEqual(ctx.exception.code, ERROR_TARGET_MISMATCH)

    def test_unknown_and_revoked_key_rejection(self) -> None:
        payload = {"configs": [valid_person_down_payload(version=1)]}
        other_key = TrustedKey(key_id="k-unknown", role=ROLE_CONFIG_SIGNER, secret="another-secret")
        bundle = SignedConfigBundle.create(
            payload=payload,
            key=other_key,
            trust_sequence=5,
            expires_at=2000.0,
        )
        with self.assertRaises(SignedConfigError) as ctx:
            verify_signed_bundle(bundle, keyring=self.keyring, high_water_mark=0)
        self.assertEqual(ctx.exception.code, ERROR_UNKNOWN_KEY)

        # Revoked key
        self.keyring.revoke_key("k-primary")
        with self.assertRaises(SignedConfigError) as ctx2:
            verify_signed_bundle(bundle, keyring=self.keyring, high_water_mark=0)
        # Even if key was known, after revocation it is rejected
        bundle_primary = SignedConfigBundle.create(
            payload=payload,
            key=self.key,
            trust_sequence=5,
            expires_at=2000.0,
        )
        with self.assertRaises(SignedConfigError) as ctx3:
            verify_signed_bundle(bundle_primary, keyring=self.keyring, high_water_mark=0)
        self.assertEqual(ctx3.exception.code, ERROR_REVOKED_KEY)

    def test_unauthorized_role_and_bad_signature_rejection(self) -> None:
        bad_role_key = TrustedKey(key_id="k-reviewer", role="reviewer", secret="secret-rev")
        self.keyring.add_key(bad_role_key)
        payload = {"configs": [valid_person_down_payload(version=1)]}
        bundle = SignedConfigBundle.create(
            payload=payload,
            key=bad_role_key,
            trust_sequence=5,
            expires_at=2000.0,
        )
        with self.assertRaises(SignedConfigError) as ctx:
            verify_signed_bundle(bundle, keyring=self.keyring, high_water_mark=0)
        self.assertEqual(ctx.exception.code, ERROR_UNAUTHORIZED_ROLE)

        # Bad signature
        bad_sig_bundle = SignedConfigBundle(
            payload=bundle.payload,
            length=bundle.length,
            sha256=bundle.sha256,
            key_id=self.key.key_id,
            signature="deadbeef" * 8,
            trust_sequence=5,
            expires_at=2000.0,
        )
        with self.assertRaises(SignedConfigError) as ctx2:
            verify_signed_bundle(bad_sig_bundle, keyring=self.keyring, high_water_mark=0)
        self.assertEqual(ctx2.exception.code, ERROR_INVALID_SIGNATURE)

    def test_pluggable_custom_verifier_hook(self) -> None:
        def custom_verifier(payload_bytes: bytes, sig: str, key: TrustedKey) -> bool:
            return sig == f"custom-ed25519-sig-for-{key.key_id}"

        custom_key = TrustedKey(
            key_id="k-hardware",
            role=ROLE_CONFIG_SIGNER,
            secret="unused-hardware-token",
            custom_verifier=custom_verifier,
        )
        self.keyring.add_key(custom_key)

        payload = {"configs": [valid_person_down_payload(version=1)]}
        canonical = canonical_bundle_bytes(payload)
        bundle = SignedConfigBundle(
            payload=payload,
            length=len(canonical),
            sha256=canonical_bundle_hash(payload),
            key_id=custom_key.key_id,
            signature="custom-ed25519-sig-for-k-hardware",
            trust_sequence=5,
            expires_at=2000.0,
        )
        verified = verify_signed_bundle(bundle, keyring=self.keyring, high_water_mark=0)
        self.assertEqual(verified.key_id, "k-hardware")

    def test_stale_trust_sequence_rejection(self) -> None:
        payload = {"configs": [valid_person_down_payload(version=1)]}
        bundle = SignedConfigBundle.create(
            payload=payload,
            key=self.key,
            trust_sequence=10,
            expires_at=2000.0,
        )
        # high_water_mark == 10 (equal)
        with self.assertRaises(SignedConfigError) as ctx:
            verify_signed_bundle(bundle, keyring=self.keyring, high_water_mark=10)
        self.assertEqual(ctx.exception.code, ERROR_STALE_SEQUENCE)

        # high_water_mark == 11 (greater)
        with self.assertRaises(SignedConfigError) as ctx2:
            verify_signed_bundle(bundle, keyring=self.keyring, high_water_mark=11)
        self.assertEqual(ctx2.exception.code, ERROR_STALE_SEQUENCE)

    def test_expiry_and_uncertain_clock_rejection(self) -> None:
        payload = {"configs": [valid_person_down_payload(version=1)]}
        bundle = SignedConfigBundle.create(
            payload=payload,
            key=self.key,
            trust_sequence=10,
            expires_at=1000.0,
        )
        # Expired
        with self.assertRaises(SignedConfigError) as ctx:
            verify_signed_bundle(
                bundle,
                keyring=self.keyring,
                high_water_mark=0,
                current_time=1500.0,
                clock_synchronized=True,
            )
        self.assertEqual(ctx.exception.code, ERROR_EXPIRED_BUNDLE)

        # Uncertain clock rejection
        with self.assertRaises(SignedConfigError) as ctx2:
            verify_signed_bundle(
                bundle,
                keyring=self.keyring,
                high_water_mark=0,
                current_time=500.0,
                clock_synchronized=False,
            )
        self.assertEqual(ctx2.exception.code, ERROR_UNCERTAIN_CLOCK)

    def test_secret_field_not_echoed_in_error(self) -> None:
        secret_value = "super-secret-api-key-value-99999"
        payload = {
            "configs": [valid_person_down_payload(version=1)],
            "api_key": secret_value,
        }
        bundle = SignedConfigBundle.create(
            payload=payload,
            key=self.key,
            trust_sequence=10,
            expires_at=2000.0,
        )
        with self.assertRaises(SignedConfigError) as ctx:
            verify_signed_bundle(bundle, keyring=self.keyring, high_water_mark=0)
        self.assertEqual(ctx.exception.code, ERROR_SECRET_FIELD)
        self.assertNotIn(secret_value, str(ctx.exception))
        self.assertIn("api_key", str(ctx.exception))


class TestDurableStoreAndRebootPersistence(unittest.TestCase):
    """2. Reboot persistence tests: HWM and LKG survival across DB close/reopen."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "config_state.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_high_water_mark_and_lkg_survives_restart(self) -> None:
        store1 = DurableConfigStateStore(self.db_path)
        self.assertEqual(store1.get_high_water_mark(), 0)

        snapshot = {
            "observed_version": 2,
            "snapshot_hash": "hash-v2",
            "configs": [valid_person_down_payload(version=2)],
        }
        store1.commit_activation(
            desired_version=2,
            observed_version=2,
            lkg_snapshot=snapshot,
            trust_sequence=15,
        )
        self.assertEqual(store1.get_high_water_mark(), 15)
        store1.close()

        # Simulate reboot: open brand new store on same path
        store2 = DurableConfigStateStore(self.db_path)
        self.assertEqual(store2.get_high_water_mark(), 15)
        state = store2.get_state()
        self.assertEqual(state["desired_version"], 2)
        self.assertEqual(state["observed_version"], 2)
        self.assertEqual(state["lkg"], snapshot)

        # Replayed sequence <= 15 must fail
        with self.assertRaises(ValueError):
            store2.commit_activation(
                desired_version=3,
                observed_version=3,
                lkg_snapshot=snapshot,
                trust_sequence=15,
            )
        with self.assertRaises(ValueError):
            store2.commit_activation(
                desired_version=3,
                observed_version=3,
                lkg_snapshot=snapshot,
                trust_sequence=14,
            )

        # Higher sequence succeeds
        store2.commit_activation(
            desired_version=3,
            observed_version=3,
            lkg_snapshot=snapshot,
            trust_sequence=16,
        )
        self.assertEqual(store2.get_high_water_mark(), 16)
        store2.close()


class TestLocalConfigActivation(unittest.TestCase):
    """3. Local config staging & boundary activation without signed bundle, plus invalid config rejection preserving LKG."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "config_state.db"
        self.store = DurableConfigStateStore(self.db_path)
        self.registry = AlertModuleRegistry()
        self.registry.register(PERSON_DOWN)
        self.registry.register(VEHICLE)
        self.manager = ConfigActivationManager(self.store, self.registry)

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_local_activation_success_updates_lkg_and_versions(self) -> None:
        cfg = valid_person_down_payload(version=1, camera_id="cam-1")
        res = self.manager.activate_local([cfg], session_id="sess-01")
        self.assertTrue(res.success)
        self.assertEqual(res.status, STATUS_ACTIVE)
        self.assertEqual(res.observed_version, 1)
        self.assertEqual(self.manager.get_observed_version(), 1)
        self.assertIsNotNone(self.manager.get_lkg())

    def test_invalid_local_config_rejected_preserving_lkg(self) -> None:
        # First valid activation: sets LKG to version 1
        cfg1 = valid_person_down_payload(version=1, camera_id="cam-1")
        res1 = self.manager.activate_local([cfg1], session_id="sess-01")
        self.assertTrue(res1.success)
        lkg_before = self.manager.get_lkg()

        # Attempt invalid local config (missing required roi, invalid thresholds)
        bad_cfg = {
            "module": "person_down",
            "camera_id": "cam-1",
            "version": 2,
            "enabled": True,
            "thresholds": {"invalid_threshold_name": 99.0},
        }
        res2 = self.manager.activate_local([bad_cfg], session_id="sess-02")
        self.assertFalse(res2.success)
        self.assertEqual(res2.status, STATUS_REJECTED)
        # Preserves previous LKG and observed_version!
        self.assertEqual(self.manager.get_observed_version(), 1)
        self.assertEqual(self.manager.get_lkg(), lkg_before)

        # Audit history records failure
        audits = self.store.get_audit_history(limit=5)
        self.assertEqual(audits[0]["status"], STATUS_REJECTED)
        self.assertEqual(audits[0]["activation_type"], ACTIVATION_TYPE_LOCAL)


class TestSignedBundleInnerConfigValidation(unittest.TestCase):
    """4. Valid signed bundle signature with invalid module config rejects activation and keeps LKG."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "config_state.db"
        self.store = DurableConfigStateStore(self.db_path)
        self.registry = AlertModuleRegistry()
        self.registry.register(PERSON_DOWN)
        self.key = TrustedKey(key_id="k-remote", role=ROLE_CONFIG_SIGNER, secret="remote-secret-key")
        self.keyring = TrustedKeyRing([self.key])
        self.manager = ConfigActivationManager(
            self.store,
            self.registry,
            keyring=self.keyring,
            target_device_id="dev-01",
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_valid_signature_with_invalid_inner_config_preserves_lkg(self) -> None:
        # Step 1: establish initial LKG at version 1
        initial_cfg = valid_person_down_payload(version=1, camera_id="cam-1")
        res_init = self.manager.activate_local([initial_cfg], session_id="sess-init")
        self.assertTrue(res_init.success)
        lkg_initial = self.manager.get_lkg()
        hwm_initial = self.manager.get_high_water_mark()

        # Step 2: create signed bundle with valid signature, but invalid inner module config
        bad_inner_cfg = {
            "module": "person_down",
            "camera_id": "cam-1",
            "version": 2,
            "enabled": True,
            # Missing required roi
            "thresholds": {"min_score": 0.5, "persistence_seconds": 2.0},
        }
        bundle = SignedConfigBundle.create(
            payload={"configs": [bad_inner_cfg]},
            key=self.key,
            trust_sequence=20,
            expires_at=9999999999.0,
            target_device_id="dev-01",
        )

        res = self.manager.activate_signed_bundle(bundle, session_id="sess-remote")
        self.assertFalse(res.success)
        self.assertEqual(res.status, STATUS_REJECTED)

        # LKG, observed_version, and HWM must remain unchanged
        self.assertEqual(self.manager.get_observed_version(), 1)
        self.assertEqual(self.manager.get_lkg(), lkg_initial)
        self.assertEqual(self.manager.get_high_water_mark(), hwm_initial)

    def test_valid_signature_and_valid_inner_config_advances_hwm_and_lkg(self) -> None:
        valid_cfg = valid_person_down_payload(version=2, camera_id="cam-1")
        bundle = SignedConfigBundle.create(
            payload={"configs": [valid_cfg]},
            key=self.key,
            trust_sequence=30,
            expires_at=9999999999.0,
            target_device_id="dev-01",
        )
        res = self.manager.activate_signed_bundle(bundle, session_id="sess-valid")
        self.assertTrue(res.success)
        self.assertEqual(res.status, STATUS_ACTIVE)
        self.assertEqual(self.manager.get_observed_version(), 2)
        self.assertEqual(self.manager.get_high_water_mark(), 30)


class TestRecorderContinuityAndEventProvenance(unittest.TestCase):
    """5. Recorder continuity check and event provenance snapshot version matching observed_version."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "config_state.db"
        self.store = DurableConfigStateStore(self.db_path)
        self.registry = AlertModuleRegistry()
        self.registry.register(PERSON_DOWN)
        self.key = TrustedKey(key_id="k-sig", role=ROLE_CONFIG_SIGNER, secret="key-secret")
        self.keyring = TrustedKeyRing([self.key])
        self.recorder = DummyRecorder()
        self.manager = ConfigActivationManager(
            self.store,
            self.registry,
            keyring=self.keyring,
            target_device_id="edge-box",
            recorder=self.recorder,
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_dir.cleanup()

    def test_recorder_continuity_across_failures_and_successes(self) -> None:
        self.assertTrue(self.recorder.is_running)
        self.assertEqual(self.recorder.stop_count, 0)
        self.assertEqual(self.recorder.reset_count, 0)

        # 1. Failed local activation
        bad_local = {"module": "person_down", "camera_id": "cam-1", "version": -1, "enabled": True}
        res1 = self.manager.activate_local([bad_local], session_id="s1")
        self.assertFalse(res1.success)
        self.assertTrue(self.recorder.is_running)
        self.assertEqual(self.recorder.stop_count, 0)
        self.assertEqual(self.recorder.reset_count, 0)

        # 2. Failed remote activation (tampered signature)
        payload = {"configs": [valid_person_down_payload(version=1, camera_id="cam-1")]}
        bad_bundle = SignedConfigBundle(
            payload=payload,
            length=len(canonical_bundle_bytes(payload)),
            sha256=canonical_bundle_hash(payload),
            key_id=self.key.key_id,
            signature="bad-sig",
            trust_sequence=1,
            expires_at=9999999999.0,
            target_device_id="edge-box",
        )
        res2 = self.manager.activate_signed_bundle(bad_bundle, session_id="s2")
        self.assertFalse(res2.success)
        self.assertTrue(self.recorder.is_running)
        self.assertEqual(self.recorder.stop_count, 0)
        self.assertEqual(self.recorder.reset_count, 0)

        # 3. Successful local activation
        good_local = valid_person_down_payload(version=1, camera_id="cam-1")
        res3 = self.manager.activate_local([good_local], session_id="s3")
        self.assertTrue(res3.success)
        self.assertTrue(self.recorder.is_running)
        self.assertEqual(self.recorder.stop_count, 0)
        self.assertEqual(self.recorder.reset_count, 0)

        # Verify event provenance matches observed_version and snapshot_hash
        prov = self.manager.get_event_provenance("person_down", "cam-1")
        self.assertEqual(prov["observed_version"], 1)
        self.assertEqual(prov["module"], "person_down")
        self.assertEqual(prov["camera_id"], "cam-1")
        self.assertEqual(prov["session_id"], "s3")
        self.assertEqual(prov["snapshot_hash"], res3.snapshot_hash)

        # 4. Successful remote activation
        good_remote = valid_person_down_payload(version=2, camera_id="cam-1")
        bundle_v2 = SignedConfigBundle.create(
            payload={"configs": [good_remote]},
            key=self.key,
            trust_sequence=10,
            expires_at=9999999999.0,
            target_device_id="edge-box",
        )
        res4 = self.manager.activate_signed_bundle(bundle_v2, session_id="s4")
        self.assertTrue(res4.success)
        self.assertTrue(self.recorder.is_running)
        self.assertEqual(self.recorder.stop_count, 0)
        self.assertEqual(self.recorder.reset_count, 0)

        # Verify event provenance updated to observed_version 2
        prov2 = self.manager.get_event_provenance("person_down", "cam-1")
        self.assertEqual(prov2["observed_version"], 2)
        self.assertEqual(prov2["session_id"], "s4")
        self.assertEqual(prov2["snapshot_hash"], res4.snapshot_hash)


if __name__ == "__main__":
    unittest.main()
