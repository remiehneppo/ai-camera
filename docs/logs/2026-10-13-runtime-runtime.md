# Runtime owner — 2026-10-13

## Scope and decisions

- Claimed task-1; read dispatch, CONTEXT, accepted ADR 0001, M06/M02 checklists. Loaded tdd and karpathy-guidelines.
- CodeGraph initially returned wrong default project; explicit projectPath found FileRecorder/OracleDetector/iter_video_frames. Markdown index unavailable; scoped docs read directly.
- Approved seam: EdgeRuntime explicit constructor execution values (no config dependency), start/status/wait/stop_analytics/stop, segments/actual_range/observations. Counterpart edge-config-owner confirmed exact call shape.
- Separate spawn processes own recorder and analytics; bounded Queue + retained observations use backpressure, not eviction. observations() drains retention. Recorder active determines outcome=running; analytics failure additionally marks degraded. Final failure is returned only when recorder finishes/stops.
- Budgets are lab convenience configuration, not target guarantees. File replay only, detector only; no tracker/domain/RTSP/RKNN claims.

## TDD evidence

1. `.venv-oracle/bin/python -m unittest discover -s tests -p test_edge_runtime.py -v`: RED 1 test, ModuleNotFoundError apps.edge.runtime.
2. First implementation same command: blocked by sandbox PermissionError creating multiprocessing Queue SemLock. Reported exact denial to lead; no escalation or alternate attempt to bypass semaphore restriction. Real green evidence must be supplied by lead outside this restricted execution.
3. `.venv-oracle/bin/python -m mypy --follow-imports=silent apps/edge/runtime.py`: initial 2 arg-type errors fixed via explicit `dict[str, Any]` execution-values annotation; rerun `Success: no issues found in 1 source file`.
4. `.venv-oracle/bin/python -m py_compile apps/edge/runtime.py tests/test_edge_runtime.py`: exit 0.

## Immediate pending gate

- Lead supplied authorized exact retry evidence: test ran, 1 failure at `len(runtime.segments()) >= 2`, actual 1. Local independent `ffprobe -show_entries frame=pts_time,key_frame` inspected generated source: only first of four frames keyframe (0,.25,.5,.75 PTS). Corrected test fixture `-g 1`, not segment assertion. Waiting lead rerun for first GREEN; no sandbox retry by owner.
- Read slice #06: concurrent topology remains residual work and entire ticket remains partial. No source ticket edited by runtime owner.
- FileRecorder.ingest(file) is unpaced. Proposed independent realtime FFmpeg producer into private FIFO, consumed by real FileRecorder.ingest, for ongoing recorder continuity tests; no recorder internals modifications.

## Authorized lead verification progression

- Same exact unittest command, lead-authorized wider execution: fixture keyframes corrected but wait returned completed notification while worker still alive. Fixed wait to require terminal worker and actual child exit/reap. GREEN 1/1, 0.253s (lead report).
- Startup-failure RED 2 tests, 0.474s: actual analytics state not_started vs expected failed. Implemented real OracleDetector construction in independent spawn worker and bounded status transport, no recorder unwind. GREEN 2/2, 0.491s (lead report). Local mypy/py_compile pass.
- Positive real-asset ORT loop and bounded observation drain test written next; RED verification requested. Current worker only constructs detector; test requires six ordered PTS observations and actual provenance.
- Lead approved narrow paced private FIFO design for real realtime file recorder: worker-owned producer and cleanup, no RTSP promise; not a sandbox workaround.

## Subsequent actual evidence and remaining blocker

- Positive ORT RED authorized 3 tests/.786s: observations [] vs six expected PTS. Actual OracleDetector.detect + iter_video_frames and bounded Queue/retention implemented. GREEN authorized 3/3, 1.094s. No normal observation eviction; explicit caller drain required when full.
- Slow-consumer stop RED authorized 4 tests/2.591s: analytics alive after stop. SIGTERM closes actual frame generator; cancellation-only queue feeder abandonment and bounded group kill fallback implemented with explicit incomplete-observations reason. GREEN authorized 4/4, 2.630s.
- Initial realtime/crash test falsely passed unpaced recording: authorized 5/5, 3.317s. Strengthened independent two-second wall pacing observation exposed end PTS5.25 not<5 (RED 5 tests/3.207s).
- Paced private FIFO implemented using real FFmpeg -re/-copyts stream copy feeding actual FileRecorder.ingest, worker-owned producer finally killed/waited. Run remained RED at first-publication-relative pacing bound (5 tests/8.475s).
- Scoped two-case experiment: default and producer cluster250ms/flush1 each took5.79/5.80s and produced12 final segments, but no sidecar while producer alive. Changed final public test to runtime-start anchor, analytics group test-only SIGKILL at2s, raw advance required before5s vs6s source. Authorized RED5 tests/7.850s: advanced None; first4 pass. This gate correctly rejects post-EOF publication burst as realtime continuity.
- User approved minimal recorder public ingest-probe option scope. Tried analyzeduration250000, producer cluster/flush tuning, then probesize32: each no preEOF publication, final12 segments/~5.79s.
- Bounded final diagnostic: producer bytes arrive at0.03s519bytes,0.03s120bytes,.53s121bytes,1.03s121bytes; early producer flush is real. One final input direct-buffer option returned FFmpeg exit183, no acceptance.
- Removed every ineffective recorder option and producer tuning. `git diff --stat apps/edge/recorder.py` empty. No recorder test edits. No further guessing: realtime preEOF continuity explicitly BLOCKED; final regression remains RED, not skipped or weakened.
- Current local mypy runtime success1file; py_compile runtime/tests exit0. SemLock test execution still requires lead-authorized wider environment, no own bypass/retry.

## Owned paths and truthful limits

- New apps/edge/runtime.py, tests/test_edge_runtime.py, this log only. recorder.py restored exactly; oracle_replay/config/doctor/server/domain untouched by this owner. No staging/commit.
- Successful narrow evidence covers independent spawn ownership, disabled and startup-failed analytics recording, actual ORT6 ordered sampled frames/provenance, bounded retention/queue and explicit analytics cancellation. Failed-observation preservation code exists but separate numeric failure regression not yet written.
- Realtime preEOF publication gate unmet. Partial FIFO work is not an accepted realtime runtime; pending lead decision to narrow deliverable or follow up. Existing six-second pacing does not prove realtime raw availability.
- Stop timeout applies separately to workers currently, with finite fallback; storage stalls/noninterruptible I/O can leave child alive and metadata incomplete, status error is explicit. No hardware/capacity/target-RTO/domain parity claims. #06/#03 stay partial, #08 unchanged.

## Q9 approved scope revision: fast-only delivery

- User explicitly approved fast-only review/delivery. Removed entire paced FIFO implementation and unused imports. EdgeRuntime rejects every mode other than fast with clear ValueError before recorder/transport initialization. Existing standalone oracle_replay realtime behavior remains unchanged.
- Kept four successful lifecycle/ORT/backpressure tests; replaced active unsupported realtime test with explicit public rejection test (not a skipped or weakened realtime implementation claim).
- `.venv-oracle/bin/python -m mypy --follow-imports=silent apps/edge/runtime.py`: Success, no issues in1 source file. py_compile runtime/tests exit0. `git diff --stat apps/edge/recorder.py`: empty.
- No proof raw segments advance after analytics crash during realtime. Narrow accepted claims only: fast disabled/startup-failure/cancel isolation, real ORT ordered results and bounded transport. Lead final focused verification requested.

## Follow-up ticket draft — realtime raw publication before source EOF

**Status:** blocked/not implemented; future independent scope approval required. #06 remains partial.

**Goal:** Independently paced file recorder publishes verifiable raw segments before EOF; analytics crash/stop does not prevent ongoing recorder progress. No RTSP/hardware/domain promise.

**Public acceptance:** six-second local all-keyframe fixture; start monotonic clock; recorder alive through first2seconds; controlled analytics group SIGKILL at2seconds; observe strictly increased raw segment end PTS before wall5seconds while recorder/source still active; final coverage complete and runtime failed outcome. Generous lab timing margins, not target guarantees. Validate actual PTS/session and closed-segment integrity unchanged.

**Actual RED:** lead authorized `.venv-oracle/bin/python -m unittest discover -s tests -p test_edge_runtime.py -v` with attempted FIFO implementation:5 tests/7.850s, other4 pass, advance None at preEOF deadline. Initial fast/postEOF sidecar test falsely green; publication-relative pacing bound also incorrect due delayed first sidecar. Start-relative preEOF test caught real missing capability.

**Diagnostic evidence:** FFmpeg -re pace totals~5.79s for6second source but12sidecars only at tail; producer mux cluster250ms/flush1 alone ineffective; optional ingest analyzeduration250000/probesize32 combinations ineffective; bytes genuinely arrive0.03s519/120bytes,.53s121,1.03s121. Final direct-input-buffer attempt FFmpeg exit183. All experimental options and paced implementation removed, no recorder diff. Do not reinstate guesses without a tight preEOF feedback loop.

**Remaining:** determine bounded ingest/AVIO behavior on supported known codec using actual executable evidence; implement minimal approved public option only when effective, preserve defaults and closed publication completeness, test producer/decoder/publisher cleanup and failed observations, then independent review. Do not close #06/#03 or open #08 on this draft.

## Final focused acceptance under revised scope

- Lead independently ran authorized runtime/config/doctor focused suite: **15/15 PASS,4.538s**. Includes fast-only runtime explicit realtime rejection; recorder/oracle replay diff empty independently verified by lead.
- Runtime owner local typecheck success1file and syntax compile exit0; dynamic multiprocessing evidence supplied by lead because teammate SemLock sandbox is restricted.
- Code frozen pending lead parallel Standards/Spec review and full-suite verification. Shared task finished for Q9 fast-only scope, not original realtime gate or entire #06/#03 closure. No commit/stage.

## Rework #1 execution and verification

- Addressed Spec high finding: replaced multiprocessing.Queue with nonblocking Unix socketpair framed JSON (`FramedSocketReceiver` and `FramedSocketSender`). Max 4MiB frame, max 4KiB status. Nonblocking reads discard incomplete frames upon worker exit, eliminating supervisor hang. Tested via `test_partial_result_worker_death_does_not_block_public_supervisor`.
- Addressed Spec medium finding: added `_cleanup_descendants` using failure-only `/proc` session scan + `pidfd_send_signal` checking session and starttime, avoiding signaling unrelated reused PIDs. Tested via `test_dead_worker_owned_ffmpeg_is_terminated_without_touching_unrelated_child`. Note: OS init reaps non-child zombies.
- Addressed Standards medium finding / Spec high finding: reused `_kill_group` in `stop()` for recorder process with ProcessLookupError and process-group handling; added explicit `_close()` to close all socket fds and process handles, eliminating ResourceWarnings. Tested via `test_immediate_tiny_budget_stop_is_safe_and_idempotent`.
- Focused runtime suite: 8/8 PASS natively (no SemLock required).
- Full edge suite (runtime, config, doctor): 18/18 PASS natively in 5.490s.
- Full repository test suite: 156/156 PASS in 45.471s.
- Mypy: `apps/edge/runtime.py` clean.
