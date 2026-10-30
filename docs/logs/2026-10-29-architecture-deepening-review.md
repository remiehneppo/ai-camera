# Architecture deepening review — 2026-10-29

## Scope and actions

- T0 review/documentation only. No runtime code, interface, schema, threshold, configuration, or accepted ADR changed.
- Read the supplied AGENTS.md, codebase-design vocabulary, architecture-report scaffold, CONTEXT.md domain language, docs/agents/domain.md, ADR-0001–0004, integration contracts, and the previous 2026-10-14 deepening review.
- Scoped from `git log -70 --format='%h %ad %s' --date=short --name-only`. Prioritized repeated changes in edge incident orchestration and replay evaluators rather than scanning the entire repository.
- Used codegraph MCP for pipeline, feature modules, perception execution, evaluator callers, and existing tests. A read-only scout independently examined snapshot ownership and dispatch/lifecycle coupling. No scout edits or verification commands.
- Applied the deletion test. Kept two candidates; rejected dispatch inspection alone because moving it would shift caller knowledge without sufficient depth. Did not reopen completed Evidence/perception deepening from the earlier review.

## Candidate decisions

1. **Strong: give Suspected incident snapshots one owner.** Four feature modules construct validated full snapshots, then `apps/edge/pipeline.py:640–690` rewrites identity, lineage, Evidence session, and quality before validating again. Person-down instead uses the separate construction path at `pipeline.py:746–830`. Concentrating these mechanics should increase locality and leverage; independent feature state, configuration, taxonomy, and anchor rules remain intact. Relevant evidence: `apps/edge/danger_zone.py:164–241`, repeated fixes `f44a442` and `b66e78c`, and behavioral tests in `tests/test_danger_zone_flow.py:529–618,709–733`.
2. **Worth exploring: make replay exercise the existing Alert feature pipeline module.** `tools/eval_all_scenarios.py:63–165` and `tools/eval_vehicle.py:38–95` duplicate clock/status, Track, pose, and feature orchestration. `tools/eval_clip.py:59–113` already uses PerceptionPipeline, and `apps/edge/perception.py:25–31` already owns consistent rational frame metadata. Preserve each command's intended thresholds and measurement scope before migrating; defaults currently differ. Historical timestamp/status fixes in `b60d5db` motivate reuse, not a new generic replay abstraction.

The interface is the test surface. No interface methods/types were proposed. No new adapter is justified for in-process snapshot construction. Replay should reuse existing detector and local-storage adapters; one adapter is a hypothetical seam, two adapters make a real seam.

ADRs remain constraints: independent feature state and compatible shared perception (0001), downstream after durable ingestion (0002), MongoDB transaction semantics (0003), and full snapshots/immutable identity-Origin/Evidence intent (0004). Candidate 1 would require a T3 ADR before an implementation changes module ownership; this review does not accept that change.

## Deliverable

- HTML: `/tmp/architecture-review-20261029T134719Z.html`.
- Editable source: `/tmp/architecture-review-20261029T134719Z.drawio`, four pages, also embedded as a download in the HTML.
- Temporary directory resolved from TMPDIR, falling back to `/tmp`. Report and diagram artifacts remain outside the repository; this required tracking log is the only intended repository addition.
- Report contains two candidate cards, source/test references, deletion tests, before/after visualizations, strength badges, ADR constraints, risks, and a top recommendation: candidate 1.
- No glossary term was adopted or sharpened. No glossary creation or ADR revision during this review.

## Exercised verification

- `.venv-oracle/bin/python tools/eval_all_scenarios.py --help`: exit 0; inspected actual options.
- `.venv-oracle/bin/python tools/eval_all_scenarios.py --videos data/benchmark/intersection_traffic_1080p.mp4 --max-frames 3 --no-pose`: exit 0; 1920×1080, 29.97002997002997 FPS, 3 frames, 19 detections, no pose, 0 emitted events.
- `.venv-oracle/bin/python tools/eval_vehicle.py --video data/benchmark/intersection_traffic_1080p.mp4 --max-frames 3`: exit 0; 3 frames, 19 detections, 0 events. Its printed `[clean (0 events)]` label is not a reviewed negative result.
- Temporary assert-based runtime smoke using FileRecorder, EventOutbox, ByteTracker, DangerZoneIncidentEngine, and PerceptionPipeline: observed `danger_zone_intrusion`, authoritative `cam-01`, retained per-module `zone-review-v1`, `low_light` in snapshot/payload quality, and matching persisted event identity. Temporary storage removed on completion.
- Browser opened the HTML and rendered both Mermaid diagrams. Asserted two candidate cards, required vocabulary in both cards, all internal anchors resolving, and four valid XML diagram pages embedded in the download.
- Desktop/tablet/mobile layouts checked at 1440×900, 768×1024, and 375×812: document width matched viewport width at all three. Inspected desktop/report screenshots and mobile screenshot; corrected Tailwind CDN reset overriding heading sizes and inline Evidence code styling. Final heading size 58px at desktop and 36px at mobile. No page JavaScript errors observed; Tailwind emitted its expected CDN-production warning.
- `xdg-open /tmp/architecture-review-20261029T134719Z.html`: exit 0 and `Opening in existing browser session`, followed by Chromium zygote broken-pipe diagnostics. User-visible desktop opening is not confirmed; separate managed-browser rendering is confirmed.

## Limits and next decision

No permanent tests, full suite, mypy, build, target hardware, live camera, reviewed annotation, detection-quality gate, or performance comparison ran. This was an investigation with runtime smoke, not an implementation. Three-frame event counts do not establish quality, negative passes, native conformance, or complete Evidence transfer.

Next question for the user: **Which of these would you like to explore?** After selection, use one clarification round at a time before designing the chosen module's interface.

## Self-evaluation

| Axis | Score | Evidence / remaining limit |
|---|---:|---|
| Accuracy | 4/5 | Source/ADR/history evidence plus runtime smoke; no full evaluator equivalence proof. |
| Completeness | 5/5 | Scoped exploration, scout, two visual candidates, top recommendation, temporary report, opening attempt, and tracking log. |
| Clarity | 4/5 | Explicit before/after and short ownership descriptions; detailed source caveats require expanding evidence sections. |
| Actionability | 5/5 | Named candidates, files, risks, preserved tests, and the next user choice; no premature interface design. |
| Conciseness | 4/5 | Two candidates only; necessary source and verification detail lengthens the report. |

Overall 4.4/5. Deliver as-is. Highest-impact next improvement depends on the selected candidate: prove its intended behavior and policy equivalence before implementation. The user can inspect the report without accepting any architecture change.

## Sequential exploration — candidate 1, round 1

- User requested discussing the candidates one at a time. Start with candidate 1; candidate 2 remains pending, not dropped.
- Re-read codebase-design, spec-and-plan clarification workflow, domain language, and codegraph evidence for IncidentEngine._create_incident, DangerZoneIncidentEngine._build_event, and PerceptionPipeline._handle_incident.
- Working interpretation: discuss ownership and constraints before designing an interface or authorizing implementation. Confidence: 95%; ownership scope still requires the user's choice.
- Recommended first decision, not yet accepted: feature modules retain scenario rules, independent temporal state, thresholds, severity/confidence, and anchor selection; shared snapshot construction owns identity, authoritative runtime context, quality/provenance binding, Evidence request construction, and validation before the existing EvidenceLifecycle handoff.
- Preserve the distinction between onset and alert-condition anchor, per-module configuration, and rule lineage. No new adapter, generic feature superclass, persistence schema, or threshold change proposed.
- Awaiting answer to whether to pursue this ownership-only scope or retain full-snapshot output from each feature module. Runtime code unchanged; no new checks ran during this discussion.

## Candidate 1 — ownership direction accepted

- User selected **Tập trung việc tạo snapshot** in the clarification prompt. Accepted direction: independent feature decisions/state with shared snapshot construction. This is not implementation authorization or acceptance of an interface design.
- Next material decision: whether to migrate all standalone feature-module callers and fixtures to the same snapshot seam, rather than preserve a second full-snapshot output path inside feature modules.
- Recommendation, awaiting acceptance: clean cutover across runtime callers, replay callers, and fixtures; standalone feature execution may still produce scenario facts, but full snapshots come from the shared module. Existing EvidenceLifecycle retains persistence/pin/recovery ownership.
- Verification targets remain emitted/persisted snapshot semantics: per-module configuration, real detector and rule lineage, capability quality, and distinct onset/alert-condition anchors. No new adapter or generic base module proposed; no runtime code changed or checks rerun.

## Candidate 1 — clean cutover accepted; scope discussion complete

- User explicitly selected A: migrate all affected callers to the shared snapshot seam; remove feature-module full-snapshot output rather than preserve a compatibility path.
- Agreed scope: each feature module retains scenario rules, independent temporal state/configuration, severity/confidence, and anchor selection. Shared snapshot construction owns event identity, authoritative context/provenance/quality binding, Evidence request construction, and validation. Existing EvidenceLifecycle keeps durable persistence, pin, transfer, and recovery ownership.
- Runtime, standalone evaluator callers, and fixtures that consume full snapshots must migrate together. Feature modules may execute independently to produce scenario facts. No change to wire/storage schemas, thresholds, onset/alert-condition semantics, or accepted ADR invariants is approved.
- Tests should retain consumer-visible assertions through the corresponding interface: scenario facts for feature decisions; final emitted/persisted snapshots for identity, configuration, provenance, quality, and Evidence anchor semantics. No adapter or generic base module needed solely for snapshot assembly.
- Candidate 1 ownership and caller-migration scope is settled. Interface design, T3 ADR/specification, and implementation authorization remain separate; no implementation has been requested.

## Candidate 2 — round 1: purpose of replay

- Began the second candidate after settling candidate 1's scope. Codegraph reconfirmed duplicated replay orchestration and different tracker/feature settings in tools/eval_all_scenarios.py, tools/eval_vehicle.py, and PerceptionPipeline.__init__.
- The material decision is whether these commands should primarily exercise the configured runtime Alert feature pipeline or remain standalone feature experiments. Code reuse alone cannot make their outputs equivalent while those policies differ.
- Recommendation, not yet accepted: runtime-path semantic replay with explicit configuration and Origin=replay, local temporary storage, and no network delivery; feature-rule experiments stay in focused feature-module tests. Reuse the existing module and detector/local-storage adapters; do not add a generic replay framework.
- No choice to preserve or replace current evaluator thresholds has been accepted. Latency scope, failure reporting, and exact replay configuration remain later discussion points. No runtime edits or checks ran in this round.

## Candidate 2 — continued purpose analysis, no selection inferred

- User asked to continue; this is not an explicit choice of runtime-path replay versus standalone feature experimentation. Continue analysis using runtime-path replay as the recommendation only.
- Codegraph reconfirmed that direct evaluators own detector calls, Track updates, and feature dispatch, whereas tools/eval_clip.py already constructs PerceptionPipeline with temporary recorder/outbox storage.
- Separate execution-path reuse from policy parity: sharing PerceptionPipeline does not prove matching model/configuration, sampling, pose scheduling, output, or latency scope. No evaluator threshold change is authorized.
- Distinguish semantic observation/snapshot replay from complete Evidence transfer or live-target readiness. Temporary recorder/outbox objects alone do not establish video coverage, complete artifacts, server receipt, or review behavior.
- Preserve failed/missing/stale versus ok_empty through the runtime seam. A failed observation may yield no event but cannot be reported as a valid negative observation. Current eval_vehicle.py:162 prints clean solely from zero event count; this is evidence of reporting ambiguity, not an independently reviewed negative result.
- Deletion target remains duplicated orchestration, not feature decision logic or sampling/reporting. Reuse existing adapters without a new replay framework. The first unresolved user decision remains the purpose of the replay commands; interface design, detailed configuration, failure-run completion policy, and measurement changes remain pending.
- No runtime code changed and no new checks ran during this discussion.

## Final recommendation agreement

The user explicitly requested **Chốt các khuyến nghị**. This section records the current agreement and supersedes earlier pending recommendation statements. Classification: T0 decision tracking only; no implementation authorization follows from this agreement.

### Candidate 1: shared Suspected incident snapshot construction

- Concentrate full-snapshot construction in one module. Feature modules retain independent scenario rules/state/configuration, severity/confidence, and anchor selection.
- The shared implementation binds authoritative runtime identity/context, per-module configuration, detector and rule lineage, capability quality, and Evidence requests, then validates the full snapshot before the existing EvidenceLifecycle handoff.
- Migrate all affected runtime/evaluator callers and fixtures together. Remove per-feature full-snapshot output and obsolete compatibility paths; standalone feature execution returns scenario facts.
- Preserve existing snapshot/storage semantics, onset versus alert-condition anchors, and EvidenceLifecycle ownership of persistence, pin, transfer, and recovery. No threshold tuning, generic feature base module, or new adapter is selected.

### Candidate 2: runtime-path semantic replay

- Make the evaluator commands primarily exercise the existing Alert feature pipeline module through PerceptionPipeline/PerceptionExecution, not separate standalone feature orchestration. Keep focused feature-rule experiments in feature-module tests.
- Keep video reading, sampling, explicit input configuration, and result summarization outside the seam. Reuse the existing replay detector and local-storage adapters; do not introduce a generic replay framework.
- Keep Origin=replay, temporary local storage, and no network delivery for the proposed replay scope. Temporary recorder/outbox objects alone do not prove complete video Evidence or server/review behavior.
- Distinguish execution-path reuse from policy parity. Do not silently replace evaluator thresholds with pipeline defaults. Matching outcomes requires matching model/configuration, sampling, pose policy, and relevant runtime semantics.
- Preserve observation status distinctions: failed/missing/stale is not ok_empty or a valid negative result. Zero emitted events alone never establishes a reviewed negative pass.
- Observe consumer-visible status, continuity, and emitted/persisted snapshots through the shared interface. Do not pin internal call ordering. This concentrates locality and increases leverage/depth across runtime and replay.

### Constraints and next stage

- Candidate discussions are complete at the recommendation/scope level. No concrete interface/type/method design, new domain term, or implementation plan has been accepted. No glossary or accepted ADR needs editing at this stage.
- Before implementation, produce the required T3 ADR and associated specification work for changed module ownership, preserving ADR-0001–0004 constraints; then resolve the concrete interface and verification path.
- Exact replay baseline configuration, run-completion behavior on observation failure, and latency measurement scope are not assigned new values or behavior here. Determine them from the existing caller contracts and an explicit design decision; do not imply equivalence or a performance gain without evidence.
- Intended order: settle and implement candidate 1's shared snapshot semantics before candidate 2's orchestration cutover, so replay does not target two snapshot shapes. This order does not authorize implementation now.
- Only this tracking document changed during final agreement. No runtime edits, tests, inference, build, typecheck, or hardware checks ran in this finalization round.

## Proposed ADR/specification drafting after user agreement

- User replied **Đồng ý** to the next stage: proposed ADR/specification and concrete interface design. This authorizes documentation/design, not runtime implementation or accepting the newly proposed technical choices.
- Classified the intended ownership/caller change T3. Added ADR-0005 incident snapshot ownership and ADR-0006 semantic replay reuse, both with status proposed; accepted ADR-0001–0004 remain unchanged.
- Compared three independent read-only scout designs: minimal construction function, context-bound session/feature module, and pipeline-private construction. Recommended a stateless construction interface with current context at call time; rejected binding lifecycle overhead and making all snapshot tests depend on pipeline/storage setup. Did not copy the scouts' sample implementation or treat its UUID/UTC generation as a mathematically pure function.
- Source inspection found per-feature producer pipeline_id/version defaults. The proposed interface explicitly preserves these active feature bindings instead of silently overwriting all producers with the common pipeline identity. It also preserves first_qualifying_observation and non-detector rule roles such as vehicle_motion.
- Added two editable draw.io sources under docs/adr/diagrams and opened them using draw.io MCP. They describe proposed ownership, not implemented runtime or Complete evidence. XML structure/link checks passed; no rendered-layout quality claim.
- OpenSpec was absent. Ran `openspec init --tools none --language vi --no-copilot-cloud --no-animation` using the installed spec-driven schema; the Copilot flag was ignored because no tool integration was selected. Adapted openspec/config.yaml with repository/domain/ADR constraints; did not install tools or generate agent instruction files.
- Created change deepen-incident-snapshots-and-replay: proposal.md, design.md, incident-snapshot/spec.md and semantic-replay/spec.md. Kept tasks.md absent at the design approval checkpoint, before a detailed implementation plan. No living specs claim these proposed requirements are implemented.
- Design proposals requiring approval: build_incident_snapshot(facts, *, context, feature), current effective replay settings per command/function rather than pipeline defaults, fail-fast detection statuses outside ok/ok_empty, and process_frame latency including local persistence. Pose status stays independent. These choices are proposed, not retroactively accepted.
- Updated docs/README.md with links to the proposed ADRs/design; did not alter unrelated historical test/benchmark claims, ticket Execution, runtime code or fixtures.

### Documentation checks observed

- `openspec validate deepen-incident-snapshots-and-replay --strict --json`: exit 0, one change passed, no issues on the first validation run.
- `openspec status --change deepen-incident-snapshots-and-replay --json`: proposal/specs/design done; tasks ready but absent, planning/apply incomplete as intended until design approval.
- Temporary Python assertion check: local Markdown destinations exist; all 19 scenarios (9 snapshot, 10 replay) have exactly one mapping row; both ADR statuses proposed; both draw.io XML files parse with unique IDs, valid edge endpoints and geometry; tasks.md remains gated. Result PASS. No permanent test or helper script created.
- Runtime tests, mypy, inference, benchmarks, live camera/native/target checks and deployments did not run because only documentation/design changed. Planned test names in design.md are explicitly not existing/passing evidence.
- Re-ran `openspec validate deepen-incident-snapshots-and-replay --strict --json` after clarifying producer identity in ADR-0005 and snapshot S03: exit 0, one change passed, no issues.
- Fresh read-only ArchitectureDocReader reviewed the six ADR/proposal/design/spec documents and reported no substantive contradictions or gaps. It confirmed the four approval choices, ownership, per-feature producer identity/configuration, anchor/payload/status semantics, and the distinction between planned tests and evidence. This is a document review, not runtime verification.
- Current checkpoint: approve the proposed ADRs/interface and replay baseline/failure/timing choices, then draft the implementation task plan. No code implementation has been authorized or performed.

## Accepted design and implementation-plan checkpoint

- User approved ADR-0005/0006, the snapshot interface, caller-specific replay baselines, fail-fast detection handling and process_frame timing scope. This approval authorizes the implementation plan, not runtime edits. This section supersedes the preceding proposed-design checkpoint without rewriting its history.
- Recorded accepted status in both ADRs; updated design status, documentation navigation, diagram approval labels and OpenSpec context. Accepted design is not implemented or runtime acceptance evidence.
- Created openspec/changes/deepen-incident-snapshots-and-replay/tasks.md: 14 dependency-ordered, unchecked tasks covering inventory, stateless snapshot construction, all five feature producers, pipeline and synthetic fixtures, three evaluators, focused regressions, finite smoke and final verification. Each task names dependencies, size/scope, acceptance and verification.
- Checkpoint A permits isolated constructor verification before caller migration. Tasks 2.1–2.7 and 3.1–3.3 form one unpublished integration batch; only checkpoint B permits declaring the clean cutover complete. No intermediate dual-shape interface, compatibility shim or evaluator-side snapshot reconstruction is allowed. This preserves locality in the snapshot module and leverage for both runtime and replay callers without another adapter.
- CutoverCallerScout identified direct engine-output consumers and synthetic fixtures. Its current-source timing/status generalizations were not adopted: existing evaluator checks do not establish the future pipeline-mediated fail-fast path. The plan explicitly requires checking pipeline.last_observation after process_frame, because [] alone does not distinguish invalid observation from valid empty.
- Added dedicated capacity-fixture task 2.7 and explicit pipeline/quality fixture migration. Legacy compatibility-only tests must be removed with the forwarding entry point; rule, anchor, quality and persistence assertions remain through the supported interface.
- Clarified that proposed test mapping names are illustrative rather than runnable nodeids; new tests follow unittest.TestCase/subTest and focused commands select whole files. New test files remain uncreated at this checkpoint.

### Observed planning verification

- Final `openspec validate deepen-incident-snapshots-and-replay --strict --json`: exit 0, one change passed, no issues.
- Final `openspec status --change deepen-incident-snapshots-and-replay --json`: proposal/specs/design/tasks done; isPlanningComplete=true. Its isComplete=true describes planning artifacts, not implementation completion or user authorization.
- Temporary Python assertions: exactly 14 unique unchecked tasks with dependencies/acceptance/verification; all 19 scenarios have one task-mapping row; relative links in the seven reviewed ADR/change documents resolve; both ADR statuses are accepted; both draw.io approval labels parse and explicitly state not implemented. Result PASS; no permanent helper/test created.
- Read-only PlanReader final review: PASS after task 2.7 and test-convention updates. Confirmed atomic checkpoint B, caller/fixture coverage, compatibility-only test removal, observation-status checks and all tasks unchecked. This is planning review, not runtime proof.
- No runtime code or fixtures edited by this planning work. No pytest, mypy, inference, synthetic-video smoke, live/native/target checks, deployment, commit or push performed. Planned CLI smoke and controlled event/persistence checks remain implementation tasks; zero emitted events will not prove reviewed negatives or Complete evidence.
- Next checkpoint: user approval of this implementation plan and explicit authorization to implement; then start task 1.1. Do not infer implementation permission from accepted ADRs or OpenSpec planning completion.

### Agent self-evaluation

Summary: 4.6/5 for the planning deliverable, not the unimplemented runtime.

- Accuracy: 4/5 — strict validation and document assertions passed; proposed test selectors are not executable until classes exist. Improvement: resolve real nodeids during task 1.1/implementation, as required by the plan.
- Completeness: 5/5 — 14 tasks, all 19 scenarios, caller/fixture migration, failure/resource handling and approval gates accounted for; final read-only review found no substantive gap.
- Clarity: 5/5 — prerequisite, unpublished batch, release checkpoint and planned-versus-observed evidence are explicitly separated.
- Actionability: 5/5 — tasks include concrete files, dependencies, acceptance, verification commands and a single next approval checkpoint.
- Conciseness: 4/5 — repeated gate cautions remain in task sections to prevent partial publication. Improvement: keep the user-facing handoff short rather than repeating the task inventory.
- Overall: 4.6/5. Critical issues: none. Top improvements below 4: none. Verdict: deliver the plan as-is, without implementation claims.
- Self-check: the assessment should match the user's request for an approved-design implementation plan; runtime verification is intentionally not claimed.

### Planned command syntax check

- Ran `bash -n` on the fenced shell block in tasks.md: exit 0. This proves shell syntax only; ffmpeg and all three replay CLI commands were not executed.

## Implementation authorized — 2026-10-30

- User replied “Đồng ý” to implementation-plan approval. T3 implementation proceeds under accepted ADR-0005/0006 and the existing OpenSpec change, without new architecture decisions, dependencies, schema changes or threshold tuning.
- Initial working tree contains prior uncommitted design documents/navigation and codegraph PID artifacts; preserve them. No commit, push or deployment authorized. Language-server status reports no configured server; use codegraph caller/impact evidence for exported-output migration.
- Evidence path: isolated constructor semantics and mutation/anchor checks at A; atomic producer/pipeline/evaluator cutover plus consumer-visible regressions at B; finite local synthetic CLI smoke and controlled event/outbox/failure/pose checks; full pytest, mypy and strict OpenSpec validation. No customer footage or external model calls. No claim of quality acceptance, complete raw Evidence or target capacity.
- Delegated read-only inventory and isolated snapshot prerequisite; parent owns integration, shared docs and final checks. Writing agents received disjoint worktrees/files and instructions to skip mid-flight gates; reported child-only checks are not substituted for parent checks on integrated changes.

### Task 1.1: current caller inventory

- Codegraph located five producer outputs: IncidentEngine._create_incident (incident.py:195–231), full builders danger_zone.py:164–241, vehicle_incident.py:212–285, parking_incident.py:213–281 and crowd_incident.py:395–462. Pipeline.py:640–690 branches on those two legacy shapes; _handle_incident:746–832 and _handle_fall_incident:834–836 must disappear after callers migrate.
- Direct evaluator consumers: eval_all_scenarios.py:162–165 calls four engines; eval_vehicle.py:95 calls vehicle. eval_clip.py:102 and live runner use process_frame and consume full snapshots; run_benchmark remains a process_frame caller, not a second feature loop. Dispatch parameters/error propagation are not changed.
- Rule-test consumers: tracking_incident/on_vehicle/pose_outcomes and feature flow modules inspect producer outputs. Synthetic FallEngine fixtures in test_pipeline.py:25–27, test_quality_odd.py:21 and test_capacity_lab.py:19–23 require complete facts. test_review_fixes.py has direct Person-down anchor assertions. Newly confirmed test_track_gap.py:70 also reads top-level anchor_time and must migrate to payload while preserving its expected anchor 10.0; not merely an unaffected [] consumer.
- Effective evaluator baseline confirmed in current codegraph output: tracker high/low/match 0.25/0.08/0.3; multi Person-down 0.85/1.2/drop15, vehicle15/120, parking20, crowd5/3, CLI200/direct300; vehicle CLI20/150 vs direct8/50, max300; clip CLI max0 and pose opt-in. Existing CLI sample_fps=10 retained. No inference or historical report overwritten for inventory.

### Checkpoint A observed

- Isolated Snapshot agent delivered apps/edge/snapshot.py and tests/test_snapshot.py; parent integrated them without changing runtime producer/caller output. SnapshotFacts/Context/FeatureContext use typed mapping groups; builder is stateless and persists nothing.
- `.venv-oracle/bin/python -m pytest -q tests/test_snapshot.py`: exit 0; 10 passed, 34 subtests passed, no skipped tests reported.
- `.venv-oracle/bin/python -m mypy apps/edge/snapshot.py`: exit 0; no issues in one source file.
- Standalone `.venv-oracle/bin/python -c <temporary driver constructor section>`: PASS for dwell/failed-pose payload retention, first_qualifying_observation anchor 0 with interval [-10,20], matching request session and nested mutation isolation.
- Released producer/fixture agents only after these checks. Prepared a finite synthetic 1280×720 video at 30000/1001 FPS in a new temporary directory using ffmpeg (exit 0); replay smoke has not yet run.

### First integrated Person-down/fixture checks

- PersonFacts delivered the Person-down facts producer and direct rule assertions, preserving onset/qualifying semantics; removed only the obsolete backward-delegation test. Included test_track_gap.py payload-anchor migration.
- Parent replaced pipeline's two output branches and private Person-down builders with one build_incident_snapshot → EvidenceLifecycle.persist path. Context/quality are evaluated for the current frame; feature producer/config/rule lineage remain distinct.
- Focused command `.venv-oracle/bin/python -m pytest -q tests/test_snapshot.py tests/test_tracking_incident.py tests/test_on_vehicle_flow.py tests/test_pose_outcomes_flow.py tests/test_track_gap.py tests/test_pipeline.py tests/test_quality_odd.py tests/test_capacity_lab.py tests/test_review_fixes.py tests/test_architecture_deepening.py`: exit 1; 140 passed, 2 failed, 40 subtests passed, 49 warnings. Both failures were new synthetic pipeline test fixtures: missing producer metadata and a uniform dim frame incorrectly expected to be normal under scoped contrast policy. No production thresholds changed.
- Corrected synthetic producer binding, used a dim checkerboard satisfying declared contrast/blur thresholds, supplied a canonical UUID for reset and a stateless fixture reset method. `.venv-oracle/bin/python -m pytest -q tests/test_pipeline.py`: exit 0, 11 passed. `.venv-oracle/bin/python -m mypy apps/edge/pipeline.py apps/edge/snapshot.py`: exit 0, no issues in two source files.
- Removed disconnected storage from the constructor-invalid-input test: exceptions must originate in the builder, not a following outbox validator. Actual no-intent proof is the pipeline integration test with a real outbox. Full cutover checkpoint B still awaits the four feature producers and evaluator slices.

### Producer integration and controlled runtime smoke

- FeatureFacts delivered four facts-only producers and their direct-rule tests. Actual rule lineage is now metadata on each engine: danger_zone_incident, vehicle_motion/vehicle_incident, parking_incident and crowd_incident; detector provenance remains runtime-owned. No thresholds, temporal state, dispatch parameters or storage schemas changed.
- Parent command `.venv-oracle/bin/python -m pytest -q tests/test_danger_zone_flow.py tests/test_vehicle_incident_flow.py tests/test_parking_incident_flow.py tests/test_crowd_incident_flow.py tests/test_event_delivery.py tests/test_crash_recovery.py tests/test_live_pipeline.py tests/test_rtsp_pipeline.py`: exit 0; 155 passed, 3 subtests passed, 13 warnings, no skipped tests reported. Warnings concern existing FastAPI lifecycle/test-client deprecations.
- `.venv-oracle/bin/python /tmp/camera-replay-smoke-6prp1fuj/pipeline_smoke.py`: exit 0. Finite controlled 720p observations through real tracker/Person-down/danger engines and local outbox emitted/persisted exactly two snapshots: person_fall and danger_zone_intrusion. Snapshot content matched outbox, source anchors/request sessions matched, Person-down fallback quality normal and danger scoped quality low_light remained distinct. Both feature config versions survived a session reset.
- The same temporary driver injected estimator failure (pose status failed while detection stayed ok), then a detection failure (status failed, no new durable event), verified rational observation clock, and confirmed no uploader/network delivery. Constructor smoke also retained first qualifying anchor 0 with [-10,20] and input mutation isolation. No raw Evidence coverage or quality gate was inferred. CLI replay portion and checkpoint B remain pending.

### Replay integration, review corrections and CLI smoke

- Replay agent supplied a patch for three evaluators and two test files. Automatic integration reported failure; its patch also contained removal of the pre-existing docs/README.md navigation row. Parent integrated only assigned code/test paths and restored that row with current status/links after integration. Did not adopt wording-only latency tests, mock-echo CLI-default tests or a new type suppression.
- All evaluators now use process_frame with replay-only local recorder/outbox. Removed their duplicated stage loops and test-only detector keyword. Reused the effective-config reporting helper in existing eval_clip rather than maintaining three copies; tools/__init__.py establishes one mypy module identity for these shared imports (no dependency or new runtime module folder).
- Corrected capture lifetime to include open/get/sampling/model/storage initialization inside try/finally. Explicit missing CLI inputs fail with exit 1; missing auto-selected optional corpus files retain inherited skip behavior. Vehicle/multi CLI reports now display actual effective configuration; commands reporting latency also state the measured process_frame/local-persistence scope.
- SnapshotReview and ProducerReview reported no actionable findings in their scopes. ReplayReview found a real hidden policy change: the old multi-scenario loop selected pose candidates using an external scheduler, but processing used PoseManager’s effective queue/batch budget 30. Passing the external scheduler to the pipeline incorrectly reduced queue/budget to 20/8. Regression with nine eligible people failed before the fix (8 != 9); retaining manager.scheduler restored nine outcomes and the original 30/30 limits. No new pose budget was invented.
- Strengthened R02 to exercise real CLI parser defaults and direct-function defaults at actual event thresholds, not explicitly supplied copies of those defaults. Strengthened R07 to capture real persisted SQLite snapshots before temporary cleanup and compare identity/payload/anchor/session for all three evaluators. R01 compares status counts and full semantic payload plus source intervals.
- R09 controlled clock now observes real detection (2ms) plus real SQLite enqueue (5ms), excluding 100ms decode: reported p50/p95 both 7ms with four persisted events. R10 covers 18 evaluator/exit variants including open, init, first/mid detection and persistence failure, with capture release and actual temporary-directory cleanup.
- Final focused replay command `.venv-oracle/bin/python -m pytest -q tests/test_eval_clip.py tests/test_semantic_replay.py`: exit 0; 15 passed, 28 subtests passed, one existing Starlette test-client warning. A preceding expanded threshold fixture used confidence 0.28 below parking’s own 0.3 gate and failed; corrected fixture to 0.35 (still below runtime tracker 0.5), retaining the real parking outcome expectation.
- `.venv-oracle/bin/python -m mypy domain/ apps/ tools/`: exit 0, no issues in 72 source files. The preceding shared-import run failed with duplicate eval_clip/tools.eval_clip module names; adding tools/__init__.py fixed package identity without a suppression or changing mypy flags.
- Real finite ONNX smoke commands, each exit 0 on the synthetic 1280x720, 30000/1001 FPS video:
  - `.venv-oracle/bin/python tools/eval_vehicle.py --video /tmp/camera-replay-smoke-6prp1fuj/replay-smoke.mp4 --max-frames 3`: 3 processed frames, zero events, CLI vehicle20/150 and tracker0.25/0.08/0.3 reported.
  - `.venv-oracle/bin/python tools/eval_all_scenarios.py --videos /tmp/camera-replay-smoke-6prp1fuj/replay-smoke.mp4 --max-frames 3 --no-pose`: 3 frames, zero events; effective four-feature config and latency scope reported.
  - `.venv-oracle/bin/python tools/eval_clip.py --video /tmp/camera-replay-smoke-6prp1fuj/replay-smoke.mp4 --max-frames 3`: 3 ok_empty observations, Origin=replay, zero events, pose disabled, pipeline tracker defaults and explicit latency scope reported.
- Existing local manifest-authorized artifacts were used; no download, customer footage, network delivery or historical dataset report overwrite. Zero-event CLI smoke is not a reviewed-negative result; controlled event/outbox smoke above supplies the event/anchor/persistence evidence separately.

### Final verification and handoff

- `.venv-oracle/bin/python -m pytest -q --junitxml=/tmp/camera-replay-smoke-6prp1fuj/pytest-results.xml`: exit 0; **890 passed, 188 subtests passed, 360 warnings**, 148.07 seconds. JUnit reports 1,078 cases including subtests, **0 failures, 0 errors, 0 skipped**. Warnings concern existing Starlette/FastAPI lifecycle/test-client and importlib deprecations; no warning suppression added.
- Final production typing gate remains `.venv-oracle/bin/python -m mypy domain/ apps/ tools/`: exit 0, no issues in 72 source files. No production code changed after that successful run; subsequent changes are docs only.
- `openspec validate deepen-incident-snapshots-and-replay --strict --json`: exit 0, one change passed, no issues after implementation/document mapping updates. The OpenSpec change is not archived; no merge, commit, push or deployment performed.
- Verified all 19 scenario rows and 21 fully qualified test nodeids in design.md against the actual full-suite JUnit testcases. Verified no remaining legacy _handle_incident/_handle_fall_incident or feature _build_event/_create_event definitions in apps/edge/tools/tests, and no direct detector.detect/tracker.update/process_tracks/process_pending calls in the three evaluators. Existing recovery/transport fixtures outside this change keep their independent contract setup.
- ReplayReview re-read the corrected implementation and returned PASS with no remaining concrete findings. This source review does not replace the parent’s executed tests/typing/smoke. SnapshotReview and ProducerReview also passed their assigned scopes.
- Updated README evaluator instructions, contract implementation notes, documentation navigation, proposal/design progress and executable scenario mapping. Accepted ADR decisions and diagram designs remain unchanged. No Makefile/build/lint gate exists for this Python reference in the identified repo tooling; no artificial gate was introduced.
- Scope complete: 14 tasks implemented and evidenced. Preserved wire/storage schema, existing authoritative backend/permissions, Evidence durable ownership, feature rules/thresholds/ODD and unrelated historical reports. Runtime replay/model smoke is not held-out quality, Complete raw Evidence, live/native lifecycle, target capacity, network receipt or human-review acceptance.
- Temporary synthetic media, driver and JUnit output are removed after their observed results and node mapping are recorded here; no new test/media/report artifact is left in the repository outside the intended source/tests/docs. Original unrelated working-tree content is not cleaned up.

### Implementation self-evaluation

| Axis | Score | Evidence / limit |
|---|---|---|
| Accuracy | 5/5 | Final tests/JUnit, typing, strict spec validation and real CLI/persistence smoke support the stated reference-path claims; broader acceptance is explicitly excluded. |
| Completeness | 5/5 | All 14 tasks and 19 scenarios covered, including caller defaults, persisted identity, pose budget and error cleanup. |
| Clarity | 4/5 | Current evidence is separated from historical planning records; the long tracking log still requires following headings to distinguish phases. |
| Actionability | 5/5 | Exact commands, full test nodeids, runtime behavior and remaining non-goals recorded; no deferred implementation. |
| Conciseness | 4/5 | Detailed per-step audit log retains some repeated limits; user handoff stays short and links here. |

Overall: 4.6/5. Critical issues: none. Improvements: use the final evidence section rather than earlier planning snapshots for current verification; keep the handoff concise. Self-check: claims match executed evidence and the approved scope. Verdict: deliver without deployment or hardware/quality claims.

## Independent code review — 2026-10-30

- User requested code review, not fixes. Reviewed the uncommitted snapshot/replay cutover against local HEAD `758bc952bce6a1490f0293023860944ad14e7ee1`, including untracked source, tests and design artifacts. The review does not cover previously committed changes since `origin/master`; its merge base is `a1690028ddbeffcf0d6e013bf6440d60a81d0581`.
- Input scope before this review-log addition: **44 files, +3,635/-1,019** (25 tracked changes, 19 untracked files including two empty OpenSpec placeholders). Excluded the pre-existing machine-local `.codegraph/daemon.pid` and `.codegraph/writer.pid`; neither is a deliverable. No production source, tests or config edited during review.
- T3 intent checked against accepted ADR-0005/0006 and all snapshot/replay OpenSpec scenarios. Split the large change into two read-only review lanes: SnapshotReview-2 checked six facts/constructor producers and ten affected test files; ReplayReview-2 checked three evaluators, shared package marker, replay tests and README instructions. Parent reviewed pipeline integration, changed fixtures, context/quality/config binding, durable handoff, documentation and verification evidence.
- **Findings: none requiring author action. Verdict: Approve (Critical 0, High 0, Medium 0).** Both independent lanes returned no confirmed patch-introduced defects. Reserved-field rejection, deep-copy isolation, source anchors, current camera/session/model/quality, per-feature producer identity, and persisted-revision retry ownership remain consistent with the accepted contracts. Removed legacy builder tests match the clean cutover rather than weakening retained behavior.
- Replay review confirmed command/function policy differences, effective pose processing queue/batch 30/30, detection failure versus pose degradation, local-only side effects, snapshot-based reporting and failure cleanup. A possible 100-event pagination issue was investigated and rejected: `EventOutbox.pending()` takes no limit and its SQL uses `fetchall()` without `LIMIT`; this is not a finding.

### Fresh checks executed by the parent reviewer

```sh
.venv-oracle/bin/python -m pytest -q tests/test_snapshot.py tests/test_pipeline.py tests/test_quality_odd.py tests/test_semantic_replay.py tests/test_eval_clip.py tests/test_danger_zone_flow.py tests/test_vehicle_incident_flow.py tests/test_parking_incident_flow.py tests/test_crowd_incident_flow.py tests/test_on_vehicle_flow.py tests/test_tracking_incident.py tests/test_pose_outcomes_flow.py tests/test_track_gap.py tests/test_capacity_lab.py tests/test_review_fixes.py --junitxml=/tmp/camera-code-review-a7oyv89g/focused-junit.xml
.venv-oracle/bin/python -m mypy domain/ apps/ tools/
openspec validate deepen-incident-snapshots-and-replay --strict --json
.venv-oracle/bin/python tools/eval_vehicle.py --video data/benchmark/intersection_traffic_1080p.mp4 --max-frames 3
```

- Focused pytest: **exit 0; 238 passed, 68 subtests passed, 49 warnings, 13.63 seconds**. Parsed JUnit: 306 cases including subtests, 0 failures, 0 errors, 0 skipped. Warnings are existing FastAPI lifecycle and Starlette test-client deprecations, without new suppressions.
- Mypy: exit 0, no issues in 72 source files. Strict OpenSpec validation: exit 0, one change passed, no issues.
- Actual vehicle CLI: exit 0, three sampled frames, 19 detections, zero events; effective CLI vehicle policy 20/150 and tracker 0.25/0.08/0.3 reported. This is an execution smoke only: intersection footage has camera motion and does not establish a reviewed negative or fixed-CCTV acceptance.
- Mutation spot-check used a separate copy of `apps/`, `domain/`, `tools/`, `tests/` under `/tmp/camera-code-review-a7oyv89g/`; the dirty repository was never mutated. Temporarily exempted facts containing only reserved `evidence_requests` from `snapshot.py:121` rejection. Ran `/home/tieubaoca/AI/AI-Camera-OC/.venv-oracle/bin/python -m pytest -q tests/test_snapshot.py --junitxml=/tmp/camera-code-review-a7oyv89g/mutation-junit.xml` with that copy as cwd: **expected exit 1**, exactly one failing `payload_reserved_violation='evidence_requests'` subtest, `ValueError not raised`. Restored the copied guard and reran the entire copied snapshot module: **exit 0, 10 passed, 34 subtests passed**. No mutation remains.
- Both draw.io sources parse as XML; rendered layout was not reviewed. Temporary JUnit/review manifest lives in `/tmp/camera-code-review-a7oyv89g/` and may disappear when temp files are cleaned.
- The author previously logged 890 full-suite tests and 188 subtests; this review ran the focused modules above, not a new full-suite run. No new live-camera/native/hardware, complete raw Evidence, server/upload/UI, deployment, CodeScene or external `ocr` check. No commit, stage, push, merge, new dependency or threshold/model change.
