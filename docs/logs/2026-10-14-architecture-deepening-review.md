# Architecture deepening review — 2026-10-14

- Skills: improve-codebase-architecture and codebase-design.
- Scope: recent 30 commits, prioritizing tracking/live preview/evidence recovery.
- Evidence: CodeGraph status/context/explore (55 files), CONTEXT.md, ADR-0001–0004, integration contracts and focused source reads. Existing tests inspected; none run.
- Strong candidate: Evidence lifecycle ownership. Pin-before-enqueue, session-ended handling, duplicate reconciliation and direct SQL/path knowledge motivate deepening. Preserve recorder independence and durable intent protocol.
- Worth exploring: perception execution/status/provenance ownership. Preserve independent feature state and stage toward accepted lifecycle conformance.
- One read-only subagent reviewed perception as requested by the skill.
- Report: /tmp/architecture-review-20261014-055948.html
- No implementation or interface selected; awaiting candidate choice for grilling.

## Exploration round 1

- User selected sequential exploration: candidate 01, then candidate 02.
- Loaded grilling and domain-modeling instructions. No implementation authorized yet.
- Existing ADR-0004 durability, pin ownership and completeness rules remain settled constraints.
- Pending decisions: scope of Evidence orchestration deepening and compatibility of existing entry points. Perception exploration follows after Evidence decisions are settled.

## Exploration round 1 decisions

- User accepted Q1: one module owns Evidence orchestration from durable intent through pin, finalize, transfer receipt and recovery; recorder retains footage/pin ownership, outbox retains durable storage.
- User accepted Q2: preserve existing entry points temporarily as forwarding calls, migrate callers, then remove obsolete forwarding calls.
- Next frontier: recovery execution ownership and explicit source-session completion; implementation remains pending design confirmation.

## Exploration round 2 decisions

- User accepted Q3: one orchestration worker per evidence store coordinates pin/finalize/recovery/upload; recorder keeps independent recording and temporary-file cleanup ownership. No additional process selected.
- User accepted Q4: upload does not end a source session. Partial finalization requires explicit session completion or an explicitly defined timeout policy; no new timeout value selected.
- Final Evidence scope proposal: retain current storage schemas and receipt formats; consolidate duplicated orchestration and direct storage knowledge, and verify behavior through crash/post-roll/partial/idempotency scenarios. Await user confirmation before implementation or moving to perception design.

## Evidence design confirmed; perception exploration begins

- User accepted Q5: retain current storage schemas and receipt formats in the first migration; consolidate orchestration and fix identified ordering/recovery behavior.
- Evidence design exploration is settled. Implementation has not been requested.
- Begin candidate 02: perception execution. Preserve ADR-0001/0004; pending decisions cover canonical observation ownership and migration scope. The full accepted PerceptionPipeline lifecycle remains a separate conformance obligation.

## Perception round 1 decisions

- User accepted Q6–Q7: first deepen shared execution/status/provenance while retaining separate preview rendering and Person fall decisions. Keep OracleDetector replay-only; use a distinct live adapter with truthful lineage, sharing ONNX inference implementation where appropriate. Explicitly report unsupported live execution until that adapter exists.
- CodeGraph confirms OracleDetector.detect rejects non-replay origin; current callers supply replay metadata even when edge Event origin is live.
- Next frontier: handling failed/missing observations in temporal decisions and the scope of sharing execution versus runtime inference instances.

## Perception round 2 decisions

- User accepted Q8–Q9: propagate failed/missing observation status, exclude missing coverage from persistence/onset, reset relevant state on session/epoch change; share runtime inference only for compatible source/session/config, without adding cross-process/network observation transport in the first iteration.
- CodeGraph and focused literal checks show ByteTracker.max_lost_time defaults to 2 seconds; IncidentEngine has no explicit observation-gap policy. Tracker expiry is not an incident continuity policy.
- Pending Q10: conservatively break unconfirmed Person fall temporal evidence at an explicit failed/missing/stale observation; require fresh post-gap onset evidence, retain cooldown and previously persisted events. Scheduled sampling intervals alone do not constitute failures. Longer policy-based gap bridging remains outside this iteration.

## Final design agreement

- User accepted Q10. Both candidate explorations are complete; Q1–Q10 accepted. This records design agreement, not implementation authorization or validation evidence.

### 1. Evidence lifecycle

- Concentrate orchestration from durable intent through pin, post-roll, finalize, verified transfer receipt and recovery in one module. One worker coordinates each evidence store; no extra process is selected. How exclusive worker ownership is enforced remains an implementation detail that must be covered by validation.
- Recorder retains independent recording, pin ownership and safe temporary-file cleanup. Outbox retains durable storage; orchestration callers must not know recorder filenames or issue outbox SQL directly.
- Persist event/outbox/evidence intent before pin. Recovery retries/query preserve immutable request identity and interval. Coverage determines completeness; file presence or upload success does not imply complete coverage.
- Upload cannot implicitly end a session. Partial finalization requires explicit source-session completion or an already defined timeout policy; no new timeout is approved here. If no timeout policy exists, do not invent one during this refactor.
- Preserve existing storage schemas and receipt formats initially. Existing entry points may forward temporarily; remove obsolete forwarding calls after caller migration.
- Verification targets: crash at intent/pin/receipt handoffs; active post-roll; partial recovery; ACK retry; concurrent recording/cleanup; exclusive orchestration ownership. No verification has been run in this design session.

### 2. Perception execution

- Concentrate execution/status/provenance rules in a deep module used by preview and edge processing. Keep preview rendering and Alert feature pipeline decisions distinct; detector/tracker stages remain internal to the eventual accepted PerceptionPipeline implementation.
- OracleDetector remains replay-only. A distinct live adapter must preserve actual origin, source clock, camera/session/epoch and provenance, reusing inference implementation where appropriate. Unsupported live execution must be explicit until that adapter exists.
- Failed/missing/stale observations remain distinct from ok_empty and must not contribute unobserved time or invented onset evidence. Break unconfirmed Person fall temporal evidence on explicit observation gaps; require fresh post-gap evidence. Retain cooldown and persisted events. Normal scheduled sampling is not a failure.
- Reset relevant state on session/epoch change. Do not use ByteTracker.max_lost_time as an incident continuity policy. No new gap-bridging threshold is selected.
- Share inference instances only for compatible source/session/config in the same runtime. No cross-process/network observation transport in this iteration. This scope does not claim the full native/reference lifecycle conformance gate has passed.
- Verification targets: failed versus ok_empty; truthful live/replay lineage; source fallback/session/epoch changes; no pre-gap onset reuse; preserved cooldown; at most one tracker update per accepted frame; unchanged rendering on valid observations.

### Implementation order and status

- Implement Evidence lifecycle first, preserving its schema/receipt compatibility, then perception execution against the settled evidence handoff.
- ADR-0001–0004 remain constraints; no ADR is reopened. No new domain term was adopted, so no glossary file was created.
- Runtime code unchanged; tests not run; implementation and acceptance evidence remain pending a user request to implement.

## Implementation — authorized by user

- User requested execution of the agreed decisions. Implemented Evidence lifecycle first, then perception execution. Local-routing toggle is absent; no local worker was invoked.
- Added apps/edge/evidence.py: durable enqueue before pin; serialized orchestration per recorder root with flock; shared reconciliation and verified transfer receipt ownership. Outbox owns SQL updates; uploader owns HTTP retry/validation. Production synthetic/pin-budget callers use the lifecycle module; compatibility entry points remain for existing tests/external callers.
- Recorder owns cleanup of known pin scratch under the same SQLite write lock as finalize; unknown files are retained. Active post-roll waits until explicit session completion. No schema migration or new timeout.
- Added apps/edge/perception.py: common status/lineage/geometry validation, public provenance and bounded one-observation reuse for a shared execution handle. ONNX implementation has distinct replay-only OracleDetector and live-only LiveDetector adapters.
- Edge processing serializes frame handling, rejects duplicate/stale frames, resets relevant state on camera/session/epoch/origin/config change, and breaks unconfirmed temporal evidence across observation gaps while retaining cooldown.
- Preview preserves actual live/replay/synthetic origin; source changes/file loops change session; fixed 30 FPS clock removed. File capture PTS and RTSP acquisition monotonic clock are distinguished.
- Added behavioral regression tests; updated old tests that expected broad temp deletion, implicit EOF, or stale outbox ACK state.
- Initial system Python test collection lacked pymongo/cv2; validation uses existing .venv-oracle. First related run: 83 tests passed. Broader recorder/replay run: 103 tests, one obsolete ACK assertion corrected and rerun below. Type check passed on eight changed/new modules and regression tests.
- Limits: real camera/native capacity/pose lifecycle and acquisition-to-recorder clock mapping are not established by these software checks. Unknown scratch ownership is preserved rather than guessed.

## Final validation

- `.venv-oracle/bin/python -m unittest tests.test_architecture_deepening tests.test_recorder tests.test_event_delivery tests.test_pin_budget_lab tests.test_oracle_replay tests.test_oracle_detector tests.test_edge_uploader tests.test_crash_recovery tests.test_tracking_incident tests.test_rtsp_pipeline tests.test_live_stream`: 155 tests, OK, 58.702 seconds. Output: `/tmp/architecture-validation.log`.
- Tests include numeric ONNX live/replay adapter checks, metadata lineage and shared-handle inference reuse, gap/onset/cooldown, duplicate frames/epoch reset, explicit EOF, safe cleanup, crash reconciliation and server evidence integration.
- Expanded mypy initially reported existing nested-dict annotations in the touched synthetic caller; annotations corrected to match existing event dictionaries. Final type-check result recorded below.
- Deprecation warnings from existing FastAPI lifecycle hooks and ResourceWarning for existing test MongoClient teardown were present; no test failures.
- No commit, push, deployment or real camera/native readiness validation performed. Unrelated untracked files preserved.
- Final mypy `--follow-imports=silent`: success, no issues in 13 files (all 12 changed/new runtime modules plus behavioral regression tests). `git diff --check`: passed.
