"""Runtime integration regressions at the perception pipeline boundary."""
from collections import namedtuple
import errno
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from apps.edge.health import EdgeHealthMonitor
from apps.edge.quota import StorageQuotaManager
from apps.edge.outbox import EventOutbox
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.recorder import FileRecorder


class TestPipelineRuntime(unittest.TestCase):
    def test_default_quota_protects_admission_and_reclaims_unowned_ring(self):
        usage = namedtuple("Usage", "total used free")
        with tempfile.TemporaryDirectory() as root:
            recorder = FileRecorder(Path(root) / "ring")
            outbox = EventOutbox(Path(root) / "state" / "events.sqlite3")
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

            pipeline = PerceptionPipeline(recorder=recorder, outbox=outbox, incident_engine=FallEngine())
            self.assertIs(pipeline.evidence.quota_manager, pipeline.health.quota_manager)
            self.assertIsNotNone(pipeline.evidence.quota_manager)
            quota = pipeline.evidence.quota_manager
            self.assertIs(quota.recorder, recorder)
            self.assertIs(quota.outbox, outbox)
            quota.disk_usage_fn = lambda path: usage(100_000_000, 99_000_000, 1_000_000)
            with self.assertRaises(OSError) as raised:
                pipeline.process_frame(np.zeros((16, 16, 3), dtype=np.uint8), 20.0, 1,
                                       detections=[])
            self.assertEqual(raised.exception.errno, errno.ENOSPC)
            self.assertEqual(outbox.pending(), [])
            self.assertEqual(outbox.evidence_requests(), [])

            directory = recorder.root / pipeline.stream_session_id
            directory.mkdir()
            media = directory / "old.mkv"
            media.write_bytes(b"ring")
            media.with_suffix(".json").write_text(json.dumps({
                "path": str(media), "session_id": pipeline.stream_session_id,
                "codec": "h264", "time_base": "1/1000", "start_pts": 0,
                "end_pts": 1000, "start_seconds": 0, "end_seconds": 1,
                "keyframe_pts": [0], "frame_interval_seconds": 0.04,
            }))
            result = pipeline.evidence.reconcile()
            self.assertIn(str(media), result["cleaned_files"])
            self.assertEqual(recorder.segments(pipeline.stream_session_id), [])
            self.assertFalse(media.exists())
            self.assertEqual(pipeline.health.get_health_snapshot()["reason"], "storage_exhausted")

    def test_supplied_quota_and_monitor_share_evidence_admission(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = FileRecorder(Path(root) / "ring")
            outbox = EventOutbox(Path(root) / "events.sqlite3")
            quota = StorageQuotaManager(recorder=recorder, outbox=outbox)
            health = EdgeHealthMonitor(quota_manager=quota)
            pipeline = PerceptionPipeline(recorder=recorder, outbox=outbox, health=health)
            self.assertIs(pipeline.evidence.quota_manager, quota)
            replacement = StorageQuotaManager(recorder=recorder, outbox=outbox)
            pipeline = PerceptionPipeline(recorder=recorder, outbox=outbox, health=health,
                                          quota_manager=replacement)
            self.assertIs(pipeline.health, health)
            self.assertIs(pipeline.health.quota_manager, replacement)
            self.assertIs(pipeline.evidence.quota_manager, replacement)

    def test_received_frame_with_failed_analytics_is_observed_not_healthy(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline = PerceptionPipeline(
                recorder=FileRecorder(Path(root) / "ring"),
                outbox=EventOutbox(Path(root) / "events.sqlite3"),
            )
            pipeline.process_frame(np.zeros((16, 16, 3), dtype=np.uint8), 0.0, 1,
                                   observation_status="failed")
            snapshot = pipeline.health.get_health_snapshot()
            self.assertEqual(snapshot["status"], "degraded")
            self.assertEqual(snapshot["reason"], "analytics_failed")
            self.assertEqual(snapshot["metrics"]["total_frames_received"], 1)

    def test_first_frame_transitions_starting_to_observed_then_stalled(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline = PerceptionPipeline(
                recorder=FileRecorder(Path(root) / "ring"),
                outbox=EventOutbox(Path(root) / "events.sqlite3"),
            )
            with patch("time.time", return_value=100.0):
                self.assertEqual(pipeline.health.get_health_snapshot()["status"], "starting")
                pipeline.process_frame(np.zeros((16, 16, 3), dtype=np.uint8), 0.0, 1,
                                       detections=[])
                snapshot = pipeline.health.get_health_snapshot()
                self.assertEqual(snapshot["status"], "healthy")
                self.assertEqual(snapshot["metrics"]["total_frames_received"], 1)
            with patch("time.time", return_value=106.0):
                snapshot = pipeline.health.get_health_snapshot()
                self.assertEqual(snapshot["status"], "degraded")
                self.assertEqual(snapshot["reason"], "queue_stall")

    def test_consecutive_frames_same_millisecond_timestamp_not_stale(self):
        """P1-09: consecutive frames with same millisecond timestamp are monotonically adjusted, not stale."""
        with tempfile.TemporaryDirectory() as root:
            pipeline = PerceptionPipeline(
                recorder=FileRecorder(Path(root) / "ring"),
                outbox=EventOutbox(Path(root) / "events.sqlite3"),
            )
            rgb = np.zeros((16, 16, 3), dtype=np.uint8)
            # Frame 1: fid=1, ts=1.000
            pipeline.process_frame(rgb, timestamp=1.000, frame_id=1, detections=[
                {"bbox": [10.0, 10.0, 20.0, 30.0], "score": 0.9, "label": "person"}
            ])
            self.assertEqual(pipeline.last_observation["detection_status"], "ok")
            self.assertEqual(len(pipeline.tracker.get_all_tracks()), 1)

            # Frame 2: fid=2, ts=1.000 (same millisecond)
            pipeline.process_frame(rgb, timestamp=1.000, frame_id=2, detections=[
                {"bbox": [10.0, 10.0, 20.0, 30.0], "score": 0.9, "label": "person"}
            ])
            self.assertNotEqual(pipeline.last_observation["detection_status"], "stale")
            self.assertEqual(pipeline.last_observation["detection_status"], "ok")
            tracks = pipeline.tracker.get_all_tracks()
            self.assertEqual(len(tracks), 1)
            self.assertEqual(len(tracks[0].history), 2)

    def test_lost_track_retains_history_until_removed(self):
        """P1-11: Track history is retained when state is 'lost', and cleared only when 'removed'."""
        with tempfile.TemporaryDirectory() as root:
            pipeline = PerceptionPipeline(
                recorder=FileRecorder(Path(root) / "ring"),
                outbox=EventOutbox(Path(root) / "events.sqlite3"),
            )
            rgb = np.zeros((16, 16, 3), dtype=np.uint8)
            det = [{"bbox": [10.0, 10.0, 20.0, 50.0], "score": 0.9, "label": "person"}]

            # Frame 0 to 4: person tracked actively
            for fid in range(5):
                pipeline.process_frame(rgb, timestamp=float(fid) * 0.1, frame_id=fid, detections=det)

            tracks = pipeline.tracker.get_all_tracks()
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0].state, "active")
            self.assertEqual(len(tracks[0].history), 5)

            # Frame 5: Missed detection -> track transitions to 'lost'
            pipeline.process_frame(rgb, timestamp=0.5, frame_id=5, detections=[])
            tracks = pipeline.tracker.get_all_tracks()
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0].state, "lost")
            # History MUST NOT be cleared when lost!
            self.assertEqual(len(tracks[0].history), 5)

            # Frame 6: Detection recovers -> track re-activated and history has 6 observations
            pipeline.process_frame(rgb, timestamp=0.6, frame_id=6, detections=det)
            tracks = pipeline.tracker.get_all_tracks()
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0].state, "active")
            self.assertEqual(len(tracks[0].history), 6)

    def test_pipeline_roi_polygon_filters_outside_tracks(self):
        """P1-13: Pipeline with roi_polygon ignores detections whose foot point is outside ROI."""
        with tempfile.TemporaryDirectory() as root:
            roi = [[0.0, 0.0], [300.0, 0.0], [300.0, 300.0], [0.0, 300.0]]
            pipeline = PerceptionPipeline(
                recorder=FileRecorder(Path(root) / "ring"),
                outbox=EventOutbox(Path(root) / "events.sqlite3"),
                roi_polygon=roi,
            )
            rgb = np.zeros((16, 16, 3), dtype=np.uint8)
            # Detection with foot point ((400+560)/2, 280) = (480, 280) outside ROI [0..300, 0..300]
            det_outside = [{"bbox": [400.0, 220.0, 560.0, 280.0], "score": 0.9, "label": "person"}]

            emitted = []
            for fid in range(35):
                events = pipeline.process_frame(rgb, timestamp=float(fid) * 0.1, frame_id=fid, detections=det_outside)
                emitted.extend(events)

            self.assertEqual(emitted, [], "Detections outside ROI must not emit incidents")

    def test_pipeline_minimal_odd_evaluation(self):
        """P1-13: Pipeline dynamically evaluates minimal ODD quality_state from RGB frames."""
        with tempfile.TemporaryDirectory() as root:
            pipeline = PerceptionPipeline(
                recorder=FileRecorder(Path(root) / "ring"),
                outbox=EventOutbox(Path(root) / "events.sqlite3"),
            )
            # Default state before any frames
            self.assertEqual(pipeline.quality_state, "unknown")

            # 1. Dark frame (low light)
            dark_rgb = np.zeros((32, 32, 3), dtype=np.uint8)
            pipeline.process_frame(dark_rgb, timestamp=1.0, frame_id=1, detections=[])
            self.assertEqual(pipeline.quality_state, "low_light")

            # 2. Overexposed / glare frame
            glare_rgb = np.full((32, 32, 3), 255, dtype=np.uint8)
            pipeline.process_frame(glare_rgb, timestamp=2.0, frame_id=2, detections=[])
            self.assertEqual(pipeline.quality_state, "glare")

            # 3. Normal contrast/brightness frame
            rng = np.random.RandomState(42)
            normal_rgb = rng.randint(40, 210, (32, 32, 3), dtype=np.uint8)
            pipeline.process_frame(normal_rgb, timestamp=3.0, frame_id=3, detections=[])
            self.assertEqual(pipeline.quality_state, "normal")

            # 4. Configured non-unknown state is not overridden
            fixed_pipeline = PerceptionPipeline(
                recorder=FileRecorder(Path(root) / "ring2"),
                outbox=EventOutbox(Path(root) / "events2.sqlite3"),
                quality_state="calibrated_fixed",
            )
            fixed_pipeline.process_frame(dark_rgb, timestamp=1.0, frame_id=1, detections=[])
            self.assertEqual(fixed_pipeline.quality_state, "calibrated_fixed")


    def test_invalid_facts_raise_value_error_before_event_or_outbox_persistence(self):
        """Invalid facts (legacy flat, missing semantic fields, or reserved payload keys) raise ValueError before durable intent."""
        with tempfile.TemporaryDirectory() as root:
            recorder = FileRecorder(Path(root) / "ring")
            outbox = EventOutbox(Path(root) / "state" / "events.sqlite3")

            class InvalidFactEngine:
                def __init__(self, mode: str):
                    self.mode = mode

                def process_tracks(self, tracks, timestamp):
                    if self.mode == "legacy_flat":
                        return [{"taxonomy": "person_fall"}]
                    if self.mode == "reserved_key":
                        return [{
                            "anchor_kind": "onset",
                            "payload": {
                                "taxonomy": "person_fall",
                                "severity": "critical",
                                "confidence": 0.9,
                                "anchor_time": float(timestamp),
                                "detection_time": float(timestamp),
                                "evidence_requests": [{"request_id": "forged"}],
                            },
                        }]
                    if self.mode == "missing_semantic":
                        return [{
                            "anchor_kind": "onset",
                            "payload": {
                                "taxonomy": "person_fall",
                            },
                        }]
                    return []

            for mode in ("legacy_flat", "reserved_key", "missing_semantic"):
                engine = InvalidFactEngine(mode=mode)
                pipeline = PerceptionPipeline(recorder=recorder, outbox=outbox, incident_engine=engine)
                rgb = np.zeros((16, 16, 3), dtype=np.uint8)
                with self.assertRaises(ValueError):
                    pipeline.process_frame(rgb, 10.0, 1, detections=[])

                self.assertEqual(outbox.pending(), [])
                self.assertEqual(outbox.evidence_requests(), [])

    def test_scoped_and_fallback_quality_distinct_with_feature_identity_across_session_resets(self):
        """Per-feature scoped quality stays distinct from fallback, and producer identities survive session reset."""
        with tempfile.TemporaryDirectory() as root:
            recorder = FileRecorder(Path(root) / "ring")
            outbox = EventOutbox(Path(root) / "state" / "events.sqlite3")

            class CustomFeatureEngine:
                factory = "custom_alert"
                pipeline_id = "custom-alert-pipeline-v1"
                pipeline_version = "2"
                config_version = "cfg-alert-v1"
                rule_lineage = [{"role": "rule", "name": "custom_rule", "version": "1.0.0"}]

                def process_tracks(self, tracks, timestamp):
                    return [{
                        "anchor_kind": "alert_condition",
                        "payload": {
                            "taxonomy": "custom_alert",
                            "severity": "medium",
                            "confidence": 0.85,
                            "anchor_time": float(timestamp),
                            "detection_time": float(timestamp),
                            "alert_metric": 42,
                        },
                    }]

                def reset(self):
                    pass

            custom_policy = {
                "version": "scoped-v1",
                "low_light_mean": 5.0,
                "glare_mean": 240.0,
                "low_contrast_std": 5.0,
                "blur_laplacian_var": 4.0,
                "freeze_frames": 3,
            }
            engine = CustomFeatureEngine()
            pipeline = PerceptionPipeline(
                recorder=recorder,
                outbox=outbox,
                incident_engines=[engine],
                capability_policies={"custom_alert": custom_policy},
            )

            # Frame with mean brightness 8: fallback policy (< 15) is low_light, but scoped policy (> 5) is normal
            dim_rgb = np.repeat(((np.indices((32, 32)).sum(axis=0) % 2) * 16).astype(np.uint8)[..., None], 3, axis=2)
            events = pipeline.process_frame(dim_rgb, timestamp=1.0, frame_id=1, detections=[])
            self.assertEqual(len(events), 1)
            ev1 = events[0]

            self.assertEqual(ev1["quality_state"], "normal")
            self.assertEqual(ev1["payload"]["quality"]["state"], "normal")
            self.assertEqual(ev1["payload"]["quality"]["policy_version"], "scoped-v1")
            self.assertEqual(ev1["payload"]["capability_scope"]["capability"], "custom_alert")
            self.assertEqual(pipeline.quality["state"], "low_light")
            self.assertEqual(ev1["pipeline_id"], "custom-alert-pipeline-v1")
            self.assertEqual(ev1["pipeline_version"], "2")
            self.assertEqual(ev1["config_version"], "cfg-alert-v1")
            self.assertTrue(any(e.get("name") == "custom_rule" for e in ev1["model_lineage"]))

            # RTSP reconnection / stream session reset
            pipeline.stream_session_id = "00000000-0000-4000-8000-000000000002"
            events2 = pipeline.process_frame(dim_rgb, timestamp=2.0, frame_id=2, detections=[])
            self.assertEqual(len(events2), 1)
            ev2 = events2[0]

            self.assertEqual(ev2["stream_session_id"], "00000000-0000-4000-8000-000000000002")
            self.assertEqual(ev2["quality_state"], "normal")
            self.assertEqual(ev2["payload"]["quality"]["policy_version"], "scoped-v1")
            self.assertEqual(ev2["pipeline_id"], "custom-alert-pipeline-v1")
            self.assertEqual(ev2["pipeline_version"], "2")
            self.assertEqual(ev2["config_version"], "cfg-alert-v1")

    def test_engine_payload_preservation(self):
        """Pipeline preserves all feature scenario fields in the payload without loss or mutation."""
        with tempfile.TemporaryDirectory() as root:
            recorder = FileRecorder(Path(root) / "ring")
            outbox = EventOutbox(Path(root) / "state" / "events.sqlite3")

            class ScenarioFeatureEngine:
                factory = "scenario_engine"
                pipeline_id = "scenario-pipeline"
                pipeline_version = "1"
                config_version = "scenario-v1"
                rule_lineage = []

                def process_tracks(self, tracks, timestamp):
                    return [{
                        "anchor_kind": "alert_condition",
                        "payload": {
                            "taxonomy": "scenario_event",
                            "severity": "high",
                            "confidence": 0.92,
                            "anchor_time": float(timestamp),
                            "detection_time": float(timestamp),
                            "track_id": 99,
                            "dwell_seconds": 15.5,
                            "custom_score": 0.88,
                            "zone_tag": "entry_gate",
                            "detections": [
                                {
                                    "bbox": [10.0, 10.0, 50.0, 80.0],
                                    "score": 0.95,
                                    "timestamp": float(timestamp),
                                    "label": "person",
                                }
                            ],
                        },
                    }]

            pipeline = PerceptionPipeline(
                recorder=recorder,
                outbox=outbox,
                incident_engine=ScenarioFeatureEngine(),
            )
            rgb = np.zeros((32, 32, 3), dtype=np.uint8)
            events = pipeline.process_frame(rgb, timestamp=1.0, frame_id=1, detections=[])
            self.assertEqual(len(events), 1)
            payload = events[0]["payload"]
            self.assertEqual(payload["track_id"], 99)
            self.assertEqual(payload["dwell_seconds"], 15.5)
            self.assertEqual(payload["custom_score"], 0.88)
            self.assertEqual(payload["zone_tag"], "entry_gate")
            self.assertEqual(payload["detections"][0]["bbox"], [10.0, 10.0, 50.0, 80.0])


