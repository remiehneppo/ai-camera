# 2026-10-13: Live Video Stream with YOLO Detections

## Summary
Implemented HTTP MJPEG live video stream (`multipart/x-mixed-replace; boundary=frame`) with real-time YOLO object detection bounding boxes, confidence labels, source indicator, and measured FPS.

## Key Decisions & Architecture
1. **Isolated Live Stream Service (`apps/server/live_stream.py`)**:
   - Encapsulated in `LiveStreamService`.
   - Dual-source acquisition: Reads primary feed from RTSP (`load_rtsp_config()`) with bounded socket timeout (`2000000` µs) to prevent hanging.
   - Smooth, graceful fallback: If RTSP fails to connect, drops, or times out, seamlessly falls back to fallback video fixture or synthetic test frame generator without raising unhandled exceptions or crashing the server.
   - Looping fallback: When video file hits EOF, rewinds frame position to 0 and loops seamlessly.
   - Detection integration: Integrates with `apps.edge.oracle_detector.OracleDetector` with `models/yolox-tiny/manifest.json` (or `data/oracle/yolox_tiny_manifest.json`) and `data/oracle/yolox_tiny.onnx`.
   - Frame annotation: Annotates bounding box rectangles (`cv2.rectangle`), labels and confidence percentages (`cv2.putText` with background tag), source badge (`SOURCE: RTSP` in green or `SOURCE: FALLBACK` in orange), and measured FPS.
   - Multipart HTTP stream formatter: Produces `--frame\r\nContent-Type: image/jpeg\r\n\r\n...`.

2. **Server Endpoints (`apps/server/main.py`)**:
   - `GET /v1/live/stream`:
     - Accepts authorization via `Authorization: Bearer <token>` or `?token=<token>`.
     - Validates dashboard or reviewer credentials; returns HTTP 401 on missing/invalid token.
     - Returns `StreamingResponse` with `media_type="multipart/x-mixed-replace; boundary=frame"`.
     - Supports optional `max_frames` parameter for testing bounded chunks without hanging.
   - `GET /v1/live/status`:
     - Accepts viewer authorization.
     - Returns current live stream status: `{"status": "running"|"idle", "source": "rtsp"|"fallback", "resolution": [w, h], "fps": float, "detections_count": int, "model": "yolox_tiny"}`.

3. **Web Dashboard UI (`apps/server/static/index.html`)**:
   - Added Live Camera Stream card with:
     - Toggle button ("Start Stream" / "Pause Stream") to save bandwidth when idle.
     - Badges for Active Source (RTSP / Fallback), FPS, and Detection count.
     - Image element `<img id="live-feed">` connected to `/v1/live/stream?token=${token}`.
     - Automatic polling of `/v1/live/status` every 2 seconds when authenticated.

4. **TDD Test Suite (`tests/test_live_stream.py`)**:
   - Tested frame annotation logic (boxes, labels, confidence, source badge, FPS).
   - Tested MJPEG stream byte formatting.
   - Tested RTSP failure and smooth switch to fallback.
   - Tested EOF looping on fallback video.
   - Tested API endpoints with authorized/unauthorized tokens.
   - Tested real ONNX detector inference on image frames.

## Verification
- Unit & integration test suite: 16/16 pass (`.venv-oracle/bin/python -m unittest tests/test_live_stream.py`).
- Full test suite: 209/209 pass (`.venv-oracle/bin/python -m unittest discover -s tests -p "test_*.py"`).
- Static typechecking: 0 errors (`.venv-oracle/bin/mypy --follow-imports=silent apps/server/live_stream.py apps/server/main.py tests/test_live_stream.py`).
