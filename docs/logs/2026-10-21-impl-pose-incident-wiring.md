# Impl: pose outcomes → incident evidence wiring

Date: 2026-10-21
Scope: `apps/edge/incident.py`, `apps/edge/pipeline.py`

## Decisions

- `IncidentEngine.process_tracks(tracks, timestamp, pose_outcomes=None)` stays fully
  backward compatible: outcome ingestion is skipped when the argument is absent/empty.
- Outcomes are accepted both as `PoseOutcome` dataclasses (via `to_dict()`) and as plain
  dicts, normalized by `_normalize_pose_outcome`; outcomes without a `track_id` are ignored.
- `_TrackIncidentState` gained `last_valid_pose` (ok outcomes only: keypoints + branch,
  executed_at, request_id, frame_id) and `last_pose_outcome` (latest terminal outcome:
  status/reason/branch/executed_at).
- `skipped` / `failed` / `cancelled` never set keypoints and are never read as a negative
  observation; the previous valid pose is left untouched.
- Incidents now carry `pose_evidence` with `status` (`none` when no request was seen),
  `reason`, `branch`, `keypoints` (only populated for `ok`), `executed_at`.
- Anchor logic is untouched: `onset` for `person_fall`, `first_qualifying_observation` for
  `person_lying_persistent`.
- Gap/clock-jump resets, per-track pruning, `observation_gap()` and `reset()` rebuild the
  state object, so pose evidence never survives a gap.
- Pipeline only forwards `pose_outcomes=` when outcomes exist, keeping legacy/simple
  incident engines with `process_tracks(tracks, timestamp)` working (tests rely on this).
- `_handle_incident` copies `self.model_lineage` per event (`_event_model_lineage`) and
  appends `{"role": "pose_estimator", "version": manifest["model_id"] or "rtmpose-tiny"}`
  once when a pose estimator with a manifest is loaded. The engine-level list is not mutated.
- `payload.pose_evidence` is attached only when the incident provides it, then validated by
  `validate_event` (payload limits: 64 KiB, finite JSON only).

## Verification

- `.venv-oracle/bin/python -m pytest tests/test_tracking_incident.py tests/test_pose.py tests/test_event_delivery.py -q`
  → 76 passed, 3 subtests passed.
- `.venv-oracle/bin/python -m pytest tests -q` → 445 passed, 112 subtests passed.
- Ad-hoc scenario checks: ok / skipped / absent outcomes, gap + reset clearing,
  payload `pose_evidence`, `pose_estimator` lineage entry, lineage isolation.
