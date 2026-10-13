# Runtime isolation and edge doctor dispatch — 2026-10-13

## Inspection and decisions

- User requested decomposition and delegation of next tickets. L2; teammate collaboration available.
- Read local Markdown tracker conventions and triage/domain instructions. CodeGraph .scratch lookup returned no indexed files; read scoped ticket/docs directly. Read-only ticket-scout verified completed/partial work and runtime seams.
- Baseline branch master; pre-existing untracked .codegraph/, .scratch/replay-measurements/, AGENTS.md are not implementation deliverables and must not be staged wholesale.
- Q1: next eligible wave. Q2: residual runtime/isolation #06 followed by narrowed startup/doctor #03, not #51 reimplementation or #07 maximum sizing.
- Q3–Q4: confirmed detector-only real ONNX CPU/x86 + file replay; public TDD seams runtime lifecycle/raw-ring query and config/startup/doctor CLI. No tracker/incident/domain engine. No full ticket closure.
- Q5–Q6: confirmed separate analytics process, bounded backpressure/no automatic drop; lab buffer/stop budgets configurable, not target capacity/RTO claims. Edge-specific doctor; server doctor unchanged. Preflight returns nonzero for invalid enabled config/artifact. Runtime supervisor preserves recorder when analytics fails, reports degraded/failed, returns error after recording finishes or explicit stop. No silent fallback.
- Final understanding explicitly confirmed by user before implementation dispatch.

## Task book

A: edge runtime orchestrator and independent ownership. Own new apps/edge/runtime.py and tests/test_edge_runtime.py; optional minimal oracle_replay.py cancellation seam only if needed. Existing recorder internals, config/doctor, domain/events/server out of scope. Real FFmpeg/ORT tests and controlled analytics worker termination; bounded observations, explicit lifecycle/status/raw queries.

B: edge immutable config/preflight and doctor. Own new apps/edge/config.py, apps/edge/doctor.py, tests/test_edge_config.py, tests/test_edge_doctor.py. Runtime A and server doctor out of scope. Allowlist actual adapters, use existing manifest validation, explicit disabled reason and capability distinctions. Integration depends on A real runtime.

Both: load tdd/karpathy-guidelines; consult CONTEXT/ADR and CodeGraph first; one failing test then minimal implementation per cycle at approved public seams. Do not commit independently. Report owned paths, red/green commands/results, focused tests/typechecks and remaining gaps. Preserve artifact completeness contract and existing unknown/missing distinctions.

## Interface coordination

A must expose small public execution/lifecycle/status interface accepting explicit execution values; no dependency on B config module. B maps validated frozen config to A public arguments and consumes real observed status only after A exists. Agree exact call shape directly before integration. Config fingerprint must exclude secret values. Lab budget defaults must be documented as convenience configuration, not signed/target guarantees.

## Verification plan

Executors self-check; lead reads key diffs and independently runs focused/integration checks and full suite. Load code-review for parallel standards/spec review. Rework findings through owning executor (maximum two rounds). Update source tickets with evidence, not blanket done. Commit reviewed owned changes/docs only on current branch; no push.

## Dispatch evidence

- Review baseline: `0c823c36ad1ca21a175d2180fbddce0db898e019` on master. `.venv-oracle/bin/python` is Python 3.12.3; `data/oracle/yolox_tiny.onnx` exists.
- Shared task-1 delegated to runtime-owner; shared task-2 delegated to edge-config-owner. Distinct owned files; both dispatched before waiting for either implementation.

## First verification obstacle

- runtime-owner reported first red (module missing), then sandbox denied multiprocessing SemLock creation. Lead reproduced exact `.venv-oracle/bin/python -m unittest discover -s tests -p test_edge_runtime.py -v` denial and requested authorized exact wider retry, not workaround.
- Authorized retry ran and found actual test failure: expected at least two segments, observed one (`tests/test_edge_runtime.py:30`). Sent evidence back to owner for first-slice correction; this is in-progress TDD, not final acceptance or review rework. Config owner independent five preflight tests reported green; startup integration waits for runtime.
- Fixture keyframes corrected (`-g 1`, independent ffprobe showed original only first keyframe). Next authorized run exposed completed notification before process exit; owner corrected wait to require reaped child. Lead authorized exact retry: disabled lifecycle 1/1 PASS in 0.253s. Analytics slices remain pending.
- Narrow private FIFO pacing approved after inspection established ingest has no real-time pacing; this is runtime design, not a sandbox workaround. Ownership/cleanup/limits must be documented and tested.
- User confirmed final review fixed point `0c823c3`.

## Incremental integration evidence

- Lead authorized exact runtime tests: startup failure + disabled lifecycle 2/2 pass (0.491s); positive real ONNX transport 3/3 pass (1.094s); bounded analytics stop under backpressure 4/4 pass (2.630s). Each new behavior had observed RED before owner implementation. Real-time progress-after-crash still pending.
- Config/doctor owner delivered scoped task-2. Lead independently ran exact focused suite with authorized permission after PermissionError evidence: 8/8 pass (1.703s), including real FFmpeg/ORT CLI, disabled recorder completion and controlled analytics SIGKILL yielding final nonzero after recorder completion. Owner mypy/compile checks documented. Final review not yet performed.

## Realtime pacing gate and approved scope expansion

- Initial crash-progress test passed unpaced recording; lead rejected it as insensitive. Added independent wall/content timing invariant; observed RED end=5.25 versus expected <5. FIFO `-re` paced input took ~5.8s but downstream default input probing withheld sidecars until EOF; producer flush tuning did not solve it.
- Revised public runtime test kills analytics at ~2s, requires raw progress before wall5s for6s source. Lead observed RED: advanced unexpectedly None; other four tests passed (suite7.850s).
- User Q8 approved minimal optional FileRecorder.ingest probing control + recorder public tests, with defaults unchanged. runtime-owner scope now additionally apps/edge/recorder.py and tests/test_recorder.py. No RTSP/contract/domain scope added. Implementation awaits verified pre-EOF publication; no claim from late burst publication.

## User-approved convergence: fast-only delivery

- Bounded diagnostics: producer bytes arrived at0.03/0.53/1.03s, yet tested minimal input probing controls produced no pre-EOF sidecars; direct buffering attempt failed FFmpeg183. Removed ineffective recorder options; recorder diff empty. No further hypotheses pursued.
- Q9 user chose review/commit verified fast-only scope, rather than leave WIP. Supersedes realtime availability for this new runtime: both runtime and edge config must explicitly reject realtime; remove paced FIFO path, retain existing oracle_replay unaffected. Move unresolved acceptance and diagnostics into follow-up ticket, not skip/claim completion. Public rejection regression replaces unsupported-feature active test.
- Both owners received narrowing instructions; final suites/reviews must run after revised implementation. No proof of realtime ring progression after analytics crash is claimed.

## Final first-pass verification and independent review

- Revised fast-only focused suite lead15/15 PASS4.538s. Scoped mypy3modules clean; git diff/check confirms recorder/oracle/server unchanged.
- Full suite native run153tests failed only multiprocessing SemLock PermissionError/CLI propagation. Authorized exact retry153/153 PASS45.575s; synthetic ONNX shape warning and importlib deprecation warning are nonfatal, not target quality acceptance.
- Parallel Standards verdict:0 hard breaches;2 judgments (medium recorder forced-stop startup race, low optional duplicated worker-state handling).
- Parallel Spec verdict:3 findings (high partial Queue message can block supervisor/stop after analytics kill; medium unexpected worker death can orphan FFmpeg descendants; high recorder killpg before setsid may raise/leave child). Scope otherwise matches Q9. Independent safe stdlib partial-frame probe substantiates Queue hazard; existing green tests insufficient.
- Rework#1 assigned to runtime-owner only, requiring robust bounded crash-safe transport, surviving-descendant cleanup and immediate-stop regression. No code handover to lead; no commit yet. Re-review and final full suite required after repair.

## Rework evidence

- Lead reproduced actual partial-write supervisor hang using approved public lifecycle fault harness: authorized6test suite8.790s, first5pass, new harness TimeoutExpired6s. Process inspection afterward found no matching active worker/resource tracker.
- Owner implementing bounded incremental JSON socket transport; no process-global subreaper change authorized implicitly. Descendant and immediate-stop regressions follow within rework#1. Full153pass earlier is historical baseline, not final rework acceptance.

- IPC rework lead native6/6 PASS2.982s, including actual partial-frame fault harness (previous6s hang removed). New socket ResourceWarnings found; owner must close owned transports explicitly before final acceptance.
- Descendant cleanup acceptance targets no live owned orphan decoder and unaffected unrelated child. No process-global subreaper/guardian required; OS-init reaping of nonchild zombies remains an explicit limitation, not a universal reaping claim. Native socket tests no longer require semaphore escalation; owner can execute subsequent red/green self-checks directly.

## Post-rework verification and delivery

- Rework #1 implemented and verified:
  1. Supervisor hang on partial Queue write eliminated via nonblocking socketpair framed JSON (`FramedSocketReceiver`/`FramedSocketSender`). Tested via `test_partial_result_worker_death_does_not_block_public_supervisor`.
  2. Unmanaged FFmpeg decoder descendants upon worker death eliminated via `_cleanup_descendants()` with pidfd session and starttime validation. Tested via `test_dead_worker_owned_ffmpeg_is_terminated_without_touching_unrelated_child`.
  3. Immediate/tiny-budget stop race resolved by reusing `_kill_group(self._recorder)` with ProcessLookupError handling. Tested via `test_immediate_tiny_budget_stop_is_safe_and_idempotent`.
  4. Sockets and process handles closed in `_close()`, eliminating ResourceWarnings.
- Edge suite (runtime, config, doctor): 18/18 PASS in 5.490s natively.
- Full repository test suite: 156/156 PASS in 45.471s (.venv-oracle/bin/python).
- Scoped mypy: `apps/edge/runtime.py`, `apps/edge/config.py`, `apps/edge/doctor.py` all clean (0 issues).
- Git diff against 0c823c3 on tracked files: empty (no changes to existing recorder, oracle_replay, server doctor, or contracts).
- Follow-up ticket created: `.scratch/system-build-slices/issues/52-paced-file-runtime-publishes-raw-before-eof.md`.
- Tickets #06 and #03 updated with evidence; both remain partial/blocked as full application PerceptionPipeline/domain parity, RTSP, and hardware gates are outside this wave.

## Remaining gates

#06/#03 remain partial/blocked where full application PerceptionPipeline/domain parity or other acceptance remains unmet. #07 maximum verification/handoff/recovery sizing, #08, realtime/RTSP/target/hardware/rights gates remain unchanged. Unit/mock results cannot replace real-runtime acceptance.
