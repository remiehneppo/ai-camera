# Live Video Stream with YOLO Detections Dispatch — 2026-10-13

## 1. Context & User Decisions
- User requested end-to-end implementation for live video streaming with real-time YOLO object detection overlaid on the Web Dashboard.
- Complexity Level: **L2** (Cross-boundary: Edge RTSP video capture, ONNX Runtime CPU YOLOX inference, OpenCV frame annotation, server HTTP multipart/x-mixed-replace MJPEG streaming, and Web Dashboard UI integration).
- Collaboration Mode: `subagent` with route `n9router/ag/gemini-3.8-flash-high`.
- Confirmed Architectural Decisions:
  1. **Protocol**: HTTP MJPEG stream (`multipart/x-mixed-replace`) with bounding boxes, labels, confidence, and FPS annotated on frames on the server. Low latency (<300ms), standard `<img>` tag support on browsers.
  2. **Video Source**: Real Lab RTSP Camera (`rtsp://192.168.1.93:554/...` from `.env.local`) with automatic fallback to sample video file on failure or network disconnection.
  3. **Pipeline Integration**: Isolated live preview worker ensuring zero lock contention on `FileRecorder` ring buffer and preventing spurious outbox event generation.

## 2. Boundaries & Write Scope
- Permitted files:
  - `apps/server/live_stream.py` (new live capture & annotation engine)
  - `apps/server/main.py` (endpoints `GET /v1/live/stream` and `GET /v1/live/status`)
  - `apps/server/static/index.html` (Live Stream viewer UI)
  - `tests/test_live_stream.py` (unit and integration tests)
- Forbidden files:
  - Do NOT modify `apps/edge/outbox.py`, `apps/edge/recorder.py`, or existing unrelated modules.

## 3. Verification Plan
- Follow strict TDD: RED test first in `tests/test_live_stream.py`, then minimal implementation to GREEN.
- Verify with Mypy typecheck.
- Full regression suite execution across the entire repository.
