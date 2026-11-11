# Review remediation — 2026-11-11

## Scope and decisions

- User request: fix all findings in the review of `master` (`9db241d`) to `origin/civi-watch` (`9bb70ee`).
- Integration target: existing `civi-watch` worktree at reviewed commit `9bb70ee`. The user's untracked Hugging Face publication log is left untouched. No commits, pushes, merges, or tags are requested.
- Tier: T1 bug fixes restoring accepted ADR-0008 behavior. No HTTP contract, database schema, RBAC, tenant scope, or new product flow changes. Leaf taxonomy options preserve the existing exact-match API. Evaluators will state unsupported/unconfigured scope instead of claiming all-scenario or recorder acceptance.
- Four disjoint worktree/branch lanes own scenario/VLM rules, training artifacts, evaluation tooling, and dashboard/media security. Integration owner owns pipeline/vehicle verification and live geometry, integration tests, documentation, and final gates.
- Verification/storyboard ownership belongs to the pipeline. Rule engines return candidate facts; their verifier field is selection metadata only. Rejected candidates must not consume verified-alert cooldown. Default verification remains offline unless a verifier is explicitly selected; no implicit cloud egress is introduced.
- Live-config vehicle geometry is initialized from actual frame dimensions for the existing lab template; snapshots remain marked uncalibrated. No site-specific calibration or metric accuracy is claimed.
- Training preparation must preserve active deployments. Dataset annotation preparation will prefer simple regeneration over an invalid cache.
- Media controls must use external credentials, restricted origins, and a pinned official image. No fixture credentials are production defaults.

## Evidence plan and progress

All review findings F1–F20 plus the go2rtc origin/auth question are in scope. Focused regressions use synthetic frames/labels/artifacts and public outcomes. UI checks use actual browser interactions with controlled API fixtures; model/HTTP/camera boundaries are not mocked as product acceptance.

Before pipeline implementation, `.venv-oracle/bin/python -m pytest -q tests/test_pipeline_verification.py` produced four expected failures: missing projected metric payload, bypassed urban verifier/cooldown, bypassed vehicle verifier, and missing visual-verifier suppression. This establishes the regression triggers on the reviewed code. Further evidence and exact final gate results will be recorded after integration.

## Security tier refinement and baseline regressions

The native media control authentication change is T2 because it changes the permission boundary. The remaining review corrections are T1 bug fixes. OpenSpec `fix-civiwatch-media-control-auth` records proposal, delta requirements, design, diagram, implementation tasks, and the user's implementation authorization. `openspec validate fix-civiwatch-media-control-auth --strict` passed before integrating the security draft into this worktree.

- After the pipeline/vehicle cutover, `.venv-oracle/bin/python -m pytest -q tests/test_pipeline_verification.py -k vehicle`: **2 passed, 2 deselected**. This proves verifier suppression and projected metric payload on the configured path; it does not prove site calibration.
- Before training implementation, `.venv-oracle/bin/python -m pytest -q tests/test_training_artifact_safety.py -k 'civiwatch_dry_run_preserves_active or regenerates_annotations_when_labels_change'`: **2 expected failures, 7 deselected**. The active manifest was overwritten and the old COCO cache omitted the new image/labels.
- Before metric implementation, `.venv-oracle/bin/python -m pytest -q tests/test_evaluation_regressions.py -k evaluate_detection_accuracy_one_to_one_enforcement`: **1 expected failure, 11 deselected**. Existing evaluation reported 100% rather than 50% recall for two ground truths sharing one prediction.
- Obsolete dashboard source-string and registration-only tests are removed, not repinned. Functional API evidence assertions remain; actual UI behavior is checked in Chromium.

## Implemented corrections

| Finding | Correction |
| --- | --- |
| F1 | Explicit/automatic observation gaps clear continuity and pair/environment timers while retaining alert cooldown; the first recovered frame cannot accrue unseen time. |
| F2 | Pipeline owns storyboard construction and verification for urban/vehicle candidates; rejected candidates release only their matching taxonomy/timestamp cooldown. |
| F3 | Explicit dry-run writes separately named blueprint artifacts, preserving active deployment files; ordinary training without CUDA fails. |
| F4 | Environmental ratios/luminance use the rasterized polygon, including the polygon's lower region for water; zero-coverage regions return no signals. |
| F5 | Consecutive unattended time resets when a person returns or observation breaks. US11 retains its existing alert-condition evidence anchor, not unattended onset. |
| F6 | Proximity duration and recent motion belong to each pair; separation, missing tracks and observation gaps reset pair continuity. |
| F7 | Remote verdicts require a JSON boolean and finite non-boolean confidence within [0, 1]; malformed responses retain the existing failed/candidate outcome. |
| F8 | Dashboard options send 21 emitted taxonomy values to the existing exact-match API. US08 remains vehicle_incident, whose branches are interaction_type values. |
| F9 | Clear removes both storage copies and credential query parameters, invalidates/aborts pending refreshes, clears protected cards/review state and detaches live/evidence/download URLs. |
| F10 | Class-aware IoU matching consumes each prediction and ground truth at most once. |
| F11 | Sampling uses source frame timestamps rather than the requested sample period. |
| F12 | COCO annotations regenerate from current labels/images; destination links refresh safely and unmanaged directories are not replaced. |
| F13 | Live-config vehicle geometry uses actual frame dimensions; the lab template remains explicitly uncalibrated. |
| F14 | go2rtc fixture sources resolve through the existing /app/data/benchmark mount. |
| F15 | Missing schedule state is not rendered as inactive; explicit true/false remain distinct. |
| F16 | Benchmark conclusions use measured results rather than hard-coded model/performance claims. |
| F17 | Extended evaluator explicitly reports US04, US10 and US14 as unconfigured without their specialized ROI/engine configuration. |
| F18 | Benchmark scope is perception only, excluding recorder/evidence packaging/WAN delivery; obsolete full-edge naming is removed. |
| F19 | Failed observations cannot produce completed benchmark results; resources are released on error paths. |
| F20 | CLI regressions use the current PerceptionPipeline execution seam; obsolete source-text/wiring checks are removed rather than repinned. |

The T2 media boundary uses official `alexxit/go2rtc:1.9.15` pinned to
`sha256:e098de5c2f8040dc3d4784ed2d5cfdac3b0979f9349afe587ef6a670a14b9f4d`.
Compose requires external media credentials. Native local authentication, restricted
WebSocket origins and administrative route exclusion are enabled; the adapter does
not leak Basic credentials across origins. README documents setup and the HTTP/TLS limit.

Integration corrections: the first focused scenario run exposed an undefined persons
list in the association update. Restoring its per-frame computation fixed that error.
A newly added cooldown test also needed to re-establish fire persistence after an
inactive interval. The US11 test was corrected to preserve the existing alert_condition
anchor contract. Mypy then required the grayscale OpenCV color as a one-element tuple.
No unrelated deprecations or source files were reformatted.

## Final verification evidence

| Command / scenario | Observed result |
| --- | --- |
| `.venv-oracle/bin/python -m pytest -q -ra` | 979 passed, 207 subtests passed, 360 deprecation warnings; exit 0; no skipped tests reported. |
| `.venv-oracle/bin/python -m mypy domain/ apps/ tools/` | No issues in 83 source files; two existing annotation-unchecked informational notes in the benchmark. |
| `.venv-oracle/bin/python -m pytest -q -ra tests/test_urban_safety_regressions.py` | After the OpenCV tuple compatibility correction: 22 passed, 17 subtests passed. |
| `openspec validate fix-civiwatch-media-control-auth --strict` | Change valid; exit 0. |
| `docker compose --env-file /dev/null config --quiet` with synthetic environment | Missing media credentials rejected; explicit synthetic credentials accepted. No real environment file was loaded. |
| Isolated digest-pinned go2rtc HTTP/WebSocket smoke | Unauthenticated /api/streams: 401; authenticated: 200; foreign WebSocket origin: 403; exit/restart/config: 404; process remained available afterward. |
| Same native image with the repository's read-only config/data mounts | Both civi-cam-01 and civi-cam-02 returned HTTP 200 with valid MP4 ftyp headers from /api/stream.mp4. Both smoke containers were removed. |
| Chromium dashboard with controlled synthetic API rows/media | All 21 leaf filters returned the exact expected taxonomy; missing/true/false schedule states remained distinct. Clear emptied inputs/storage/cards and detached live/evidence/download URLs, including while a refresh was in flight. URL credentials disappeared while unrelated query parameters survived; clear + reload did not restore tokens. Desktop and narrow-viewport surfaces were opened; the final page reported no JavaScript exceptions. |
| Real evaluator CLI, synthetic 64x64/5fps MP4, YOLOX-tiny HCMC, --max-frames 4 --sample-fps 5 --no-pose --extended-scenarios | Four frames processed; 11 scenarios evaluated and US04/US10/US14 explicitly unconfigured; exit 0. Zero detections/events is not negative-scenario acceptance. |
| Real evaluator CLI with an explicit missing video and the same detector | Exit 1 with failure reported. |
| Real-model perception benchmark timing smoke, synthetic 25fps clip sampled at 10fps | Four source timestamps observed at process_frame: 0.00, 0.08, 0.16, 0.24; completed. Instrumentation wrapped the real pipeline without replacing inference. |
| COCO regeneration smoke, synthetic local images/labels | Editing YOLO class 0 to 2 changed the regenerated COCO category from 1 to 3; annotation cache was not reused. |
| `df -h . /tmp` | 46 GiB available after verification. |

The static dashboard harness encountered a selector typo and browser-tool interception/
evaluation limitations; later phases independently confirmed cleared DOM/storage and
URL/reload behavior. The static server's unhandled health probe can show HTTP 404;
this harness is not a running backend or a full Compose acceptance claim.

No existing Compose services were recreated, no cloud inference/customer-data egress
was performed, and no GPU training, site calibration, physical-camera, target-hardware,
full MongoDB transaction lab or production deployment acceptance is claimed. The
separate unittest command was not repeated because the documented full pytest suite
was run. Standalone lint/build commands were not run; pytest and mypy are the documented gates.
The user's publication log is untouched. No commit, push, merge or tag was made.

Acceptance cleanup: both owned browser tabs were closed, the isolated static server
was stopped, and generated synthetic media/JSON fixtures were removed. Temporary
implementation worktrees remain available under /tmp/civiwatch-fixes-bvu9i6ii for
patch recovery; they are not part of the deliverable or staged changes.

## Publication authorization

The user subsequently requested commit and push. Publication targets the existing
`civi-watch` branch and its `origin/civi-watch` upstream, without force push, merge
or tag. Only remediation source, regressions, example placeholders, diagrams/specs
and technical documentation are selected. `.codegraph/.gitignore` and the user's
Hugging Face publication log remain outside this commit. Commit/push results are
reported in the conversation rather than embedding a self-referential commit hash.
