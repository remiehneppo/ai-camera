"""Tests for RTMPose estimation and Pose Request lifecycle."""

from __future__ import annotations

import math
from pathlib import Path
import unittest

import cv2
import numpy as np

from apps.edge.pose import (
    PoseManager,
    PoseOutcome,
    PoseRequest,
    RtmposeEstimator,
)


class TestRtmposeEstimator(unittest.TestCase):
    """Tests for RtmposeEstimator ONNX inference and SimCC decoding."""

    manifest_path: str
    model_path: str
    estimator: RtmposeEstimator

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest_path = "models/rtmpose-tiny/manifest.json"
        cls.model_path = "models/rtmpose-tiny/rtmpose_tiny.onnx"
        cls.estimator = RtmposeEstimator(
            manifest_path=cls.manifest_path,
            model_path=cls.model_path,
        )

    def test_estimator_dummy_image(self) -> None:
        """Estimator returns 17 COCO keypoints on dummy RGB input."""
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        bbox = [100.0, 100.0, 300.0, 400.0]
        keypoints = self.estimator.estimate(rgb, bbox)

        self.assertEqual(len(keypoints), 17)
        expected_names = [
            "nose",
            "left_eye",
            "right_eye",
            "left_ear",
            "right_ear",
            "left_shoulder",
            "right_shoulder",
            "left_elbow",
            "right_elbow",
            "left_wrist",
            "right_wrist",
            "left_hip",
            "right_hip",
            "left_knee",
            "right_knee",
            "left_ankle",
            "right_ankle",
        ]
        for i, kp in enumerate(keypoints):
            self.assertEqual(kp["name"], expected_names[i])
            self.assertTrue(math.isfinite(kp["x"]))
            self.assertTrue(math.isfinite(kp["y"]))
            self.assertTrue(math.isfinite(kp["score"]))
            self.assertGreaterEqual(kp["score"], 0.0)
            self.assertLessEqual(kp["score"], 1.0)

    def test_estimator_real_image_shibuya(self) -> None:
        """Estimator on real Shibuya image maps keypoints back to original frame coordinates."""
        img_path = Path("data/oracle/shibuya_people.jpg")
        if not img_path.is_file():
            self.skipTest("Shibuya fixture image not found")

        bgr = cv2.imread(str(img_path))
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        # Person bounding box in Shibuya image
        bbox = [521.84, 1376.08, 709.68, 1932.82]
        keypoints = self.estimator.estimate(rgb, bbox)

        self.assertEqual(len(keypoints), 17)
        kp_dict = {kp["name"]: kp for kp in keypoints}

        # Validate head is higher up than ankles in original coordinates
        nose = kp_dict["nose"]
        left_ankle = kp_dict["left_ankle"]
        right_ankle = kp_dict["right_ankle"]

        # Nose y should be around 1400, ankles around 1800-1900
        self.assertLess(nose["y"], left_ankle["y"])
        self.assertLess(nose["y"], right_ankle["y"])
        self.assertGreater(nose["y"], 1350.0)
        self.assertLess(nose["y"], 1450.0)

        # X coordinates should be within/near person bbox width [500, 730]
        for kp in keypoints:
            self.assertGreater(kp["x"], 450.0)
            self.assertLess(kp["x"], 780.0)

        # Head / shoulder keypoints should have reasonable confidence
        self.assertGreater(kp_dict["right_ear"]["score"], 0.5)
        self.assertGreater(kp_dict["left_shoulder"]["score"], 0.5)


class TestPoseManagerLifecycle(unittest.TestCase):
    """Tests for PoseManager lifecycle, deadlines, epochs, and bounded queue."""

    manifest_path: str
    model_path: str
    estimator: RtmposeEstimator

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest_path = "models/rtmpose-tiny/manifest.json"
        cls.model_path = "models/rtmpose-tiny/rtmpose_tiny.onnx"
        cls.estimator = RtmposeEstimator(
            manifest_path=cls.manifest_path,
            model_path=cls.model_path,
        )

    def setUp(self) -> None:
        self.manager = PoseManager(
            estimator=self.estimator,
            max_queue_size=4,
            max_cached_frames=4,
        )

    def test_deadline_timeout_produces_skipped(self) -> None:
        """Requests with expired deadline receive terminal outcome 'skipped' with 'deadline_exceeded'."""
        req = PoseRequest(
            request_id="req-dl-1",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=10,
            track_id=1,
            bbox=[100.0, 100.0, 200.0, 300.0],
            deadline=5.0,  # Deadline at t=5.0
            clock_domain="event_time",
        )
        self.manager.submit_request(req)

        # Process at current_time=6.0 (deadline exceeded)
        outcomes = self.manager.process_pending(current_time=6.0)
        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.request_id, "req-dl-1")
        self.assertEqual(outcome.status, "skipped")
        self.assertEqual(outcome.reason, "deadline_exceeded")
        self.assertEqual(len(outcome.keypoints), 0)

    def test_epoch_reset_produces_cancelled(self) -> None:
        """When core_epoch changes, outstanding requests from older epoch fail with 'cancelled' ('epoch_mismatch')."""
        req1 = PoseRequest(
            request_id="req-ep-1",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=10,
            track_id=1,
            bbox=[100.0, 100.0, 200.0, 300.0],
            deadline=100.0,
            clock_domain="event_time",
        )
        req2 = PoseRequest(
            request_id="req-ep-2",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=2,
            frame_id=20,
            track_id=2,
            bbox=[150.0, 150.0, 250.0, 350.0],
            deadline=100.0,
            clock_domain="event_time",
        )
        self.manager.submit_request(req1)
        self.manager.submit_request(req2)

        # Crash or epoch change to epoch 2
        cancelled = self.manager.set_epoch(2)
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0].request_id, "req-ep-1")
        self.assertEqual(cancelled[0].status, "cancelled")
        self.assertEqual(cancelled[0].reason, "epoch_mismatch")

        # req2 remains in queue
        self.assertEqual(self.manager.queued_count(), 1)

    def test_bounded_queue_prevents_memory_leak(self) -> None:
        """Bounded request queue rejects excess requests with 'skipped' ('queue_full')."""
        manager = PoseManager(
            estimator=self.estimator,
            max_queue_size=2,
            max_cached_frames=2,
        )
        for i in range(2):
            req = PoseRequest(
                request_id=f"req-q-{i}",
                camera_id="cam-1",
                stream_session_id="sess-1",
                core_epoch=1,
                frame_id=i,
                track_id=i,
                bbox=[100.0, 100.0, 200.0, 300.0],
                deadline=100.0,
                clock_domain="event_time",
            )
            accepted = manager.submit_request(req)
            self.assertTrue(accepted)

        # 3rd request overflows queue
        overflow_req = PoseRequest(
            request_id="req-q-overflow",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=3,
            track_id=3,
            bbox=[100.0, 100.0, 200.0, 300.0],
            deadline=100.0,
            clock_domain="event_time",
        )
        accepted = manager.submit_request(overflow_req)
        self.assertFalse(accepted)

        # Terminal queue has the skipped overflow outcome
        outcomes = manager.poll_terminal_outcomes()
        overflow_outcome = [o for o in outcomes if o.request_id == "req-q-overflow"]
        self.assertEqual(len(overflow_outcome), 1)
        self.assertEqual(overflow_outcome[0].status, "skipped")
        self.assertEqual(overflow_outcome[0].reason, "queue_full")

    def test_bounded_frame_cache_expires_old_frames(self) -> None:
        """Frame buffer eviction results in 'skipped' with 'frame_buffer_expired'."""
        manager = PoseManager(
            estimator=self.estimator,
            max_queue_size=10,
            max_cached_frames=2,
        )
        dummy_rgb = np.zeros((100, 100, 3), dtype=np.uint8)

        # Cache frame 1 and 2
        manager.cache_frame("cam-1", "sess-1", 1, 1, dummy_rgb)
        manager.cache_frame("cam-1", "sess-1", 1, 2, dummy_rgb)
        # Cache frame 3 -> evicts frame 1
        manager.cache_frame("cam-1", "sess-1", 1, 3, dummy_rgb)

        # Request for evicted frame 1
        req = PoseRequest(
            request_id="req-evicted",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=1,
            track_id=1,
            bbox=[10.0, 10.0, 50.0, 80.0],
            deadline=100.0,
            clock_domain="event_time",
        )
        manager.submit_request(req)
        outcomes = manager.process_pending(current_time=10.0)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].status, "skipped")
        self.assertEqual(outcomes[0].reason, "frame_buffer_expired")

    def test_successful_request_execution(self) -> None:
        """Valid cached frame within deadline produces 'ok' outcome with 17 keypoints."""
        dummy_rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        self.manager.cache_frame("cam-1", "sess-1", 1, 5, dummy_rgb)

        req = PoseRequest(
            request_id="req-ok-1",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=5,
            track_id=1,
            bbox=[50.0, 50.0, 200.0, 350.0],
            deadline=20.0,
            clock_domain="event_time",
        )
        self.manager.submit_request(req)
        outcomes = self.manager.process_pending(current_time=10.0)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].status, "ok")
        self.assertIsNone(outcomes[0].reason)
        self.assertEqual(len(outcomes[0].keypoints), 17)

    def test_direct_request_pose_api(self) -> None:
        """request_pose synchronous API handles frame directly or from cache."""
        dummy_rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        req = PoseRequest(
            request_id="req-direct-1",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=1,
            track_id=1,
            bbox=[50.0, 50.0, 200.0, 350.0],
            deadline=20.0,
            clock_domain="event_time",
        )
        outcome = self.manager.request_pose(req, rgb=dummy_rgb, current_time=10.0)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(len(outcome.keypoints), 17)


class TestPipelinePoseIntegration(unittest.TestCase):
    """Tests for PerceptionPipeline pose integration and status separation."""

    def setUp(self) -> None:
        import tempfile
        import shutil
        from apps.edge.outbox import EventOutbox
        from apps.edge.pipeline import PerceptionPipeline
        from apps.edge.recorder import FileRecorder

        self.tmp_dir = tempfile.mkdtemp()
        self.recorder_dir = Path(self.tmp_dir) / "recorder"
        self.recorder_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(self.tmp_dir) / "outbox.db"
        self.recorder = FileRecorder(self.recorder_dir)
        self.outbox = EventOutbox(self.db_path)
        self.estimator = RtmposeEstimator()
        self.pose_manager = PoseManager(estimator=self.estimator, max_queue_size=10, max_cached_frames=10)
        self.pipeline = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            pose_manager=self.pose_manager,
        )

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_pipeline_caches_frames_and_serves_request_pose(self) -> None:
        """Pipeline caches processed frame, allowing synchronous request_pose lookup."""
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        self.pipeline.process_frame(rgb, timestamp=1.0, frame_id=1, detections=[])

        req = PoseRequest(
            request_id="req-pipe-1",
            camera_id=self.pipeline.camera_id,
            stream_session_id=self.pipeline.stream_session_id,
            core_epoch=self.pipeline.core_epoch,
            frame_id=1,
            track_id=1,
            bbox=[50.0, 50.0, 150.0, 250.0],
            deadline=10.0,
        )
        outcome = self.pipeline.request_pose(req)
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(len(outcome.keypoints), 17)

    def test_pipeline_without_pose_manager_fails_cleanly(self) -> None:
        """Pipeline without pose_manager returns failed status with reason."""
        from apps.edge.pipeline import PerceptionPipeline

        pipeline_no_pose = PerceptionPipeline(
            recorder=self.recorder,
            outbox=self.outbox,
            pose_manager=None,
        )
        req = PoseRequest(
            request_id="req-no-mgr",
            camera_id=pipeline_no_pose.camera_id,
            stream_session_id=pipeline_no_pose.stream_session_id,
            core_epoch=1,
            frame_id=1,
            bbox=[10.0, 10.0, 50.0, 50.0],
            deadline=10.0,
        )
        outcome = pipeline_no_pose.request_pose(req)
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.reason, "pose_manager_unavailable")

    def test_pipeline_epoch_change_invalidates_requests(self) -> None:
        """Pipeline set_core_epoch invalidates older epoch requests in pose manager."""
        req = PoseRequest(
            request_id="req-pipe-ep1",
            camera_id=self.pipeline.camera_id,
            stream_session_id=self.pipeline.stream_session_id,
            core_epoch=1,
            frame_id=1,
            bbox=[10.0, 10.0, 50.0, 50.0],
            deadline=100.0,
        )
        self.pose_manager.submit_request(req)
        self.assertEqual(self.pose_manager.queued_count(), 1)

        self.pipeline.set_core_epoch(2)
        self.assertEqual(self.pose_manager.queued_count(), 0)
        outcomes = self.pose_manager.poll_terminal_outcomes()
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].status, "cancelled")
        self.assertEqual(outcomes[0].reason, "epoch_mismatch")

    def test_status_separation_detection_ok_pose_skipped(self) -> None:
        """Detection success is distinct from pose failure or skip."""
        outcome = PoseOutcome(
            request_id="req-sep-1",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=1,
            track_id=1,
            status="skipped",
            reason="deadline_exceeded",
        )
        observation_batch = {
            "detection_status": "ok",
            "pose_status": outcome.status,
            "pose_reason": outcome.reason,
            "detections": [{"bbox": [10, 10, 50, 50], "score": 0.9}],
            "pose_outcomes": [outcome.to_dict()],
        }
        self.assertEqual(observation_batch["detection_status"], "ok")
        self.assertEqual(observation_batch["pose_status"], "skipped")
        self.assertEqual(observation_batch["pose_reason"], "deadline_exceeded")


if __name__ == "__main__":
    unittest.main()
