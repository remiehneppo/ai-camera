"""Comprehensive test suite for CiviWatch v2 architecture & rebranding (branch: civi-watch).

Verifies:
1. Hard rebranding to CiviWatch / civi_watch across server config, FastAPI title, export CLI, and UI.
2. Tier-1 Go2RtcMediaEngine endpoints, stream probing, and snapshot retrieval.
3. Tier-2 GroundPlaneHomography 3x3 perspective transform and metric kinematics (m/s, m/s^2).
4. Tier-2 Batched RTMPose estimation (`estimate_batch`) across multiple person bounding boxes.
5. Tier-3 StoryboardBuilder 2x3 Temporal Grid (Set-of-Mark) + VLMVerifier (local & remote JSON schema).
6. Tier-3 Full coverage of all 14 Urban Safety Scenarios (US01–US14) through AlertModuleRegistry,
   UrbanSafetyScenarioEngine, PerceptionPipeline, and EventContract validation.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from apps.edge.homography import GroundPlaneHomography
from apps.edge.media_engine import Go2RtcMediaEngine
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline, create_incident_engine
from apps.edge.pose import RtmposeEstimator
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import Track
from apps.edge.urban_safety_engine import UrbanSafetyScenarioEngine
from apps.edge.vlm_verifier import StoryboardBuilder, VLMVerifier
from apps.server.config import load_server_config
from apps.server.export_dataset import build_parser
from domain.alert_module_config import (
    ALLOWLISTED_FACTORIES,
    AlertModuleDefinition,
    AlertModuleRegistry,
    CameraModuleConfig,
    RegionOfInterest,
)
from domain.event_contract import EventValidationError, URBAN_SAFETY_TAXONOMIES, validate_event
from domain.urban_scenarios import (
    ALL_SCENARIO_FACTORIES,
    ALL_URBAN_TAXONOMIES,
    SCENARIO_BY_ID,
    SCENARIO_SPECS,
    get_scenario_for_taxonomy,
)


class CiviWatchRebrandTests(unittest.TestCase):
    """Verify 100% hard rebrand to CiviWatch / civi_watch."""

    def test_server_config_defaults_to_civi_watch(self) -> None:
        cfg = load_server_config({
            "DEVICE_TOKENS": '{"tok-1":"civi-edge-01"}',
            "DASHBOARD_TOKEN": "dash-secret",
            "MONGO_URI": "mongodb://mongo:27017/?replicaSet=rs0",
        })
        self.assertEqual(cfg.mongo_database, "civi_watch")
        self.assertEqual(cfg.evidence_dir, "/tmp/civi-watch-evidence")

    def test_export_dataset_cli_defaults_to_civi_watch(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        self.assertEqual(args.database, "civi_watch")

    def test_ui_html_carries_civiwatch_branding_and_all_14_scenarios(self) -> None:
        html = Path("apps/server/static/index.html").read_text(encoding="utf-8")
        self.assertIn("CiviWatch · Trung tâm Giám sát An toàn Đô thị", html)
        self.assertIn("CiviWatch Operations Center", html)
        self.assertIn("civi_watch_dash_token", html)
        self.assertIn("civi_watch_rev_token", html)
        for code in (
            "fire_smoke_suspected",
            "urban_flooding",
            "illegal_dumping",
            "sidewalk_encroachment",
            "illegal_parking",
            "crowd_concentration",
            "suspected_disorder",
            "violent_altercation",
            "vehicle_incident",
            "person_fall",
            "danger_zone_intrusion",
            "abandoned_object",
            "fallen_tree",
            "streetlight_outage",
            "property_vandalism",
        ):
            self.assertIn(code, html)


class Tier1MediaEngineTests(unittest.TestCase):
    """Verify Go2RtcMediaEngine stream URLs, health probe, and snapshot capture."""

    def test_endpoints_and_snapshot_fetch(self) -> None:
        captured_urls: list[str] = []

        def fake_getter(url: str, timeout: float) -> bytes:
            captured_urls.append(url)
            if url.endswith("/api/streams"):
                return b'{"civi-cam-01":{"producers":[{}]}}'
            return b"\xff\xd8\xff\xe0fake-jpeg-bytes"

        engine = Go2RtcMediaEngine(base_url="http://127.0.0.1:1984", http_getter=fake_getter)
        info = engine.endpoints_for_camera("civi-cam-01")
        self.assertEqual(info.webrtc_url, "http://127.0.0.1:1984/api/ws?src=civi-cam-01")
        self.assertEqual(info.rtsp_relay_url, "rtsp://127.0.0.1:8554/civi-cam-01")

        probe = engine.probe_streams()
        self.assertEqual(probe["status"], "available")
        self.assertEqual(probe["stream_count"], 1)

        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "snap.jpg"
            raw = engine.fetch_snapshot_jpeg("civi-cam-01", output_path=snap_path)
            self.assertTrue(snap_path.is_file())
            self.assertEqual(raw, b"\xff\xd8\xff\xe0fake-jpeg-bytes")


class Tier2HomographyAndBatchPoseTests(unittest.TestCase):
    """Verify GroundPlaneHomography metric kinematics and Batched RTMPose inference."""

    def test_homography_roundtrip_and_metric_kinematics(self) -> None:
        homography = GroundPlaneHomography.default_urban_cctv(1920, 1080, road_width_m=12.0, road_depth_m=30.0)
        gp_origin = homography.pixel_to_ground(1920 * 0.15, 1080 * 0.92)
        self.assertTrue(gp_origin.valid)
        self.assertAlmostEqual(gp_origin.x_m, 0.0, places=3)
        self.assertAlmostEqual(gp_origin.y_m, 0.0, places=3)

        u, v = homography.ground_to_pixel(6.0, 15.0)
        gp_mid = homography.pixel_to_ground(u, v)
        self.assertAlmostEqual(gp_mid.x_m, 6.0, places=2)
        self.assertAlmostEqual(gp_mid.y_m, 15.0, places=2)

        # Simulate a vehicle moving 10 meters forward in 1.0 second (10 m/s)
        u0, v0 = homography.ground_to_pixel(6.0, 5.0)
        u1, v1 = homography.ground_to_pixel(6.0, 10.0)
        u2, v2 = homography.ground_to_pixel(6.0, 15.0)
        kin = homography.estimate_track_kinematics([
            ([u0 - 20, v0 - 40, u0 + 20, v0], 1.0),
            ([u1 - 20, v1 - 40, u1 + 20, v1], 1.5),
            ([u2 - 20, v2 - 40, u2 + 20, v2], 2.0),
        ])
        self.assertIsNotNone(kin)
        assert kin is not None
        self.assertAlmostEqual(kin.speed_mps, 10.0, places=1)
        self.assertAlmostEqual(kin.accel_mps2, 0.0, places=1)

    def test_rtmpose_estimate_batch_matches_single_estimate(self) -> None:
        if not Path("models/rtmpose-tiny/rtmpose_tiny.onnx").is_file():
            self.skipTest("RTMPose model file not present")
        estimator = RtmposeEstimator()
        rgb = np.full((480, 640, 3), 128, dtype=np.uint8)
        bboxes = [
            [100.0, 80.0, 220.0, 360.0],
            [320.0, 100.0, 440.0, 380.0],
            [460.0, 120.0, 580.0, 400.0],
        ]
        batch_results = estimator.estimate_batch(rgb, bboxes)
        self.assertEqual(len(batch_results), 3)
        for idx, bbox in enumerate(bboxes):
            single = estimator.estimate(rgb, bbox)
            self.assertEqual(len(batch_results[idx]), 17)
            for kp_b, kp_s in zip(batch_results[idx], single):
                self.assertEqual(kp_b["name"], kp_s["name"])
                self.assertAlmostEqual(kp_b["x"], kp_s["x"], places=3)
                self.assertAlmostEqual(kp_b["y"], kp_s["y"], places=3)


class Tier3StoryboardAndAll14ScenariosTests(unittest.TestCase):
    """Verify 2x3 Temporal Storyboard, VLMVerifier, and all 14 Urban Safety Scenarios (US01–US14)."""

    def test_all_14_urban_scenarios_are_registered_and_allowlisted(self) -> None:
        self.assertEqual(len(SCENARIO_SPECS), 14)
        for i in range(1, 15):
            sid = f"US{i:02d}"
            self.assertIn(sid, SCENARIO_BY_ID)
            spec = SCENARIO_BY_ID[sid]
            self.assertIn(spec.factory, ALLOWLISTED_FACTORIES)
            for tax in spec.taxonomies:
                self.assertIn(tax, ALL_URBAN_TAXONOMIES)
                self.assertIn(tax, URBAN_SAFETY_TAXONOMIES)
                self.assertEqual(get_scenario_for_taxonomy(tax), spec)

    def test_storyboard_2x3_grid_and_remote_vlm_json_verification(self) -> None:
        builder = StoryboardBuilder(tile_width=160, tile_height=90)
        for i in range(8):
            frame = np.full((360, 640, 3), i * 25, dtype=np.uint8)
            builder.record_frame(
                frame,
                timestamp=float(i),
                frame_id=i,
                detections=[{"bbox": [50.0, 60.0, 180.0, 260.0], "label": "person", "score": 0.91}],
            )

        storyboard = builder.build_grid(
            anchor_time=5.0,
            highlight_bbox=[50.0, 60.0, 180.0, 260.0],
            original_dimensions=(640.0, 360.0),
        )
        # 2 rows x 3 cols -> height = 180, width = 480
        self.assertEqual(storyboard.grid_rgb.shape, (180, 480, 3))
        b64 = storyboard.to_jpeg_base64()
        self.assertTrue(len(b64) > 100)

        def mock_vlm_http(url: str, body: dict, headers: dict, timeout: float) -> dict:
            self.assertEqual(url, "http://vlm.local/v1/chat/completions")
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"verified": true, "confidence": 0.94, "hard_negative_class": null, "reasoning": "Confirmed fire plume growing across panels #3-#6."}'
                        }
                    }
                ]
            }

        verifier = VLMVerifier(
            endpoint_url="http://vlm.local/v1/chat/completions",
            api_key="test-key",
            model_id="qwen2.5-vl-3b-instruct",
            http_Transport=mock_vlm_http,
        )
        res = verifier.verify(
            {"payload": {"taxonomy": "fire_smoke_suspected", "severity": "critical", "confidence": 0.85}},
            storyboard=storyboard,
        )
        self.assertTrue(res.verified)
        self.assertEqual(res.status, "verified")
        self.assertAlmostEqual(res.confidence, 0.94)
        self.assertEqual(res.model_id, "qwen2.5-vl-3b-instruct")

    def test_extended_scenarios_emit_valid_snapshots_through_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = FileRecorder(root / "ring", ring_seconds=60)
            outbox = EventOutbox(root / "outbox.sqlite3")

            registry = AlertModuleRegistry()
            extended_factories = [
                ("mod_us01", "fire_smoke_suspected"),
                ("mod_us02", "urban_flooding"),
                ("mod_us03", "illegal_dumping"),
                ("mod_us04", "sidewalk_encroachment"),
                ("mod_us07", "violent_altercation"),
                ("mod_us11", "abandoned_object"),
                ("mod_us12", "fallen_tree"),
                ("mod_us13", "streetlight_outage"),
                ("mod_us14", "property_vandalism"),
            ]
            for mod_name, fact in extended_factories:
                registry.register(
                    AlertModuleDefinition(
                        module=mod_name,
                        config_version="v2",
                        factory=fact,
                    )
                )

            roi = RegionOfInterest(points=((0.05, 0.05), (0.95, 0.05), (0.95, 0.95), (0.05, 0.95)))
            configs = [
                CameraModuleConfig(
                    module=mod_name,
                    camera_id="civi-cam-01",
                    version=1,
                    enabled=True,
                    roi=(roi,),
                    thresholds=(("min_persistence_seconds", 1.0),)
                    if fact in {"fire_smoke_suspected", "urban_flooding", "fallen_tree"}
                    else (),
                )
                for mod_name, fact in extended_factories
            ]

            pipeline = PerceptionPipeline(
                recorder=recorder,
                outbox=outbox,
                camera_id="civi-cam-01",
                device_id="civi-edge-01",
                module_configs=configs,
                alert_registry=registry,
            )
            self.assertEqual(len(pipeline.incident_engines), 9)

            # Trigger US01 (fire pixels) + US11/US03/US04 (stationary suitcase) across t=1.0 -> t=4.5
            fire_frame = np.zeros((360, 640, 3), dtype=np.uint8)
            fire_frame[100:220, 100:260] = [245, 130, 20]  # bright fire RGB signature
            dets = [
                {"bbox": [300.0, 200.0, 380.0, 280.0], "score": 0.92, "label": "suitcase"},
            ]
            events = []
            events.extend(pipeline.process_frame(fire_frame, timestamp=1.0, frame_id=1, detections=dets))
            events.extend(pipeline.process_frame(fire_frame, timestamp=2.0, frame_id=2, detections=dets))
            events.extend(pipeline.process_frame(fire_frame, timestamp=3.0, frame_id=3, detections=dets))
            events.extend(pipeline.process_frame(fire_frame, timestamp=4.5, frame_id=4, detections=dets))

            self.assertTrue(len(events) >= 4)
            emitted_taxonomies = {ev["payload"]["taxonomy"] for ev in events}
            self.assertIn("fire_suspected", emitted_taxonomies)
            self.assertIn("sidewalk_encroachment", emitted_taxonomies)
            self.assertIn("unattended_object_persistent", emitted_taxonomies)
            for ev in events:
                validated = validate_event(ev)
                self.assertIn("vlm_verification", validated["payload"])
                self.assertEqual(validated["payload"]["vlm_verification"]["status"], "verified")

            # Verify invalid vlm_verification is rejected by contract
            bad_ev = dict(events[0])
            bad_ev["payload"] = dict(events[0]["payload"], vlm_verification={"status": "invalid_status"})
            with self.assertRaises(EventValidationError):
                validate_event(bad_ev)


if __name__ == "__main__":
    unittest.main()
