"""Integration coverage for ticket #27: on-vehicle review with its own priority.

The edge engine may demote a person-lying event to ``person_on_stationary_vehicle`` only when
the person went down onto a motorcycle that was already stationary and upright. Every danger
signal (observed falling onset, fallen/overturning vehicle, late or moving vehicle, observation
gap) must keep the normal review priority. The final case drives the real pipeline, outbox,
server ingest, review and dataset export paths.

Fixtures are deterministic software-lab frames; they are integration evidence, not field,
hardware, ODD or production-capacity acceptance.
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
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import Track, bbox_iou
from apps.server.config import load_server_config
from apps.server.main import create_app
from domain.event_contract import validate_event
from tests.test_server_evidence import server_env

DASHBOARD = {"Authorization": "Bearer dashboard-secret-token"}
DEVICE = {"Authorization": "Bearer token-edge-1"}
REVIEWER = {"Authorization": "Bearer reviewer-secret-alice"}

# Motorcycle bbox is 60 wide x 100 tall (AR 0.6): a parked, upright two-wheeler.
BIKE_UPRIGHT = [300.0, 180.0, 360.0, 280.0]
# Overturned two-wheeler: 140 wide x 40 tall (AR 3.5).
BIKE_FALLEN = [300.0, 240.0, 440.0, 280.0]
# Person lying horizontally across the bike: 160 wide x 60 tall (AR 2.67).
PERSON_LYING = [245.0, 200.0, 405.0, 260.0]
# Person standing in front of the bike: 60 wide x 160 tall (AR 0.375).
PERSON_STANDING = [300.0, 120.0, 360.0, 280.0]


def _track(track_id: int, bbox: list[float], timestamp: float, label: str) -> Track:
    return Track(track_id, list(bbox), 0.9, label, timestamp)


def _advance(
    engine: IncidentEngine,
    tracks: list[Track],
    boxes: dict[int, list[float]],
    *,
    start: float,
    stop: float,
    step: float = 0.1,
) -> list[dict[str, Any]]:
    """Drive every track through the engine one frame at a time until it emits."""
    emitted: list[dict[str, Any]] = []
    timestamp = start
    while timestamp <= stop + 1e-9 and not emitted:
        for track in tracks:
            track.update(boxes[track.track_id], 0.9, timestamp)
        emitted.extend(engine.process_tracks(tracks, timestamp=timestamp))
        timestamp = round(timestamp + step, 2)
    return emitted


class OnVehicleIncidentEngineTests(unittest.TestCase):
    """Ticket #27 edge semantics: low-priority on-vehicle review plus danger overrides."""

    def test_on_vehicle_stationary_upright_emits_low_severity(self) -> None:
        """Lying on a parked upright motorcycle is reviewed, never suppressed."""
        engine = IncidentEngine(
            min_lying_duration=3.0,
            persistent_lying_duration=3.0,
            cooldown_seconds=30.0,
        )
        bike = _track(700, BIKE_UPRIGHT, 0.0, "motorcycle")
        self.assertEqual(engine.process_tracks([bike], timestamp=0.0), [])

        person = _track(701, PERSON_LYING, 1.0, "person")
        first_qualifying_time = 1.0
        self.assertGreater(
            bbox_iou(PERSON_LYING, BIKE_UPRIGHT),
            engine.vehicle_overlap_iou,
            "the fixture must actually overlap the vehicle so bbox-overlap suppression is exercised",
        )

        emitted = _advance(
            engine,
            [bike, person],
            {700: BIKE_UPRIGHT, 701: PERSON_LYING},
            start=1.0,
            stop=5.0,
        )

        self.assertEqual(len(emitted), 1, "on-vehicle lowers priority; it must not suppress the event")
        incident = emitted[0]
        self.assertEqual(incident["taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(incident["severity"], "low")
        self.assertEqual(incident["anchor_kind"], "first_qualifying_observation")
        self.assertAlmostEqual(incident["anchor_time"], first_qualifying_time, delta=1e-6)
        self.assertEqual(incident["track_id"], 701)
        self.assertEqual(incident["vehicle_track_id"], 700)
        self.assertIn("vehicle_track_id", incident)

    def test_danger_override_falling_onset_with_vehicle(self) -> None:
        """An observed fast drop over the bike stays a critical person_fall."""
        engine = IncidentEngine(min_lying_duration=3.0, cooldown_seconds=30.0)
        bike = _track(710, BIKE_UPRIGHT, 0.0, "motorcycle")
        self.assertEqual(engine.process_tracks([bike], timestamp=0.0), [])

        person = _track(711, PERSON_STANDING, 1.0, "person")
        bike.update(BIKE_UPRIGHT, 0.9, 1.0)
        self.assertEqual(engine.process_tracks([bike, person], timestamp=1.0), [])
        self.assertTrue(engine._states[711].had_standing)
        self.assertGreater(bbox_iou(PERSON_STANDING, BIKE_UPRIGHT), engine.vehicle_overlap_iou)

        emitted = _advance(
            engine,
            [bike, person],
            {710: BIKE_UPRIGHT, 711: PERSON_LYING},
            start=1.1,
            stop=6.0,
        )

        self.assertEqual(len(emitted), 1)
        incident = emitted[0]
        self.assertEqual(incident["taxonomy"], "person_fall")
        self.assertEqual(incident["severity"], "critical")
        self.assertEqual(incident["anchor_kind"], "onset")
        self.assertEqual(incident["track_id"], 711)
        self.assertNotIn("vehicle_track_id", incident)

    def test_danger_override_fallen_vehicle(self) -> None:
        """A fallen or overturning vehicle prevents the low-priority on-vehicle label."""
        with self.subTest("already fallen motorcycle"):
            engine = IncidentEngine(persistent_lying_duration=1.0, cooldown_seconds=30.0)
            bike = _track(720, BIKE_FALLEN, 0.0, "motorcycle")
            self.assertEqual(engine.process_tracks([bike], timestamp=0.0), [])

            person = _track(721, PERSON_LYING, 1.0, "person")
            emitted = _advance(
                engine,
                [bike, person],
                {720: BIKE_FALLEN, 721: PERSON_LYING},
                start=1.0,
                stop=3.0,
            )

            self.assertEqual(len(emitted), 1)
            incident = emitted[0]
            self.assertEqual(incident["taxonomy"], "person_lying_persistent")
            self.assertEqual(incident["severity"], "high")
            self.assertNotIn("vehicle_track_id", incident)

        with self.subTest("motorcycle overturns after the lying onset"):
            engine = IncidentEngine(persistent_lying_duration=1.0, cooldown_seconds=30.0)
            bike = _track(730, BIKE_UPRIGHT, 0.0, "motorcycle")
            self.assertEqual(engine.process_tracks([bike], timestamp=0.0), [])

            person = _track(731, PERSON_LYING, 0.5, "person")
            bike.update(BIKE_UPRIGHT, 0.9, 0.5)
            self.assertEqual(engine.process_tracks([bike, person], timestamp=0.5), [])
            # The vehicle qualified at onset; the later tilt must revoke the demotion.
            self.assertEqual(engine._states[731].on_vehicle_track_id, 730)

            emitted: list[dict[str, Any]] = []
            for index in range(6, 21):
                timestamp = round(index * 0.1, 2)
                current_bike = BIKE_FALLEN if timestamp >= 1.0 else BIKE_UPRIGHT
                bike.update(current_bike, 0.9, timestamp)
                person.update(PERSON_LYING, 0.9, timestamp)
                emitted.extend(engine.process_tracks([bike, person], timestamp=timestamp))

            self.assertEqual(len(emitted), 1)
            incident = emitted[0]
            self.assertEqual(incident["taxonomy"], "person_lying_persistent")
            self.assertEqual(incident["severity"], "high")
            self.assertNotIn("vehicle_track_id", incident)

    def test_late_or_moving_vehicle_not_on_vehicle(self) -> None:
        """A vehicle that was not already parked cannot demote a ground-level lying event."""
        with self.subTest("motorcycle arrives after the person is already lying"):
            engine = IncidentEngine(persistent_lying_duration=1.0, cooldown_seconds=30.0)
            person = _track(740, PERSON_LYING, 0.0, "person")
            self.assertEqual(engine.process_tracks([person], timestamp=0.0), [])
            self.assertIsNone(engine._states[740].on_vehicle_track_id)

            bike = _track(741, BIKE_UPRIGHT, 0.8, "motorcycle")
            emitted: list[dict[str, Any]] = []
            emitted.extend(engine.process_tracks([bike, person], timestamp=0.8))
            self.assertIsNone(
                engine._states[740].on_vehicle_track_id,
                "a vehicle arriving after the lying onset must not be snapshotted retroactively",
            )
            emitted.extend(
                _advance(
                    engine,
                    [bike, person],
                    {741: BIKE_UPRIGHT, 740: PERSON_LYING},
                    start=0.9,
                    stop=2.5,
                )
            )

            self.assertEqual(len(emitted), 1)
            incident = emitted[0]
            self.assertEqual(incident["taxonomy"], "person_lying_persistent")
            self.assertEqual(incident["severity"], "high")
            self.assertNotIn("vehicle_track_id", incident)

        with self.subTest("motorcycle is still moving and only stops afterwards"):
            engine = IncidentEngine(
                persistent_lying_duration=1.0,
                cooldown_seconds=30.0,
                max_motion_speed=50.0,
            )
            person = _track(750, PERSON_LYING, 0.0, "person")
            bike = _track(751, [100.0, 180.0, 160.0, 280.0], 0.0, "motorcycle")
            self.assertEqual(engine.process_tracks([bike, person], timestamp=0.0), [])

            emitted: list[dict[str, Any]] = []
            for index in range(1, 16):
                timestamp = round(index * 0.1, 2)
                # 20 px per 0.1s = 200 px/s > max_motion_speed, then it parks across
                # the person at t=1.0. The late stop must not demote the event.
                offset = min(index * 20.0, 200.0)
                bike.update([100.0 + offset, 180.0, 160.0 + offset, 280.0], 0.9, timestamp)
                person.update(PERSON_LYING, 0.9, timestamp)
                emitted.extend(engine.process_tracks([bike, person], timestamp=timestamp))
                if emitted:
                    break

            self.assertEqual(len(emitted), 1)
            incident = emitted[0]
            self.assertEqual(incident["taxonomy"], "person_lying_persistent")
            self.assertEqual(incident["severity"], "high")
            self.assertNotIn("vehicle_track_id", incident)

    def test_observation_gap_resets_vehicle_and_person_continuity(self) -> None:
        """A gap drops the old vehicle stationarity and restarts the lying qualification."""
        with self.subTest("explicit observation_gap clears vehicle history"):
            engine = IncidentEngine(
                persistent_lying_duration=1.0,
                cooldown_seconds=30.0,
                max_observation_gap=1.0,
            )
            bike = _track(760, BIKE_UPRIGHT, 0.0, "motorcycle")
            person = _track(761, PERSON_LYING, 0.2, "person")
            self.assertEqual(engine.process_tracks([bike], timestamp=0.0), [])
            for index in range(2, 7):
                timestamp = round(index * 0.1, 2)
                bike.update(BIKE_UPRIGHT, 0.9, timestamp)
                person.update(PERSON_LYING, 0.9, timestamp)
                self.assertEqual(engine.process_tracks([bike, person], timestamp=timestamp), [])
            self.assertEqual(engine._states[761].on_vehicle_track_id, 760)
            self.assertIn(760, engine._vehicle_states)

            engine.observation_gap()
            self.assertEqual(engine._vehicle_states, {}, "gap must drop pre-gap vehicle continuity")
            self.assertIsNone(engine._states[761].on_vehicle_track_id)
            self.assertIsNone(engine._states[761].first_qualifying_time)

            emitted: list[dict[str, Any]] = []
            timestamp = 0.7
            while timestamp <= 2.5 and not emitted:
                bike.update(BIKE_UPRIGHT, 0.9, timestamp)
                person.update(PERSON_LYING, 0.9, timestamp)
                emitted.extend(engine.process_tracks([bike, person], timestamp=timestamp))
                timestamp = round(timestamp + 0.1, 2)

            self.assertEqual(len(emitted), 1)
            incident = emitted[0]
            self.assertEqual(incident["taxonomy"], "person_lying_persistent")
            self.assertEqual(incident["severity"], "high")
            self.assertNotIn("vehicle_track_id", incident)
            self.assertAlmostEqual(incident["anchor_time"], 0.7, delta=1e-6)

        with self.subTest("timestamp gap larger than max_observation_gap resets continuity"):
            engine = IncidentEngine(
                persistent_lying_duration=1.0,
                cooldown_seconds=30.0,
                max_observation_gap=1.0,
            )
            bike = _track(770, BIKE_UPRIGHT, 0.0, "motorcycle")
            person = _track(771, PERSON_LYING, 0.2, "person")
            self.assertEqual(engine.process_tracks([bike], timestamp=0.0), [])
            for index in range(2, 7):
                timestamp = round(index * 0.1, 2)
                bike.update(BIKE_UPRIGHT, 0.9, timestamp)
                person.update(PERSON_LYING, 0.9, timestamp)
                self.assertEqual(engine.process_tracks([bike, person], timestamp=timestamp), [])
            self.assertEqual(engine._states[771].on_vehicle_track_id, 770)

            # Reconnect after 1.4s with no vehicle observation: the pre-gap vehicle state
            # must not be reused, and no premature event may fire.
            self.assertEqual(
                engine.process_tracks([person], timestamp=2.0),
                [],
                "a gap must not trigger an event from the pre-gap qualifying window",
            )
            self.assertEqual(engine._vehicle_states, {})
            self.assertIsNone(engine._states[771].on_vehicle_track_id)
            self.assertAlmostEqual(engine._states[771].first_qualifying_time, 2.0)

            bike.update(BIKE_UPRIGHT, 0.9, 2.1)
            emitted: list[dict[str, Any]] = []
            emitted.extend(engine.process_tracks([bike, person], timestamp=2.1))
            self.assertEqual(emitted, [], "post-gap lying window must restart from t=2.0")

            timestamp = 2.2
            while timestamp <= 4.0 and not emitted:
                bike.update(BIKE_UPRIGHT, 0.9, timestamp)
                person.update(PERSON_LYING, 0.9, timestamp)
                emitted.extend(engine.process_tracks([bike, person], timestamp=timestamp))
                timestamp = round(timestamp + 0.1, 2)

            self.assertEqual(len(emitted), 1)
            incident = emitted[0]
            self.assertEqual(incident["taxonomy"], "person_lying_persistent")
            self.assertEqual(incident["severity"], "high")
            self.assertNotIn("vehicle_track_id", incident)
            self.assertAlmostEqual(incident["anchor_time"], 2.0, delta=1e-6)


class OnVehiclePipelineToServerTests(unittest.TestCase):
    """Ticket #27 end-to-end: pipeline -> outbox -> ingest -> review -> dataset export."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="on-vehicle-flow-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.rgb = np.zeros((360, 640, 3), dtype=np.uint8)

    def _pipeline(self) -> tuple[PerceptionPipeline, EventOutbox]:
        outbox = EventOutbox(self.root / "state" / "events.sqlite3")
        pipeline = PerceptionPipeline(
            recorder=FileRecorder(self.root / "ring"),
            outbox=outbox,
            incident_engine=IncidentEngine(
                min_lying_duration=3.0,
                persistent_lying_duration=1.0,
                cooldown_seconds=30.0,
            ),
            camera_id="lab-camera-01",
            device_id="lab-edge-01",
        )
        return pipeline, outbox

    def _produce_on_vehicle_event(self, pipeline: PerceptionPipeline) -> dict[str, Any]:
        bike_det = [{"bbox": list(BIKE_UPRIGHT), "score": 0.9, "label": "motorcycle"}]
        for index in range(6):  # the motorcycle is already parked before the person appears
            pipeline.process_frame(
                self.rgb,
                timestamp=round(index * 0.1, 2),
                frame_id=index,
                detections=bike_det,
            )

        person_det = {"bbox": list(PERSON_LYING), "score": 0.88, "label": "person"}
        emitted: list[dict[str, Any]] = []
        for index in range(6, 50):
            events = pipeline.process_frame(
                self.rgb,
                timestamp=round(index * 0.1, 2),
                frame_id=index,
                detections=[*bike_det, person_det],
            )
            emitted.extend(events)
            if emitted:
                break
        self.assertEqual(len(emitted), 1, "expected exactly one on-vehicle review event")
        return emitted[0]

    def test_e2e_pipeline_to_outbox_server_review_and_dataset_export(self) -> None:
        pipeline, outbox = self._pipeline()
        produced = self._produce_on_vehicle_event(pipeline)
        payload = produced["payload"]
        self.assertEqual(payload["taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(payload["severity"], "low")
        self.assertIn("vehicle_track_id", payload)
        self.assertEqual(
            payload["evidence_requests"][0]["evidence_anchor_kind"],
            "first_qualifying_observation",
        )
        self.assertEqual(validate_event(produced), produced)

        pending = outbox.pending()
        self.assertEqual(len(pending), 1, "the low-priority review event must still be queued")
        item = pending[0]
        self.assertEqual(item["event"]["event_id"], produced["event_id"])
        self.assertEqual(item["event"]["payload"]["taxonomy"], "person_on_stationary_vehicle")

        database = "on_vehicle_flow_" + uuid4().hex
        server_root = Path(tempfile.mkdtemp(prefix="on-vehicle-flow-srv-"))
        self.addCleanup(shutil.rmtree, server_root, ignore_errors=True)
        config = load_server_config(server_env(str(server_root / "evidence"), database))
        app = create_app(config)
        store = app.state.event_store
        store.ensure_ready()
        self.addCleanup(store.close)
        self.addCleanup(store.database.client.drop_database, database)
        client = TestClient(app)
        self.addCleanup(client.close)

        ingested = client.post(
            "/v1/events",
            content=json.dumps(item["event"], ensure_ascii=False),
            headers={
                **DEVICE,
                "Content-Type": "application/json",
                "Idempotency-Key": item["message_id"],
            },
        )
        self.assertEqual(ingested.status_code, 200, ingested.text)
        receipt = ingested.json()
        self.assertEqual(receipt["event_hash"], item["event_hash"])
        self.assertTrue(receipt["accepted"])
        outbox.mark_delivered(item["message_id"], receipt)
        self.assertEqual(outbox.pending(), [])

        listing = client.get("/v1/events", headers=DASHBOARD)
        self.assertEqual(listing.status_code, 200, listing.text)
        rows = listing.json()["events"]
        row = next(r for r in rows if r["event"]["event_id"] == produced["event_id"])
        self.assertEqual(row["review_priority"], "low")
        self.assertEqual(row["taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(row["severity"], "low")

        low_severity = client.get("/v1/events?severity=low", headers=DASHBOARD)
        self.assertEqual(low_severity.status_code, 200, low_severity.text)
        self.assertIn(
            produced["event_id"],
            [r["event"]["event_id"] for r in low_severity.json()["events"]],
        )

        by_taxonomy = client.get(
            "/v1/events?taxonomy=person_on_stationary_vehicle", headers=DASHBOARD
        )
        self.assertEqual(by_taxonomy.status_code, 200, by_taxonomy.text)
        self.assertEqual(
            [r["event"]["event_id"] for r in by_taxonomy.json()["events"]],
            [produced["event_id"]],
        )
        self.assertEqual(by_taxonomy.json()["events"][0]["review_priority"], "low")

        reviewed = client.post(
            f"/v1/events/{row['event']['device_id']}/{row['event']['event_id']}/review",
            json={
                "action": "confirm",
                "expected_review_version": 0,
                "viewed_event_revision": row["event"]["revision"],
                "viewed_event_hash": receipt["event_hash"],
                "viewed_evidence_versions": row["evidence_versions"],
                "reason": "on-vehicle posture reviewed at low priority",
            },
            headers=REVIEWER,
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        review_state = reviewed.json()
        self.assertEqual(review_state["decision"], "confirmed")
        self.assertEqual(review_state["review_version"], 1)
        self.assertEqual(review_state["reviewed_taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(review_state["reviewed_severity"], "low")
        self.assertEqual(review_state["reviewed_review_priority"], "low")

        exported = client.get("/v1/dataset/export?format=json&decision=confirmed", headers=DASHBOARD)
        self.assertEqual(exported.status_code, 200, exported.text)
        exported_body = exported.json()
        self.assertEqual(exported_body["count"], 1)
        record = exported_body["records"][0]
        self.assertEqual(record["event_id"], produced["event_id"])
        self.assertEqual(record["taxonomy"], "person_on_stationary_vehicle")
        self.assertEqual(record["severity"], "low")
        self.assertEqual(record["review_priority"], "low")
        self.assertEqual(record["reviewed_decision"], "confirmed")
        self.assertEqual(record["reviewed_event_hash"], receipt["event_hash"])
        self.assertEqual(record["model_lineage"], produced["model_lineage"])
        self.assertTrue(record["model_lineage"], "exported record must keep producer lineage")
        self.assertEqual(
            record["original_ai_payload"]["taxonomy"], "person_on_stationary_vehicle"
        )

        filtered = client.get(
            "/v1/dataset/export?format=json&decision=confirmed"
            "&taxonomy=person_on_stationary_vehicle",
            headers=DASHBOARD,
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        filtered_body = filtered.json()
        self.assertEqual(filtered_body["count"], 1)
        filtered_record = filtered_body["records"][0]
        self.assertEqual(filtered_record["event_id"], produced["event_id"])
        self.assertEqual(filtered_record["review_priority"], "low")
        self.assertEqual(filtered_record["model_lineage"], record["model_lineage"])


if __name__ == "__main__":
    unittest.main()
