# Documentation and architecture synchronization: 2026-11-11

## Scope and decisions

- Request: analyze the updated version and synchronize project documentation with code and confirmed technical decisions.
- Target: `civi-watch` at `17d9a32`, including the v2 introduction `9bb70ee` and review remediation. The initially selected workspace remains at `9db241d`; no checkout or changes occur there.
- Tier T0: documentation and diagrams only. No runtime behavior, contracts, permissions or module ownership changes are authorized by this task.
- Domain terms come from the Language section of `CONTEXT.md`; no competing `GLOSSARY.md` is introduced.
- Accepted ADR decisions remain historical decision records. Current implementation/evidence must be distinguished from accepted design intent; ADR-0007 remains proposed.
- Scope follows the last 20 commits: `pipeline.py` changed eight times, `eval_all_scenarios.py` and `incident.py` five times, and `vehicle_incident.py` four times.
- The architecture HTML report belongs in the operating-system temp directory. Its candidates are proposals, not accepted changes, and contain no concrete interface designs.
- Preserve `.codegraph/.gitignore`, the untracked Hugging Face publication log, historical reports/logs and customer/secret data. No commit or push is requested for this documentation task.

## Evidence and progress

Codegraph is available for the updated worktree. Research uses the accepted snapshot/replay ADRs, proposed RTSP ADR, accepted v2 ADR and the committed remediation evidence. Three read-only lanes inspect runtime ownership, evaluation/training claims and active-document discrepancies before edits.

## Documentation corrections

- Replace stale top-level 893/918 test claims and blanket 14-scenario acceptance with one current status index and dated observed evidence. Keep historical report measurements unchanged.
- Describe candidate facts, synchronous verification, one snapshot constructor and SQLite intent commit before independent recorder pin/file I/O. Feature temporal state and human review remain separate.
- State that default feature verifiers force offline mode, storyboard composition uses available buffered history, and replay alone does not guarantee post-anchor frames.
- Distinguish auxiliary go2rtc helpers from actual direct OpenCV/FFmpeg live capture. Its native control authentication smoke does not establish single-session fanout, WebRTC latency or retained raw coverage.
- Distinguish homography templates from site calibration and graph-dependent pose batching from a proven target speedup.
- Keep accepted ADR decisions intact, ADR-0007 proposed, target/native/field gates open, and model-manifest approval flags separate from release/legal clearance.
- Add current media-auth/security limits to the security reference plan without endorsing unverified foreign ADRs, legal interpretations, HSM/TPM, mTLS, NVR or production topology.

## Architectural deepenings implemented

### 1. Candidate 1: Semantic replay runner (`tools/replay_runner.py`)
- Created deep module `tools/replay_runner.py` encapsulating video decode validation, rational microsecond timestamping (`pts = round((frame_idx / native_fps) * 10^6) * Fraction("1/1000000")`), step stride calculation, ephemeral SQLite outbox/ring lifecycle (`tempfile.TemporaryDirectory`), and fail-fast observation status checking.
- Refactored five evaluation callers to delegate to `run_replay_session`:
  - `tools/compare_models_benchmark.py:evaluate_perception_pipeline_on_video`
  - `tools/eval_all_scenarios.py:evaluate_video`
  - `tools/eval_vehicle.py:evaluate_clip`
  - `tools/eval_clip.py:evaluate`
  - `tools/run_benchmark.py:run_single_benchmark`
- Replaced ~450 lines of duplicate loop logic across tools. Fixed the legacy `run_benchmark.py` clock divergence (F11) so timestamps derive from source frame time, and added fail-fast status verification (F19).
- Added interface regression tests in `tests/test_evaluation_regressions.py` (`TestReplayRunnerDeepening`).

### 2. Candidate 2: Suspected incident verification seam (`apps/edge/vlm_verifier.py`)
- Implemented `CandidateVerificationCoordinator` in `apps/edge/vlm_verifier.py` encapsulating storyboard buffering, grid building, verifier dispatch, verdict decoration (`facts["payload"]["vlm_verification"]`), cooldown rejection (`engine.reject_candidate(facts)`), and verifier lineage enrichment via `verify_candidate(..., return (verified, rule_lineage))`.
- Simplified `apps/edge/pipeline.py:748–806`: the pipeline no longer accesses storyboard internals, builds storyboard grids, mutates verification dictionaries directly, or manages rejection cooldown calls.
- Preserved synchronous candidate emission, ADR-0005/0008 ownership, and offline default verifier (`endpoint_url=""`).
- Added interface regression tests in `tests/test_pipeline_verification.py` (`test_candidate_verification_coordinator_orchestrates_verification_and_lineage`).
- The future asynchronous post-roll queue (+3s keyframe hold) remains a planned Tier T2 OpenSpec proposal.

### 3. Verification results
- `.venv-oracle/bin/python -m mypy domain/ apps/ tools/`: Success: no issues found in 84 source files.
- `.venv-oracle/bin/python -m pytest -q -ra`: 982 passed, 360 warnings, 207 subtests passed in 165.99s.
- End-to-end smoke test on `tools/run_benchmark.py`: verified on synthetic 25 FPS clip sampled at 10 FPS; observed exact rational timestamps `[0.0, 0.08, 0.16, 0.24]` without clock divergence.

## Architecture report and visuals

- HTML report: `/tmp/architecture-review-20261111-092708.html`; created using the OS temp-directory fallback, not committed into the repository.
- Candidates: semantic replay module depth (`Strong`) and Suspected incident verification locality (`Worth exploring`). Both apply the deletion test, actual adapter variation and interface-as-test-surface principle. No concrete interface, queue, delay or runtime redesign is approved.
- Opened through `xdg-open`, then inspected in Chromium: two candidate cards, two rendered Mermaid graphs, no diagram errors or JavaScript exceptions; desktop and 390-pixel layouts show no horizontal overflow.
- `H04-current-reference-runtime.drawio` has two pages: current candidate/verification/durability ownership and current live-capture/auxiliary-media paths. It supplements rather than rewrites historical ADR diagrams.
- Draw.io MCP parsed both page descriptors and opened the first page with obstacle-aware routing. Draw.io Desktop is unavailable, so no PNG export is claimed.
