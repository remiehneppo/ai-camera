# 01: Live Video Stream with YOLO Detections

Status: ready-for-human
Execution: completed
Owner: Agent

## What to build
- `apps/server/live_stream.py`: `LiveStreamService` handling video capture (RTSP with fallback), YOLO inference via `OracleDetector`, frame annotation (OpenCV boxes, labels, confidences, source badge, FPS counter), and MJPEG multipart generator.
- `apps/server/main.py`: Endpoints `GET /v1/live/stream` and `GET /v1/live/status` with viewer token authentication.
- `apps/server/static/index.html`: Live Stream viewer card with controls and status badges.
- `tests/test_live_stream.py`: Complete test suite with RED -> GREEN TDD workflow.

## Acceptance Criteria
- [x] Frame annotation draws bboxes, labels, confidence, source badge (`RTSP` or `FALLBACK`), and measured FPS.
- [x] Fallback switches to sample video fixture when RTSP fails/disconnects without unhandled exceptions.
- [x] MJPEG generator formats multipart boundary frames (`--frame\r\nContent-Type: image/jpeg\r\n\r\n...`).
- [x] `/v1/live/stream` authenticates via Bearer header or `?token=` query param; returns 401 on missing/invalid token.
- [x] `/v1/live/status` authenticates viewer and returns current stream metrics.
- [x] Web UI displays video stream, source/fps badges, and play/pause toggle.
- [x] Full test suite and Mypy pass.

## Comments
- 2026-10-13: Ticket claimed. Preparing TDD test suite.
- 2026-10-13: Implementation complete. All 16 unit tests and all 209 project tests pass. Mypy checks clean.

