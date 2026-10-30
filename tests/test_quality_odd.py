"""Ticket #21: quality/ODD status flows observation -> event -> detail, separate from supported ODD."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline, assess_capability_quality, assess_quality
from apps.edge.recorder import FileRecorder
from domain.event_contract import EventValidationError, validate_event

POLICY = {"version": "site-a-v2", "low_light_mean": 15.0, "glare_mean": 240.0,
          "low_contrast_std": 5.0, "blur_laplacian_var": 4.0, "freeze_frames": 3}


def noisy(seed):
    return np.random.RandomState(seed).randint(40, 210, (32, 32, 3), dtype=np.uint8)


class FallEngine:
    def process_tracks(self, tracks, timestamp):
        return [{
            "anchor_kind": "onset",
            "payload": {
                "taxonomy": "person_fall",
                "severity": "critical",
                "confidence": 0.9,
                "anchor_time": float(timestamp),
                "detection_time": float(timestamp),
                "lifecycle": "candidate",
                "detections": [
                    {
                        "bbox": [2.0, 2.0, 10.0, 14.0],
                        "score": 0.9,
                        "timestamp": float(timestamp),
                        "label": "person",
                    }
                ],
            },
        }]

    def reset(self): pass
    def observation_gap(self): pass


def make(root, **kw):
    return PerceptionPipeline(recorder=FileRecorder(Path(root) / "ring"),
                              outbox=EventOutbox(Path(root) / "e.sqlite3"), **kw)


class TestAssessQuality(unittest.TestCase):
    def test_normal_is_supported_with_policy_version(self):
        q = assess_quality(noisy(1), POLICY)
        self.assertEqual((q["state"], q["odd_supported"], q["policy_version"]), ("normal", True, "site-a-v2"))

    def test_degraded_states_are_not_supported(self):
        for frame, state in [(np.zeros((32, 32, 3), np.uint8), "low_light"),
                             (np.full((32, 32, 3), 255, np.uint8), "glare"),
                             (np.full((32, 32, 3), 100, np.uint8), "low_contrast")]:
            q = assess_quality(frame, POLICY)
            self.assertEqual((q["state"], q["odd_supported"]), (state, False))

    def test_blur_detected(self):
        g = np.tile(np.linspace(40, 210, 32, dtype=np.uint8), (32, 1))
        q = assess_quality(np.stack([g] * 3, -1), POLICY)
        self.assertEqual((q["state"], q["odd_supported"]), ("blur", False))

    def test_missing_frame_is_unknown_not_normal(self):
        q = assess_quality(None, POLICY, reason="detection_stale")
        self.assertEqual((q["state"], q["odd_supported"], q["reason"]), ("unknown", None, "detection_stale"))


class TestCapabilityQualityScope(unittest.TestCase):
    def test_each_capability_camera_scope_uses_its_own_versioned_policy(self):
        frame = noisy(17)
        person_down = assess_capability_quality(
            frame, capability="person_down", camera_id="cam-01", site_id="site-a", policy=POLICY
        )
        vehicle = assess_capability_quality(
            frame, capability="vehicle_incident", camera_id="cam-01", site_id="site-a",
            policy={**POLICY, "version": "vehicle-v3", "low_light_mean": 250.0},
        )
        self.assertEqual(person_down["scope"], {"capability": "person_down", "camera_id": "cam-01", "site_id": "site-a"})
        self.assertEqual(person_down["quality"]["policy_version"], "site-a-v2")
        self.assertTrue(person_down["quality"]["odd_supported"])
        self.assertEqual(vehicle["quality"]["policy_version"], "vehicle-v3")
        self.assertEqual(vehicle["quality"]["state"], "low_light")

    def test_missing_policy_is_unknown_not_default_supported(self):
        result = assess_capability_quality(
            noisy(18), capability="person_down", camera_id="cam-01"
        )
        self.assertEqual(result["quality"], {"state": "unknown", "odd_supported": None, "reason": "policy_unconfigured", "policy_version": None})

    def test_policy_without_explicit_thresholds_is_rejected(self):
        # A version alone must not inherit DEFAULT_ODD_POLICY thresholds silently.
        with self.assertRaises(ValueError):
            assess_capability_quality(noisy(19), capability="person_down", camera_id="cam-01",
                                      policy={"version": "only-version-v1"})

    def test_non_numeric_or_non_finite_threshold_is_rejected(self):
        for bad in (float("nan"), float("inf"), True, "12.0"):
            with self.assertRaises(ValueError):
                assess_capability_quality(noisy(22), capability="person_down", camera_id="cam-01",
                                          policy={**POLICY, "glare_mean": bad})

    def test_invalid_scope_or_version_fails_fast(self):
        for kwargs in (
            {"capability": "", "camera_id": "cam-01"},
            {"capability": "person_down", "camera_id": "  "},
            {"capability": "person_down", "camera_id": "cam-01", "site_id": ""},
            {"capability": "person_down", "camera_id": "cam-01", "policy": {"low_light_mean": 15.0}},
        ):
            with self.assertRaises(ValueError):
                assess_capability_quality(noisy(20), **kwargs)

    def test_unconfigured_policy_keeps_both_signals(self):
        # Never-measured quality must stay distinguishable from an observation gap,
        # and the caller's observation reason must not be discarded.
        result = assess_capability_quality(
            noisy(21), capability="person_down", camera_id="cam-01", reason="detection_stale"
        )
        self.assertEqual(result["quality"]["reason"], "policy_unconfigured")
        self.assertEqual(result["quality"]["observation_reason"], "detection_stale")
        self.assertIsNone(result["quality"]["policy_version"])

    def test_optional_blur_threshold_is_validated(self):
        # An unvalidated value would surface as TypeError inside assess_quality.
        for bad in ("4.0", float("nan"), True):
            with self.assertRaises(ValueError):
                assess_capability_quality(noisy(23), capability="person_down", camera_id="cam-01",
                                          policy={**POLICY, "blur_laplacian_var": bad})

    def test_freeze_frames_does_not_change_capability_quality(self):
        # Freeze detection is stateful and lives on the pipeline, not in this stateless helper.
        without = assess_capability_quality(noisy(24), capability="person_down", camera_id="cam-01", policy={**POLICY, "freeze_frames": None})
        with_freeze = assess_capability_quality(noisy(24), capability="person_down", camera_id="cam-01", policy={**POLICY, "freeze_frames": 2})
        self.assertEqual(without["quality"], with_freeze["quality"])
        self.assertNotEqual(without["quality"]["state"], "frozen")

    def test_missing_frame_with_policy_is_unknown_invalid_frame(self):
        result = assess_capability_quality(
            None, capability="person_down", camera_id="cam-01", policy=POLICY
        )
        self.assertEqual(result["scope"]["site_id"], None)
        self.assertEqual(result["quality"]["state"], "unknown")
        self.assertIsNone(result["quality"]["odd_supported"])
        self.assertEqual(result["quality"]["reason"], "invalid_frame")


class TestPipelineQuality(unittest.TestCase):
    def test_static_scene_with_noise_is_not_frozen_but_identical_frames_are(self):
        with tempfile.TemporaryDirectory() as root:
            p = make(root, odd_policy=POLICY)
            for i in range(5):  # static scene, sensor noise differs per frame
                p.process_frame(noisy(i), float(i), i, detections=[])
            self.assertEqual(p.last_observation["quality"]["state"], "normal")
            same = noisy(99)
            for i in range(5, 10):
                p.process_frame(same.copy(), float(i), i, detections=[])
            self.assertEqual(p.last_observation["quality"]["state"], "frozen")
            self.assertFalse(p.last_observation["quality"]["odd_supported"])

    def test_recovery_reason_recorded(self):
        with tempfile.TemporaryDirectory() as root:
            p = make(root, odd_policy=POLICY)
            p.process_frame(np.zeros((32, 32, 3), np.uint8), 1.0, 1, detections=[])
            p.process_frame(noisy(3), 2.0, 2, detections=[])
            q = p.last_observation["quality"]
            self.assertEqual(q["state"], "normal")
            self.assertEqual(q["recovery_reason"], "recovered_from_low_light")

    def test_missing_observation_marks_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            p = make(root, odd_policy=POLICY)
            p.process_frame(noisy(1), 1.0, 1, detections=[])
            p.process_frame(noisy(2), 2.0, 2, detections=[], observation_status="failed")
            q = p.last_observation["quality"]
            self.assertEqual((q["state"], q["odd_supported"]), ("unknown", None))
            self.assertEqual(p.quality_state, "unknown")

    def test_event_carries_quality_incl_degraded(self):
        with tempfile.TemporaryDirectory() as root:
            p = make(root, odd_policy=POLICY, incident_engine=FallEngine())
            ev = p.process_frame(np.zeros((32, 32, 3), np.uint8), 1.0, 1, detections=[])[0]
            self.assertEqual(ev["quality_state"], "low_light")
            q = ev["payload"]["quality"]
            self.assertEqual((q["state"], q["odd_supported"], q["policy_version"]),
                             ("low_light", False, "site-a-v2"))

    def test_configured_state_is_not_claimed_supported(self):
        with tempfile.TemporaryDirectory() as root:
            p = make(root, quality_state="calibrated_fixed", incident_engine=FallEngine())
            ev = p.process_frame(noisy(1), 1.0, 1, detections=[])[0]
            self.assertIsNone(ev["payload"]["quality"]["odd_supported"])

    def test_observation_gap_and_lineage_reset_clears_freeze_state(self):
        with tempfile.TemporaryDirectory() as root:
            p = make(root, odd_policy={"freeze_frames": 2, "version": "test-v1"})
            frame = noisy(1)
            p.process_frame(frame, 1.0, 1, detections=[])
            p.observation_gap()
            self.assertEqual(p.quality["state"], "unknown")
            self.assertIsNone(p.quality["odd_supported"])
            # First frame after gap should NOT be marked frozen
            p.process_frame(frame, 2.0, 2, detections=[])
            self.assertEqual(p.quality["state"], "normal")
            self.assertTrue(p.quality["odd_supported"])

            # Session lineage reset also clears freeze state
            p.stream_session_id = "new-session-id"
            p.process_frame(frame, 3.0, 3, detections=[])
            self.assertEqual(p.quality["state"], "normal")
            self.assertTrue(p.quality["odd_supported"])

    def test_stale_frame_records_quality_in_last_observation(self):
        with tempfile.TemporaryDirectory() as root:
            p = make(root, odd_policy=POLICY)
            p.process_frame(noisy(1), 1.0, 5, detections=[])
            p.process_frame(noisy(2), 1.1, 4, detections=[])  # fid 4 <= 5
            obs = p.last_observation
            self.assertEqual(obs["detection_status"], "stale")
            self.assertEqual(obs["quality_state"], "unknown")
            self.assertEqual(obs["quality"]["reason"], "detection_stale")

    def test_localized_motion_does_not_trigger_false_freeze(self):
        with tempfile.TemporaryDirectory() as root:
            p = make(root, odd_policy={"freeze_frames": 2, "version": "test-v1"})
            base = noisy(42)
            for i in range(4):
                f = base.copy()
                f[2:10, 2+i:10+i] = 255
                p.process_frame(f, float(i), i, detections=[])
            self.assertEqual(p.quality["state"], "normal")
            self.assertTrue(p.quality["odd_supported"])


class TestContract(unittest.TestCase):
    def _event(self, quality):
        with tempfile.TemporaryDirectory() as root:
            p = make(root, incident_engine=FallEngine())
            ev = p.process_frame(noisy(1), 1.0, 1, detections=[])[0]
        ev = {**ev, "payload": {**ev["payload"], "quality": quality}}
        return validate_event(ev)

    def test_valid_quality_accepted_and_bad_rejected(self):
        self._event({"state": "unknown", "odd_supported": None})
        for bad in ({"state": "normal", "odd_supported": "yes"}, {"odd_supported": True}, "normal"):
            with self.assertRaises(EventValidationError):
                self._event(bad)

    def test_normal_cannot_be_unsupported_and_degraded_cannot_be_supported(self):
        with self.assertRaises(EventValidationError):
            self._event({"state": "blur", "odd_supported": True})


if __name__ == "__main__":
    unittest.main()
