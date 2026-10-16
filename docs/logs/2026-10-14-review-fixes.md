# Review finding fixes

## Confirmed decisions

User requested all findings fixed and explicitly confirmed:
- Build on current dirty working tree; preserve existing edits and unrelated files.
- State reserve exhaustion must reject before enqueue, leaving no event/outbox/evidence-intent commit or ACK.
- Recorder-owned atomic, fail-closed cleanup; protect unknown/active scratch.
- Wire quota and health lifecycle into runtime, add regressions, do not commit.

## Plan and task book

1. task-3 / cleanup-fix: quota + recorder cleanup and quota/recorder regression tests. Owns tests/test_quota.py, including changed pre-enqueue expectation.
2. task-4 / admission-fix: EvidenceLifecycle admission and dedicated evidence regressions. Coordinate ENOSPC API with cleanup/runtime teammates.
3. task-5 / runtime-fix: pipeline quota injection/default integration, monitor startup lifecycle and runtime/health tests.
4. Lead: review combined changes against all findings, independently run tests/checks, request repairs if needed, record results and hand off.

Implementation tasks dispatched concurrently with disjoint file ownership. Teammates inherit configured routes; no explicit teammate model override supported. All must use current files, never reset existing edits, and report real commands/results.

## Inspection

- CodeGraph context queried for quota, recorder ownership, reserve admission and health startup with explicit project path; returned local outbox/recorder entry points.
- Git status/diff reviewed: pre-existing edits in evidence.py, health.py, live_pipeline.py, quota.py and earlier implementation log; untracked review log and other local files. Existing improvements do not yet supply pre-enqueue admission or runtime quota wiring.

## Verification

- cleanup-fix completed recorder-owned atomic cleanup and deterministic ownership/scratch/concurrency regressions; 57 quota+recorder tests passed.
- admission-fix completed reserve-only pre-enqueue ENOSPC guard, then added direct outbox-volume reserve check (no metric aggregation). Six focused admission tests and 77 storage/event delivery regressions passed. Existing reconciliation edits retained.
- runtime-fix added default/injected quota wiring and health startup/stall/stop/restart lifecycle. Verification still in progress.
- Independent reviewer found no blocker in cleanup/admission/initial runtime patch; 51 focused tests passed on `.venv-oracle/bin/python`.
- Lead combined run caught failed-analytics health regression while runtime red-green work was ongoing (131 tests, 1 failure); implementer corrected analytics failure reporting.
- Subsequent lead run (133 tests) caught newly added recorder-start rollback regression (runner reported running after start error); returned to runtime implementer and awaiting final ready signal before acceptance.
- Final READY runtime self-check: 32 pytest tests passed; independent reviewer confirmed latest startup rollback and runtime tests (32 passed).
- Lead final combined command: `.venv-oracle/bin/python -m unittest tests.test_evidence_lifecycle tests.test_quota tests.test_recorder tests.test_pipeline tests.test_live_pipeline tests.test_health tests.test_pose tests.test_event_delivery -q`: **133 tests, 36.852s, OK, exit 0**. Expected warning logs from injected ownership error and RTSP fallback tests.
- Lead mypy initially found missing `scratch` list annotation in recorder cleanup. Returned scoped repair to cleanup-fix; it added `scratch: list[Path]`. Lead reran `.venv-oracle/bin/python -m mypy --follow-imports=silent apps/edge/evidence.py apps/edge/recorder.py apps/edge/quota.py apps/edge/health.py apps/edge/live_pipeline.py apps/edge/pipeline.py`: **Success: no issues found in 6 source files**.
- Post-annotation lead focused cleanup+quota tests: **15 tests, 0.534s, OK**. `git diff --check`: clean.
- All reported findings addressed; overlap retained in original review but resolved by shared atomic cleanup fix. Existing dirty edits preserved. No commits, full repository suite, hardware or actual disk-full fault acceptance claimed.

## Final behavior and limits

- Quota cleanup delegates to recorder under pin/finalization write lock and preserves unknown scratch, producer parts, active pins and watermark-protected segments; ownership or metadata inspection failures do not authorize deletion.
- Event admission rejects with ENOSPC before enqueue if state reserve is exhausted, including events without evidence and separate outbox directory reserve check.
- Pipeline default/injected quota connects evidence and health; runtime transitions startup/readiness/received/stalled/stopped/restarted truthfully and reports analytics failure as degraded.
- Disk capacity snapshots remain advisory rather than storage reservations; quota health capacity metrics still represent configured storage volume, not aggregate volumes. Unknown scratch is intentionally retained. Cleanup without authoritative recorder is a no-op.
