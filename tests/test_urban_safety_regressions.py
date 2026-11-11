"""Behavioral regression tests for CiviWatch Urban Safety Findings F1, F2, F4, F5, F6, F7.

Verifies:
- F1: observation_gap clears per-track continuity/motion/association evidence while preserving alert cooldown;
  first recovered sample cannot accrue gap duration (explicit and automatic max gap).
- F2: UrbanSafetyScenarioEngine always emits candidate facts; pipeline owns verification;
  UrbanSafetyScenarioEngine.reject_candidate(facts) releases only matching cooldown, preserving unrelated cooldowns;
  direct process_tracks cooldown suppresses un-rejected duplicate alerts.
- F4: Polygon rasterization strictly confines fire/smoke/water/luminance within polygon mask;
  outside pixels (including lower bounding box for water) never contribute;
  supports normalized, pixel, and rectangle ROI formats with safe zero-coverage behavior.
- F5: Independent consecutive unattended timer resets while a nearby person is present and on gap;
  duration and anchor_time reflect actual continuous unattended observation.
- F6: Pair-specific consecutive proximity/interaction timer and rolling window motion;
  ordinary first encounter between older tracks cannot trigger violent altercation;
  timer and window motion reset after pair separates, a track goes missing, or an observation gap occurs.
- F7: Strict remote VLM verdict requires actual bool and finite bounded numeric confidence;
  malformed outputs take the existing failed/retain-candidate policy rather than successful verification.
"""

from __future__ import annotations

import os
from typing import Any
import unittest
from unittest.mock import patch

import numpy as np

from apps.edge.tracker import Track
from apps.edge.urban_safety_engine import UrbanSafetyScenarioEngine, extract_environmental_signals
from apps.edge.vlm_verifier import VLMVerifier


def _make_track(
    tid: int | str,
    bbox: list[float],
    ts: float,
    label: str = "person",
    score: float = 0.9,
) -> Track:
    tr = Track(track_id=tid, bbox=bbox, score=score, label=label, timestamp=ts)
    tr.state = "active"
    return tr


class TestF1ObservationGapRegressions(unittest.TestCase):
    """F1: observation_gap clears continuity/motion/association but preserves cooldown; no accrual on recovery."""

    def test_explicit_gap_clears_dwell_and_first_recovered_frame_cannot_accrue(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="sidewalk_encroachment",
            roi_polygon=[[0.0, 0.0], [640.0, 0.0], [640.0, 360.0], [0.0, 360.0]],
            min_dwell_seconds=3.0,
            max_observation_gap=2.0,
        )
        car = _make_track(1, [100.0, 100.0, 160.0, 160.0], 0.0, label="car")

        # Tracked across t=0.0 and t=2.0 (dwell=2.0s < 3.0s) -> no alert
        self.assertEqual(engine.process_tracks([car], timestamp=0.0), [])
        car.timestamp = 2.0
        self.assertEqual(engine.process_tracks([car], timestamp=2.0), [])

        # Explicit observation gap occurs (e.g. RTSP reconnect / dropped frames)
        engine.observation_gap()

        # First recovered sample 8 seconds later at t=10.0: must NOT accrue 8s gap into dwell
        car.timestamp = 10.0
        self.assertEqual(engine.process_tracks([car], timestamp=10.0), [])

        # Frame at t=12.0 (only 2.0s since recovery at t=10.0, still below min_dwell_seconds=3.0) -> no alert
        car.timestamp = 12.0
        self.assertEqual(engine.process_tracks([car], timestamp=12.0), [])

        # Frame at t=13.0 (3.0s continuous observation since recovery) -> exactly 1 event emitted
        car.timestamp = 13.0
        events = engine.process_tracks([car], timestamp=13.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["taxonomy"], "sidewalk_encroachment")
        self.assertAlmostEqual(events[0]["payload"]["dwell_seconds"], 3.0, places=2)

    def test_explicit_gap_clears_motion_evidence(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="property_vandalism",
            roi_polygon=[[0.0, 0.0], [640.0, 0.0], [640.0, 360.0], [0.0, 360.0]],
            min_impact_duration_seconds=2.0,
            motion_energy_threshold=30.0,
            max_observation_gap=2.0,
        )
        # Person oscillates vigorously before gap (speed = 120 px/s > 30, net_disp = 0 -> non-linear)
        p1 = _make_track(1, [100.0, 100.0, 140.0, 200.0], 0.0, label="person")
        engine.process_tracks([p1], timestamp=0.0)
        p1_mid = _make_track(1, [160.0, 100.0, 200.0, 200.0], 0.5, label="person")
        engine.process_tracks([p1_mid], timestamp=0.5)
        p1_back = _make_track(1, [100.0, 100.0, 140.0, 200.0], 1.0, label="person")
        engine.process_tracks([p1_back], timestamp=1.0)

        # Gap clears prior motion peak evidence
        engine.observation_gap()

        # Person stands completely still after gap for 2 seconds (speed = 0.0 px/s)
        p_still = _make_track(1, [100.0, 100.0, 140.0, 200.0], 10.0, label="person")
        self.assertEqual(engine.process_tracks([p_still], timestamp=10.0), [])
        p_still.timestamp = 11.0
        self.assertEqual(engine.process_tracks([p_still], timestamp=11.0), [])
        p_still.timestamp = 12.0
        # Post-gap stationary person must NOT trigger vandalism from pre-gap motion
        self.assertEqual(engine.process_tracks([p_still], timestamp=12.0), [])

    def test_explicit_gap_clears_association_evidence(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="illegal_dumping",
            min_dwell_seconds=2.0,
            owner_separation_px=100.0,
            max_observation_gap=2.0,
        )
        person = _make_track(10, [210.0, 180.0, 250.0, 280.0], 0.0, label="person")
        suitcase = _make_track(20, [200.0, 200.0, 240.0, 240.0], 0.0, label="suitcase")

        # Suitcase observed near person at t=0.0 and t=1.0 (creates association)
        engine.process_tracks([person, suitcase], timestamp=0.0)
        person.timestamp = 1.0
        suitcase.timestamp = 1.0
        engine.process_tracks([person, suitcase], timestamp=1.0)

        # Gap clears association evidence
        engine.observation_gap()

        # After gap, suitcase appears alone across t=10.0..12.0 (person departed before recovery)
        suitcase.timestamp = 10.0
        self.assertEqual(engine.process_tracks([suitcase], timestamp=10.0), [])
        suitcase.timestamp = 11.0
        self.assertEqual(engine.process_tracks([suitcase], timestamp=11.0), [])
        suitcase.timestamp = 12.0
        events = engine.process_tracks([suitcase], timestamp=12.0)
        self.assertEqual(len(events), 1)
        # Association was cleared across gap: taxonomy must be accumulation, not dropping action
        self.assertEqual(events[0]["payload"]["taxonomy"], "unlawful_waste_accumulation")
        self.assertFalse(events[0]["payload"]["has_observed_drop_action"])

    def test_automatic_max_gap_clears_continuity_and_first_recovered_frame_cannot_accrue(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="sidewalk_encroachment",
            roi_polygon=[[0.0, 0.0], [640.0, 0.0], [640.0, 360.0], [0.0, 360.0]],
            min_dwell_seconds=3.0,
            max_observation_gap=2.0,
        )
        bench = _make_track(1, [100.0, 100.0, 180.0, 180.0], 0.0, label="bench")
        self.assertEqual(engine.process_tracks([bench], timestamp=0.0), [])
        bench.timestamp = 1.5
        self.assertEqual(engine.process_tracks([bench], timestamp=1.5), [])

        # Time jump from 1.5 to 5.0 (dt=3.5 > max_observation_gap=2.0) triggers automatic gap
        bench.timestamp = 5.0
        self.assertEqual(engine.process_tracks([bench], timestamp=5.0), [])

        # Frame at t=7.0 (2.0s since recovery) -> below 3.0s dwell
        bench.timestamp = 7.0
        self.assertEqual(engine.process_tracks([bench], timestamp=7.0), [])

        # Frame at t=8.0 (3.0s continuous observation since recovery at t=5.0) -> triggers
        bench.timestamp = 8.0
        events = engine.process_tracks([bench], timestamp=8.0)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["payload"]["dwell_seconds"], 3.0, places=2)

    def test_gap_preserves_alert_cooldown_explicit_and_automatic(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="sidewalk_encroachment",
            roi_polygon=[[0.0, 0.0], [640.0, 0.0], [640.0, 360.0], [0.0, 360.0]],
            min_dwell_seconds=1.0,
            cooldown_seconds=30.0,
            max_observation_gap=2.0,
        )
        t1 = _make_track(1, [50.0, 50.0, 120.0, 120.0], 0.0, label="chair")
        engine.process_tracks([t1], timestamp=0.0)
        t1.timestamp = 1.0
        ev1 = engine.process_tracks([t1], timestamp=1.0)
        self.assertEqual(len(ev1), 1, "Initial incident emits")

        # Explicit gap: cooldown must be preserved
        engine.observation_gap()

        # t=5.0..6.0 is within 30s cooldown of t=1.0 -> duplicate must be suppressed
        t2 = _make_track(2, [50.0, 50.0, 120.0, 120.0], 5.0, label="chair")
        self.assertEqual(engine.process_tracks([t2], timestamp=5.0), [])
        t2.timestamp = 6.0
        self.assertEqual(engine.process_tracks([t2], timestamp=6.0), [])

        # Automatic gap jump from 6.0 to 18.0 (dt=12.0 > 2.0) -> cooldown still within 30s
        t2.timestamp = 18.0
        self.assertEqual(engine.process_tracks([t2], timestamp=18.0), [])
        t2.timestamp = 20.0
        self.assertEqual(engine.process_tracks([t2], timestamp=20.0), [])

        # At t=32.5 (cooldown 1.0 + 30.0 = 31.0 expired): alert emitted after continuous dwell
        t2.timestamp = 31.5
        engine.process_tracks([t2], timestamp=31.5)
        t2.timestamp = 32.5
        ev2 = engine.process_tracks([t2], timestamp=32.5)
        self.assertEqual(len(ev2), 1, "Incident emits once cooldown expires")


class TestF2PipelineVerificationAndCandidateRejection(unittest.TestCase):
    """F2: Pipeline owns central verification; engine emits candidate facts and implements reject_candidate."""

    def test_engine_always_emits_candidates_and_retains_verifier_lineage_metadata(self) -> None:
        verifier = VLMVerifier(model_id="qwen-pipeline-v2")
        engine = UrbanSafetyScenarioEngine(
            factory="fire_smoke_suspected",
            vlm_verifier=verifier,
            min_persistence_seconds=1.0,
            fire_ratio_threshold=0.05,
        )

        # Lineage retains configured verifier role for pipeline inspection
        roles = {item["role"]: item["version"] for item in engine.rule_lineage}
        self.assertIn("vlm_verifier", roles)
        self.assertEqual(roles["vlm_verifier"], "qwen-pipeline-v2")

        # Feed frame with fire RGB pixels across t=0.0 and t=1.5
        fire_rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        fire_rgb[:, :] = [245, 130, 20]
        self.assertEqual(engine.process_tracks([], timestamp=0.0, rgb=fire_rgb), [])
        events = engine.process_tracks([], timestamp=1.5, rgb=fire_rgb)

        self.assertEqual(len(events), 1)
        # Engine emits pure candidate facts; verifier is not executed inside engine
        self.assertEqual(events[0]["payload"]["lifecycle"], "candidate")
        self.assertNotIn("vlm_verification", events[0]["payload"])

    def test_engine_emits_low_confidence_candidate_without_local_vlm_suppression(self) -> None:
        # Default verifier min_confidence=0.55; engine min_score=0.25.
        # A 0.40-score track passes rule threshold; engine emits candidate without VLM filtering.
        engine = UrbanSafetyScenarioEngine(
            factory="sidewalk_encroachment",
            roi_polygon=[[0.0, 0.0], [640.0, 0.0], [640.0, 360.0], [0.0, 360.0]],
            min_dwell_seconds=1.0,
            min_score=0.25,
            enable_vlm=True,
        )
        car = _make_track(1, [100.0, 100.0, 180.0, 180.0], 0.0, label="car", score=0.40)
        engine.process_tracks([car], timestamp=0.0)
        car.timestamp = 1.0
        events = engine.process_tracks([car], timestamp=1.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["lifecycle"], "candidate")
        self.assertNotIn("vlm_verification", events[0]["payload"])

    def test_reject_candidate_releases_cooldown_for_later_true_incident(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="fire_smoke_suspected",
            min_persistence_seconds=1.0,
            cooldown_seconds=30.0,
        )
        # Emit candidate at t=2.0
        engine.process_tracks([], timestamp=1.0, environmental_signals={"fire_ratio": 0.1})
        cand1 = engine.process_tracks([], timestamp=2.0, environmental_signals={"fire_ratio": 0.1})
        self.assertEqual(len(cand1), 1)
        self.assertEqual(cand1[0]["payload"]["taxonomy"], "fire_suspected")
        self.assertEqual(cand1[0]["payload"]["detection_time"], 2.0)

        # Direct process_tracks cooldown blocks immediate duplicate at t=3.0
        self.assertEqual(
            engine.process_tracks([], timestamp=3.0, environmental_signals={"fire_ratio": 0.1}),
            [],
            "Active cooldown suppresses duplicate alert",
        )

        # Pipeline verifies candidate and rejects it (e.g. VLM confirms harmless exhaust steam)
        engine.reject_candidate(cand1[0])

        # Later true incident at t=4.0 (well within old 30s cooldown): MUST emit because cooldown was released
        cand2 = engine.process_tracks([], timestamp=4.0, environmental_signals={"fire_ratio": 0.1})
        self.assertEqual(len(cand2), 1, "Later true incident emitted after pipeline rejection released cooldown")
        self.assertEqual(cand2[0]["payload"]["taxonomy"], "fire_suspected")
        self.assertEqual(cand2[0]["payload"]["detection_time"], 4.0)

    def test_reject_candidate_preserves_unrelated_cooldowns_and_mismatched_detection_time(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="urban_safety_vlm",
            min_persistence_seconds=1.0,
            min_dark_duration_seconds=1.0,
            luminance_threshold=30.0,
            cooldown_seconds=30.0,
        )
        # Fire candidate emitted at t=2.0
        engine.process_tracks([], timestamp=1.0, environmental_signals={"fire_ratio": 0.2, "mean_luma": 100.0})
        cand_fire = engine.process_tracks([], timestamp=2.0, environmental_signals={"fire_ratio": 0.2, "mean_luma": 100.0})
        self.assertEqual(len(cand_fire), 1)
        self.assertEqual(cand_fire[0]["payload"]["taxonomy"], "fire_suspected")

        # Dark candidate emitted at t=5.0
        engine.process_tracks([], timestamp=4.0, environmental_signals={"fire_ratio": 0.0, "mean_luma": 5.0})
        cand_dark = engine.process_tracks([], timestamp=5.0, environmental_signals={"fire_ratio": 0.0, "mean_luma": 5.0})
        self.assertEqual(len(cand_dark), 1)
        self.assertEqual(cand_dark[0]["payload"]["taxonomy"], "streetlight_outage")

        # Rejection with mismatched detection_time must NOT release cooldown
        engine.reject_candidate({"payload": {"taxonomy": "streetlight_outage", "detection_time": 999.0}})
        self.assertEqual(
            engine.process_tracks([], timestamp=6.0, environmental_signals={"fire_ratio": 0.0, "mean_luma": 5.0}),
            [],
            "Dark cooldown must not be released by mismatched detection_time",
        )
        # Reject only fire candidate
        engine.reject_candidate(cand_fire[0])

        # Re-establish one second of fire persistence after the inactive interval.
        self.assertEqual(engine.process_tracks([], timestamp=7.0, environmental_signals={"fire_ratio": 0.2, "mean_luma": 5.0}), [])
        evs = engine.process_tracks([], timestamp=8.0, environmental_signals={"fire_ratio": 0.2, "mean_luma": 5.0})
        taxonomies = [e["payload"]["taxonomy"] for e in evs]
        self.assertIn("fire_suspected", taxonomies, "Rejected candidate taxonomy cooldown was released")
        self.assertNotIn("streetlight_outage", taxonomies, "Unrelated candidate cooldown remained active")

        # Exact timestamp equality check with epoch-sized timestamps
        engine_epoch = UrbanSafetyScenarioEngine(factory="fire_smoke_suspected", min_persistence_seconds=0.0, cooldown_seconds=30.0)
        epoch_ts = 1_700_000_000.0
        cand_epoch = engine_epoch.process_tracks([], timestamp=epoch_ts, environmental_signals={"fire_ratio": 0.2})
        self.assertEqual(len(cand_epoch), 1)
        # Differing timestamp must NOT release cooldown
        engine_epoch.reject_candidate({"payload": {"taxonomy": "fire_suspected", "detection_time": epoch_ts + 0.001}})
        self.assertEqual(
            engine_epoch.process_tracks([], timestamp=epoch_ts + 1.0, environmental_signals={"fire_ratio": 0.2}),
            [],
            "Epoch-scale cooldown must not be released when detection_time differs",
        )
        # Exact timestamp match releases cooldown
        engine_epoch.reject_candidate(cand_epoch[0])
        ev_released = engine_epoch.process_tracks([], timestamp=epoch_ts + 1.0, environmental_signals={"fire_ratio": 0.2})
        self.assertEqual(len(ev_released), 1, "Epoch-scale cooldown released with exact detection_time match")


class TestF4PolygonRasterizationRegressions(unittest.TestCase):
    """F4: Rasterize actual polygon for environmental signals; pixels outside polygon never contribute."""

    def test_polygon_rasterization_excludes_outside_pixels_for_fire_smoke_and_luminance(self) -> None:
        # Triangular ROI in upper-left of 100x100 frame: bounding box is [10..50, 10..50]
        triangle_roi = [[10.0, 10.0], [50.0, 10.0], [10.0, 50.0]]
        fire_outside_rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        smoke_outside_rgb = np.zeros((100, 100, 3), dtype=np.uint8)

        # Paint fire / smoke strictly OUTSIDE the triangle in its bounding box (x + y >= 65)
        # and across the frame. Inside triangle (x + y <= 55, x>=10, y>=10) remains pure black (0,0,0).
        for y in range(100):
            for x in range(100):
                if 10 <= x <= 50 and 10 <= y <= 50:
                    if x + y >= 65:
                        fire_outside_rgb[y, x] = [245, 130, 20]
                        smoke_outside_rgb[y, x] = [165, 165, 165]
                elif x > 50 or y > 50:
                    fire_outside_rgb[y, x] = [200, 200, 200]
                    smoke_outside_rgb[y, x] = [165, 165, 165]

        sigs_fire = extract_environmental_signals(fire_outside_rgb, roi_polygon=triangle_roi)
        self.assertEqual(sigs_fire.get("fire_ratio", 0.0), 0.0)
        self.assertEqual(sigs_fire.get("mean_luma", 0.0), 0.0)

        sigs_smoke = extract_environmental_signals(smoke_outside_rgb, roi_polygon=triangle_roi)
        self.assertEqual(sigs_smoke.get("smoke_ratio", 0.0), 0.0)
        self.assertEqual(sigs_smoke.get("mean_luma", 0.0), 0.0)

        # Conversely, paint fire inside the triangle: ratio and luminance must rise cleanly
        for y in range(10, 30):
            for x in range(10, 30):
                if x + y <= 45:
                    fire_outside_rgb[y, x] = [245, 130, 20]
        sigs_active = extract_environmental_signals(fire_outside_rgb, roi_polygon=triangle_roi)
        self.assertGreater(sigs_active["fire_ratio"], 0.1)
        self.assertGreater(sigs_active["mean_luma"], 10.0)

    def test_polygon_rasterization_excludes_outside_pixels_in_water_lower_region(self) -> None:
        # Narrow-bottom polygon: top is wide [10..90], bottom is narrow [10..20]
        poly = [[10.0, 10.0], [90.0, 10.0], [20.0, 90.0], [10.0, 90.0]]
        rgb = np.zeros((100, 100, 3), dtype=np.uint8)

        # In lower half of bounding box (y in [55..90]), paint water blue [20, 80, 200] at x in [60..89]
        # (inside the bounding box lower half, but strictly OUTSIDE the polygon)
        rgb[55:90, 60:90] = [20, 80, 200]

        sigs = extract_environmental_signals(rgb, roi_polygon=poly)
        self.assertEqual(sigs.get("water_ratio", 0.0), 0.0, "Water outside polygon must not contribute to lower region")

        # Now paint water INSIDE the polygon's lower region (x in [11..22], y in [60..85])
        rgb[60:85, 11:22] = [20, 80, 200]
        sigs_inside = extract_environmental_signals(rgb, roi_polygon=poly)
        self.assertGreater(sigs_inside["water_ratio"], 0.15)

    def test_roi_supports_normalized_and_pixel_rectangular_vertex_polygons(self) -> None:
        rgb = np.zeros((100, 100, 3), dtype=np.uint8)
        rgb[20:40, 20:40] = [245, 130, 20]  # fire in [20..40, 20..40]

        # 1. Pixel rectangular vertex polygon [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        pixel_poly = [[20.0, 20.0], [40.0, 20.0], [40.0, 40.0], [20.0, 40.0]]
        sigs_pixel = extract_environmental_signals(rgb, roi_polygon=pixel_poly)
        self.assertGreater(sigs_pixel["fire_ratio"], 0.8)

        # 2. Normalized rectangular vertex polygon points in [0, 1]
        norm_poly = [[0.2, 0.2], [0.4, 0.2], [0.4, 0.4], [0.2, 0.4]]
        sigs_norm_poly = extract_environmental_signals(rgb, roi_polygon=norm_poly)
        self.assertGreater(sigs_norm_poly["fire_ratio"], 0.8)

        # 3. Engine supports rectangular vertex ROI for environmental extraction
        eng = UrbanSafetyScenarioEngine(
            factory="fire_smoke_suspected",
            roi_polygon=pixel_poly,
            min_persistence_seconds=1.0,
            fire_ratio_threshold=0.5,
        )
        self.assertEqual(eng.process_tracks([], timestamp=0.0, rgb=rgb), [])
        evs = eng.process_tracks([], timestamp=1.0, rgb=rgb)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["taxonomy"], "fire_suspected")

    def test_safe_zero_coverage_for_out_of_frame_and_degenerate_polygons(self) -> None:
        dark_rgb = np.full((100, 100, 3), 5, dtype=np.uint8)  # pitch dark
        fire_rgb = np.full((100, 100, 3), 200, dtype=np.uint8)

        # Completely out-of-frame polygon
        out_poly = [[200.0, 200.0], [300.0, 200.0], [200.0, 300.0]]
        sigs_out = extract_environmental_signals(fire_rgb, roi_polygon=out_poly)
        self.assertEqual(sigs_out.get("fire_ratio", 0.0), 0.0)
        self.assertEqual(sigs_out.get("smoke_ratio", 0.0), 0.0)
        self.assertEqual(sigs_out.get("water_ratio", 0.0), 0.0)

        # Collinear zero-area polygon
        collinear_poly = [[10.0, 10.0], [50.0, 10.0], [30.0, 10.0]]
        sigs_collinear = extract_environmental_signals(fire_rgb, roi_polygon=collinear_poly)
        self.assertEqual(sigs_collinear.get("fire_ratio", 0.0), 0.0)

        # Engine with out-of-frame polygon on dark frame must NOT crash or falsely trigger streetlight outage
        engine = UrbanSafetyScenarioEngine(
            factory="streetlight_outage",
            roi_polygon=out_poly,
            min_dark_duration_seconds=0.0,
        )
        events = engine.process_tracks([], timestamp=1.0, rgb=dark_rgb)
        self.assertEqual(events, [], "Zero-coverage ROI must not falsely trigger streetlight outage")


class TestF5UnattendedTimerRegressions(unittest.TestCase):
    """F5: Independent consecutive unattended timer resets while person nearby and on gap."""

    def test_unattended_timer_resets_while_person_nearby_and_counts_only_unattended_duration(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="abandoned_object",
            min_unattended_seconds=3.0,
            owner_separation_px=100.0,
            max_observation_gap=2.0,
        )
        suitcase = _make_track(2, [200.0, 200.0, 240.0, 240.0], 0.0, label="suitcase")
        person = _make_track(1, [210.0, 180.0, 250.0, 280.0], 0.0, label="person")

        # Suitcase sits next to person from t=0.0 to t=6.0 (dwell=6.0s, but person is nearby)
        for t in (0.0, 2.0, 4.0, 6.0):
            suitcase.timestamp = t
            person.timestamp = t
            self.assertEqual(engine.process_tracks([suitcase, person], timestamp=t), [])

        # At t=7.0, person leaves: unattended timer starts at t=7.0
        suitcase.timestamp = 7.0
        self.assertEqual(engine.process_tracks([suitcase], timestamp=7.0), [], "0s unattended -> no alert")

        # At t=8.0: unattended for 1.0s < 3.0s -> no alert
        suitcase.timestamp = 8.0
        self.assertEqual(engine.process_tracks([suitcase], timestamp=8.0), [], "1s unattended -> no alert")

        # At t=9.0: person briefly returns nearby -> resets unattended timer
        suitcase.timestamp = 9.0
        person.timestamp = 9.0
        self.assertEqual(engine.process_tracks([suitcase, person], timestamp=9.0), [])

        # At t=10.0: person departs again -> unattended timer restarts fresh from t=10.0
        suitcase.timestamp = 10.0
        self.assertEqual(engine.process_tracks([suitcase], timestamp=10.0), [])

        # At t=12.0: 2.0s unattended since t=10.0 -> no alert
        suitcase.timestamp = 12.0
        self.assertEqual(engine.process_tracks([suitcase], timestamp=12.0), [])

        # At t=13.0: 3.0s continuous unattended observation reached -> triggers!
        suitcase.timestamp = 13.0
        events = engine.process_tracks([suitcase], timestamp=13.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["taxonomy"], "abandoned_object_dropped")
        self.assertAlmostEqual(events[0]["payload"]["unattended_seconds"], 3.0, places=2)
        # US11 uses alert_condition: evidence remains anchored when the duration threshold is met.
        self.assertAlmostEqual(events[0]["payload"]["anchor_time"], 13.0, places=2)
        self.assertAlmostEqual(events[0]["payload"]["detection_time"], 13.0, places=2)

    def test_unattended_timer_resets_on_gap_and_does_not_accrue_gap_time(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="abandoned_object",
            min_unattended_seconds=3.0,
            owner_separation_px=100.0,
            max_observation_gap=2.0,
        )
        box = _make_track(5, [300.0, 300.0, 350.0, 350.0], 0.0, label="suitcase")

        # Unattended for 2.0s (t=0.0..2.0)
        self.assertEqual(engine.process_tracks([box], timestamp=0.0), [])
        box.timestamp = 2.0
        self.assertEqual(engine.process_tracks([box], timestamp=2.0), [])

        # Observation gap occurs (jump from t=2.0 to t=8.0 > max_observation_gap=2.0)
        box.timestamp = 8.0
        self.assertEqual(engine.process_tracks([box], timestamp=8.0), [], "First recovered frame must not trigger")

        # t=10.0 is 2.0s post-gap -> still below 3.0s
        box.timestamp = 10.0
        self.assertEqual(engine.process_tracks([box], timestamp=10.0), [])

        # t=11.0 reaches the alert condition after 3.0s of continuous post-gap observation.
        box.timestamp = 11.0
        events = engine.process_tracks([box], timestamp=11.0)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["payload"]["unattended_seconds"], 3.0, places=2)
        self.assertAlmostEqual(events[0]["payload"]["anchor_time"], 11.0, places=2)


class TestF6PairInteractionRegressions(unittest.TestCase):
    """F6: Pair-specific consecutive proximity timer and window motion reset on separation/missing/gap."""

    def test_ordinary_first_encounter_between_older_tracks_does_not_trigger_altercation(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="violent_altercation",
            min_interaction_seconds=3.0,
            proximity_distance_px=140.0,
            motion_energy_threshold=35.0,
            max_observation_gap=2.0,
        )
        # Both tracks run rapidly while far apart (t=0..4, speed=50 px/s each, dist >= 200 > 140),
        # then slow down to a calm walk (10 px/s) before first entering proximity at t=7.0.
        for t in range(5):
            ts = float(t)
            p1 = _make_track(1, [20.0 + ts * 50.0, 100.0, 60.0 + ts * 50.0, 200.0], ts)
            p2 = _make_track(2, [620.0 - ts * 50.0, 100.0, 660.0 - ts * 50.0, 200.0], ts)
            self.assertEqual(engine.process_tracks([p1, p2], timestamp=ts), [])

        for step, ts in enumerate((5.0, 6.0), start=1):
            p1 = _make_track(1, [220.0 + step * 10.0, 100.0, 260.0 + step * 10.0, 200.0], ts)
            p2 = _make_track(2, [420.0 - step * 10.0, 100.0, 460.0 - step * 10.0, 200.0], ts)
            self.assertEqual(engine.process_tracks([p1, p2], timestamp=ts), [])

        # At t=7.0, they enter proximity for the VERY FIRST TIME (dist = 140px <= 140px) calmly
        p1_enc = _make_track(1, [250.0, 100.0, 290.0, 200.0], 7.0)
        p2_enc = _make_track(2, [390.0, 100.0, 430.0, 200.0], 7.0)
        self.assertEqual(
            engine.process_tracks([p1_enc, p2_enc], timestamp=7.0),
            [],
            "First encounter must NOT trigger 3s critical altercation",
        )

        # At t=8.0, t=9.0 (< 3.0s) and t=10.0 (3.0s in proximity, standing calmly, speed=0.0): must NOT trigger
        for ts in (8.0, 9.0, 10.0):
            p1_enc.timestamp = ts
            p2_enc.timestamp = ts
            self.assertEqual(
                engine.process_tracks([p1_enc, p2_enc], timestamp=ts),
                [],
                "Calm proximity must NOT trigger altercation from pre-encounter lifetime motion",
            )

    def test_pair_interaction_timer_and_motion_reset_when_pair_separates(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="violent_altercation",
            min_interaction_seconds=3.0,
            proximity_distance_px=140.0,
            motion_energy_threshold=35.0,
            max_observation_gap=2.0,
        )
        # Pair interacts with high motion for 2.0s (t=0.0..2.0)
        p1 = _make_track(1, [100.0, 100.0, 140.0, 200.0], 0.0)
        p2 = _make_track(2, [130.0, 100.0, 170.0, 200.0], 0.0)
        engine.process_tracks([p1, p2], timestamp=0.0)

        p1 = _make_track(1, [125.0, 100.0, 165.0, 200.0], 1.0)
        p2 = _make_track(2, [155.0, 100.0, 195.0, 200.0], 1.0)
        engine.process_tracks([p1, p2], timestamp=1.0)

        p1 = _make_track(1, [150.0, 100.0, 190.0, 200.0], 2.0)
        p2 = _make_track(2, [180.0, 100.0, 220.0, 200.0], 2.0)
        self.assertEqual(engine.process_tracks([p1, p2], timestamp=2.0), [], "2s < 3s threshold")

        # At t=3.0, they separate (dist = 300px > 140px)
        p1_far = _make_track(1, [100.0, 100.0, 140.0, 200.0], 3.0)
        p2_far = _make_track(2, [400.0, 100.0, 440.0, 200.0], 3.0)
        self.assertEqual(engine.process_tracks([p1_far, p2_far], timestamp=3.0), [])

        # At t=4.0, they come close again with motion: timer must restart fresh (0s interaction)
        p1_close = _make_track(1, [200.0, 100.0, 240.0, 200.0], 4.0)
        p2_close = _make_track(2, [230.0, 100.0, 270.0, 200.0], 4.0)
        self.assertEqual(engine.process_tracks([p1_close, p2_close], timestamp=4.0), [])

        # At t=5.0 and t=6.0 (1s and 2s since re-encounter): must NOT trigger
        for ts in (5.0, 6.0):
            p1_close = _make_track(1, [200.0 + (ts - 4.0) * 20.0, 100.0, 240.0 + (ts - 4.0) * 20.0, 200.0], ts)
            p2_close = _make_track(2, [230.0 + (ts - 4.0) * 20.0, 100.0, 270.0 + (ts - 4.0) * 20.0, 200.0], ts)
            self.assertEqual(engine.process_tracks([p1_close, p2_close], timestamp=ts), [])

        # At t=7.0 (3.0s consecutive active interaction since t=4.0) -> triggers
        p1_close = _make_track(1, [260.0, 100.0, 300.0, 200.0], 7.0)
        p2_close = _make_track(2, [290.0, 100.0, 330.0, 200.0], 7.0)
        events = engine.process_tracks([p1_close, p2_close], timestamp=7.0)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["payload"]["interaction_duration_seconds"], 3.0, places=2)

    def test_pair_interaction_timer_and_motion_reset_when_track_goes_missing(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="violent_altercation",
            min_interaction_seconds=3.0,
            proximity_distance_px=140.0,
            motion_energy_threshold=35.0,
            max_observation_gap=2.0,
        )
        p1 = _make_track(1, [100.0, 100.0, 140.0, 200.0], 0.0)
        p2 = _make_track(2, [130.0, 100.0, 170.0, 200.0], 0.0)
        engine.process_tracks([p1, p2], timestamp=0.0)
        p1 = _make_track(1, [125.0, 100.0, 165.0, 200.0], 1.0)
        p2 = _make_track(2, [155.0, 100.0, 195.0, 200.0], 1.0)
        engine.process_tracks([p1, p2], timestamp=1.0)
        p1 = _make_track(1, [150.0, 100.0, 190.0, 200.0], 2.0)
        p2 = _make_track(2, [180.0, 100.0, 220.0, 200.0], 2.0)
        self.assertEqual(engine.process_tracks([p1, p2], timestamp=2.0), [])

        # At t=3.0, track 2 disappears from the frame
        p1 = _make_track(1, [150.0, 100.0, 190.0, 200.0], 3.0)
        self.assertEqual(engine.process_tracks([p1], timestamp=3.0), [])

        # At t=4.0, track 2 reappears close to track 1: timer and window motion must reset
        p1 = _make_track(1, [150.0, 100.0, 190.0, 200.0], 4.0)
        p2 = _make_track(2, [180.0, 100.0, 220.0, 200.0], 4.0)
        self.assertEqual(engine.process_tracks([p1, p2], timestamp=4.0), [])

        # t=5.0, t=6.0 (only 1s and 2s since reappearance, even with active motion) -> must NOT trigger
        for ts in (5.0, 6.0):
            dx = (ts - 4.0) * 25.0
            p1 = _make_track(1, [150.0 + dx, 100.0, 190.0 + dx, 200.0], ts)
            p2 = _make_track(2, [180.0 + dx, 100.0, 220.0 + dx, 200.0], ts)
            self.assertEqual(engine.process_tracks([p1, p2], timestamp=ts), [])

        # t=7.0 (3.0s consecutive active interaction since t=4.0) -> triggers
        p1 = _make_track(1, [225.0, 100.0, 265.0, 200.0], 7.0)
        p2 = _make_track(2, [255.0, 100.0, 295.0, 200.0], 7.0)
        events = engine.process_tracks([p1, p2], timestamp=7.0)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["payload"]["interaction_duration_seconds"], 3.0, places=2)

    def test_pair_interaction_timer_and_motion_reset_on_observation_gap(self) -> None:
        engine = UrbanSafetyScenarioEngine(
            factory="violent_altercation",
            min_interaction_seconds=3.0,
            proximity_distance_px=140.0,
            motion_energy_threshold=35.0,
            max_observation_gap=2.0,
        )
        p1 = _make_track(1, [100.0, 100.0, 140.0, 200.0], 0.0)
        p2 = _make_track(2, [130.0, 100.0, 170.0, 200.0], 0.0)
        engine.process_tracks([p1, p2], timestamp=0.0)
        p1 = _make_track(1, [130.0, 100.0, 170.0, 200.0], 1.0)
        p2 = _make_track(2, [160.0, 100.0, 200.0, 200.0], 1.0)
        engine.process_tracks([p1, p2], timestamp=1.0)
        p1 = _make_track(1, [160.0, 100.0, 200.0, 200.0], 2.0)
        p2 = _make_track(2, [190.0, 100.0, 230.0, 200.0], 2.0)
        engine.process_tracks([p1, p2], timestamp=2.0)

        # Automatic gap jump from t=2.0 to t=10.0 (> 2.0s)
        p1 = _make_track(1, [190.0, 100.0, 230.0, 200.0], 10.0)
        p2 = _make_track(2, [220.0, 100.0, 260.0, 200.0], 10.0)
        self.assertEqual(engine.process_tracks([p1, p2], timestamp=10.0), [])

        # At t=12.0 (only 2.0s post-gap): must NOT trigger
        p1 = _make_track(1, [220.0, 100.0, 260.0, 200.0], 12.0)
        p2 = _make_track(2, [250.0, 100.0, 290.0, 200.0], 12.0)
        self.assertEqual(engine.process_tracks([p1, p2], timestamp=12.0), [])

        # At t=13.0 (3.0s continuous active post-gap interaction): triggers
        p1 = _make_track(1, [250.0, 100.0, 290.0, 200.0], 13.0)
        p2 = _make_track(2, [280.0, 100.0, 320.0, 200.0], 13.0)
        events = engine.process_tracks([p1, p2], timestamp=13.0)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["payload"]["interaction_duration_seconds"], 3.0, places=2)


class TestF7RemoteVLMStrictVerdictRegressions(unittest.TestCase):
    """F7: Strict remote verdict actual bool and finite bounded numeric confidence."""

    def test_valid_remote_vlm_verdict_true_and_false_are_supported(self) -> None:
        def mock_transport(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"verified": true, "confidence": 0.92, "hard_negative_class": null, "reasoning": "Real altercation"}'
                        }
                    }
                ]
            }

        verifier = VLMVerifier(
            endpoint_url="http://vlm.local/v1/chat/completions",
            min_confidence=0.55,
            http_transport=mock_transport,
        )
        res_true = verifier.verify({"payload": {"taxonomy": "violent_altercation", "confidence": 0.8}})
        self.assertTrue(res_true.verified)
        self.assertEqual(res_true.status, "verified")
        self.assertAlmostEqual(res_true.confidence, 0.92, places=2)

        def mock_false(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"verified": false, "confidence": 0.88, "hard_negative_class": "friendly_greeting_or_hug", "reasoning": "Just hugging"}'
                        }
                    }
                ]
            }

        verifier_false = VLMVerifier(
            endpoint_url="http://vlm.local/v1/chat/completions",
            min_confidence=0.55,
            http_transport=mock_false,
        )
        res_false = verifier_false.verify({"payload": {"taxonomy": "violent_altercation", "confidence": 0.8}})
        self.assertFalse(res_false.verified)
        self.assertEqual(res_false.status, "filtered_false_positive")
        self.assertEqual(res_false.hard_negative_class, "friendly_greeting_or_hug")

    def test_malformed_verdicts_and_confidences_take_failed_retain_candidate_policy(self) -> None:
        malformed_contents: list[Any] = [
            '{"verified": "false", "confidence": 0.95}',       # truthy string "false"
            '{"verified": "true", "confidence": 0.95}',        # string "true"
            '{"verified": 1, "confidence": 0.95}',             # integer 1
            '{"verified": 0, "confidence": 0.95}',             # integer 0
            '{"verified": null, "confidence": 0.95}',          # null
            '{"confidence": 0.95}',                            # missing "verified"
            '{"verified": true}',                              # missing "confidence"
            '{"verified": true, "confidence": true}',          # bool as confidence
            '{"verified": true, "confidence": "0.95"}',        # string confidence
            '{"verified": true, "confidence": NaN}',           # JSON NaN
            '{"verified": true, "confidence": Infinity}',      # JSON Infinity
            '{"verified": true, "confidence": 1.5}',           # out of bounds > 1.0
            '{"verified": true, "confidence": -0.2}',          # out of bounds < 0.0
            {"verified": True, "confidence": float("nan")},    # raw NaN
            {"verified": True, "confidence": float("inf")},    # raw Inf
            "not a json string",                               # invalid JSON
            '["not", "a", "dict"]',                            # non-object JSON
        ]

        for payload_content in malformed_contents:
            with self.subTest(content=payload_content):
                def mock_bad(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
                    return {"choices": [{"message": {"content": payload_content}}]}

                verifier = VLMVerifier(
                    endpoint_url="http://vlm.local/v1/chat/completions",
                    http_transport=mock_bad,
                )
                res = verifier.verify({"payload": {"taxonomy": "violent_altercation", "confidence": 0.77}})
                # Malformed output takes existing failed/retain-candidate policy
                self.assertEqual(
                    res.status,
                    "failed",
                    f"Payload {payload_content!r} must result in status='failed', not verified/filtered",
                )
                self.assertTrue(res.verified, "Failed status retains candidate (verified=True)")
                self.assertAlmostEqual(res.confidence, 0.77, places=2)

    def test_default_offline_vlm_policy_remains_local(self) -> None:
        # Without CIVIWATCH_VLM_URL, VLMVerifier runs local offline deterministic verification
        env = {k: v for k, v in os.environ.items() if k != "CIVIWATCH_VLM_URL"}
        with patch.dict(os.environ, env, clear=True):
            verifier = VLMVerifier()
            self.assertIsNone(verifier.endpoint_url)
            res = verifier.verify({"payload": {"taxonomy": "fire_smoke_suspected", "confidence": 0.85}})
            self.assertIn(res.status, {"verified", "filtered_false_positive"})
            self.assertIn(res.verified, {True, False})


if __name__ == "__main__":
    unittest.main()
