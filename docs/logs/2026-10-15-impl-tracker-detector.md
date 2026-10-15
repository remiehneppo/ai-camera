# Implementation Log: Tracker & Oracle Detector Enhancements (P1-12, P2-09, P2-10)

Date: 2026-10-15
Author: Subagent (Tracker & Oracle Detector)
Scope: Fixes for P1-12, P2-09, P2-10 in `apps/edge/tracker.py`, `apps/edge/oracle_detector.py`, `tests/test_oracle_detector.py`, and `tests/test_tracker_lifecycle.py`.

---

## 1. Context & Architecture Requirements

Based on:
- `docs/logs/2026-10-15-full-flow-code-review.md` (P1-12, P2-09, P2-10)
- `docs/architecture/contracts.md` (§7 Track lifecycle: tentative/confirmed/lost/ended)
- `docs/architecture/system-architecture.md` (Track lifecycle tentative/confirmed/lost/ended; measured vs predicted point)
- File boundary constraints: Only edit `apps/edge/tracker.py`, `apps/edge/oracle_detector.py`, `tests/test_oracle_detector.py`, and create `tests/test_tracker_lifecycle.py`. Do NOT touch `tests/test_tracking_incident.py` directly to prevent merge conflicts with concurrent subagents.

---

## 2. Codegraph MCP Code Exploration

We utilized the `codegraph` MCP tool (`codegraph_status`, `codegraph_context`, `codegraph_explore`) over project path `/home/tieubaoca/AI/AI-Camera-OC`:
- **OracleDetector** (`apps/edge/oracle_detector.py:147`):
  - Preprocessing: `scale = min(model_height / height, model_width / width)`, resized with `int(width * scale)` and `int(height * scale)`.
  - Coordinate unscaling: `boxes / scale` divided both X and Y by the single scalar `scale`.
  - NMS postprocessing: `intersection = ... + 1`, `area = ... + 1`, using discrete pixel offset conventions on continuous float coordinates.
- **ByteTracker** (`apps/edge/tracker.py:146`):
  - Track initialization: `self.state = "active"` immediately created confirmed active tracks on the very first frame.
  - Association: Only static `bbox_iou(t.bbox, d["bbox"])` without motion extrapolation. At 3 FPS, fast-moving objects (speed > 100 px/s) experience IoU < 0.2, causing track loss and ID fragmentation.

---

## 3. Implementation Details

### Step 1: P2-09 — Removal of `+ 1` Offset in Real-Coordinate NMS (`apps/edge/oracle_detector.py:131-137`)
- **Problem**: Discrete grid pixel offset `+ 1` was carried over from Pascal VOC discrete coordinate conventions into continuous floating-point bounding boxes. For small bounding boxes (e.g. 2x2 or 4x4), adding 1 adds 25%-50% artificial area and heavily distorts IoU.
- **Fix**:
  - `intersection = np.maximum(0, np.minimum(boxes[index, 2:], boxes[rest, 2:]) - np.maximum(boxes[index, :2], boxes[rest, :2]))`
  - `intersection = intersection[:, 0] * intersection[:, 1]`
  - `area = np.prod(np.maximum(0, boxes[index, 2:] - boxes[index, :2]))`
  - `areas = np.prod(np.maximum(0, boxes[rest, 2:] - boxes[rest, :2]), axis=1)`
  - `union = area + areas - intersection`
  - `iou = np.where(union > 0, intersection / union, 0.0)`
  - `order = rest[iou <= config["nms_threshold"]]`
- **Tests**: Updated `test_nms_uses_continuous_coordinates_without_plus_one_pixel_offset_and_per_class` in `tests/test_oracle_detector.py`:
  - Verified boxes with continuous IoU = 0.333 <= 0.45 are retained (where previously `+ 1` yielded 0.50 and wrongly suppressed the box).
  - Verified boxes with continuous IoU = 0.60 > 0.45 are properly suppressed.

### Step 2: P2-10 — Independent `scale_x` and `scale_y` for Letterbox Unscaling (`apps/edge/oracle_detector.py:87-88, 116-117`)
- **Problem**: Resizing images with `(int(width * scale), int(height * scale))` truncates floating-point dimensions. Unscaling predictions with the scalar `scale` assumed exact isotropic scaling, introducing sub-pixel drift (up to 3.5 px on 852x1515 images).
- **Fix**:
  - Derived independent scale factors from the actual resized image dimensions:
    ```python
    scale_x = resized.shape[1] / width
    scale_y = resized.shape[0] / height
    scales = np.array([scale_x, scale_y, scale_x, scale_y], dtype=np.float32)
    boxes = np.concatenate((predictions[:, :2] - predictions[:, 2:4] / 2,
                            predictions[:, :2] + predictions[:, 2:4] / 2), axis=1) / scales
    ```
- **Tests**: Added `test_letterbox_subpixel_drift_rescaling_uses_independent_scale_x_and_scale_y` in `tests/test_oracle_detector.py`. Verified boundary detection at `x=233` maps to `852.0` (image edge) rather than `848.54` (3.46 px drift).

### Step 3: P1-12 — Tentative State and Constant Velocity Prediction (`apps/edge/tracker.py`)
- **Requirements**:
  1. New tracks start in `"tentative"` state; require >= 2 consecutive matched frames to transition to `"active"`.
  2. Tentative tracks not matched on the next frame are removed immediately (`mark_removed()`, not marked `lost`).
  3. Constant velocity motion prediction: predicts bounding box at frame timestamp `ts` to maintain IoU >= 0.2 at 3 FPS.
  4. Zero new library dependencies (pure Python / NumPy).
  5. Preserve public signature of `ByteTracker`:
     `ByteTracker(high_threshold=0.5, low_threshold=0.1, match_threshold=0.2, match_threshold_low=0.1, max_lost_time=2.0, activate_after=2)`.
  6. Track states conform to `{"tentative", "active", "lost", "removed"}`.
- **Implementation**:
  - Added `Track.predict_bbox(self, timestamp: float) -> list[float]`:
    - If `len(self.history) < 2` or `dt <= 0`, returns current `bbox`.
    - Otherwise calculates instantaneous velocity `vx = (latest.cx - prev.cx) / dt_obs`, `vy = (latest.cy - prev.cy) / dt_obs`.
    - Projects `pred_cx = latest.cx + vx * dt`, `pred_cy = latest.cy + vy * dt`, keeping dimensions `w` and `h`.
  - Added `consecutive_hits: int = 1` and `state: str = "active"` (optional parameter, default "active" for direct instantiation backwards compatibility).
  - Updated `Track.update`: increments `consecutive_hits`, transitions `tentative -> active` when `consecutive_hits >= 2`.
  - Updated `ByteTracker.update`:
    - Stage 1a: Active tracks matched with high-score detections using motion-predicted IoU.
    - Stage 1b: Tentative tracks matched with remaining high-score detections. If matched and `consecutive_hits >= activate_after`, promote to `active`. Unmatched tentative tracks are immediately marked `removed`.
    - Stage 2: Remaining active tracks matched with low-score detections using motion-predicted IoU.
    - Stage 3: Lost tracks matched with remaining high detections using motion-predicted IoU, re-activating to `active`.
    - Unmatched high detections initialize new tracks with `state = "tentative"`.
- **Tests**: Created `tests/test_tracker_lifecycle.py` with 6 dedicated test cases:
  1. `test_new_track_starts_as_tentative_and_activates_on_second_hit`
  2. `test_unmatched_tentative_track_is_removed_immediately`
  3. `test_fast_moving_object_at_3fps_matched_via_constant_velocity`
  4. `test_lost_track_recovery_with_motion_prediction`
  5. `test_predict_bbox_unit_geometry`
  6. `test_track_states_conform_to_allowed_set`

---

## 4. Oracle Parity & Conformance Analysis

### Parity with `tests/test_oracle_conformance.py` & Golden Fixtures
When running `tests/test_oracle_conformance.py`:
- 6 tests PASSED.
- 2 tests failed with `ValueError: bbox_xyxy mismatch`:
  1. `test_real_detector_matches_versioned_independent_reference` (on `shibuya_lower_center`, shape 1515x852).
  2. `test_fast_and_paced_replay_match_independent_decoded_pixel_reference` (on 426x320 fixture).
- **Root Cause Analysis**:
  - In `fixtures/oracle/golden-v1.json` and `tools/oracle_conformance.py:reference_postprocess`, the golden reference was recorded with the uncorrected isotropic scale: `boxes /= min(416 / height, 416 / width)`.
  - For `shibuya_lower_center` (852x1515):
    - `scale = 416 / 1515 = 0.274587...`
    - `int(852 * scale) = int(233.9485...) = 233`
    - `scale_x = 233 / 852 = 0.273474...`
    - Correct unscaling by `scale_x` shifts the horizontal coordinates by ~1.176 pixels (e.g. from `288.83` to `290.01`).
    - Because `tools/oracle_conformance.py` enforces `bbox_xyxy` tolerance of `1e-3` (0.001 px), this intentional sub-pixel drift correction exceeds the strict tolerance.
  - Per prompt instructions: `"nếu fixture parity đổi kết quả, báo rõ chênh lệch trong log thay vì sửa fixture bừa."`
    We do NOT modify `fixtures/oracle/golden-v1.json` or `tools/oracle_conformance.py`, preserving artifact provenance while clearly logging the exact discrepancy.

---

## 5. Notes for Parent Coordinator / Integration

1. **Track Lifecycle `tentative` State**:
   - `Track.state` now includes `"tentative"` alongside `"active"`, `"lost"`, and `"removed"`.
   - `ByteTracker.update()` returns only `active` tracks (`[t for t in self.tracks if t.state == "active"]`).
   - Consequently, on frame 1 of a new detection, `update()` returns `[]`. On frame 2 (upon second consecutive detection), the track activates and is returned.
   - **Impact on `tests/test_tracking_incident.py`**:
     The unit tests `test_bytetracker_single_object_tracking`, `test_bytetracker_two_stage_low_score_association`, and `test_bytetracker_lost_and_removed_lifecycle` in `test_tracking_incident.py` were written assuming single-frame track activation (`len(tracks) == 1` on frame 1). Similarly, persistent lying tests where an object appears already lying on frame 0 will anchor at `t=0.1` (frame 1) instead of `t=0.0` (frame 0) because frame 0 is tentative.
     Once the other subagent completes their work on `tests/test_tracking_incident.py`, these assertions can be updated to reflect the 2-frame tentative lifecycle.
