# AI Tracker & Fall Detection IncidentEngine Log — 2026-10-13

## 1. Overview
- Implemented `ByteTracker` and `Track` in `apps/edge/tracker.py`.
- Implemented `IncidentEngine` in `apps/edge/incident.py`.
- Implemented unit and behavioral tests in `tests/test_tracking_incident.py`.

## 2. Key Decisions & Technical Implementation
- **ByteTracker (`apps/edge/tracker.py`)**:
  - IoU-based multi-stage matching following ByteTrack principles:
    - Stage 1: High-score detections ($score \ge 0.5$) matched with active tracks.
    - Stage 2: Low-score detections ($0.1 \le score < 0.5$) matched with remaining active tracks to recover tracks during occlusion.
    - Stage 3: High-score remaining detections matched with lost tracks for re-identification before spawning new tracks.
  - Track lifecycle: `active`, `lost`, `removed` based on `max_lost_time` aging.
  - Track kinematics: maintains history of `[timestamp, bbox, cx, cy, aspect_ratio, score]`, calculates sliding window vertical velocity ($v_y = \Delta cy / \Delta t$) and aspect ratio change ($\Delta w/h$).
- **IncidentEngine (`apps/edge/incident.py`)**:
  - Fall onset detection: requires prior standing state ($w/h < 0.85$), downward drop velocity ($v_y \ge 15.0$ px/s), or sudden aspect ratio inversion to horizontal ($w/h \ge 1.2$).
  - Persistent lying verification: tracks horizontal state with low motion ($speed \le 50.0$ px/s) for $> 3.0$ seconds after onset.
  - False positive rejection:
    - Normal walking ($w/h \approx 0.4$) produces no alerts.
    - Sitting down ($w/h \approx 0.68 < 0.85$) produces no alerts.
    - Bending down ($w/h \ge 1.2$ for $< 1.2$s then recovering to standing) cancels candidate without alert.
    - Early recovery (standing back up $< 3.0$s after fall) cancels candidate without alert.
    - Already lying objects without prior standing do not trigger onset.
  - Cooldown: 30-second debounce per `track_id` suppresses duplicate alerts.
  - Structured output schema:
    ```python
    {
        "taxonomy": "person_fall",
        "severity": "critical",
        "anchor_kind": "onset",
        "anchor_time": float,
        "detection_time": float,
        "track_id": int | str,
        "confidence": float,
        "detections": list[dict],
    }
    ```

## 3. Test Evidence & Verification
- **TDD RED state**: `tests/test_tracking_incident.py` failed with `ModuleNotFoundError: No module named 'apps.edge.tracker'` before implementation.
- **TDD GREEN state**: 14 tests passing in `tests/test_tracking_incident.py`.
- **Mypy type check**: Clean type checks with 0 errors (`.venv-oracle/bin/mypy --follow-imports=silent apps/edge/tracker.py apps/edge/incident.py tests/test_tracking_incident.py`).
- **Regression check**: Full repository test suite passed (223 tests, 0 failures, 0 errors).
