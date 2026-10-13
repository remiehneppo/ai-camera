# PRD: Live Video Stream with YOLO Detections

## Overview
Provide real-time live video streaming with YOLO object detection overlays in the AI-Camera-OC lab environment.
The live stream runs as an isolated preview service (independent of `FileRecorder` and `Outbox`) to avoid lock contention and prevent false outbox events.

## Objectives
1. Stream MJPEG (`multipart/x-mixed-replace; boundary=frame`) over HTTP with YOLO bounding box, label, confidence, source badge, and FPS annotations.
2. Ingest frames from the Lab RTSP Camera (`rtsp://192.168.1.93:554/...`) with seamless fallback to a sample video file if RTSP is unreachable or drops.
3. Provide status endpoint `GET /v1/live/status` and viewer authentication on both stream and status endpoints.
4. Provide dashboard UI with live stream card, status indicators, and play/pause controls.
