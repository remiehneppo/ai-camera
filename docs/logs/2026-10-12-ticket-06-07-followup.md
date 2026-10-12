# Tickets 06/07 software-lab follow-up — 2026-10-12

## Actions and decisions

- User requested implementation of the next ticket. Read local tracker rules, PRD, tickets 06/07/08 and prior ticket-07 log; inspected git status and recent commits.
- Ticket 08 is blocked by 07; 06/07 remain partial. Do not bypass tracker dependency gates or infer target acceptance from unit fixtures.
- User selected completing missing work in 06/07 before 08, selected existing software lab/file replay, and explicitly confirmed shared understanding. Hardware/RTSP gates remain open.
- Complexity L2: cross-cutting replay acceptance and ring-budget proof. Collaboration mode teammate.
- Read-only parallel investigations: replay-investigation (task-1) identifies actual replay/analytics acceptance seams; budget-investigation (task-2) identifies existing ring-budget decisions and missing parameters. No implementation delegated yet.
- Loaded karpathy-guidelines and tdd. TDD seams must be confirmed before writing tests. Await investigation evidence to propose workload/budget and seams to user.
- Current branch master; pre-existing untracked .codegraph/ and AGENTS.md are excluded from this work.
- Initial CodeGraph query without projectPath returned unrelated storage symbols; reran with absolute repository projectPath, which reports 19 indexed files and FileRecorder APIs. Subsequent queries must use explicit projectPath.
- No source edits or tests executed by lead during initial investigation. No pyproject.toml at repository root; determine validation commands from actual repository configuration rather than assume a typechecker.

## Confirmed implementation scope

- Investigation task-1 ran existing recorder suite: 11/11 pass. ReplayFrame has timing metadata only; realtime is paced synchronous replay, not a bounded drop/deadline scheduler. No analytics consumer exists to prove domain parity.
- Investigation task-2 found approved nominal ring600/pre10/post20, but no maximum verification/handoff/recovery or signed margins. Pins/watermark can retain data beyond nominal ring duration; no production sizing proof claimed.
- User explicitly approved harness/report + delayed-pin regression and both public TDD seams: FileRecorder.replay/actual_range; FileRecorder.record_file/advance_watermark/pin + EventOutbox.reconcile_evidence.
- Plan/delegation: task-3 replay-investigation owns new replay_lab.py/test_replay_lab.py; task-4 budget-investigation owns recorder regression tests and only evidence-required recorder/outbox fixes. Independent work runs in parallel. Lead owns documentation/tracker, review, full validation and final commit.
- No real analytics pipeline, RTSP/hardware acceptance, approved maximum budget or opening #08 in this slice. #06/#07 stay partial.

## Implementation and verification

- Task-3 added public `run_lab` and CLI in `apps/edge/replay_lab.py`; normalized metadata traces compare fast/realtime/slow callbacks. Report labels callback progress honestly, measures lag relative to first callback, queries pre-recorded raw coverage, and lists limitations. Four vertical TDD slices red→green: module creation, finite parameter validation, CLI error boundary, single-frame range error. New suite 4/4 pass.
- Task-4 added two real-FFmpeg delayed-pin regressions in `tests/test_recorder.py`. Watermark advances before late pin; raw segments are actually pruned. Lab retention2 proves within range complete and expired pre-roll partial. Retention32/12 with onset22 preserve requested[12,42], report actual[11,42.9]/[29,42.9], complete/partial; independent clip survives raw cleanup. Initial failures were incorrect fixture/boundary expectations, not production bugs; no recorder/outbox fix required. Recorder suite 13/13 pass.
- Lead independently ran `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`: 43/43 pass in 13.787s. `python3 -m compileall -q apps domain tests` and `git diff --check`: pass. Neither mypy nor pyright installed; no static typecheck claimed.
- Fixture versions reported: Python3.12.3, FFmpeg6.1.1-3ubuntu5, MPEG4 64x64/10fps with PTS offset3; small harness fixture0.6s, retention worker fixture40s. Harness trace times3/3.2/3.4, raw coverage complete[3,3.5], 3 frames/run. Example slow callback0.25s: elapsed0.783s, lag0.351s (observed values, not an SLO).
- README documents CLI and limits. Ticket06 stale pin/recovery wording corrected without closing RTSP checkbox; both ticket comments link evidence and preserve partial/#08blocked.
- Lead independently ran the CLI with generated0.6s offset3 fixture: parity true, 3 frames each, raw complete[3,3.5] unchanged in every run; fast/realtime/slow elapsed0.032/0.432/0.783s; slow callback completion lag0.351s.
- Review standards: PASS, 0 hard-standard/heuristic findings; reviewer independently ran new suite4/4 pass. Review spec: PASS, 0 findings against user-approved narrowed scope; reviewer independently ran recorder+lab17/17 pass. Reviewed actual pruning before late pin, immutable requested intervals, independent clip survival, and explicit limitations/gates. No RTSP/hardware or production sizing acceptance inferred.
- User approved code-review base dcce99e. Since changes are uncommitted, review uses working-tree diff plus explicitly listed new files (not an empty three-dot diff). Explicit-route parallel subagent review timed out at120s with no report; no background jobs remain. Re-dispatched the two read-only review axes as durable teammates standards-review/spec-review; no implementation takeover.
