"""Integration coverage for ticket #53: pose outcomes reach the person-down flow.

Every case drives the real consumer (``IncidentEngine`` via ``PerceptionPipeline``): no
scheduler counter is trusted as proof. Scenarios are deterministic software-lab fixtures
(frame/track/session → outcome → incident/detail/evidence → review), so they prove
integration only and are not held-out, ODD, quality, or production-capacity evidence.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from fastapi.testclient import TestClient

from apps.edge.incident import IncidentEngine
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.pose import PoseManager, PoseOutcome, PoseScheduler, RtmposeEstimator
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import Track
from apps.server.config import load_server_config
from apps.server.dataset import export_dataset_records
from apps.server.main import create_app
from domain.event_contract import canonical_event_hash, validate_event
from tests.test_server_evidence import server_env

COCO_KEYPOINTS = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]

STANDING_BBOX = [100.0, 100.0, 160.0, 320.0]
LYING_BBOX = [100.0, 170.0, 300.0, 320.0]

DASHBOARD = {"Authorization": "Bearer dashboard-secret-token"}
DEVICE = {"Authorization": "Bearer token-edge-1"}
REVIEWER = {"Authorization": "Bearer reviewer-secret-alice"}


def _shifted(bbox: list[float], dy: float) -> list[float]:
    return [bbox[0], bbox[1] + dy, bbox[2], bbox[3] + dy]


def _detections(bbox: list[float]) -> list[dict[str, Any]]:
    return [{"bbox": list(bbox), "score": 0.9, "label": "person"}]


def _fall_plan(frames: int = 9, start: float = 1.0, step: float = 0.5) -> list[tuple[float, list[float]]]:
    """Standing → lying → continuing downward slide; onset stays deterministic."""
    plan: list[tuple[float, list[float]]] = []
    for index in range(frames):
        if index == 0:
            bbox = STANDING_BBOX
        elif index == 1:
            bbox = LYING_BBOX
        else:
            bbox = _shifted(LYING_BBOX, 10.0 * (index - 1))
        plan.append((start + index * step, bbox))
    return plan


class _StubDetector:
    """Detector stub pinning provenance; fixtures always supply detections explicitly."""

    provenance = {"model_id": "lab-person-detector-v1", "model_sha256": "a" * 64}

    def detect(self, rgb: np.ndarray, frame: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("fixture supplies detections; detector must not run")


class _MockPoseEstimator:
    """Pose estimator over 17 COCO keypoints that can be switched into a hard failure."""

    def __init__(self) -> None:
        self.manifest = {"model_id": "rtmpose-tiny-256x192"}
        self.fail = False
        self.calls = 0

    def estimate(self, rgb: np.ndarray, bbox: list[float]) -> list[dict[str, Any]]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("inference_failed")
        return [
            {
                "name": name,
                "x": float(bbox[0] + index * 3.0),
                "y": float(bbox[1] + index * 4.0),
                "score": 0.87,
            }
            for index, name in enumerate(COCO_KEYPOINTS)
        ]


def _track(track_id: int, bbox: list[float], timestamp: float) -> Track:
    return Track(track_id, list(bbox), 0.9, "person", timestamp)


class PoseOutcomesFlowTests(unittest.TestCase):
    """Ticket #53 acceptance: pose outcomes enter incident, event, review and export."""

    def _pipeline(
        self,
        estimator: Any,
        *,
        scheduler: PoseScheduler | None = None,
        incident_engine: IncidentEngine | None = None,
    ) -> tuple[PerceptionPipeline, EventOutbox]:
        root = Path(tempfile.mkdtemp(prefix="pose-flow-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        outbox = EventOutbox(root / "state" / "events.sqlite3")
        manager = PoseManager(estimator=estimator, scheduler=scheduler)
        pipeline = PerceptionPipeline(
            recorder=FileRecorder(root / "ring"),
            outbox=outbox,
            detector=_StubDetector(),
            pose_manager=manager,
            incident_engine=incident_engine,
            camera_id="cam-pose-flow",
            device_id="lab-edge-01",
        )
        return pipeline, outbox

    def _run_plan(
        self,
        pipeline: PerceptionPipeline,
        plan: list[tuple[float, list[float]]],
        *,
        frame_offset: int = 0,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rgb = np.full((480, 640, 3), 128, dtype=np.uint8)
        events: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        for index, (timestamp, bbox) in enumerate(plan):
            events.extend(
                pipeline.process_frame(
                    rgb,
                    timestamp=timestamp,
                    frame_id=frame_offset + index + 1,
                    detections=_detections(bbox),
                )
            )
            observations.append(pipeline.last_observation)
        return events, observations

    def _outcomes(self, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [outcome for obs in observations for outcome in obs.get("pose_outcomes") or []]

    def test_pose_outcome_success_reaches_incident_and_event(self) -> None:
        """An 'ok' outcome reaches the incident and the durable event with anchor + lineage."""
        pipeline, outbox = self._pipeline(estimator=RtmposeEstimator())
        events, observations = self._run_plan(pipeline, _fall_plan())

        self.assertEqual(len(events), 1, "one fall alert expected from the fall fixture")
        event = events[0]
        payload = event["payload"]
        evidence = payload["pose_evidence"]

        self.assertEqual(payload["taxonomy"], "person_fall")
        self.assertEqual(evidence["status"], "ok")
        self.assertEqual(evidence["branch"], "fast_fall")
        self.assertIsNone(evidence["reason"])
        self.assertEqual([kp["name"] for kp in evidence["keypoints"]], COCO_KEYPOINTS)
        self.assertEqual(len(evidence["keypoints"]), 17)
        # Evidence stays anchored to the onset, never to the alert condition.
        self.assertLess(payload["anchor_time"], payload["detection_time"])

        incident_frame = observations[-1]
        self.assertEqual(incident_frame["detection_status"], "ok")
        self.assertEqual(incident_frame["pose_status"], "ok")
        self.assertEqual(
            [(o["track_id"], o["status"], o["branch"]) for o in incident_frame["pose_outcomes"]],
            [(payload["track_id"], "ok", "fast_fall")],
        )
        self.assertEqual(len(incident_frame["pose_outcomes"][0]["keypoints"]), 17)

        pending = outbox.pending()
        self.assertEqual(len(pending), 1, "the alert must be durably queued for delivery")
        stored = pending[0]["event"]
        self.assertEqual(stored["payload"]["pose_evidence"], evidence)

        versions = {entry["role"]: entry["version"] for entry in stored["model_lineage"]}
        self.assertEqual(versions["detector"], "lab-person-detector-v1")
        self.assertEqual(versions["pose_estimator"], "rtmpose-tiny-256x192")

        self.assertEqual(validate_event(stored), stored)
        self.assertEqual(pending[0]["event_hash"], canonical_event_hash(validate_event(stored)))

        metrics = pipeline.get_pose_metrics()["fast_fall"]
        self.assertGreaterEqual(metrics["scheduled"], 1)
        self.assertEqual(metrics["attempted"], metrics["scheduled"])
        self.assertEqual(metrics["coverage"], 1.0)

    def test_pose_outcome_skipped_and_failed_do_not_create_false_negative_or_fake_keypoints(self) -> None:
        """Failed and skipped outcomes keep empty keypoints and never suppress the alert."""
        estimator = _MockPoseEstimator()
        estimator.fail = True
        failing_pipeline, failing_outbox = self._pipeline(estimator=estimator)
        events, observations = self._run_plan(failing_pipeline, _fall_plan())

        self.assertEqual(len(events), 1, "a failed pose estimate must not suppress the fall alert")
        failed_event = events[0]
        failed_evidence = failed_event["payload"]["pose_evidence"]
        self.assertEqual(failed_event["payload"]["taxonomy"], "person_fall")
        self.assertEqual(failed_evidence["status"], "failed")
        self.assertEqual(failed_evidence["reason"], "inference_failed")
        self.assertEqual(failed_evidence["keypoints"], [])

        failed_outcomes = self._outcomes(observations)
        self.assertTrue(failed_outcomes)
        self.assertEqual({o["status"] for o in failed_outcomes}, {"failed"})
        self.assertTrue(all(o["keypoints"] == [] for o in failed_outcomes))
        self.assertEqual(observations[-1]["pose_status"], "failed")
        self.assertEqual(observations[-1]["pose_reason"], "inference_failed")
        self.assertEqual(failing_pipeline.get_pose_metrics()["fast_fall"]["failed"], len(failed_outcomes))
        self.assertEqual(validate_event(failing_outbox.pending()[0]["event"]), failing_outbox.pending()[0]["event"])

        # Deadline exceeded: the scheduler never gets budget, so the request misses its deadline.
        skipping_estimator = _MockPoseEstimator()
        skipping_pipeline, _ = self._pipeline(
            estimator=skipping_estimator,
            scheduler=PoseScheduler(max_queue_size=20, batch_budget=0),
        )
        events, observations = self._run_plan(skipping_pipeline, _fall_plan(frames=11))

        self.assertEqual(len(events), 1, "a skipped pose request must not suppress the fall alert")
        skipped_event = events[0]
        skipped_evidence = skipped_event["payload"]["pose_evidence"]
        self.assertEqual(skipped_event["payload"]["taxonomy"], "person_fall")
        self.assertEqual(skipped_evidence["status"], "skipped")
        self.assertEqual(skipped_evidence["reason"], "deadline_exceeded")
        self.assertEqual(skipped_evidence["keypoints"], [])

        skipped_outcomes = self._outcomes(observations)
        self.assertTrue(skipped_outcomes)
        self.assertEqual({o["status"] for o in skipped_outcomes}, {"skipped"})
        self.assertEqual({o["reason"] for o in skipped_outcomes}, {"deadline_exceeded"})
        self.assertTrue(all(o["keypoints"] == [] for o in skipped_outcomes))
        self.assertEqual(skipping_estimator.calls, 0, "a deadline miss must never be reported as an estimate")
        metrics = skipping_pipeline.get_pose_metrics()["fast_fall"]
        self.assertEqual(metrics["attempted"], 0)
        self.assertEqual(metrics["skipped"], len(skipped_outcomes))
        self.assertEqual(validate_event(skipped_event), skipped_event)

    def test_epoch_mismatch_cancels_pose_and_records_stale_metric(self) -> None:
        """Older-epoch requests are cancelled as epoch_mismatch and counted as stale."""
        pipeline, _ = self._pipeline(estimator=_MockPoseEstimator())
        req = PoseOutcome(
            request_id="req-old-epoch",
            camera_id="cam-pose-flow",
            stream_session_id="session-epoch",
            core_epoch=0,
            frame_id=1,
            track_id=1,
            status="cancelled",
            reason="epoch_mismatch",
            branch="fast_fall",
            executed_at=1.0,
        )
        pipeline.pose_scheduler.record_scheduled("fast_fall", 1)
        pipeline.pose_scheduler.record_outcome(req)
        metrics = pipeline.get_pose_metrics()["fast_fall"]
        self.assertEqual(metrics["stale"], 1)

        # Domain receives cancelled outcome without fabricating keypoints
        engine = IncidentEngine()
        track = _track(1, STANDING_BBOX, 1.0)
        engine.process_tracks([track], 1.0, pose_outcomes=[req])
        evidence = engine._pose_evidence(engine._states[1])
        self.assertEqual(evidence["status"], "cancelled")
        self.assertEqual(evidence["reason"], "epoch_mismatch")
        self.assertEqual(evidence["keypoints"], [])

    def test_onset_valid_pose_preserved_across_later_shedding(self) -> None:
        """Valid pose at onset is preserved in incident evidence even if post-onset frames are shed."""
        estimator = _MockPoseEstimator()
        pipeline, _ = self._pipeline(
            estimator=estimator,
            scheduler=PoseScheduler(max_queue_size=20, batch_budget=1),
        )
        events, observations = self._run_plan(pipeline, _fall_plan())
        self.assertEqual(len(events), 1)
        event = events[0]
        evidence = event["payload"]["pose_evidence"]
        self.assertEqual(evidence["status"], "ok")
        self.assertEqual(len(evidence["keypoints"]), 17)
        self.assertIsNotNone(evidence["request_id"])
        self.assertIsNotNone(evidence["frame_id"])

    def test_event_contract_validates_pose_evidence_strictly(self) -> None:
        """domain.event_contract validates payload.pose_evidence schema strictly."""
        from domain.event_contract import EventValidationError
        from tests.test_event_delivery import event_fixture

        valid = event_fixture()
        valid["payload"]["pose_evidence"] = {
            "status": "ok",
            "reason": None,
            "branch": "fast_fall",
            "keypoints": [{"name": "nose", "x": 10.0, "y": 20.0, "score": 0.9}],
            "executed_at": 10.0,
        }
        validated = validate_event(valid)
        self.assertEqual(validated["payload"]["pose_evidence"], valid["payload"]["pose_evidence"])

        # Invalid status
        bad_status = event_fixture()
        bad_status["payload"]["pose_evidence"] = {"status": "invalid_status", "keypoints": []}
        with self.assertRaisesRegex(EventValidationError, "status"):
            validate_event(bad_status)

        # Non-ok status with non-empty keypoints
        bad_kps = event_fixture()
        bad_kps["payload"]["pose_evidence"] = {
            "status": "failed",
            "keypoints": [{"name": "nose", "x": 10.0, "y": 20.0, "score": 0.9}],
        }
        with self.assertRaisesRegex(EventValidationError, "empty keypoints"):
            validate_event(bad_kps)

    def test_track_gap_and_clock_jump_resets_pose_evidence_without_false_certainty(self) -> None:
        """A gap or clock jump drops pose keypoints, branch and motion instead of carrying them."""
        estimator = _MockPoseEstimator()
        pipeline, outbox = self._pipeline(estimator=estimator)
        pre_gap = [
            (1.0, STANDING_BBOX),
            (1.5, LYING_BBOX),
            (2.0, _shifted(LYING_BBOX, 10.0)),
        ]
        self._run_plan(pipeline, pre_gap)

        pre_state = pipeline.incident_engine._states[1]
        self.assertTrue(pre_state.had_standing)
        self.assertEqual(len(pre_state.last_valid_pose["keypoints"]), 17)
        self.assertEqual(pre_state.last_pose_outcome["status"], "ok")

        estimator.fail = True
        settled = _shifted(LYING_BBOX, 10.0)
        post_gap = [(4.0, settled)] + [(4.0 + 0.5 * step, settled) for step in range(1, 11)]
        events, _ = self._run_plan(pipeline, post_gap, frame_offset=len(pre_gap))

        post_state = pipeline.incident_engine._states[1]
        self.assertIsNone(post_state.last_valid_pose, "pre-gap keypoints must not survive the gap")
        self.assertEqual(post_state.last_pose_outcome["status"], "failed")
        self.assertGreaterEqual(post_state.last_pose_outcome["executed_at"], 4.0)

        self.assertEqual(len(events), 1)
        event = events[0]
        evidence = event["payload"]["pose_evidence"]
        # had_standing/onset were dropped with the state: the post-gap alert is the
        # persistent-lying path, not a continuation of the pre-gap fall candidate.
        self.assertEqual(event["payload"]["taxonomy"], "person_lying_persistent")
        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(evidence["keypoints"], [])
        # Evidence reports the newest terminal outcome, which may predate the alert frame
        # because persistent-lying sampling is slower than the frame rate.
        self.assertLessEqual(evidence["executed_at"], event["payload"]["detection_time"])
        self.assertGreaterEqual(evidence["executed_at"], 4.0)
        self.assertEqual(validate_event(event), event)
        self.assertEqual(validate_event(outbox.pending()[0]["event"]), outbox.pending()[0]["event"])

        # Clock jump: an event-time regression also rebuilds the track state.
        engine = IncidentEngine(persistent_lying_duration=3.0, cooldown_seconds=0.0)
        bbox = settled
        okay = PoseOutcome(
            request_id="req-clock-ok",
            camera_id="cam-pose-flow",
            stream_session_id="session-clock",
            core_epoch=1,
            frame_id=1,
            track_id=1,
            status="ok",
            keypoints=[{"name": name, "x": 1.0, "y": 2.0, "score": 0.9} for name in COCO_KEYPOINTS],
            executed_at=10.0,
            branch="fast_fall",
        )
        self.assertEqual(engine.process_tracks([_track(1, bbox, 10.0)], 10.0, pose_outcomes=[okay]), [])
        self.assertEqual(len(engine._states[1].last_valid_pose["keypoints"]), 17)

        stale = PoseOutcome(
            request_id="req-clock-failed",
            camera_id="cam-pose-flow",
            stream_session_id="session-clock",
            core_epoch=1,
            frame_id=2,
            track_id=1,
            status="failed",
            reason="inference_failed",
            executed_at=5.0,
            branch="persistent_lying",
        )
        self.assertEqual(engine.process_tracks([_track(1, bbox, 5.0)], 5.0, pose_outcomes=[stale]), [])
        jumped = engine._states[1]
        self.assertIsNone(jumped.last_valid_pose)
        self.assertEqual(jumped.last_pose_outcome["status"], "failed")
        self.assertEqual(jumped.last_pose_outcome["executed_at"], 5.0)
        self.assertFalse(jumped.had_standing, "the pre-jump motion history must not be reused")

        clock_events: list[dict[str, Any]] = []
        timestamp = 5.5
        while timestamp <= 9.0:
            clock_events.extend(engine.process_tracks([_track(1, bbox, timestamp)], timestamp))
            timestamp = round(timestamp + 0.5, 3)
        self.assertEqual(len(clock_events), 1)
        clock_event = clock_events[0]
        self.assertEqual(clock_event["anchor_kind"], "first_qualifying_observation")
        payload = clock_event["payload"]
        self.assertEqual(payload["taxonomy"], "person_lying_persistent")
        clock_evidence = payload["pose_evidence"]
        self.assertEqual(clock_evidence["status"], "failed")
        self.assertEqual(clock_evidence["reason"], "inference_failed")
        self.assertEqual(clock_evidence["keypoints"], [])
        self.assertLess(clock_evidence["executed_at"], 10.0, "pre-jump outcome must not be reused")

    def test_overload_shedding_and_recovery_flow(self) -> None:
        """Queue pressure sheds low-priority pose work as skipped/queue_full and recovers."""
        pipeline, _ = self._pipeline(
            estimator=_MockPoseEstimator(),
            scheduler=PoseScheduler(max_queue_size=2, batch_budget=0, persistent_lying_deadline=30.0),
        )
        rgb = np.full((480, 640, 3), 128, dtype=np.uint8)
        lying_pair = [_detections([100.0, 170.0, 300.0, 320.0])[0],
                      _detections([400.0, 170.0, 600.0, 320.0])[0]]
        events: list[dict[str, Any]] = []
        shed_observations: list[dict[str, Any]] = []
        timestamp = 1.0
        for index in range(12):
            events.extend(
                pipeline.process_frame(
                    rgb, timestamp=timestamp, frame_id=index + 1, detections=lying_pair
                )
            )
            observation = pipeline.last_observation
            if observation.get("pose_outcomes"):
                shed_observations.append(observation)
            timestamp += 0.5

        shed_outcomes = self._outcomes(shed_observations)
        self.assertGreaterEqual(len(shed_outcomes), 6, "queue pressure must actually shed requests")
        self.assertEqual({o["status"] for o in shed_outcomes}, {"skipped"})
        self.assertEqual({o["reason"] for o in shed_outcomes}, {"queue_full"})
        self.assertTrue(all(o["keypoints"] == [] for o in shed_outcomes))
        for observation in shed_observations:
            self.assertEqual(observation["pose_status"], "skipped")
            self.assertEqual(observation["pose_reason"], "queue_full")

        self.assertEqual(len(events), 2, "both lying tracks must still alert while pose is shed")
        for event in events:
            self.assertEqual(event["payload"]["taxonomy"], "person_lying_persistent")
            evidence = event["payload"]["pose_evidence"]
            self.assertEqual(evidence["status"], "skipped")
            self.assertEqual(evidence["reason"], "queue_full")
            self.assertEqual(evidence["keypoints"], [])
            self.assertEqual(validate_event(event), event)

        metrics = pipeline.get_pose_metrics()
        self.assertEqual(metrics["persistent_lying"]["skipped"], len(shed_outcomes))
        self.assertEqual(metrics["persistent_lying"]["attempted"], 0)
        self.assertEqual(metrics["overall"]["skipped"], len(shed_outcomes))
        self.assertEqual(metrics["overall"]["coverage"], 0.0)

        manager = pipeline.pose_manager
        self.assertEqual(manager.get_capability_status(), "degraded")
        self.assertEqual(manager.get_degraded_reason(), "queue_near_capacity")

        # Drain the backlog and let the hysteresis ramp bring capability back to full.
        for _ in range(6):
            manager.process_pending(100.0)
        self.assertEqual(manager.queued_count(), 0)
        self.assertEqual(manager.get_capability_status(), "full")
        self.assertIsNone(manager.get_degraded_reason())

        pipeline.pose_scheduler.batch_budget = 10
        recovered_events = pipeline.process_frame(
            rgb, timestamp=timestamp + 1.0, frame_id=13, detections=lying_pair
        )
        recovered = pipeline.last_observation
        self.assertEqual({o["status"] for o in recovered["pose_outcomes"]}, {"ok"})
        self.assertTrue(all(len(o["keypoints"]) == 17 for o in recovered["pose_outcomes"]))
        self.assertEqual(recovered["pose_status"], "ok")
        self.assertEqual(recovered_events, [])

    def test_e2e_pose_outcomes_through_outbox_to_server_and_review(self) -> None:
        """Pose evidence survives pipeline → outbox → ingest → review → dataset export."""
        pipeline, outbox = self._pipeline(estimator=_MockPoseEstimator())
        events, _ = self._run_plan(pipeline, _fall_plan())
        self.assertEqual(len(events), 1)
        produced = events[0]
        self.assertEqual(produced["payload"]["pose_evidence"]["status"], "ok")

        pending = outbox.pending()
        self.assertEqual(len(pending), 1)
        item = pending[0]
        self.assertEqual(item["event"]["event_id"], produced["event_id"])
        self.assertEqual(item["event"]["payload"]["pose_evidence"], produced["payload"]["pose_evidence"])

        database = "pose_flow_" + uuid4().hex
        root = Path(tempfile.mkdtemp(prefix="pose-flow-srv-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        config = load_server_config(server_env(str(root / "evidence"), database))
        app = create_app(config)
        store = app.state.event_store
        store.ensure_ready()
        self.addCleanup(store.close)
        self.addCleanup(store.database.client.drop_database, database)
        client = TestClient(app)
        self.addCleanup(client.close)

        receipt_response = client.post(
            "/v1/events",
            content=json.dumps(item["event"], ensure_ascii=False),
            headers={**DEVICE, "Content-Type": "application/json", "Idempotency-Key": item["message_id"]},
        )
        self.assertEqual(receipt_response.status_code, 200, receipt_response.text)
        receipt = receipt_response.json()
        self.assertEqual(receipt["event_hash"], item["event_hash"])
        outbox.mark_delivered(item["message_id"], receipt)
        self.assertEqual(outbox.pending(), [])

        listing = client.get("/v1/events", headers=DASHBOARD)
        self.assertEqual(listing.status_code, 200, listing.text)
        row = next(r for r in listing.json()["events"] if r["event"]["event_id"] == produced["event_id"])
        served_event = row["event"]
        self.assertEqual(served_event, produced)
        self.assertEqual(served_event["payload"]["pose_evidence"]["status"], "ok")
        self.assertEqual(len(served_event["payload"]["pose_evidence"]["keypoints"]), 17)
        self.assertEqual(
            {entry["role"] for entry in served_event["model_lineage"]},
            {"detector", "pose_estimator"},
        )

        review_body = {
            "action": "confirm",
            "expected_review_version": 0,
            "viewed_event_revision": served_event["revision"],
            "viewed_event_hash": receipt["event_hash"],
            "viewed_evidence_versions": row["evidence_versions"],
            "reason": "pose evidence and lineage verified",
        }
        reviewed = client.post(
            f"/v1/events/{served_event['device_id']}/{served_event['event_id']}/review",
            json=review_body,
            headers=REVIEWER,
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        self.assertEqual(reviewed.json()["decision"], "confirmed")
        self.assertEqual(reviewed.json()["review_version"], 1)

        records = export_dataset_records(store=store, split="all", decision="confirmed")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["reviewed_decision"], "confirmed")
        self.assertEqual(record["reviewed_event_hash"], receipt["event_hash"])
        versions = {entry["role"]: entry["version"] for entry in record["model_lineage"]}
        self.assertEqual(versions["detector"], "lab-person-detector-v1")
        self.assertEqual(versions["pose_estimator"], "rtmpose-tiny-256x192")
        exported_evidence = record["original_ai_payload"]["pose_evidence"]
        self.assertEqual(exported_evidence["status"], "ok")
        self.assertEqual(exported_evidence["branch"], "fast_fall")
        self.assertEqual(len(exported_evidence["keypoints"]), 17)

        api_export = client.get("/v1/dataset/export?format=json&decision=confirmed", headers=DASHBOARD)
        self.assertEqual(api_export.status_code, 200, api_export.text)
        body = api_export.json()
        self.assertEqual(body["count"], 1)
        api_record = body["records"][0]
        self.assertEqual(
            {entry["role"] for entry in api_record["model_lineage"]},
            {"detector", "pose_estimator"},
        )
        self.assertEqual(api_record["original_ai_payload"]["pose_evidence"], exported_evidence)


if __name__ == "__main__":
    unittest.main()
