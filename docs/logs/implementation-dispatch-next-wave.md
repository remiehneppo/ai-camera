# Dispatch: next feasible software-lab wave

## Confirmed decisions

- User selected the next feasible wave in `.scratch/system-build-slices`, not the module-parent tracker.
- User explicitly confirmed scope: software gaps in #06/#07, ONNX CPU/x86 + file replay; advance #03/#08 only when actual dependency evidence allows it.
- Preserve hardware/RTSP/RKNN and field acceptance gates. Unit fixtures do not close runtime/target gates.
- Current branch: `master`. Pre-existing untracked `.codegraph/` and `AGENTS.md` are excluded from this work's commit.

## Actions and task book

1. Read issue-tracker and triage guidance; CodeGraph Markdown file query returned no matches, so used local tracker discovery.
2. Read slice PRD and tickets #03/#06/#07. #06/#07 are partial; #03 blocked; #08 remains blocked by #07.
3. Loaded TDD guidance. New test seams require user confirmation before tests are written.
4. Created shared tasks `task-1` and `task-2`; dispatched read-only investigations in parallel to `replay-analytics` and `pin-budget`.
   - task-1: actual analytics/replay gaps, minimal feasible software slice, proposed public seams and ownership.
   - task-2: actual pin/ring-budget gaps, runtime proof versus target gates, proposed public seams and ownership.
5. No source edits delegated yet. Await evidence to establish non-overlapping implementation scopes.
6. Read prior follow-up log: metadata replay harness and actual raw-pruning delayed-pin tests already exist; do not duplicate them. No maximum verification/handoff/recovery budget was approved. Instructed both investigators to use explicit CodeGraph projectPath (default index can be unrelated) and read domain guidance.
7. Loaded karpathy-guidelines: require surgical changes and no speculative runtime/framework. Initial task-1 candidate is a detector-stage software integration report, not domain parity or realtime-stress acceptance; exact seams pending.

## Investigation evidence and approved implementation

- task-1: existing 26 recorder/replay tests passed; ORT1.20.1 CPU, NumPy1.26.4 and lab model/photo available. `run_oracle` decodes/inferences but has no observation-consumer/recorder composition. No track/pose/domain event consumer exists, so domain parity remains open. Existing oracle scoped mypy check passed.
- task-2: nominal ring600/pre10/post20 exists, but approved maximum verification/handoff/recovery/margins absent. Actual delayed pruning tests already exist. `recorder.py:213-214` changes no-artifact completeness to unknown, potentially losing known missing coverage; lead read this source directly.
- User Q3 explicitly approved A+B and public test seams: synchronous run_oracle observation callback + detector-recorder lab/CLI; pin-budget lab/CLI through FileRecorder/EventOutbox, including minimal preserve-missing fix if reproduced by public API test.
- task-3 assigned to replay-analytics: oracle_replay.py, new oracle_recorder_lab.py and corresponding tests; no recorder/outbox changes.
- task-4 assigned to pin-budget: new pin_budget_lab.py/test, surgical recorder.py missing-coverage fix and recorder regression if needed; no oracle changes.
- Both implementation briefs require vertical TDD, focused tests/scoped mypy, real lab CLI evidence, explicit limitations, no full suite or commit by executors. Lead owns docs/tracker and final verification.
- Both reports are software diagnostics, NOT domain parity, concurrent ingest isolation, realtime stress, signed sizing proof or hardware acceptance. #06/#07 stay partial and #08 blocked unless actual gates are satisfied.

## Review baseline

- Loaded code-review skill. User Q4 approved baseline `162a8500684aa47f2a806b8112aa947447899d50` (HEAD before this wave).
- Changes are uncommitted: review uses `git diff 162a850 -- <owned tracked paths>` plus explicit new task files, not an empty three-dot HEAD diff. Existing untracked `.codegraph/` and `AGENTS.md` excluded.
- Standards and approved narrowed ticket spec will be reviewed independently in parallel after executors finish.

## Independent verification and review

- Lead read new modules/tests and tracked callback/recorder diff. Full suite using `.venv-oracle/bin/python`: 94/94 pass in24.124s. Scoped mypy on oracle_replay/oracle_recorder_lab/pin_budget_lab: no issues3files; diff whitespace check passed.
- Lead independently executed positive detector-recorder CLI: statusok, paritytrue, each mode3 observations ×13detections, raw complete. Independently ran expired ring CLI: pending requested, retained/request missing, build failed and no artifact.
- Standards review: one hard issue (artifact completeness `missing` conflicts with contracts §4), one possible duplicated-config smell. Spec review: 0 findings for initial narrowed approval, 51 focused tests pass with optional runtime. Standards reviewer used python3:31tests pass with4 optional skips, not real-ORT acceptance.
- User Q5 explicitly chose retain existing artifact contract and separate request coverage from artifact completeness. This supersedes Q3's proposed preserve-missing manifest change: no-artifact receipt must remain failed/unknown; retained request coverage may report missing. No schema extension.
- Rework #1 sent to pin-budget: restore recorder/test baseline, adjust new report/test to distinguish dimensions, remove trivial duplicate config construction; focused checks and re-review required.

## Rework acceptance

- pin-budget rework#1 restored recorder.py and test_recorder.py to baseline (lead verified no diff). New regression now expects request coverage missing and no-artifact receipt failed/unknown; no schema change.
- Lead independently reran impacted budget/recorder/event-delivery suites:31/31 pass in14.768s. Real final CLI reports request_coverage=missing, build_state=failed, artifact_completeness=unknown, artifact=None.
- Config duplication removed; explicit two-dimension report limitation added. Both reviewers re-requested to verify correction.

## Final review verdict and handoff

- Standards re-review PASS: 0 hard breaches / 0 prior smells remaining. Reviewer verified recorder/test baseline diff empty and separate dimensions;17 focused tests pass, no skips.
- Spec Q5 re-review PASS:0 findings;4 focused budget tests pass. Earlier A review remains valid. No source schema/outbox/framework changes.
- Lead final full suite after rework:94/94 pass in24.079s using optional oracle runtime; synthetic numerical ORT fixture emits a shape-merge warning, suite succeeds. This is software test evidence, not target quality acceptance.
- Final deliverables: synchronous observation callback, detector–recorder diagnostic CLI, caller-scenario pin-budget CLI, public-interface regressions, README usage, source ticket evidence and dispatch log.
- #06/#07 intentionally remain partial; #03/#08 not opened. Remaining gates: actual domain consumer/parity, concurrent recorder/runtime isolation, realtime workload, signed maximum budgets, RTSP/target/storage/hardware and production rights/clearance.
- Commit plan: reviewed owned files/docs only on master, conventional message `feat(edge): add replay and pin-budget lab reports`, refs #06/#07 (not Closes); no push. Baseline recorder implementation remains untouched.

## Acceptance and delivery plan

- Confirm proposed public test seams with user.
- Delegate implementation; each executor supplies red/green test evidence and focused checks.
- Lead reviews key diffs and independently verifies acceptance; run full suite once at completion and load code-review skill.
- Update ticket evidence without overstating completion; record remaining blockers.
- Commit only reviewed changes on current branch; no push requested.
