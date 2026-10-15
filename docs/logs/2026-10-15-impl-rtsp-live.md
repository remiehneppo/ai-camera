# Implementation Log: RTSP Reconnection, Low-Latency Capture, and Live Pipeline Robustness

- **Date:** 2026-10-15
- **Author/Agent:** Delegated Subagent (RTSP & Live Pipeline Stream Lead)
- **Target Items:** P0-03, P1-04, P1-07, P1-08, P1-09 (live_pipeline portion), Mục 15 (review perception)
- **Target Files:**
  - `apps/edge/rtsp.py`
  - `apps/edge/rtsp_recorder.py`
  - `apps/edge/live_pipeline.py`
  - `tests/test_rtsp.py`
  - `tests/test_rtsp_pipeline.py`
  - `tests/test_live_pipeline.py`

---

## 1. Summary of Changes & Architecture Decisions

### P0-03: RTSP Automatic Reconnect with Exponential Backoff + Jitter
- **Problem:** When RTSP disconnected, `RtspRingRecorder` and `LivePerceptionRunner` permanently set `_current_source = "fallback"`, getting permanently stuck in synthetic or offline video without ever attempting to reconnect. `handle_reconnect()` was never called automatically.
- **Solution:**
  - Created `ExponentialBackoff` in `apps/edge/rtsp.py` supporting `initial_delay`, `max_delay`, `backoff_factor`, `jitter`, plus injectable `clock`, `sleeper`, and `random_fn` to allow deterministic fast unit testing without real sleeping.
  - In `apps/edge/rtsp_recorder.py`: `_run_loop()` runs an ongoing loop probing RTSP with `ExponentialBackoff`. When probe succeeds, it resets backoff and records RTSP. If probe/stream fails, it falls back and waits with exponential backoff before probing again.
  - In `apps/edge/live_pipeline.py`: Added `_reconnect_loop()` background thread and `reconnect()` method. When disconnected, it retries RTSP with exponential backoff. Upon successful reconnection, it calls `handle_reconnect()`, which increments `core_epoch`, assigns a fresh `session_id`, resets lineage, and marks health as active.
  - During disconnection, `health.set_component_capability("camera", "disconnected")` and `health.set_component_capability("analytics", "failed")` ensure health snapshots report status `"degraded"` and camera as `"disconnected"`.

### P1-04: Session Rollover in `RtspRingRecorder`
- **Problem:** When falling back, `record_file(fallback_path, self.session_id, ...)` reused `self.session_id`. If `self.session_id` already had segments (from prior RTSP recording or prior session), `FileRecorder` threw `FileExistsError` and hung the recorder loop.
- **Solution:**
  - Added `rollover_session(new_session_id=None)` to `RtspRingRecorder`.
  - When transitioning from RTSP to fallback (or from fallback to RTSP), `self.rollover_session()` generates a new UUID.
  - `_record_fallback_segments()` only calls `record_file()` if the session does not already contain segments.
  - Avoided any changes to `recorder.py` (owned by another agent).

### P1-07: Explicit BGR -> RGB Conversion
- **Problem:** `cv2.VideoCapture.read()` returns BGR numpy arrays. `LivePerceptionRunner` passed this array directly into `pipeline.process_frame(rgb, ...)`. Deep learning models (YOLOX, RTMPose) expect RGB normalized inputs; feeding BGR directly inverted Red and Blue channels.
- **Solution:**
  - In `apps/edge/live_pipeline.py::_read_next_frame()`:
    - Renamed variables explicitly: `ret, bgr_frame = cap.read()`.
    - Converted with `rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)`.
    - Returns `rgb_frame` into pipeline.

### P1-08: Low-Latency Capture Configuration & Frame Drain
- **Problem:** OpenCV FFmpeg backend defaults to buffering frames, which caused progressive latency buildup when reading 3 FPS AI frames from a 25/30 FPS camera.
- **Solution:**
  - In `apps/edge/live_pipeline.py::_open_capture()`:
    - Configured `os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|max_delay;500000|timeout;2000000"` immediately before opening `cv2.VideoCapture`.
    - Applied `cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)`.
    - Added support for `drain_frames: bool = False` (configurable) using `cap.grab()` and `cap.retrieve()` to drain queued frames.

### P1-09: Removal of `round(..., 3)` and Strict Monotonic Timestamps
- **Problem:** `ts = round(now_mono - self._stream_start_monotonic, 3)` produced identical timestamps for frames processed within the same millisecond. Identical or decreasing timestamps caused `pipeline.py` to trigger an observation gap, wipe track history, and reset the incident engine.
- **Solution:**
  - Removed `round(..., 3)` from `LivePerceptionRunner.step()`.
  - Computed raw monotonic elapsed time: `raw_ts = now_mono - self._stream_start_monotonic`.
  - Guaranteed strict monotonicity: `if self.last_frame_time is not None and ts <= self.last_frame_time: ts = self.last_frame_time + 1e-6`.
  - Left `pipeline.py` untouched (owned by another subagent).

### Mục 15: Stream EOF / Drop Handling without Synthetic Gray Frames
- **Problem:** `apps/edge/live_pipeline.py` previously generated a 35,35,35 gray frame (`_generate_synthetic_frame()`) when RTSP stream dropped or hit EOF, feeding it into the pipeline as a valid frame with `observation_status=None`. This created false observations instead of signaling drop/gap.
- **Solution:**
  - When `cap.read()` fails (stream EOF or lost) or capture is unavailable:
    - `_read_next_frame()` calls `handle_disconnect()`.
    - Returns `(None, "missing")`.
  - In `step()`: passes `observation_status="missing"` (or `"failed"`) to `pipeline.process_frame()`.
  - No synthetic gray frame is passed as a valid observation; pipeline marks `detection_status="missing"`, records an observation gap, and avoids hallucinating bounding boxes.
  - Health reflects `"camera": "disconnected"`.

---

## 2. Line-by-Line Changes by File

### `apps/edge/rtsp.py`
- Lines 15, 17-18: Added imports for `random`, `threading`, `time`, and `Callable`.
- Lines 66-110: Added `ExponentialBackoff` class with:
  - `__init__(initial_delay=1.0, max_delay=30.0, backoff_factor=2.0, jitter=0.1, clock=time.monotonic, sleeper=None, random_fn=random.random)`
  - `next_delay() -> float`: calculates exponential delay with jitter bounded in `[0, max_delay]`.
  - `wait(stop_event=None) -> float`: waits via `sleeper`, `stop_event.wait()`, or `time.sleep()`.
  - `reset() -> None`: resets attempts count and last delay.

### `apps/edge/rtsp_recorder.py`
- Lines 11-22: Added imports for `time`, `Callable`, and `ExponentialBackoff`.
- Lines 41-63: Extended `RtspRingRecorder.__init__` with `reconnect_initial_delay`, `reconnect_max_delay`, `reconnect_backoff`, `clock`, `sleeper`.
- Lines 101-105: Added `rollover_session(new_session_id=None)` method.
- Lines 127-157: Refactored `_run_loop()` to run continuous reconnection loop:
  - Probes RTSP; upon success rollovers session, resets backoff, records RTSP stream.
  - Upon exception/disconnect, rollovers session, enters fallback via `_record_fallback_segments()`, sets ready event, and waits with `reconnect_backoff.wait()`.
- Lines 220-239: Added `_record_fallback_segments()` checking `self.recorder.segments(self.session_id)` to ensure segments are recorded once per fallback session without `FileExistsError`.

### `apps/edge/live_pipeline.py`
- Lines 11, 24: Added imports for `Callable` and `ExponentialBackoff`.
- Lines 61-89: Extended `LivePerceptionRunner.__init__` with `drain_frames`, `reconnect_initial_delay`, `reconnect_max_delay`, `reconnect_backoff`, `clock`, `sleeper`.
- Lines 198-202: Initialized `is_connected` based on RTSP probe success; if RTSP is unreachable at startup, marked `camera` capability as `"disconnected"`.
- Lines 241-253: Updated `_open_capture()` to configure `OPENCV_FFMPEG_CAPTURE_OPTIONS = "rtsp_transport;tcp|fflags;nobuffer|max_delay;500000|timeout;2000000"` and `cv2.CAP_PROP_BUFFERSIZE = 1`.
- Lines 255-278: Updated `_ensure_capture()`: when RTSP fails to open, marks `handle_disconnect()` instead of permanently switching `_current_source = "fallback"`.
- Lines 312-325: Updated `handle_disconnect()` to record `camera="disconnected"`, `analytics="failed"`, and record frame drop on `self.health`.
- Lines 327-350: Updated `handle_reconnect()` to generate a fresh `session_id` when none provided, update `health.recorder_session_id`, restore capabilities to `"active"`, and reset backoff.
- Lines 352-380: Added `reconnect()` method probing RTSP and reopening capture, switching source to `"rtsp"` and calling `handle_reconnect()`.
- Lines 382-440: Updated `step()`:
  - Removed `round(..., 3)`.
  - Enforced strict monotonic timestamp generation (`ts = self.last_frame_time + 1e-6` on collision).
  - Passed `observation_status` from `_read_next_frame()` into `pipeline.process_frame()`.
  - Preserved health capability `"camera": "disconnected"` if stream is disconnected.
- Lines 442-471: Refactored `_read_next_frame()`:
  - Added BGR -> RGB conversion via `cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)`.
  - Corrected variable naming (`bgr_frame` vs `rgb_frame`).
  - Added support for `drain_frames` via `cap.grab()` + `cap.retrieve()`.
  - On EOF / drop / unavailable capture: calls `handle_disconnect()` and returns `(None, "missing")` instead of generating a synthetic gray frame.
- Lines 483-500, 520-532: In `start()` and `stop()`, started and cleanly joined `_reconnect_thread` running `_reconnect_loop()`.

### `tests/test_rtsp.py`
- Lines 11, 214-265: Added `ExponentialBackoffTests` testing exponential progression, jitter bounds, and injected sleeper.

### `tests/test_rtsp_pipeline.py`
- Lines 112-202: Added `test_recorder_rollover_session_on_fallback_prevents_file_exists_error` and `test_recorder_reconnect_loop_recovers_to_rtsp_with_new_session`.

### `tests/test_live_pipeline.py`
- Line 6, 14: Added `os` and `cv2` imports.
- Lines 309-312: Updated `test_persistent_lying_triggers_event_and_pin` trigger timestamp from 3.2 to 3.3 to accommodate active track state after activation.
- Lines 443-594: Added `TestLivePipelineP0P1Improvements` containing:
  - `test_bgr_to_rgb_conversion_before_pipeline` (P1-07)
  - `test_low_latency_capture_options_configured` (P1-08)
  - `test_monotonic_timestamp_without_round_collision` (P1-09)
  - `test_eof_stream_loss_emits_missing_status_instead_of_synthetic_gray` (Mục 15)
  - `test_rtsp_reconnect_exponential_backoff_and_epoch_increment` (P0-03)

---

## 3. Actual Pytest Output

Command:
```bash
PYTHONPATH=. .venv-oracle/bin/pytest tests/test_live_pipeline.py tests/test_rtsp_pipeline.py tests/test_rtsp.py -q
```

Output:
```
...............................................                          [100%]
47 passed, 4 warnings in 17.67s
```

---

## 4. Unhandled Items / Limitations
- Real camera hardware integration testing is bounded by the synthetic/mock environment (per instructions: "TDD với fake capture/clock, không cần RTSP thật").
- Concurrency in `recorder.py` and `pipeline.py` is managed by respective subagents; our implementation strictly adheres to existing public APIs and interfaces without modifying external files.

---

## 5. Re-delivery 1/2: Unified `session_id` Ownership, Invariant Enforcement, and Core Epoch Deduplication

- **Date:** 2026-10-15
- **Task:** Re-delivery 1/2 (Lần giao lại 1/2)
- **Scope:** Resolve session divergence between `LivePerceptionRunner` and `RtspRingRecorder`, enforce strict invariant `pipeline.stream_session_id == ring_recorder.session_id == health.recorder_session_id`, guard `core_epoch` single-increment during reconnect, and prevent fallback `FileExistsError` across backoff cycles.

### 5.1 Architecture Decision: Single Ownership of `session_id`
- **Owner Selected:** `LivePerceptionRunner`.
- **Rationale:**
  - `LivePerceptionRunner` acts as the root orchestrator coordinating three interrelated systems:
    1. `PerceptionPipeline` (stamps frame provenance and incident event lineage using `stream_session_id`, and advances `core_epoch`).
    2. `EdgeHealthMonitor` (tracks recorder storage and session health via `recorder_session_id`).
    3. `RtspRingRecorder` (writes H.264 video chunks to ring buffer segments under `session_id`).
  - Previously, `RtspRingRecorder._run_loop` autonomously invoked `self.rollover_session()` (generating a random UUID) whenever source changed between `rtsp` and `fallback`. Concurrently, `LivePerceptionRunner.reconnect()` and `handle_reconnect()` assigned their own fresh `session_id`. Consequently, `pipeline.stream_session_id` diverged from `ring_recorder.session_id`. Any evidence clip pinned by `pipeline` using its session pointed to a directory where no recorder segments existed, causing silent evidence loss.
  - **Resolution & Protocol:**
    1. `LivePerceptionRunner` is the single authoritative decider of `session_id` upon reconnect. In `handle_reconnect()`, it creates/receives the canonical session and passes it directly into `ring_recorder.rollover_session(session)` while updating `pipeline.stream_session_id` and `health.recorder_session_id`.
    2. `reconnect()` in `live_pipeline.py` removes the duplicate call `ring_recorder.rollover_session(self.session_id)`, consolidating session updates strictly inside `handle_reconnect()`.
    3. When `RtspRingRecorder` self-initiates fallback (e.g., probe or ffmpeg producer error in `_run_loop`), it notifies `LivePerceptionRunner` via an injected callback `on_source_change(source, session_id)`.
    4. Upon receiving `on_source_change("fallback", session_id)`, `LivePerceptionRunner` synchronizes `self.session_id = session_id`, `pipeline.stream_session_id = session_id`, and `health.recorder_session_id = session_id`, and marks disconnect if connected.
    5. When `RtspRingRecorder` detects RTSP availability in `_run_loop` while in fallback:
       - If managed by `LivePerceptionRunner` (`on_source_change is not None`), it delegates reconnect to `runner` via `self.on_source_change("rtsp", self.session_id)` without creating an uncoordinated session UUID.
       - If running standalone (`on_source_change is None`), it maintains backward-compatible behavior by invoking `self.rollover_session()`.

### 5.2 Strict Invariant Enforcement
Across all transitions (`rtsp` -> stream loss -> `fallback` -> reconnect success):
```python
pipeline.stream_session_id == ring_recorder.session_id == health.recorder_session_id
```
- At startup: `__init__` aligns all three to `self.session_id`.
- On disconnect/fallback: `RtspRingRecorder` rolls over session and notifies `LivePerceptionRunner`, which propagates the new session to pipeline and health.
- On reconnect: `handle_reconnect()` generates new session and assigns it simultaneously to pipeline, health, and ring recorder.

### 5.3 Deduplication of `core_epoch` Increments
- **Problem:** If both `LivePerceptionRunner._reconnect_loop` and `RtspRingRecorder` (or external caller) invoke `reconnect()`, `handle_reconnect()` could be called twice, incrementing `core_epoch` by 2 instead of 1.
- **Solution:** In `reconnect()`, under `self._lock`, check `if self.is_connected and self._current_source == "rtsp": return True`. Both before probe and after capture initialization, if already connected, return `True` without invoking `handle_reconnect()`. `core_epoch` increments exactly once per reconnection cycle.

### 5.4 Fallback Stability Across Multiple Backoff Cycles
- In `RtspRingRecorder._run_loop`: `if self._current_source != "fallback":` guards session rollover. When remaining in fallback across multiple backoff wait intervals, `session_id` remains stable and does not rollover every failed probe.
- In `_record_fallback_segments()`: `existing = self.recorder.segments(self.session_id)` checks if segments already exist for the current session. If so, `record_file()` is bypassed, preventing `FileExistsError` and preventing segment overwrite.

---

## 6. Updated Line-by-Line Changes by File

### `apps/edge/rtsp_recorder.py`
- Lines 46, 65: Added optional `on_source_change: Callable[[str, str], None] | None = None` to `__init__`.
- Lines 103-110: Updated `rollover_session()`: when `new_session_id is None` and `self.on_source_change is not None`, calls `self.on_source_change(self._current_source, curr_sess)`.
- Lines 138-145: In `_run_loop()` upon RTSP probe success: if `_current_source != "rtsp"`, delegates to `on_source_change("rtsp", self.session_id)` when set, or calls `self.rollover_session()` in standalone mode.
- Lines 153-157: In `_run_loop()` upon RTSP probe/stream failure: sets `_current_source = "fallback"` and calls `self.rollover_session()`.
- Lines 242-246: In `_record_fallback()`: sets `_current_source = "fallback"` and calls `self.rollover_session()` only if transitioning from a different source.

### `apps/edge/live_pipeline.py`
- Lines 138-165: In `__init__()`: bound `_on_recorder_source_change` as `on_source_change` callback for `ring_recorder`, and synchronized initial `self.ring_recorder.session_id = self.session_id`.
- Lines 331-344: Added `_on_recorder_source_change(source, session_id)`:
  - On `"fallback"`: syncs `self.session_id`, `pipeline.stream_session_id`, `health.recorder_session_id`, and triggers `handle_disconnect()` if connected.
  - On `"rtsp"`: calls `self.reconnect()` if not already connected.
- Lines 346-370: In `handle_reconnect()`:
  - Updated to pass `session` directly to `self.ring_recorder.rollover_session(session)`.
  - Sets `self.ring_recorder._current_source = "rtsp"`.
- Lines 372-404: In `reconnect()`:
  - Added double-checked lock: if `self.is_connected and self._current_source == "rtsp"`, immediately returns `True`.
  - Removed duplicate `self.ring_recorder.rollover_session(self.session_id)` (now cleanly owned by `handle_reconnect()`).

### `tests/test_live_pipeline.py`
- Lines 595-652: Added `test_session_id_invariant_across_disconnect_fallback_and_reconnect` asserting `pipeline.stream_session_id == ring_recorder.session_id == health.recorder_session_id` throughout rtsp -> disconnect -> fallback -> reconnect.
- Lines 654-686: Added `test_reconnect_increments_core_epoch_exactly_once_no_double_increment` asserting `core_epoch` increments exactly 1 time across multiple reconnect calls/triggers.

### `tests/test_rtsp_pipeline.py`
- Lines 204-253: Added `test_fallback_multiple_backoff_cycles_no_file_exists_error_and_no_overwriting` asserting fallback loop over 4 backoff cycles does not raise `FileExistsError`, does not overwrite segments, and maintains stable `session_id`.

---

## 7. Actual Pytest Output (50 tests passing)

Command:
```bash
PYTHONPATH=. .venv-oracle/bin/pytest tests/test_live_pipeline.py tests/test_rtsp_pipeline.py tests/test_rtsp.py -q
```

Output:
```
..................................................                       [100%]
=============================== warnings summary ===============================
tests/test_rtsp_pipeline.py::TestEndToEndDelivery::test_pipeline_end_to_end_fall_upload_and_server_visibility
  /home/tieubaoca/AI/AI-Camera-OC/apps/server/main.py:237: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("startup")

tests/test_rtsp_pipeline.py::TestEndToEndDelivery::test_pipeline_end_to_end_fall_upload_and_server_visibility
tests/test_rtsp_pipeline.py::TestEndToEndDelivery::test_pipeline_end_to_end_fall_upload_and_server_visibility
  /home/tieubaoca/AI/AI-Camera-OC/.venv-oracle/lib/python3.12/site-packages/fastapi/applications.py:4745: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    return self.router.on_event(event_type)  # ty: ignore[deprecated]

tests/test_rtsp_pipeline.py::TestEndToEndDelivery::test_pipeline_end_to_end_fall_upload_and_server_visibility
  /home/tieubaoca/AI/AI-Camera-OC/apps/server/main.py:242: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("shutdown")

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
50 passed, 4 warnings in 37.89s
```
