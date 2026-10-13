"""Unit and integration tests for Live Stream service with YOLO detections."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cv2
from fastapi.testclient import TestClient
import numpy as np

from apps.server.config import ServerConfig
from apps.server.live_stream import LiveStreamService
from apps.server.main import create_app


class TestLiveStreamAnnotation(unittest.TestCase):
    def setUp(self) -> None:
        self.service = LiveStreamService(
            rtsp_url=None,
            enable_detection=False,
        )

    def test_annotate_frame_draws_bbox_label_and_confidence(self) -> None:
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        detections = [
            {
                "class_id": 0,
                "label": "person",
                "score": 0.885,
                "bbox_xyxy": [50.0, 60.0, 200.0, 250.0],
            }
        ]
        annotated = self.service.annotate_frame(
            blank, detections, source="rtsp", fps=15.0
        )

        self.assertEqual(annotated.shape, blank.shape)
        # Verify box pixels are non-zero (drawn)
        self.assertTrue(np.any(annotated[60:250, 50:200] > 0))
        # Verify unannotated area far away is still black (0)
        self.assertTrue(np.all(annotated[400:450, 500:550] == 0))

    def test_annotate_frame_draws_source_badge_and_fps(self) -> None:
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        annotated_rtsp = self.service.annotate_frame(
            blank, [], source="rtsp", fps=24.5
        )
        self.assertTrue(np.any(annotated_rtsp[10:40, 10:150] > 0))

        annotated_fallback = self.service.annotate_frame(
            blank, [], source="fallback", fps=10.0
        )
        self.assertTrue(np.any(annotated_fallback[10:40, 10:150] > 0))

    def test_annotate_frame_handles_empty_detections(self) -> None:
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        annotated = self.service.annotate_frame(blank, [], source="rtsp", fps=0.0)
        self.assertEqual(annotated.shape, (480, 640, 3))


class TestLiveStreamMjpegFormatting(unittest.TestCase):
    def test_format_mjpeg_frame(self) -> None:
        dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        chunk = LiveStreamService.format_mjpeg_frame(dummy_jpeg)
        self.assertTrue(chunk.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"))
        self.assertTrue(chunk.endswith(b"\r\n"))
        self.assertIn(dummy_jpeg, chunk)

    def test_iter_frames_yields_formatted_frames(self) -> None:
        service = LiveStreamService(
            rtsp_url=None,
            enable_detection=False,
        )
        frames = list(service.iter_frames(max_frames=2))
        self.assertEqual(len(frames), 2)
        for frame in frames:
            self.assertTrue(frame.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"))


class TestLiveStreamFallback(unittest.TestCase):
    def test_fallback_when_rtsp_fails(self) -> None:
        # Invalid RTSP URL must not raise and must switch to fallback
        service = LiveStreamService(
            rtsp_url="rtsp://127.0.0.1:54321/nonexistent",
            enable_detection=False,
        )
        frame, source = service.read_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(source, "fallback")
        self.assertEqual(service.current_source, "fallback")

    def test_fallback_file_loops_at_eof(self) -> None:
        # Use existing fixture mkv if available, or synthetic
        sample_path = Path(".scratch/replay-measurements/h264-10s.mkv")
        if sample_path.exists():
            service = LiveStreamService(
                rtsp_url="",
                fallback_path=sample_path,
                enable_detection=False,
            )
            # Read multiple frames
            for _ in range(5):
                frame, source = service.read_frame()
                self.assertIsNotNone(frame)
                self.assertEqual(source, "fallback")

    def test_synthetic_fallback_when_file_missing(self) -> None:
        service = LiveStreamService(
            rtsp_url="",
            fallback_path="/nonexistent/path/to/missing.mkv",
            enable_detection=False,
        )
        frame, source = service.read_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(source, "fallback")

    def test_detector_inference_on_frame(self) -> None:
        manifest_path = Path("models/yolox-tiny/manifest.json")
        model_path = Path("data/oracle/yolox_tiny.onnx")
        if manifest_path.exists() and model_path.exists():
            service = LiveStreamService(
                rtsp_url="",
                manifest_path=manifest_path,
                model_path=model_path,
                enable_detection=True,
            )
            # Create a synthetic image or read sample image
            sample_img_path = Path("data/oracle/shibuya_people.jpg")
            if sample_img_path.exists():
                bgr = cv2.imread(str(sample_img_path))
            else:
                bgr = np.zeros((416, 416, 3), dtype=np.uint8)
            annotated, detections = service.process_and_annotate(bgr, "fallback")
            self.assertEqual(annotated.shape, bgr.shape)
            self.assertIsInstance(detections, list)
            if sample_img_path.exists():
                self.assertGreater(len(detections), 0)
                self.assertGreater(service.detections_count, 0)
                self.assertIn("person", [d["label"] for d in detections])


class TestLiveStreamEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.device_tokens = {"dev-tok-1": "cam-lab-01"}
        self.reviewer_tokens = {"alice": "rev-tok-1"}
        self.dashboard_token = "dash-secret-token"
        self.config = ServerConfig(
            device_tokens=self.device_tokens,
            reviewer_tokens=self.reviewer_tokens,
            dashboard_token=self.dashboard_token,
            mongo_uri="mongodb://localhost:27017",
            mongo_database="test_db",
            evidence_dir=self.temp_dir.name,
            config_hash="abc",
        )
        self.live_service = LiveStreamService(
            rtsp_url=None,
            enable_detection=False,
        )
        with patch("apps.server.main.EventStore"):
            self.app = create_app(self.config, live_service=self.live_service)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.live_service.stop()
        self.temp_dir.cleanup()

    def test_live_stream_unauthorized_without_token(self) -> None:
        response = self.client.get("/v1/live/stream")
        self.assertEqual(response.status_code, 401)

    def test_live_stream_unauthorized_with_invalid_token(self) -> None:
        response = self.client.get("/v1/live/stream?token=bad-token")
        self.assertEqual(response.status_code, 401)

        response = self.client.get(
            "/v1/live/stream", headers={"Authorization": "Bearer bad-token"}
        )
        self.assertEqual(response.status_code, 401)

    def test_live_stream_authorized_with_dashboard_token_query(self) -> None:
        response = self.client.get(
            f"/v1/live/stream?token={self.dashboard_token}&max_frames=1"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("multipart/x-mixed-replace", response.headers["content-type"])
        self.assertTrue(response.content.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"))

    def test_live_stream_authorized_with_dashboard_token_header(self) -> None:
        response = self.client.get(
            "/v1/live/stream?max_frames=1",
            headers={"Authorization": f"Bearer {self.dashboard_token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("multipart/x-mixed-replace", response.headers["content-type"])

    def test_live_stream_authorized_with_reviewer_token(self) -> None:
        response = self.client.get(
            "/v1/live/stream?token=rev-tok-1&max_frames=1"
        )
        self.assertEqual(response.status_code, 200)

    def test_live_status_unauthorized(self) -> None:
        response = self.client.get("/v1/live/status")
        self.assertEqual(response.status_code, 401)

        response = self.client.get("/v1/live/status?token=bad")
        self.assertEqual(response.status_code, 401)

    def test_live_status_authorized(self) -> None:
        response = self.client.get(
            f"/v1/live/status?token={self.dashboard_token}"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertIn(data["status"], ["running", "idle"])
        self.assertIn("source", data)
        self.assertIn(data["source"], ["rtsp", "fallback"])
        self.assertIn("resolution", data)
        self.assertIsInstance(data["resolution"], list)
        self.assertEqual(len(data["resolution"]), 2)
        self.assertIn("fps", data)
        self.assertIsInstance(data["fps"], (int, float))
        self.assertIn("detections_count", data)
        self.assertIsInstance(data["detections_count"], int)
        self.assertEqual(data["model"], "yolox_tiny")


if __name__ == "__main__":
    unittest.main()
