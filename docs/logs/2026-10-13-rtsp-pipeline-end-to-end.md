# RTSP Ring Buffer Recorder & Pipeline End-to-End Delivery Log — 2026-10-13

## 1. Overview
- Implemented `RtspRingRecorder` in `apps/edge/rtsp_recorder.py`.
- Implemented `PerceptionPipeline` in `apps/edge/pipeline.py`.
- Created comprehensive test suite in `tests/test_rtsp_pipeline.py`.
- Completed integration of Direction 1 (AI Tracking + Fall IncidentEngine) and Direction 2 (RTSP Ring Buffer Ingest + Automatic Evidence Clip Pinning & Upload).
- Updated local issue tickets #13, #14, and #25 to `Execution: done`.

## 2. Key Decisions & Technical Implementation
- **RtspRingRecorder (`apps/edge/rtsp_recorder.py`)**:
  - Continuous 10-minute (600s) rolling ring buffer ingest into `FileRecorder(root, ring_seconds=600)`.
  - Automatic RTSP configuration resolution via `apps.edge.rtsp.load_rtsp_config()` with parameter overrides.
  - Strict credential sanitization: all logs, reprs, exception reports, and status payloads use `redact_rtsp_url` and `sanitize_probe_output`, guaranteeing camera credentials never leak.
  - Background recording lifecycle (`start()`, `stop()`, `status()`) with context manager support.
  - Graceful fallback: when RTSP probing or streaming fails (network drop, offline camera, or invalid credentials), automatically falls back to sample video fixture (`.scratch/replay-measurements/h264-10s.mkv` or synthetic fixture generated on-the-fly) without raising or halting.
  - Transparently exposes reference to underlying `FileRecorder` and active `session_id`.

- **PerceptionPipeline (`apps/edge/pipeline.py`)**:
  - Full perception-to-delivery composition: `OracleDetector` $\rightarrow$ `ByteTracker` $\rightarrow$ `IncidentEngine` $\rightarrow$ `FileRecorder` $\rightarrow$ `EventOutbox` $\rightarrow$ `EdgeUploader`.
  - Method `process_frame(rgb, timestamp, frame_id, detections=None) -> list[dict[str, Any]]`:
    - Handles object detection inference with PTS/Fraction timebase matching Oracle contract.
    - Normalizes detections (`bbox`, `bbox_xyxy`) for `ByteTracker`.
    - Evaluates tracks in `IncidentEngine`.
    - When `person_fall` is emitted:
      - Builds canonical event snapshot validated against `domain.event_contract.validate_event`:
        `taxonomy="person_fall"`, `severity="critical"`, `origin="live"`, ISO-8601 timestamps with timezone.
      - Attaches structured evidence request: `anchor_kind="onset"`, `anchor_time`, `requested_start = anchor_time - 10`, `requested_end = anchor_time + 20` using `domain.evidence_contract.make_evidence_request`.
      - Calls `recorder.pin(request_id, session_id, requested_start, requested_end, owner)`.
      - Atomically enqueues event into `EventOutbox.enqueue(event)` (SQLite `delivery_outbox`, `event_revisions`, `evidence_requests`).
  - Method `trigger_upload(*, reconcile=True) -> int`:
    - Reconciles evidence pins into finalized `.mkv` clip artifacts in `recorder` and marks outbox requests `fulfilled` or `partial`.
    - Delivers pending event metadata to server `POST /v1/events` via `deliver_pending`.
    - Invokes `uploader.upload_pending()` to upload evidence clips to server `PUT /v1/evidence/{device_id}/{event_id}/{request_id}`.

## 3. Test Evidence & Verification
- **TDD RED state**: `tests/test_rtsp_pipeline.py` initially failed with `ModuleNotFoundError: No module named 'apps.edge.pipeline'`.
- **TDD GREEN state**: All 9 tests in `tests/test_rtsp_pipeline.py` pass cleanly in ~5.5s:
  - `test_recorder_initialization_defaults_and_references` (OK)
  - `test_recorder_fallback_on_unreachable_rtsp_and_redaction` (OK)
  - `test_recorder_context_manager` (OK)
  - `test_recorder_synthetic_fallback_generation` (OK)
  - `test_standing_and_walking_sequence_produces_no_incidents` (OK)
  - `test_pipeline_with_real_oracle_detector_inference` (OK)
  - `test_fall_sequence_triggers_atomic_event_pin_and_outbox` (OK)
  - `test_pipeline_cooldown_suppresses_rapid_duplicate_events` (OK)
  - `test_pipeline_end_to_end_fall_upload_and_server_visibility` (OK - verified event and evidence clip stored in Mongo and accessible on Dashboard).
- **Mypy type check**:
  Command: `.venv-oracle/bin/mypy --follow-imports=silent apps/edge/rtsp_recorder.py apps/edge/pipeline.py tests/test_rtsp_pipeline.py`
  Result: `Success: no issues found in 3 source files`.
- **Full regression suite**:
  Command: `.venv-oracle/bin/python -m unittest discover -s tests -p "test_*.py"`
  Result: `Ran 232 tests in 77.752s: OK` (0 failures, 0 errors).
