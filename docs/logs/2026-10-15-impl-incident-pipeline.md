# Implementation Log: Incident & Pipeline Fixes (P0-01, P0-02, P1-09, P1-10, P1-11, P1-13)

Date: 2026-10-15
Author: Subagent (Incident & Pipeline)
Scope: Fixes for P0-01, P0-02, P1-09, P1-10, P1-11, P1-13 in `apps/edge/incident.py`, `apps/edge/pipeline.py` and test suites.

## Context & Plan

Based on findings in `docs/logs/2026-10-15-full-flow-code-review.md`, `docs/architecture/contracts.md`, and `docs/adr/0001-feature-pipeline-boundaries.md`:
1. **P0-01**: `IncidentEngine` only processes tracks where `label == "person"`. Tracks with other labels (car, motorcycle, truck, bus, etc.) are ignored.
2. **P0-02**: Branch `person_lying_persistent` must enforce stationary speed (`speed <= max_motion_speed`) across `persistent_lying_duration`. If moving, `first_qualifying_time` is reset to `ts`.
3. **P1-09**: In `pipeline.py`, ensure strictly monotonic timestamps (`ts = max(ts, self._last_timestamp + 1e-6)` when `fid > self._last_frame_id`) to avoid false stale observation gaps when consecutive frames arrive within the same millisecond. (Do not touch `live_pipeline.py`).
4. **P1-10**: Do not overwrite `onset_time` when track is in `in_fall_candidate` and still moving fast (`speed > max_motion_speed`); only update `lying_start_time`.
5. **P1-11**: Only clear `track.history` when `track.state == "removed"`, not when `track.state == "lost"`.
6. **P1-13**: Add optional `roi_polygon` (default `None` for backward compatibility) and filter objects by bottom-center foot coordinate `((bbox[0] + bbox[2]) / 2.0, bbox[3])`. Add minimal ODD frame assessment (`quality_state` dynamically assessed if initialized to "unknown").

Workflow: TDD (write red tests first, verify failure, implement fix, verify green).

## Step 1: P0-01 - Filter Non-Person Tracks in IncidentEngine

- **Problem**: `IncidentEngine.process_tracks` did not check `track.label == "person"`. Vehicles (`car`, `motorcycle`, `bus`, `truck`) with wide bounding boxes (AR >= 1.2) triggered false `person_lying_persistent` alerts after 3 seconds.
- **TDD Test**: Added `test_non_person_tracks_ignored_by_incident_engine` in `tests/test_tracking_incident.py`.
  - Red outcome: Failed with `AssertionError: Lists differ: [{'taxonomy': 'person_lying_persistent'}] != []`.
- **Implementation**: In `apps/edge/incident.py`:
  - `observed_ids = {track.track_id for track in tracks if getattr(track, "label", None) == "person"}`
  - Guard check in loop: `if getattr(track, "label", None) != "person": continue`.
- **Result**: Test passed. All 29 existing and new tests pass.

## Step 2: P0-02 - Stationary Speed Enforcement for Persistent Lying

- **Problem**: `person_lying_persistent` did not check motion speed. Moving horizontal objects/people could trigger persistent lying alerts while actively moving across the camera.
- **TDD Test**: Added `test_person_lying_persistent_requires_stationary_speed` in `tests/test_tracking_incident.py`.
  - Red outcome: Failed with `AssertionError: Lists differ: [{'taxonomy': 'person_lying_persistent'}] != []` at t=3.1 (triggered prematurely while moving).
- **Implementation**: In `apps/edge/incident.py`:
  - Added `moving_frames: int = 0` to `_TrackIncidentState`.
  - In `person_lying_persistent` branch:
    - If `speed > self.max_motion_speed`: increment `moving_frames`. When `moving_frames >= 2` (sustained motion, ignoring single-frame sensor jitter), reset `state.first_qualifying_time = ts`. Never emit alert while moving.
    - If `speed <= self.max_motion_speed`: reset `moving_frames = 0`, initialize `first_qualifying_time` if `None`, and require continuous stationary duration `ts - first_qualifying_time > persistent_lying_duration`.
- **Result**: Both `test_person_lying_persistent_requires_stationary_speed` and `test_persistent_lying_transient_speed_jitter_preserves_anchor_time` pass cleanly. All 30 tests pass.

## Step 3: P1-09 - Strictly Monotonic Timestamps in PerceptionPipeline

- **Problem**: When two consecutive frames were processed within the same millisecond or experienced clock jitter (`ts <= self._last_timestamp`), `PerceptionPipeline` treated the frame as stale, triggering `_observation_gap()`, resetting incident detection, and wiping tracking history.
- **TDD Test**: Added `test_consecutive_frames_same_millisecond_timestamp_not_stale` in `tests/test_pipeline.py`.
  - Red outcome: Failed with `AssertionError: 'stale' == 'stale'` and wiped track history.
- **Implementation**: In `apps/edge/pipeline.py`:
  - Kept stale check strictly for `fid <= self._last_frame_id`.
  - When `fid > self._last_frame_id` and `self._last_timestamp is not None and ts <= self._last_timestamp`: enforce strict monotonicity via `ts = self._last_timestamp + 1e-6`.
  - Avoided modifying `live_pipeline.py` per boundary constraints.
- **Result**: Test passed. All 31 tests pass.

## Step 4: P1-10 - Do Not Overwrite onset_time When Candidate Still Moving

- **Problem**: When a person was in `in_fall_candidate` and tumbled/moved on the floor (`speed > max_motion_speed`), `IncidentEngine` overwrote both `lying_start_time = ts` and `onset_time = ts`. This shifted the evidence pre10/post20s video anchor away from the true start of the fall, cutting off the actual falling phase in evidence clips.
- **TDD Test**: Added `test_fall_candidate_motion_does_not_overwrite_onset_time` in `tests/test_tracking_incident.py`.
  - Red outcome: Failed with `AssertionError: 1.0 != 0.5 within 0.05 delta (0.5 difference)`.
- **Implementation**: In `apps/edge/incident.py`:
  - When `speed > self.max_motion_speed`: only update `state.lying_start_time = ts`. Retain the existing `state.onset_time`.
- **Result**: Test passed. All 32 tests pass.

## Step 5: P1-11 - Retain track.history on Lost State

- **Problem**: When a track experienced a single-frame occlusion or missed detection, its state transitioned to `lost`. `pipeline.py` unconditionally cleared `track.history` for all tracks where `state != "active"`. When the track re-associated on the next frame, all historical observations were lost, breaking fall detection logic (vertical velocity, aspect ratio inversion).
- **TDD Test**: Added `test_lost_track_retains_history_until_removed` in `tests/test_pipeline.py`.
  - Red outcome: Failed with `AssertionError: 0 != 5` (history wiped on lost frame).
- **Implementation**: In `apps/edge/pipeline.py`:
  - Changed condition to `if track.state == "removed": track.history.clear()`.
- **Result**: Test passed. All 33 tests pass.

## Step 6: P1-13 - ROI Polygon Filtering & Minimal ODD Evaluation

- **Problem**: Missing ROI (Region of Interest) filtering allowed events to trigger for objects outside the monitored roadway/area (e.g., pedestrians or resting people on sidewalks/benches). Missing ODD (Operational Design Domain) dynamic checks left `quality_state` permanently set to static `"unknown"`.
- **Assumptions & Minimal Design**:
  - `roi_polygon`: Optional parameter (default `None` for backward compatibility). When supplied, object's foot point `((bbox[0] + bbox[2]) / 2.0, bbox[3])` is checked via 2D Ray casting (`point_in_polygon`). Detections outside ROI are pruned in `pipeline.py` before tracking, and `IncidentEngine` additionally performs foot-point ROI check on incoming tracks.
  - Minimal ODD: Implemented `evaluate_odd(rgb)` computing luminance mean and contrast standard deviation. Flags `low_light` (mean < 15.0), `glare` (mean > 240.0), `low_contrast` (std < 5.0), and `normal` otherwise.
  - Contract compatibility: Only dynamic evaluation runs when `quality_state == "unknown"`; pre-configured fixed states (e.g. `"calibrated_fixed"`, `"degraded"`) are preserved. Output remains within the 64-char string constraint of `domain/event_contract.py`.
- **TDD Tests**:
  - `test_incident_engine_roi_polygon_filtering` in `tests/test_tracking_incident.py`.
  - `test_pipeline_roi_polygon_filters_outside_tracks` in `tests/test_pipeline.py`.
  - `test_pipeline_minimal_odd_evaluation` in `tests/test_pipeline.py`.
  - Red outcome: Failed with `TypeError` (unknown kwargs) and `AssertionError: 'unknown' != 'low_light'`.
- **Implementation**:
  - `apps/edge/incident.py`: added `point_in_polygon()`, `roi_polygon` argument to `IncidentEngine.__init__`, and foot-point filter in `process_tracks()`.
  - `apps/edge/pipeline.py`: added `evaluate_odd()`, `roi_polygon` argument to `PerceptionPipeline.__init__`, propagation to `incident_engine`, ODD update on RGB frame, and detection pruning against ROI.
- **Result**: All tests pass.

## Final Verification Summary

- Test command:
  ```bash
  PYTHONPATH=. .venv-oracle/bin/pytest tests/test_tracking_incident.py tests/test_pipeline.py -q
  ```
- Result: **36 passed in 0.70s** (100% pass rate).
- File changes breakdown:
  - `apps/edge/incident.py:12-30`: added `point_in_polygon` Ray casting helper.
  - `apps/edge/incident.py:39`: added `moving_frames` to `_TrackIncidentState`.
  - `apps/edge/incident.py:60, 74`: added `roi_polygon` parameter and attribute.
  - `apps/edge/incident.py:122`: filtered `observed_ids` strictly for `label == "person"`.
  - `apps/edge/incident.py:132-138`: added non-person label guard and foot-point ROI filter.
  - `apps/edge/incident.py:158, 181, 184`: reset `moving_frames` on recovery or non-lying.
  - `apps/edge/incident.py:202`: removed `state.onset_time = ts` during fast tumbling motion in fall candidate (P1-10).
  - `apps/edge/incident.py:225-231`: enforced stationary speed for persistent lying (P0-02).
  - `apps/edge/pipeline.py:17, 32-46`: imported `point_in_polygon` and added `evaluate_odd()`.
  - `apps/edge/pipeline.py:70, 92-94`: added `roi_polygon` parameter and configured quality state tracking.
  - `apps/edge/pipeline.py:131-134`: passed `roi_polygon` to `incident_engine`.
  - `apps/edge/pipeline.py:182-184`: enforced strictly monotonic timestamp (`ts = self._last_timestamp + 1e-6`) when `fid > _last_frame_id` (P1-09).
  - `apps/edge/pipeline.py:204-219`: added dynamic ODD evaluation and detection ROI filtering.
  - `apps/edge/pipeline.py:227`: changed `track.history.clear()` condition from `track.state != "active"` to `track.state == "removed"` (P1-11).





