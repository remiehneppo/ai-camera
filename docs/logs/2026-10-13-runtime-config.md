# Edge configuration and doctor — 2026-10-13

## Scope and decisions

Owned paths: `apps/edge/config.py`, `apps/edge/doctor.py`, `tests/test_edge_config.py`, `tests/test_edge_doctor.py`, this log. No staging/commit or edits to runtime/recorder/manifest/server modules. Pre-existing `.codegraph/`, `.scratch/replay-measurements/`, `AGENTS.md` untouched.

Loaded tdd and karpathy-guidelines. Approved public seams: immutable config loading, doctor/startup CLI. CodeGraph default index initially returned harness project; explicit `projectPath=/home/tieubaoca/AI/AI-Camera-OC` returned actual OracleDetector/load_manifest/FileRecorder. Consulted CONTEXT, ADR-0001/0004, #03/#06 and dispatch log.

Only `file`/`onnx_cpu` accepted. No credential fields supported: unknown fields rejected without echoing keys/values; local paths reject URL credentials. Frozen snapshot only retains validated scalar values. Config fingerprint hashes public execution configuration, never secret-bearing unknown input. Enabled analytics requires local artifact paths; preflight constructs the actual OracleDetector, which uses existing load_manifest plus installed versions, real ORT provider and tensor validation. Disabled analytics carries reason and never initializes ORT. Preflight availability is not running health.

Defaults are lab conveniences, configurable in JSON: sample_fps 2, mode fast, segment_seconds 2, ring_seconds 600, queue_capacity 8, observation_capacity 64, stop_timeout_seconds 3, io_timeout_seconds 30. None are target/capacity/RTO guarantees.

## TDD evidence so far

All commands use `.venv-oracle/bin/python -m unittest ... -v` (pytest absent in this venv).

1. `tests.test_edge_config`: RED `ModuleNotFoundError: apps.edge.config`, 1 error; GREEN `Ran 1 test ... OK` after frozen config/hash implementation.
2. `tests.test_edge_config.EdgeConfigTests.test_unsupported_config_is_rejected_without_echoing_values`: RED `ValueError not raised` for unknown backend, 1 failure (and assertion-context access error); GREEN `Ran 2 tests ... OK` after strict allowlist/types/timings/IDs/paths validation. Later disabled mutable model-path RED also `ValueError not raised`; GREEN after all optional artifact values are validated even when disabled.
3. `tests.test_edge_doctor`: RED `ModuleNotFoundError: apps.edge.doctor`; GREEN `Ran 1 test ... OK`, explicit test-only OracleDetector patch raises if disabled preflight initializes it.
4. `tests.test_edge_doctor.EdgeDoctorTests.test_enabled_preflight_validates_real_pinned_ort_and_rejects_bad_artifact`: RED expected available, actual disabled; GREEN actual approved `data/oracle/yolox_tiny.onnx` and `models/yolox-tiny/manifest.json` load through real ORT CPU provider; invalid artifact returns unavailable/error without leaking path.
5. `tests.test_edge_doctor.EdgeDoctorTests.test_doctor_cli_reports_disabled_and_invalid_configuration_nonzero_without_secrets`: RED empty stdout JSON parse; GREEN JSON preflight and return 1 for unsupported backend/source/unknown field/invalid enabled artifacts.

Focused run `.venv-oracle/bin/python -m unittest tests.test_edge_config tests.test_edge_doctor -v`: 5 tests, all OK (0.512s, before startup integration test added).
Typecheck `.venv-oracle/bin/python -m mypy apps/edge/config.py apps/edge/doctor.py --follow-imports=silent`: `Success: no issues found in 2 source files`.

## Runtime coordination / open gate

Agreed directly with runtime-owner: `EdgeRuntime(**execution_values).start()`, `observations()` drains retained observations, `status()`, `wait()`, `stop()`. State literals recorder not_started/starting/running/completed/stopped/failed; analytics also disabled. Outcome remains running while recorder active even if analytics failed; degraded flag and final outcome failed. CLI must drain to avoid bounded backpressure deadlock, preserve recorder completion, sanitize error diagnostics, exit nonzero on analytics failure only after recording completes/stop.

Runtime-owner reported multiprocessing SemLock sandbox denial and requested holding integration until real analytics wiring and green gate exist. Real FFmpeg+ORT --start test written but not executed yet; no runtime completion claim. #03/#06 partial, no #08 or domain/tracker/incident/RTSP/RKNN/hardware claims.

## Doctor usage

JSON example (paths are explicit and interpreted from the CLI working directory):

```json
{"source":"/cleared/lab/source.mkv","output_dir":"/lab/raw","source_type":"file","backend":"onnx_cpu","manifest_path":"models/yolox-tiny/manifest.json","model_path":"data/oracle/yolox_tiny.onnx"}
```

`python -m apps.edge.doctor --config config.json` prints one JSON preflight report; return 0 means available/explicitly disabled, not runtime health or source decodability. JSON with `"analytics_enabled":false` requires no model/manifest, supplies default explicit disabled reason if absent; no ORT initialization. Unsupported adapter/unknown input yields generic error/nonzero without reflecting user input. No secret configuration is accepted by this file-only lab seam.

A source existence check is not a decode validation. Preflight currently checks FFmpeg/ffprobe availability and actual enabled model/provider contract; source media validity and recorder progress must be observed in the real execution lifecycle.

## Startup integration resumed

Lead verified real A startup-failure slice GREEN2/2 and authorized disabled CLI GREEN1/1 (0.243s); subsequently A positive real ORT replay GREEN3/3 (1.094s), as communicated by lead/runtime-owner. Exact agreed runtime interface exists; implemented `--start` mapping frozen execution values to real EdgeRuntime. Polling drains observations continuously (bounded retention/queue does not silently drop), emits observed state transitions and waits for terminal outcome of BOTH children. Fault outcome does not prematurely cancel recorder. Explicit KeyboardInterrupt requests stop; final cancellation gate still depends on A stop implementation.

TDD startup red `.venv-oracle/bin/python -m unittest tests.test_edge_doctor.EdgeDoctorTests.test_start_cli_disabled_analytics_records_to_completion -v`: return 2, `unrecognized arguments: --start`. Implemented startup mapping; local green attempt returns sanitized `PermissionError` because semaphore operations denied in delegated workspace sandbox. Diagnostic direct Queue check emits `_multiprocessing.SemLock PermissionError: [Errno 13] Permission denied` plus `[sandbox: file access denied under workspace-write mode]`; no escalation requested here. Lead authorized exact disabled CLI retry passes1/1.

Full focused native `.venv-oracle/bin/python -m unittest tests.test_edge_config tests.test_edge_doctor -v`: Ran 8 tests in 0.892s, failures3, independent tests5 pass. All three failures show actual sanitized PermissionError during startup; no false green claim. Lead exact retry requested. Positive test uses actual approved ORT artifact + FFmpeg generated cleared red fixture, capacity1/1, expects2 observations and completed recorder/raw files. Fault test explicitly patches ONLY real EdgeRuntime.start wrapper for test-only SIGKILL after public status reports real analytics running, consumes actual public CLI results, checks failed analytics/nonzero + completed recorder, finally real stop cleanup. Approved by lead; not hardware/native recovery/RTO evidence.

## Lead-authorized real integration evidence

Lead independently retried exact focused command with approved wider permissions after environment denial: `.venv-oracle/bin/python -m unittest tests.test_edge_config tests.test_edge_doctor -v` — **8/8 PASS, 1.703s**. Includes actual approved ONNX CPU startup with FFmpeg file replay, disabled recorder completion, and controlled real analytics SIGKILL returning final nonzero while recorder completes. This is lead-supplied actual execution evidence, not a delegated sandbox pass.

Final delegated typecheck `.venv-oracle/bin/python -m mypy apps/edge/config.py apps/edge/doctor.py --follow-imports=silent`: `Success: no issues found in 2 source files`. Owned source/tests compile via compileall. No staging/commit. Awaiting lead review; full #03/#06 acceptance remains partial (domain pipelines/target/hardware/RTSP/RKNN/out-of-scope gates unchanged). Runtime stop/cancellation refinement belongs to A and must receive its own real green evidence; B does not claim target stop RTO or recovery capacity.

Startup invocation: `python -m apps.edge.doctor --config config.json --start`. Prints preflight first, then observed lifecycle transition snapshots/final result with config_hash and observations_consumed. Returns1 for invalid enabled preflight or runtime failure; analytics runtime failure lets recorder finish first. Source/decode and operational failure diagnostics sanitize exception values, retain error type on generic execution failures. Observation bodies are intentionally consumed by this detector-only CLI diagnostic, not persisted as domain events.

## Concise caller handoff

Run from repository root with the pinned oracle environment:

```sh
.venv-oracle/bin/python -m apps.edge.doctor --config config.json
.venv-oracle/bin/python -m apps.edge.doctor --config config.json --start
```

Minimal enabled `config.json` (replace source/output paths with cleared local lab paths):

```json
{"source":"/cleared/lab/source.mkv","output_dir":"/lab/raw","backend":"onnx_cpu","source_type":"file","manifest_path":"models/yolox-tiny/manifest.json","model_path":"data/oracle/yolox_tiny.onnx","sample_fps":2,"queue_capacity":8,"observation_capacity":64}
```

For recorder-only execution use `{"source":"/cleared/lab/source.mkv","output_dir":"/lab/raw","analytics_enabled":false,"disabled_reason":"recorder-only lab run"}`. Preflight return0 means tooling/model available or analytics explicitly disabled, NOT running health, media validity, or rights/ODD clearance for arbitrary input. `--start` is separate actual execution; observed runtime errors return nonzero, and analytics failure does not cancel independent recorder progress.

**Bounded observation caller obligation:** API clients must repeatedly call `observations()` while running; the queue and retained observations deliberately backpressure analytics instead of evicting/dropping. Calling `wait()` alone without consuming can stall when retention fills. The CLI drains automatically and reports only consumed counts; clients needing detector observation bodies must consume/persist them themselves. These are detector observations, not tracked/domain events.

Lab limitations: file replay and exact approved ONNX CPU artifact only, pinned optional runtime plus FFmpeg/ffprobe required, lab model rights restriction retained. Budget defaults/config values are conveniences, not certified capacity/RTO; no RTSP/RKNN/hardware/production/domain pipeline claims. Public CLI sanitizes exceptions, so use reported error_type rather than assuming availability from preflight. Delegated workspace sandbox may forbid multiprocessing semaphores; explicit authorized host verification is required there, not a fake adapter or silent fallback.

## Runtime handoff limitation — unresolved realtime continuity gate

Runtime-owner reports the final public realtime pre-EOF continuity regression remains **RED**, not skipped: paced FFmpeg FIFO execution genuinely lasts6s, but existing ingest publishes sidecars only afterEOF for the tiny fixture. Ineffective recorder tuning was reverted; lead has evidence. Earlier fast replay and doctor8/8 integration evidence remains scoped to those tested cases and does not establish raw-ring availability while realtime ingest is ongoing. No blanket runtime readiness or realtime continuity claim. Follow-up or explicit lead-approved scope narrowing is required; #06/#03 remain partial as before.

## Q9 scope revision — fast-only accepted delivery

User approved fast-only narrowed delivery (lead message). **Current EdgeConfig rejects every mode except `fast`, including `realtime`, before preflight/execution**. Runtime-owner confirms the same runtime rejection; existing lower-level oracle_replay remains unchanged and is not this runtime's accepted realtime capability. Prior8/8 green above is historical and requires rerun after this revision. Realtime preEOF sidecar continuity remains unresolved follow-up, not accepted or silently supported.

Public config regression RED: `.venv-oracle/bin/python -m unittest tests.test_edge_config.EdgeConfigTests.test_realtime_mode_is_explicitly_unsupported_by_edge_runtime_config -v` => FAIL `ValueError not raised`. Implemented fast-only validation; config suite GREEN3/3,0.008s. Public CLI regression checks realtime `--start` returns1 generic invalid configuration without secret sentinel leak. Actual controlled SIGKILL test now uses fast replay, sample_fps4 and3s content (not realtime pacing).

Current focused delegated suite `.venv-oracle/bin/python -m unittest tests.test_edge_config tests.test_edge_doctor -v`:10 tests0.984s,7 pass,3 actual startup PermissionError from delegated semaphore restrictions. Lead authorized exact revision rerun requested. Mypy2 modules clean. No recorder/runtime/oracle_replay edits by B.

The enabled JSON example above can explicitly include `"mode":"fast"`; omitting mode uses fast. No realtime mode should be supplied to doctor/startup. All current delivered CLI/config behavior is fast file replay only. Lab budgeting and no-drop consumption obligations remain unchanged; real ongoing realtime ring availability is excluded.

## Revised fast-only lead verification

Lead independently authorized revised focused runtime/config/doctor suite: **15/15 PASS,4.538s** (lead-supplied result after Q9 fast-only changes). This supersedes the historical8/8 result for current scope. Lead verified recorder/oracle diffs empty. Shared task2 already completed; owned code frozen while parallel Standards/Spec review and full suite run. No commit/stage; realtime continuity remains an excluded follow-up gate, not repaired by narrowing.
