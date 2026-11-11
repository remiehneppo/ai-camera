"""Regressions for visual verification ownership and configured vehicle kinematics."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from apps.edge.homography import GroundPlaneHomography
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder
from apps.edge.urban_safety_engine import UrbanSafetyScenarioEngine
from apps.edge.vlm_verifier import CandidateVerificationCoordinator, VLMVerifier
from domain.alert_module_config import CameraModuleConfig


class PipelineVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.recorder = FileRecorder(self.root / "ring", ring_seconds=60)
        self.outbox = EventOutbox(self.root / "outbox.sqlite3")
        self.frame = np.zeros((360, 640, 3), dtype=np.uint8)
        self.frame[100:220, 100:260] = [245, 130, 20]

    def test_selected_verifier_receives_visual_evidence_and_can_suppress_fire(self) -> None:
        def provider(url: str, body: dict, headers: dict, timeout: float) -> dict:
            content = body["messages"][0]["content"]
            image_url = next(item["image_url"]["url"] for item in content if item["type"] == "image_url")
            encoded = np.frombuffer(base64.b64decode(image_url.split(",", 1)[1]), dtype=np.uint8)
            bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            has_orange = bool(np.any((bgr[:, :, 2] > 200) & (bgr[:, :, 1] > 80) & (bgr[:, :, 0] < 80)))
            return {"choices": [{"message": {"content": json.dumps({
                "verified": not has_orange, "confidence": 0.94,
                "hard_negative_class": "orange_sign" if has_orange else None,
                "reasoning": "Observed orange sign in visual evidence",
            })}}]}

        verifier = VLMVerifier(endpoint_url="http://review.invalid/v1/chat/completions", http_transport=provider)
        pipeline = PerceptionPipeline(
            recorder=self.recorder, outbox=self.outbox,
            incident_engines=[UrbanSafetyScenarioEngine(factory="fire_smoke_suspected", min_persistence_seconds=1)],
            vlm_verifier=verifier,
        )
        self.assertEqual(pipeline.process_frame(self.frame, 1.0, 1, detections=[]), [])
        self.assertEqual(pipeline.process_frame(self.frame, 2.2, 2, detections=[]), [])
        self.assertEqual(self.outbox.pending(), [])

    def test_rejected_fire_candidate_does_not_consume_accepted_alert_cooldown(self) -> None:
        decisions = iter((False, True))

        def provider(url: str, body: dict, headers: dict, timeout: float) -> dict:
            return {"choices": [{"message": {"content": json.dumps({
                "verified": next(decisions), "confidence": 0.94,
                "hard_negative_class": None, "reasoning": "Reviewed temporal evidence",
            })}}]}

        pipeline = PerceptionPipeline(
            recorder=self.recorder, outbox=self.outbox,
            incident_engines=[UrbanSafetyScenarioEngine(factory="fire_smoke_suspected", min_persistence_seconds=1)],
            vlm_verifier=VLMVerifier(endpoint_url="http://review.invalid/v1/chat/completions", http_transport=provider),
        )
        self.assertEqual(pipeline.process_frame(self.frame, 1.0, 1, detections=[]), [])
        self.assertEqual(pipeline.process_frame(self.frame, 2.2, 2, detections=[]), [])
        accepted = pipeline.process_frame(self.frame, 3.2, 3, detections=[])
        self.assertEqual([event["payload"]["taxonomy"] for event in accepted], ["fire_suspected"])
        self.assertEqual(accepted[0]["payload"]["vlm_verification"]["confidence"], 0.94)
        self.assertEqual(pipeline.process_frame(self.frame, 4.2, 4, detections=[]), [])

    def _vehicle_pipeline(self, verifier: VLMVerifier | None = None) -> PerceptionPipeline:
        return PerceptionPipeline(
            recorder=self.recorder, outbox=self.outbox, camera_id="review-camera",
            module_configs=[CameraModuleConfig(
                module="vehicle_incident", camera_id="review-camera", version=1, enabled=True,
            )],
            vlm_verifier=verifier,
        )

    def _rollover(self, pipeline: PerceptionPipeline) -> list[dict]:
        events = []
        for index in range(11):
            x = 100.0 + index * 8.0
            events.extend(pipeline.process_frame(self.frame, index * 0.1, index, detections=[{
                "label": "motorcycle", "score": 0.95, "bbox": [x, 200.0, x + 40.0, 280.0],
            }]))
        events.extend(pipeline.process_frame(self.frame, 1.1, 11, detections=[{
            "label": "motorcycle", "score": 0.95, "bbox": [180.0, 220.0, 300.0, 275.0],
        }]))
        return events

    def test_configured_vehicle_incident_includes_projected_metric_position(self) -> None:
        events = self._rollover(self._vehicle_pipeline())
        self.assertEqual([event["payload"]["interaction_type"] for event in events], ["vehicle_rollover_or_barrier"])
        metric = events[0]["payload"]["metric_kinematics"]
        expected = GroundPlaneHomography.default_urban_cctv(640, 360).bbox_foot_to_ground([180, 220, 300, 275])
        self.assertAlmostEqual(metric["x_m"], expected.x_m, places=3)
        self.assertAlmostEqual(metric["y_m"], expected.y_m, places=3)
        self.assertEqual(events[0]["calibration_version"], "uncalibrated")

    def test_selected_verifier_can_suppress_vehicle_candidate(self) -> None:
        def provider(url: str, body: dict, headers: dict, timeout: float) -> dict:
            return {"choices": [{"message": {"content": json.dumps({
                "verified": False, "confidence": 0.94,
                "hard_negative_class": "ordinary_stop", "reasoning": "No rollover in visual evidence",
            })}}]}

        verifier = VLMVerifier(endpoint_url="http://review.invalid/v1/chat/completions", http_transport=provider)
        self.assertEqual(self._rollover(self._vehicle_pipeline(verifier)), [])
        self.assertEqual(self.outbox.pending(), [])

    def test_candidate_verification_coordinator_orchestrates_verification_and_lineage(self) -> None:
        decisions = iter((True, False))

        def provider(url: str, body: dict, headers: dict, timeout: float) -> dict:
            return {"choices": [{"message": {"content": json.dumps({
                "verified": next(decisions), "confidence": 0.92,
                "hard_negative_class": "steam_mist", "reasoning": "Temporal review",
            })}}]}

        verifier = VLMVerifier(endpoint_url="http://review.invalid/v1/chat/completions", http_transport=provider)
        coordinator = CandidateVerificationCoordinator(default_verifier=verifier)
        engine = UrbanSafetyScenarioEngine(factory="fire_smoke_suspected", min_persistence_seconds=1.0)

        # Before active recording, storyboard is empty
        self.assertEqual(len(coordinator.storyboard), 0)

        # Record observation buffers frame
        coordinator.record_observation(self.frame, 1.0, 1, [], [engine])
        self.assertEqual(len(coordinator.storyboard), 1)

        # Candidate 1: verified
        facts_verified = {
            "anchor_kind": "alert_condition",
            "payload": {
                "taxonomy": "fire_suspected",
                "detection_time": 2.0,
                "severity": "critical",
                "confidence": 0.85,
            },
        }
        passed, lineage = coordinator.verify_candidate(
            facts_verified,
            engine=engine,
            timestamp=2.0,
            frame_dimensions=(640.0, 360.0),
        )
        self.assertTrue(passed)
        self.assertTrue(facts_verified["payload"]["vlm_verification"]["verified"])
        self.assertEqual(facts_verified["payload"]["vlm_verification"]["status"], "verified")
        self.assertTrue(any(entry["role"] == "vlm_verifier" for entry in lineage))

        # Candidate 2: rejected; releases cooldown on matching (taxonomy, detection_time)
        engine._last_alert_by_taxonomy["fire_suspected"] = 3.0
        facts_rejected = {
            "anchor_kind": "alert_condition",
            "payload": {
                "taxonomy": "fire_suspected",
                "detection_time": 3.0,
                "severity": "critical",
                "confidence": 0.85,
            },
        }
        passed_reject, _ = coordinator.verify_candidate(
            facts_rejected,
            engine=engine,
            timestamp=3.0,
            frame_dimensions=(640.0, 360.0),
        )
        self.assertFalse(passed_reject)
        self.assertFalse(facts_rejected["payload"]["vlm_verification"]["verified"])
        self.assertNotIn("fire_suspected", engine._last_alert_by_taxonomy)

        # Clear resets storyboard buffer
        coordinator.clear()
        self.assertEqual(len(coordinator.storyboard), 0)
