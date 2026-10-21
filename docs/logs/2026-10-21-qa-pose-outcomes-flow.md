# QA: pose outcomes → person-down flow (ticket #53)

Date: 2026-10-21
Scope: `tests/test_pose_outcomes_flow.py` (new integration coverage for
`.scratch/system-build-slices/issues/53-pose-outcomes-di-vao-person-down-flow.md`).
Implementation under test: `apps/edge/incident.py`, `apps/edge/pipeline.py` (unmodified here).

## Decisions

- Every case drives the real consumer through `PerceptionPipeline.process_frame` →
  `IncidentEngine.process_tracks(pose_outcomes=...)` → `_handle_incident` → outbox.
  Scheduler counters are only used as a cross-check, never as the proof of delivery.
- Fixtures are deterministic software-lab fixtures (fixed frame ids, event-time timestamps,
  fixed bboxes): standing → lying → 10 px/frame downward slide. No weights are downloaded;
  the success case uses the pinned `models/rtmpose-tiny` artifact, the other cases use a
  17-COCO-keypoint mock estimator (or the same artifact with `batch_budget=0`).
- `_StubDetector` supplies provenance only; detections are always passed explicitly so the
  detector never runs and lineage stays reproducible (`round`-free, no inference timing).
- Signals the state reset in the gap/clock-jump case are behavioural, not only white-box:
  the post-gap/post-jump alert is `person_lying_persistent` (no onset), while the pre-gap
  state had `had_standing=True` and a fall candidate.
- Mongo-backed E2E uses `tests.test_server_evidence.server_env` and a per-run database name,
  drops the database before closing the store (cleanup LIFO), mirroring `tests/test_review_api.py`.

## Coverage map (acceptance criteria → assertions)

| Case | Proof |
| --- | --- |
| success | incident `pose_evidence.status=ok`, `branch=fast_fall`, 17 named COCO keypoints, anchor < detection_time; outbox event payload identical; `model_lineage` has `detector` + `pose_estimator`; `validate_event` round-trips and hash matches; metrics attempted == scheduled |
| failed / skipped | `inference_failed` and `deadline_exceeded` reach the incident as `status`/`reason` with `keypoints=[]`; alert (`person_fall`) is still emitted; estimator never called in the deadline case (`calls == 0`); metric counters match the observed outcomes |
| gap / clock jump | pre-gap `last_valid_pose` 17 keypoints; after the gap `last_valid_pose is None`, outcome is the post-gap failure, alert taxonomy switches to `person_lying_persistent`, evidence keypoints `[]`; clock-jump regression (10.0 → 5.0) rebuilds state and never reuses the pre-jump outcome (`executed_at < 10.0`) |
| overload / recovery | `queue_full` skips on both lying tracks, recorded in `observation.pose_outcomes` (`pose_status=skipped`, `pose_reason=queue_full`), on both incidents (`status=skipped`, `keypoints=[]`), and in branch + overall metrics; capability `degraded/queue_near_capacity` → drain → `full/None`; a post-recovery frame returns `ok` with 17 keypoints |
| E2E outbox → server → review → export | outbox event ingested by `/v1/events` (200, `event_hash` matches outbox), `mark_delivered` empties pending, `/v1/events` returns the event byte-identical (pose evidence intact, both lineage roles), review `confirm` returns version 1, `export_dataset_records` and `/v1/dataset/export?format=json&decision=confirmed` keep `model_lineage` (`detector` + `pose_estimator`) and `original_ai_payload.pose_evidence` |

## Verification

- `.venv-oracle/bin/python -m pytest tests/test_pose_outcomes_flow.py` → **5 passed** (twice, back-to-back).
- `.venv-oracle/bin/python -m pytest tests/test_pose_outcomes_flow.py tests/test_rtsp_pipeline.py -q` → 17 passed.
- Full suite at the time of writing: `pytest tests` → `1 failed, 449 passed` and a baseline
  run *without* this file → `6 failed, 439 passed`, with the same Mongo/uvicorn-backed tests
  (`test_crash_recovery`, `test_dataset_lineage`, `test_rtsp_pipeline::TestEndToEndDelivery`)
  failing only under full-suite load; each of them passes when rerun in isolation
  (`9 passed`). Treated as pre-existing environment flakiness, not a regression from this file.

## Limits

These are synthetic integration fixtures: they prove wiring, ordering, reset semantics and
persistence, not held-out accuracy, ODD coverage, recall/FP/latency, capacity, or any
production/field acceptance. Video/pose real-workload and unknown-case comparison remain
separate per the ticket's release boundary.
