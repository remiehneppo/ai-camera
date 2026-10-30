"""Behavior tests for incident snapshot construction (ADR-0005, specs S01-S09)."""

from __future__ import annotations

import copy
from typing import Any
import unittest
from uuid import UUID

from apps.edge.snapshot import build_incident_snapshot
from domain.event_contract import validate_event


def _valid_context(**overrides: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "camera_id": "cam-front-01",
        "device_id": "edge-box-01",
        "stream_session_id": "11111111-1111-4111-8111-111111111111",
        "origin": "live",
        "model_lineage": [
            {"role": "detector", "version": "yolov8n-1.0.0"},
            {"role": "pose_estimator", "version": "rtmpose-m"},
        ],
        "model_artifact_hash": "sha256-abcdef0123456789abcdef0123456789",
        "calibration_version": "calib-v1.2",
        "quality": {
            "state": "normal",
            "odd_supported": True,
        },
    }
    ctx.update(overrides)
    return ctx


def _valid_feature(**overrides: Any) -> dict[str, Any]:
    feat: dict[str, Any] = {
        "pipeline_id": "person-down-pipeline-v1",
        "pipeline_version": "1.0.0",
        "config_version": "cfg-person-v1",
        "rule_lineage": [
            {"role": "person_down_rules", "version": "1.0.0"},
        ],
    }
    feat.update(overrides)
    return feat


def _person_down_facts() -> dict[str, Any]:
    return {
        "anchor_kind": "onset",
        "payload": {
            "taxonomy": "person_fall",
            "severity": "critical",
            "confidence": 0.95,
            "anchor_time": 100.0,
            "detection_time": 105.0,
            "lifecycle": "candidate",
            "track_id": 42,
            "detections": [{"bbox": [10.0, 20.0, 30.0, 40.0], "confidence": 0.9}],
            "pose_evidence": {
                "status": "ok",
                "reason": None,
                "branch": "fall",
                "keypoints": [{"name": "nose", "x": 10.0, "y": 20.0, "score": 0.9}],
            },
        },
    }


def _danger_zone_facts() -> dict[str, Any]:
    return {
        "anchor_kind": "alert_condition",
        "payload": {
            "taxonomy": "danger_zone_intrusion",
            "severity": "high",
            "confidence": 0.88,
            "anchor_time": 200.0,
            "detection_time": 200.0,
            "module": "danger_zone",
            "factory": "danger_zone_v1",
            "track_id": 7,
            "person_label": "person",
            "dwell_seconds": 15.5,
            "bbox": [50.0, 60.0, 100.0, 150.0],
            "detections": [{"bbox": [50.0, 60.0, 100.0, 150.0], "confidence": 0.88}],
        },
    }


def _vehicle_incident_facts() -> dict[str, Any]:
    return {
        "anchor_kind": "alert_condition",
        "payload": {
            "taxonomy": "vehicle_incident",
            "severity": "critical",
            "confidence": 0.92,
            "anchor_time": 300.0,
            "detection_time": 300.5,
            "interaction_type": "collision",
            "track_id": 12,
            "track_ids": [12, 15],
            "detections": [{"bbox": [10.0, 10.0, 80.0, 90.0], "confidence": 0.9}],
        },
    }


def _parking_incident_facts() -> dict[str, Any]:
    return {
        "anchor_kind": "alert_condition",
        "payload": {
            "taxonomy": "illegal_parking",
            "severity": "medium",
            "confidence": 0.85,
            "anchor_time": 400.0,
            "detection_time": 425.0,
            "track_id": 99,
            "vehicle_label": "car",
            "dwell_seconds": 25.0,
            "bbox": [120.0, 140.0, 200.0, 220.0],
            "detections": [{"bbox": [120.0, 140.0, 200.0, 220.0], "confidence": 0.85}],
        },
    }


def _crowd_incident_facts() -> dict[str, Any]:
    return {
        "anchor_kind": "alert_condition",
        "payload": {
            "taxonomy": "crowd_concentration",
            "severity": "medium",
            "confidence": 0.89,
            "anchor_time": 500.0,
            "detection_time": 503.0,
            "crowd_count": 8,
            "track_id": 101,
            "track_ids": [101, 102, 103, 104, 105, 106, 107, 108],
            "persistence_seconds": 3.0,
            "disorder_metrics": {"kinetic_energy": 12.5, "dispersion": 0.4},
            "detections": [{"bbox": [0.0, 0.0, 10.0, 10.0], "confidence": 0.8}],
        },
    }


class TestIncidentSnapshotConstruction(unittest.TestCase):
    """Test suite for build_incident_snapshot per design.md and spec S01-S09."""

    def test_all_feature_facts_construct_valid_snapshots(self) -> None:
        """S01: Facts from all five features construct valid full snapshots through the shared seam."""
        features_data: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
            (
                "person_down",
                _person_down_facts(),
                _valid_feature(
                    pipeline_id="person-down-pipeline-v1",
                    pipeline_version="1.0.0",
                    config_version="cfg-person-1",
                    rule_lineage=[{"role": "person_down_rules", "version": "1.0.0"}],
                ),
            ),
            (
                "danger_zone",
                _danger_zone_facts(),
                _valid_feature(
                    pipeline_id="danger-zone-pipeline-v1",
                    pipeline_version="1.0.0",
                    config_version="cfg-dz-1",
                    rule_lineage=[{"role": "danger_zone_incident", "version": "1.0.0"}],
                ),
            ),
            (
                "vehicle_incident",
                _vehicle_incident_facts(),
                _valid_feature(
                    pipeline_id="vehicle-incident-pipeline-v1",
                    pipeline_version="1.0.0",
                    config_version="cfg-veh-1",
                    rule_lineage=[
                        {"role": "vehicle_motion", "version": "1.0.0"},
                        {"role": "vehicle_incident", "version": "1.0.0"},
                    ],
                ),
            ),
            (
                "parking_incident",
                _parking_incident_facts(),
                _valid_feature(
                    pipeline_id="parking-incident-pipeline-v1",
                    pipeline_version="1.0.0",
                    config_version="cfg-park-1",
                    rule_lineage=[{"role": "parking_incident", "version": "1.0.0"}],
                ),
            ),
            (
                "crowd_incident",
                _crowd_incident_facts(),
                _valid_feature(
                    pipeline_id="crowd-incident-pipeline-v1",
                    pipeline_version="1.0.0",
                    config_version="cfg-crowd-1",
                    rule_lineage=[{"role": "crowd_incident", "version": "1.0.0"}],
                ),
            ),
        ]

        context = _valid_context()
        for name, facts, feature in features_data:
            with self.subTest(feature=name):
                snapshot = build_incident_snapshot(facts, context=context, feature=feature)
                validated = validate_event(snapshot)
                self.assertEqual(validated["schema_version"], 1)
                self.assertEqual(validated["revision"], 1)
                self.assertEqual(validated["camera_id"], context["camera_id"])
                self.assertEqual(validated["device_id"], context["device_id"])
                self.assertEqual(validated["stream_session_id"], context["stream_session_id"])
                self.assertEqual(validated["origin"], context["origin"])
                self.assertEqual(validated["pipeline_id"], feature["pipeline_id"])
                self.assertEqual(validated["pipeline_version"], feature["pipeline_version"])
                self.assertEqual(validated["config_version"], feature["config_version"])
                self.assertEqual(validated["quality_state"], context["quality"]["state"])
                self.assertEqual(validated["payload"]["quality"], context["quality"])
                self.assertEqual(len(validated["payload"]["evidence_requests"]), 1)
                self.assertEqual(
                    validated["payload"]["evidence_requests"][0]["session_id"],
                    context["stream_session_id"],
                )

    def test_snapshot_envelope_in_facts_is_rejected_before_persist(self) -> None:
        """S02: Facts supplying envelope or reserved fields are strictly rejected."""
        context = _valid_context()
        feature = _valid_feature()

        # 1. Facts with envelope fields at top level
        top_level_envelope_violations: list[tuple[str, dict[str, Any]]] = [
            ("schema_version", {"schema_version": 1}),
            ("event_id", {"event_id": "00000000-0000-4000-8000-000000000000"}),
            ("camera_id", {"camera_id": "cam-override"}),
            ("device_id", {"device_id": "device-override"}),
            ("origin", {"origin": "live"}),
            ("stream_session_id", {"stream_session_id": "00000000-0000-4000-8000-000000000000"}),
            ("quality", {"quality": {"state": "normal"}}),
            ("evidence_requests", {"evidence_requests": []}),
            ("capability_scope", {"capability_scope": {}}),
        ]
        for field, bad_field in top_level_envelope_violations:
            with self.subTest(top_level_violation=field):
                facts: dict[str, Any] = _danger_zone_facts()
                facts.update(bad_field)
                with self.assertRaises(ValueError):
                    build_incident_snapshot(facts, context=context, feature=feature)

        # 2. Facts payload with reserved fields
        payload_reserved_violations: list[tuple[str, dict[str, Any]]] = [
            ("quality", {"quality": {"state": "normal", "odd_supported": True}}),
            ("evidence_requests", {"evidence_requests": []}),
            ("capability_scope", {"capability_scope": {"capability": "dz"}}),
            ("event_id", {"event_id": "00000000-0000-4000-8000-000000000000"}),
            ("schema_version", {"schema_version": 1}),
            ("produced_at", {"produced_at": "2026-10-30T00:00:00Z"}),
            ("model_lineage", {"model_lineage": []}),
            ("quality_state", {"quality_state": "normal"}),
        ]
        for field, bad_field in payload_reserved_violations:
            with self.subTest(payload_reserved_violation=field):
                facts = _danger_zone_facts()
                facts["payload"].update(bad_field)
                with self.assertRaises(ValueError):
                    build_incident_snapshot(facts, context=context, feature=feature)

        # 3. Missing required semantic fields in payload
        for field in ("taxonomy", "severity", "confidence", "anchor_time", "detection_time"):
            with self.subTest(missing_payload_field=field):
                facts = _danger_zone_facts()
                del facts["payload"][field]
                with self.assertRaises(ValueError):
                    build_incident_snapshot(facts, context=context, feature=feature)

    def test_feature_quality_and_configuration_isolation(self) -> None:
        """S03: Separate features with distinct config/lineage/quality maintain isolation."""
        context_scoped = _valid_context(
            quality={"state": "degraded", "odd_supported": None, "reason": "poor_lighting"},
            capability_scope={"capability": "danger_zone", "camera_id": "cam-front-01"},
        )
        feature_scoped = _valid_feature(
            pipeline_id="danger-zone-pipeline-v1",
            pipeline_version="2.1.0",
            config_version="cfg-dz-scoped-v2",
            rule_lineage=[{"role": "danger_zone_incident", "version": "2.1.0"}],
        )
        snapshot_scoped = build_incident_snapshot(
            _danger_zone_facts(),
            context=context_scoped,
            feature=feature_scoped,
        )

        context_pipeline = _valid_context(
            quality={"state": "normal", "odd_supported": True},
        )
        feature_pipeline = _valid_feature(
            pipeline_id="vehicle-incident-pipeline-v1",
            pipeline_version="1.0.0",
            config_version="cfg-veh-v1",
            rule_lineage=[
                {"role": "vehicle_motion", "version": "1.0.0"},
                {"role": "vehicle_incident", "version": "1.0.0"},
            ],
        )
        snapshot_pipeline = build_incident_snapshot(
            _vehicle_incident_facts(),
            context=context_pipeline,
            feature=feature_pipeline,
        )

        # Verify scoped feature
        self.assertEqual(snapshot_scoped["pipeline_id"], "danger-zone-pipeline-v1")
        self.assertEqual(snapshot_scoped["config_version"], "cfg-dz-scoped-v2")
        self.assertEqual(snapshot_scoped["quality_state"], "degraded")
        self.assertEqual(
            snapshot_scoped["payload"]["capability_scope"],
            {"capability": "danger_zone", "camera_id": "cam-front-01"},
        )
        self.assertIn(
            {"role": "danger_zone_incident", "version": "2.1.0"},
            snapshot_scoped["model_lineage"],
        )

        # Verify pipeline default feature
        self.assertEqual(snapshot_pipeline["pipeline_id"], "vehicle-incident-pipeline-v1")
        self.assertEqual(snapshot_pipeline["config_version"], "cfg-veh-v1")
        self.assertEqual(snapshot_pipeline["quality_state"], "normal")
        self.assertNotIn("capability_scope", snapshot_pipeline["payload"])
        roles = [entry["role"] for entry in snapshot_pipeline["model_lineage"]]
        self.assertIn("vehicle_motion", roles)
        self.assertIn("vehicle_incident", roles)

    def test_scenario_payload_fields_and_lifecycle_are_preserved(self) -> None:
        """S04: Scenario-specific payload fields survive; non-Person features get no false lifecycle."""
        context = _valid_context()

        # Person-down keeps candidate lifecycle
        person_facts = _person_down_facts()
        person_snap = build_incident_snapshot(
            person_facts,
            context=context,
            feature=_valid_feature(pipeline_id="person-down-pipeline-v1"),
        )
        self.assertEqual(person_snap["payload"]["lifecycle"], "candidate")
        self.assertIn("pose_evidence", person_snap["payload"])

        # Danger zone preserves dwell_seconds and bbox, does NOT insert lifecycle
        dz_facts = _danger_zone_facts()
        dz_snap = build_incident_snapshot(
            dz_facts,
            context=context,
            feature=_valid_feature(pipeline_id="danger-zone-pipeline-v1"),
        )
        self.assertEqual(dz_snap["payload"]["dwell_seconds"], 15.5)
        self.assertEqual(dz_snap["payload"]["bbox"], [50.0, 60.0, 100.0, 150.0])
        self.assertEqual(dz_snap["payload"]["module"], "danger_zone")
        self.assertNotIn("lifecycle", dz_snap["payload"])

        # Vehicle incident preserves interaction_type and track_ids, does NOT insert lifecycle
        veh_facts = _vehicle_incident_facts()
        veh_snap = build_incident_snapshot(
            veh_facts,
            context=context,
            feature=_valid_feature(pipeline_id="vehicle-incident-pipeline-v1"),
        )
        self.assertEqual(veh_snap["payload"]["interaction_type"], "collision")
        self.assertEqual(veh_snap["payload"]["track_ids"], [12, 15])
        self.assertNotIn("lifecycle", veh_snap["payload"])

        # Crowd incident preserves crowd_count and disorder_metrics, does NOT insert lifecycle
        crowd_facts = _crowd_incident_facts()
        crowd_snap = build_incident_snapshot(
            crowd_facts,
            context=context,
            feature=_valid_feature(pipeline_id="crowd-incident-pipeline-v1"),
        )
        self.assertEqual(crowd_snap["payload"]["crowd_count"], 8)
        self.assertEqual(
            crowd_snap["payload"]["disorder_metrics"],
            {"kinetic_energy": 12.5, "dispersion": 0.4},
        )
        self.assertNotIn("lifecycle", crowd_snap["payload"])

    def test_snapshot_does_not_alias_mutable_input(self) -> None:
        """S05: Mutating caller input post-construction leaves returned snapshot intact and vice versa."""
        facts = _danger_zone_facts()
        context = _valid_context()
        feature = _valid_feature(
            rule_lineage=[{"role": "danger_zone_incident", "version": "1.0.0"}],
        )

        snapshot = build_incident_snapshot(facts, context=context, feature=feature)

        # Mutate facts after call
        facts["anchor_kind"] = "onset"
        facts["payload"]["confidence"] = 0.11
        facts["payload"]["dwell_seconds"] = 999.9
        facts["payload"]["detections"].append({"bbox": [0, 0, 0, 0], "confidence": 0.0})

        # Mutate context after call
        context["camera_id"] = "cam-mutated"
        context["quality"]["state"] = "mutated_state"
        context["model_lineage"].append({"role": "injected_model", "version": "9.9.9"})

        # Mutate feature after call
        feature["config_version"] = "cfg-mutated"
        feature["rule_lineage"].append({"role": "injected_rule", "version": "9.9.9"})

        # Assert snapshot did not change
        self.assertEqual(snapshot["camera_id"], "cam-front-01")
        self.assertEqual(snapshot["config_version"], "cfg-person-v1")
        self.assertEqual(snapshot["quality_state"], "normal")
        self.assertEqual(snapshot["payload"]["quality"]["state"], "normal")
        self.assertEqual(snapshot["payload"]["confidence"], 0.88)
        self.assertEqual(snapshot["payload"]["dwell_seconds"], 15.5)
        self.assertEqual(len(snapshot["payload"]["detections"]), 1)
        self.assertEqual(len(snapshot["model_lineage"]), 3)
        self.assertEqual(
            snapshot["payload"]["evidence_requests"][0]["evidence_anchor_kind"],
            "alert_condition",
        )

        # Mutate returned snapshot; verify original inputs were not affected
        snapshot["payload"]["dwell_seconds"] = 777.7
        self.assertEqual(facts["payload"]["dwell_seconds"], 999.9)

    def test_source_anchor_kind_and_interval_are_preserved(self) -> None:
        """S06: Onset, qualifying observation and alert-condition anchors maintain original interval."""
        context = _valid_context()
        feature = _valid_feature()

        # Onset with detection_time much later than anchor_time
        facts_onset: dict[str, Any] = {
            "anchor_kind": "onset",
            "payload": {
                "taxonomy": "person_fall",
                "severity": "critical",
                "confidence": 0.9,
                "anchor_time": 0.0,
                "detection_time": 15.0,
            },
        }
        snap_onset = build_incident_snapshot(facts_onset, context=context, feature=feature)
        req_onset = snap_onset["payload"]["evidence_requests"][0]
        self.assertEqual(req_onset["evidence_anchor_kind"], "onset")
        self.assertEqual(req_onset["evidence_anchor_time"], 0.0)
        self.assertEqual(req_onset["requested_start"], -10.0)
        self.assertEqual(req_onset["requested_end"], 20.0)
        self.assertEqual(req_onset["policy_version"], "lab-pre10-post20-v1")

        # First qualifying observation
        facts_fqo: dict[str, Any] = {
            "anchor_kind": "first_qualifying_observation",
            "payload": {
                "taxonomy": "person_lying_persistent",
                "severity": "high",
                "confidence": 0.85,
                "anchor_time": 45.0,
                "detection_time": 60.0,
            },
        }
        snap_fqo = build_incident_snapshot(facts_fqo, context=context, feature=feature)
        req_fqo = snap_fqo["payload"]["evidence_requests"][0]
        self.assertEqual(req_fqo["evidence_anchor_kind"], "first_qualifying_observation")
        self.assertEqual(req_fqo["evidence_anchor_time"], 45.0)
        self.assertEqual(req_fqo["requested_start"], 35.0)
        self.assertEqual(req_fqo["requested_end"], 65.0)

        # Alert condition
        facts_alert: dict[str, Any] = {
            "anchor_kind": "alert_condition",
            "payload": {
                "taxonomy": "danger_zone_intrusion",
                "severity": "high",
                "confidence": 0.9,
                "anchor_time": 120.0,
                "detection_time": 120.0,
            },
        }
        snap_alert = build_incident_snapshot(facts_alert, context=context, feature=feature)
        req_alert = snap_alert["payload"]["evidence_requests"][0]
        self.assertEqual(req_alert["evidence_anchor_kind"], "alert_condition")
        self.assertEqual(req_alert["evidence_anchor_time"], 120.0)
        self.assertEqual(req_alert["requested_start"], 110.0)
        self.assertEqual(req_alert["requested_end"], 140.0)

    def test_invalid_input_is_rejected_by_constructor(self) -> None:
        """Malformed context or source anchors cannot produce a snapshot."""
        context = _valid_context()
        feature = _valid_feature()
        payload = _danger_zone_facts()["payload"]
        invalid_cases = [
            ({"anchor_kind": "onset", "payload": {**payload, "anchor_time": float("nan")}}, context),
            ({"anchor_kind": "onset", "payload": {**payload, "confidence": float("inf")}}, context),
            ({"anchor_kind": "not_an_anchor", "payload": payload}, context),
            (_danger_zone_facts(), _valid_context(stream_session_id="not-a-valid-uuid")),
            (_danger_zone_facts(), {k: v for k, v in context.items() if k != "camera_id"}),
            ("not-a-mapping", context),
            (_danger_zone_facts(), _valid_context(forbidden_extra="token")),
        ]
        for bad_facts, bad_context in invalid_cases:
            with self.subTest(facts=bad_facts, context=bad_context):
                with self.assertRaises(ValueError):
                    build_incident_snapshot(bad_facts, context=bad_context, feature=feature)

    def test_camera_session_reset_preserves_feature_isolation(self) -> None:
        """S09: Interleaving camera/session contexts preserves exact binding and feature isolation."""
        ctx_cam_a = _valid_context(
            camera_id="cam-alpha",
            stream_session_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )
        ctx_cam_b = _valid_context(
            camera_id="cam-beta",
            stream_session_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        )
        feat_dz = _valid_feature(
            pipeline_id="danger-zone-pipeline-v1",
            config_version="cfg-dz",
            rule_lineage=[{"role": "danger_zone_incident", "version": "1.0.0"}],
        )
        feat_veh = _valid_feature(
            pipeline_id="vehicle-incident-pipeline-v1",
            config_version="cfg-veh",
            rule_lineage=[{"role": "vehicle_incident", "version": "1.0.0"}],
        )

        snap_a = build_incident_snapshot(_danger_zone_facts(), context=ctx_cam_a, feature=feat_dz)
        snap_b = build_incident_snapshot(_vehicle_incident_facts(), context=ctx_cam_b, feature=feat_veh)

        self.assertEqual(snap_a["camera_id"], "cam-alpha")
        self.assertEqual(snap_a["stream_session_id"], "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        self.assertEqual(snap_a["pipeline_id"], "danger-zone-pipeline-v1")
        self.assertEqual(snap_a["payload"]["evidence_requests"][0]["session_id"], "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

        self.assertEqual(snap_b["camera_id"], "cam-beta")
        self.assertEqual(snap_b["stream_session_id"], "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        self.assertEqual(snap_b["pipeline_id"], "vehicle-incident-pipeline-v1")
        self.assertEqual(snap_b["payload"]["evidence_requests"][0]["session_id"], "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

    def test_fresh_identity_and_timestamps_per_call(self) -> None:
        """Constructing twice from identical facts/context mints new UUIDs and valid timestamps."""
        facts = _danger_zone_facts()
        context = _valid_context()
        feature = _valid_feature()

        snap1 = build_incident_snapshot(facts, context=context, feature=feature)
        snap2 = build_incident_snapshot(facts, context=context, feature=feature)

        self.assertNotEqual(snap1["event_id"], snap2["event_id"])
        self.assertNotEqual(snap1["message_id"], snap2["message_id"])
        self.assertNotEqual(
            snap1["payload"]["evidence_requests"][0]["request_id"],
            snap2["payload"]["evidence_requests"][0]["request_id"],
        )
        UUID(snap1["event_id"])
        UUID(snap2["event_id"])
        self.assertTrue(snap1["event_time"].endswith("Z"))
        self.assertTrue(snap1["produced_at"].endswith("Z"))

    def test_model_lineage_merge_and_vehicle_motion_preservation(self) -> None:
        """Runtime detector/pose provenance and feature rule lineage (including vehicle_motion) merge cleanly."""
        context = _valid_context(
            model_lineage=[
                {"role": "detector", "version": "yolov8x-2.0.0"},
                {"role": "pose_estimator", "version": "rtmpose-l-1.0.0"},
            ],
        )
        feature = _valid_feature(
            rule_lineage=[
                {"role": "vehicle_motion", "version": "1.2.0"},
                {"role": "vehicle_incident", "version": "1.0.0"},
                # Attempt to inject a detector role from feature: should be filtered out
                {"role": "vehicle_detector", "version": "fake-detector"},
            ],
        )

        snapshot = build_incident_snapshot(_vehicle_incident_facts(), context=context, feature=feature)
        roles = [entry["role"] for entry in snapshot["model_lineage"]]
        self.assertEqual(roles, ["detector", "pose_estimator", "vehicle_motion", "vehicle_incident"])
        self.assertNotIn("vehicle_detector", roles)


if __name__ == "__main__":
    unittest.main()
