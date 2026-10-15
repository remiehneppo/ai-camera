"""Tests for RTMPose estimation and Pose Request lifecycle."""

from __future__ import annotations

import math
from pathlib import Path
import time
import unittest

import cv2
import numpy as np

from apps.edge.pose import (
    BranchMetrics,
    PoseManager,
    PoseOutcome,
    PoseRequest,
    PoseScheduler,
    RtmposeEstimator,
)
from apps.edge.tracker import Track


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


class TestPoseBranchClassification(unittest.TestCase):
    """Tests for 3-branch classification (fast_fall, slow_collapse, persistent_lying)."""

    def setUp(self) -> None:
        self.scheduler = PoseScheduler(
            min_drop_velocity=15.0,
            min_ar_change=0.35,
            slow_drop_velocity=3.0,
            slow_ar_change=0.15,
            standing_aspect_ratio=0.85,
            lying_aspect_ratio=1.2,
            persistent_sample_interval=1.0,
        )

    def test_classify_fast_fall_high_velocity(self) -> None:
        """Track with rapid downward velocity is classified as fast_fall."""
        # Initial upright person at t=1.0
        track = Track(track_id=1, bbox=[100.0, 100.0, 150.0, 300.0], score=0.9, label="person", timestamp=1.0)
        # Dropping rapidly at t=2.0 (cy changes from 200 to 250 -> 50 px/s)
        track.update(bbox=[100.0, 150.0, 200.0, 350.0], score=0.9, timestamp=2.0)

        branch = self.scheduler.classify_track(track, current_time=2.0)
        self.assertEqual(branch, "fast_fall")

    def test_classify_fast_fall_sudden_aspect_ratio_change(self) -> None:
        """Track with sudden aspect ratio change is classified as fast_fall."""
        track = Track(track_id=2, bbox=[100.0, 100.0, 150.0, 300.0], score=0.9, label="person", timestamp=1.0)
        # ar changed from 50/200=0.25 to 150/100=1.5 (change = 1.25 >= 0.35)
        track.update(bbox=[100.0, 120.0, 250.0, 220.0], score=0.9, timestamp=1.5)

        branch = self.scheduler.classify_track(track, current_time=1.5)
        self.assertEqual(branch, "fast_fall")

    def test_classify_slow_collapse_gradual_change(self) -> None:
        """Track with moderate velocity / progressive posture change is classified as slow_collapse."""
        track = Track(track_id=3, bbox=[100.0, 100.0, 150.0, 300.0], score=0.9, label="person", timestamp=1.0)
        # cy moves from 200 to 206 in 1.0s (6 px/s, between 3.0 and 15.0), ar changes 0.2
        track.update(bbox=[100.0, 106.0, 180.0, 280.0], score=0.9, timestamp=2.0)

        branch = self.scheduler.classify_track(track, current_time=2.0)
        self.assertEqual(branch, "slow_collapse")

    def test_classify_persistent_lying_already_down(self) -> None:
        """Track with aspect ratio >= 1.2 and no recent kinematic onset is classified as persistent_lying."""
        # Already lying down at t=1.0 (w=250, h=100 -> ar=2.5)
        track = Track(track_id=4, bbox=[100.0, 200.0, 350.0, 300.0], score=0.9, label="person", timestamp=1.0)
        track.update(bbox=[100.0, 200.0, 350.0, 300.0], score=0.9, timestamp=2.0)

        branch = self.scheduler.classify_track(track, current_time=2.0)
        self.assertEqual(branch, "persistent_lying")

    def test_classify_normal_standing_returns_none(self) -> None:
        """Normal standing upright person is not scheduled for pose."""
        track = Track(track_id=5, bbox=[100.0, 100.0, 150.0, 300.0], score=0.9, label="person", timestamp=1.0)
        track.update(bbox=[100.0, 100.0, 150.0, 300.0], score=0.9, timestamp=2.0)

        branch = self.scheduler.classify_track(track, current_time=2.0)
        self.assertIsNone(branch)

    def test_persistent_lying_periodic_sampling(self) -> None:
        """Persistent lying candidate is only scheduled periodically per sampling interval."""
        track = Track(track_id=6, bbox=[100.0, 200.0, 350.0, 300.0], score=0.9, label="person", timestamp=1.0)
        reqs1 = self.scheduler.schedule_tracks([track], current_time=1.0, frame_id=1, camera_id="c1", stream_session_id="s1", core_epoch=1)
        self.assertEqual(len(reqs1), 1)
        self.assertEqual(reqs1[0].branch, "persistent_lying")

        # Next frame at t=1.2 (within 1.0s interval) should NOT generate a new request
        reqs2 = self.scheduler.schedule_tracks([track], current_time=1.2, frame_id=2, camera_id="c1", stream_session_id="s1", core_epoch=1)
        self.assertEqual(len(reqs2), 0)

        # After sampling interval passes (t=2.1), a request is generated
        reqs3 = self.scheduler.schedule_tracks([track], current_time=2.1, frame_id=3, camera_id="c1", stream_session_id="s1", core_epoch=1)
        self.assertEqual(len(reqs3), 1)


class TestPoseSchedulerFairnessAntiStarvation(unittest.TestCase):
    """Tests for fair scheduling and anti-starvation across active branches."""

    def test_burst_fast_fall_does_not_starve_other_branches(self) -> None:
        """A burst of fast_fall requests does not starve slow_collapse or persistent_lying."""
        scheduler = PoseScheduler(batch_budget=4, min_shares={"fast_fall": 1, "slow_collapse": 1, "persistent_lying": 1})

        # Submit 15 fast_fall requests, 2 slow_collapse requests, and 2 persistent_lying requests
        for i in range(15):
            scheduler.submit_request(PoseRequest(
                request_id=f"ff-{i}",
                camera_id="cam-1",
                stream_session_id="sess-1",
                core_epoch=1,
                frame_id=1,
                bbox=[10, 10, 50, 50],
                deadline=10.0,
                branch="fast_fall",
                priority=1,
            ))
        for i in range(2):
            scheduler.submit_request(PoseRequest(
                request_id=f"sc-{i}",
                camera_id="cam-1",
                stream_session_id="sess-1",
                core_epoch=1,
                frame_id=1,
                bbox=[10, 10, 50, 50],
                deadline=10.0,
                branch="slow_collapse",
                priority=2,
            ))
        for i in range(2):
            scheduler.submit_request(PoseRequest(
                request_id=f"pl-{i}",
                camera_id="cam-1",
                stream_session_id="sess-1",
                core_epoch=1,
                frame_id=1,
                bbox=[10, 10, 50, 50],
                deadline=10.0,
                branch="persistent_lying",
                priority=3,
            ))

        # Schedule batch with budget = 4
        batch, _ = scheduler.schedule_batch(current_time=1.0)
        self.assertEqual(len(batch), 4)

        branches_in_batch = [req.branch for req in batch]
        # Anti-starvation guarantee: all 3 active branches must be present!
        self.assertIn("fast_fall", branches_in_batch)
        self.assertIn("slow_collapse", branches_in_batch)
        self.assertIn("persistent_lying", branches_in_batch)

        # Fast fall gets 2 slots (guaranteed 1 + remaining 1), other branches get 1 each
        self.assertEqual(branches_in_batch.count("fast_fall"), 2)
        self.assertEqual(branches_in_batch.count("slow_collapse"), 1)
        self.assertEqual(branches_in_batch.count("persistent_lying"), 1)


class TestPoseBranchMetrics(unittest.TestCase):
    """Tests for tracking scheduled, attempted, skipped, failed, stale, and coverage per branch."""

    def test_metrics_tracking_per_branch(self) -> None:
        scheduler = PoseScheduler()

        # Branch 1: fast_fall (2 ok, 1 skipped)
        req_ff1 = PoseRequest("ff1", "c1", "s1", 1, 1, [0, 0, 10, 10], 10.0, branch="fast_fall")
        req_ff2 = PoseRequest("ff2", "c1", "s1", 1, 1, [0, 0, 10, 10], 10.0, branch="fast_fall")
        req_ff3 = PoseRequest("ff3", "c1", "s1", 1, 1, [0, 0, 10, 10], 0.5, branch="fast_fall")
        scheduler.record_scheduled("fast_fall", 3)
        scheduler.record_outcome(PoseOutcome("ff1", "c1", "s1", 1, 1, "ok", branch="fast_fall"))
        scheduler.record_outcome(PoseOutcome("ff2", "c1", "s1", 1, 1, "ok", branch="fast_fall"))
        scheduler.record_outcome(PoseOutcome("ff3", "c1", "s1", 1, 1, "skipped", reason="deadline_exceeded", branch="fast_fall"))

        # Branch 2: slow_collapse (1 ok, 1 failed)
        scheduler.record_scheduled("slow_collapse", 2)
        scheduler.record_outcome(PoseOutcome("sc1", "c1", "s1", 1, 1, "ok", branch="slow_collapse"))
        scheduler.record_outcome(PoseOutcome("sc2", "c1", "s1", 1, 1, "failed", reason="inference_error", branch="slow_collapse"))

        # Branch 3: persistent_lying (1 ok, 1 stale)
        scheduler.record_scheduled("persistent_lying", 2)
        scheduler.record_outcome(PoseOutcome("pl1", "c1", "s1", 1, 1, "ok", branch="persistent_lying"))
        scheduler.record_outcome(PoseOutcome("pl2", "c1", "s1", 1, 1, "cancelled", reason="epoch_mismatch", branch="persistent_lying"))

        metrics = scheduler.get_metrics()

        # Check fast_fall
        ff = metrics["fast_fall"]
        self.assertEqual(ff["scheduled"], 3)
        self.assertEqual(ff["attempted"], 2)
        self.assertEqual(ff["skipped"], 1)
        self.assertEqual(ff["failed"], 0)
        self.assertEqual(ff["stale"], 0)
        self.assertAlmostEqual(ff["coverage"], 2 / 3, places=3)

        # Check slow_collapse
        sc = metrics["slow_collapse"]
        self.assertEqual(sc["scheduled"], 2)
        self.assertEqual(sc["attempted"], 2)
        self.assertEqual(sc["skipped"], 0)
        self.assertEqual(sc["failed"], 1)
        self.assertEqual(sc["stale"], 0)
        self.assertEqual(sc["coverage"], 1.0)

        # Check persistent_lying
        pl = metrics["persistent_lying"]
        self.assertEqual(pl["scheduled"], 2)
        self.assertEqual(pl["attempted"], 1)
        self.assertEqual(pl["skipped"], 0)
        self.assertEqual(pl["failed"], 0)
        self.assertEqual(pl["stale"], 1)
        self.assertEqual(pl["coverage"], 0.5)


class TestOverloadDegradation(unittest.TestCase):
    """Tests for shedding lower-priority work under overload and capability degradation."""

    def test_overload_sheds_routine_work_first(self) -> None:
        """When queue reaches capacity, persistent_lying is shed first and capability is degraded."""
        scheduler = PoseScheduler(max_queue_size=5, overload_queue_threshold=0.8)

        # Fill queue with 3 fast_fall and 2 persistent_lying requests
        for i in range(3):
            scheduler.submit_request(PoseRequest(f"ff-{i}", "c1", "s1", 1, 1, [0, 0, 10, 10], 10.0, branch="fast_fall", priority=1))
        for i in range(2):
            scheduler.submit_request(PoseRequest(f"pl-{i}", "c1", "s1", 1, 1, [0, 0, 10, 10], 10.0, branch="persistent_lying", priority=3))

        self.assertEqual(scheduler.queued_count(), 5)

        # Now submit another fast_fall request during overload
        new_ff = PoseRequest("ff-new", "c1", "s1", 1, 1, [0, 0, 10, 10], 10.0, branch="fast_fall", priority=1)
        success = scheduler.submit_request(new_ff)
        self.assertTrue(success)

        # The persistent_lying request should have been shed to make room!
        self.assertEqual(scheduler.capability_status, "degraded")
        self.assertIn("overload_shedding_routine_pose", str(scheduler.degraded_reason))

        # Check shed outcomes
        shed = scheduler.poll_shed_outcomes()
        self.assertGreaterEqual(len(shed), 1)
        self.assertEqual(shed[0].branch, "persistent_lying")
        self.assertEqual(shed[0].status, "skipped")
        self.assertEqual(shed[0].reason, "overload_shedding_routine_pose")

        # Fast fall requests are still in the queue!
        queued_branches = scheduler.get_queued_branches()
        self.assertIn("fast_fall", queued_branches)


class TestHysteresisRecovery(unittest.TestCase):
    """Tests for recovery hysteresis requiring sustained calm cycles to prevent flapping."""

    def test_recovery_ramp_with_hysteresis(self) -> None:
        scheduler = PoseScheduler(recovery_cycles=3)
        scheduler.trigger_overload(reason="overload_shedding_routine_pose")

        self.assertEqual(scheduler.capability_status, "degraded")
        self.assertEqual(scheduler.degraded_reason, "overload_shedding_routine_pose")

        # Calm cycle 1: must remain degraded! (Does NOT flap to full on single empty cycle)
        scheduler.step_evaluation_cycle(calm=True)
        self.assertEqual(scheduler.capability_status, "degraded")

        # Calm cycle 2: still degraded
        scheduler.step_evaluation_cycle(calm=True)
        self.assertEqual(scheduler.capability_status, "degraded")

        # Interruption: an overload cycle occurs! Resets calm counter
        scheduler.step_evaluation_cycle(calm=False, overload_reason="queue_near_capacity")
        self.assertEqual(scheduler.capability_status, "degraded")
        self.assertEqual(scheduler.degraded_reason, "queue_near_capacity")

        # Now 3 consecutive calm cycles needed
        scheduler.step_evaluation_cycle(calm=True)
        self.assertEqual(scheduler.capability_status, "degraded")

        scheduler.step_evaluation_cycle(calm=True)
        self.assertEqual(scheduler.capability_status, "degraded")

        # 3rd calm cycle: now recovered to full!
        scheduler.step_evaluation_cycle(calm=True)
        self.assertEqual(scheduler.capability_status, "full")
        self.assertIsNone(scheduler.degraded_reason)


class TestPipelinePoseIntegrationDeepened(unittest.TestCase):
    """Tests for PerceptionPipeline automatic scheduling, metrics exposure, and status."""

    def setUp(self) -> None:
        import tempfile
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

    def test_pipeline_status_and_pose_metrics_exposure(self) -> None:
        """Pipeline exposes pose_capability and branch metrics in status() and get_pose_metrics()."""
        status = self.pipeline.status()
        self.assertIn("pose_capability", status)
        self.assertIn("pose_metrics", status)
        self.assertEqual(status["pose_capability"]["status"], "full")

        metrics = self.pipeline.get_pose_metrics()
        self.assertIn("fast_fall", metrics)
        self.assertIn("slow_collapse", metrics)
        self.assertIn("persistent_lying", metrics)

    def test_pipeline_process_frame_schedules_and_records_coverage(self) -> None:
        """process_frame schedules pose candidate from active track and records coverage."""
        rgb = np.zeros((480, 640, 3), dtype=np.uint8)

        # Frame 1: initial person track
        det1 = [{"bbox": [100.0, 100.0, 150.0, 300.0], "score": 0.9, "label": "person"}]
        self.pipeline.process_frame(rgb, timestamp=1.0, frame_id=1, detections=det1)

        # Frame 2: rapid drop (fast_fall)
        det2 = [{"bbox": [100.0, 200.0, 200.0, 350.0], "score": 0.9, "label": "person"}]
        self.pipeline.process_frame(rgb, timestamp=2.0, frame_id=2, detections=det2)

        metrics = self.pipeline.get_pose_metrics()
        self.assertGreaterEqual(metrics["fast_fall"]["scheduled"], 1)
        self.assertGreaterEqual(metrics["fast_fall"]["attempted"], 1)
        self.assertGreater(metrics["fast_fall"]["coverage"], 0.0)

        # Check observation metadata contains pose capability and metrics
        obs = self.pipeline.last_observation
        self.assertIsNotNone(obs)
        assert obs is not None
        self.assertIn("pose_capability", obs)
        self.assertIn("pose_metrics", obs)


class TestPoseTerminalOutcomesAndClockDomain(unittest.TestCase):
    """Tests for P0-04 (terminal outcomes delivery and deduplication) and P2-08 (clock domain standardization)."""

    def setUp(self) -> None:
        self.estimator = RtmposeEstimator()
        self.manager = PoseManager(
            estimator=self.estimator,
            max_queue_size=2,
            max_cached_frames=5,
        )

    def test_process_pending_returns_shed_outcomes_when_queue_full(self) -> None:
        """When queue overflows, process_pending drains and returns shed outcomes exactly once."""
        dummy_rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        self.manager.cache_frame("cam-1", "sess-1", 1, 0, dummy_rgb)
        self.manager.cache_frame("cam-1", "sess-1", 1, 1, dummy_rgb)

        for i in range(2):
            req = PoseRequest(
                request_id=f"req-ok-{i}",
                camera_id="cam-1",
                stream_session_id="sess-1",
                core_epoch=1,
                frame_id=i,
                bbox=[100.0, 100.0, 200.0, 300.0],
                deadline=100.0,
                clock_domain="event_time",
            )
            accepted = self.manager.submit_request(req)
            self.assertTrue(accepted)

        # 3rd request overflows queue
        overflow_req = PoseRequest(
            request_id="req-overflow",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=2,
            bbox=[100.0, 100.0, 200.0, 300.0],
            deadline=100.0,
            clock_domain="event_time",
        )
        accepted = self.manager.submit_request(overflow_req)
        self.assertFalse(accepted)

        # process_pending must return outcomes for both queued requests AND the shed outcome
        outcomes = self.manager.process_pending(current_time=1.0)
        req_ids = [o.request_id for o in outcomes]
        self.assertIn("req-overflow", req_ids)
        self.assertIn("req-ok-0", req_ids)
        self.assertIn("req-ok-1", req_ids)
        self.assertEqual(len(outcomes), 3)

        overflow_outcome = next(o for o in outcomes if o.request_id == "req-overflow")
        self.assertEqual(overflow_outcome.status, "skipped")
        self.assertEqual(overflow_outcome.reason, "queue_full")

        # Second call to process_pending returns empty (no duplicate outcomes returned)
        outcomes_second = self.manager.process_pending(current_time=2.0)
        self.assertEqual(len(outcomes_second), 0)

        # poll_terminal_outcomes is also empty (already drained)
        outcomes_polled = self.manager.poll_terminal_outcomes()
        self.assertEqual(len(outcomes_polled), 0)

    def test_process_pending_returns_cancelled_outcomes_on_set_epoch_exactly_once(self) -> None:
        """set_epoch cancellation outcomes are drained and returned by process_pending exactly once."""
        req = PoseRequest(
            request_id="req-epoch-1",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=1,
            bbox=[100.0, 100.0, 200.0, 300.0],
            deadline=100.0,
            clock_domain="event_time",
        )
        self.manager.submit_request(req)
        self.assertEqual(self.manager.queued_count(), 1)

        # Epoch changed: cancels req-epoch-1
        cancelled = self.manager.set_epoch(2)
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(self.manager.queued_count(), 0)

        # process_pending must return the cancelled outcome
        outcomes = self.manager.process_pending(current_time=5.0)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].request_id, "req-epoch-1")
        self.assertEqual(outcomes[0].status, "cancelled")
        self.assertEqual(outcomes[0].reason, "epoch_mismatch")

        # Second call does not duplicate
        outcomes_second = self.manager.process_pending(current_time=6.0)
        self.assertEqual(len(outcomes_second), 0)

        # poll_terminal_outcomes is empty
        self.assertEqual(len(self.manager.poll_terminal_outcomes()), 0)

    def test_submit_request_older_epoch_returned_in_process_pending_once(self) -> None:
        """submit_request for an older epoch is rejected and returned in process_pending exactly once."""
        self.manager.set_epoch(3)
        old_req = PoseRequest(
            request_id="req-old-epoch",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=2,
            frame_id=1,
            bbox=[100.0, 100.0, 200.0, 300.0],
            deadline=100.0,
            clock_domain="event_time",
        )
        accepted = self.manager.submit_request(old_req)
        self.assertFalse(accepted)

        outcomes = self.manager.process_pending(current_time=10.0)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].request_id, "req-old-epoch")
        self.assertEqual(outcomes[0].status, "cancelled")
        self.assertEqual(outcomes[0].reason, "epoch_mismatch")

        # Second call returns nothing
        outcomes_second = self.manager.process_pending(current_time=11.0)
        self.assertEqual(len(outcomes_second), 0)

    def test_executed_at_standardized_by_clock_domain(self) -> None:
        """executed_at must match request clock_domain (event_time vs wall_clock)."""
        dummy_rgb = np.zeros((480, 640, 3), dtype=np.uint8)
        self.manager.cache_frame("cam-1", "sess-1", 1, 10, dummy_rgb)

        event_time_ts = 42.125
        req_event = PoseRequest(
            request_id="req-ev-time",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=10,
            bbox=[50.0, 50.0, 200.0, 300.0],
            deadline=50.0,
            clock_domain="event_time",
        )
        self.manager.submit_request(req_event)

        outcomes = self.manager.process_pending(current_time=event_time_ts)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].request_id, "req-ev-time")
        self.assertEqual(outcomes[0].status, "ok")
        self.assertEqual(outcomes[0].executed_at, event_time_ts)

        # Wall clock request
        req_wall = PoseRequest(
            request_id="req-wall-time",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=10,
            bbox=[50.0, 50.0, 200.0, 300.0],
            deadline=time.time() + 10.0,
            clock_domain="wall_clock",
        )
        self.manager.submit_request(req_wall)
        before_t = time.time()
        outcomes_wall = self.manager.process_pending(current_time=100.0)
        after_t = time.time()
        self.assertEqual(len(outcomes_wall), 1)
        self.assertGreaterEqual(outcomes_wall[0].executed_at, before_t - 0.1)
        self.assertLessEqual(outcomes_wall[0].executed_at, after_t + 0.1)

        # Synchronous request_pose clock domain check
        sync_req_ev = PoseRequest(
            request_id="req-sync-ev",
            camera_id="cam-1",
            stream_session_id="sess-1",
            core_epoch=1,
            frame_id=10,
            bbox=[50.0, 50.0, 200.0, 300.0],
            deadline=100.0,
            clock_domain="event_time",
        )
        sync_outcome = self.manager.request_pose(sync_req_ev, rgb=dummy_rgb, current_time=77.5)
        self.assertEqual(sync_outcome.executed_at, 77.5)



if __name__ == "__main__":
    unittest.main()
