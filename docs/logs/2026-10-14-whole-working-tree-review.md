# Whole working tree review — 2026-10-14

Subsequent authorized remediation and current validation are recorded in
[the fixes log](2026-10-14-whole-working-tree-fixes.md). Findings below preserve
the original review evidence, not the post-fix status.

## Scope and decisions

- User invoked code-review and explicitly selected the whole working tree, including uncommitted and untracked implementation files. No Git baseline/diff restriction applies.
- Reviewed Standards and Spec independently with two reviewers. Used CodeGraph for structure; some runtime symbol snippets had stale locations, so current known files supplied source evidence.
- Sources: AGENTS.md, CONTEXT.md, docs/README.md, architecture/contracts.md, system-architecture.md, implementation-plan.md, ADRs and local slice/live-stream tickets. Pending native/pose/production work is not reported as a newly discovered defect.
- Consulted review.log as hypotheses only. Its placeholder-IP claims are stale/redacted; current Dockerfile has 0.0.0.0, token URLs already encodeURIComponent, and compare_batch intentionally skips absent FRAME keys. Scratch recorder snapshots are historical, not runtime implementation evidence.
- Runtime code, contracts and existing worktree edits were preserved. This report is the only review-authored repository change.

## Standards

### S1 — P1: Default Docker server cannot import its required preview dependencies

Dockerfile:5 installs only requirements.txt (FastAPI, PyMongo, Uvicorn). apps/server/main.py:22 imports live_stream unconditionally; apps/server/live_stream.py:12 imports cv2 and then numpy. Those packages exist only in optional requirements-oracle.txt. A clean image cannot start the advertised server command. Reproduced import failure by excluding optional packages through an import hook in the existing environment: ModuleNotFoundError for cv2. This is dependency/build-path evidence, not a Docker build result. Include required dependencies or make the optional preview integration truly optional.

### S2 — P1: Finalized evidence can be overwritten

apps/server/main.py:370 uses os.replace for every upload; apps/server/store.py:318 replaces the manifest unconditionally. TestClient with isolated filesystem/mock store accepted PUT A and then different bytes B for the same identity, both 200; final file was B. Contracts §3.2 requires immutable finalized bytes and a new artifact identity for replacement. Validate existing identity/hash and make concurrent uploads conflict-safe before publishing; preserve idempotent receipts.

### S3 — P1: Evidence ownership and filesystem path boundaries are unchecked

apps/server/main.py:328 checks only authenticated device identity; lines 360–370 use event_id/request_id directly without validating an event/request relationship. Isolated TestClient PUT for an unknown event/request returned 200. Encoded event_id %2e%2e wrote evidence/escape.mkv outside the intended device/event subtree. This reproduction proves subtree escape, not arbitrary host-file overwrite. Config also permits path-like device IDs. Contracts §3.1 binds requests to an owner event/revision. Validate IDs, path containment, declared request and metadata before filesystem mutation.

### S4 — P1: Review freshness ignores actual evidence and flags identical retries

apps/server/store.py:256–258 compares the submitted evidence map only with event.payload.evidence_versions; it never checks stored evidence manifests. Lines 318–321 mark reviewed events stale on every upload. Disposable real Mongo reproduction: capture a review with {}, upload complete v1, submit captured review => confirmed with {}, needs_re_review=False; identical upload retry => needs_re_review=True. Contracts §5 requires exact viewed evidence versions, conflict on meaningful changes, and no re-review from retry. Read/version evidence within the review/update concurrency boundary and compare meaningful content.

### S5 — P1: Server evidence has no persistent container storage

compose.yaml:24 defines server without an evidence volume; apps/server/config.py:81 defaults to /tmp/ai-camera-evidence. Container recreation loses acknowledged clips while Mongo receipts persist on a separate volume; edge may already release local pins. Contracts §4 requires a durable server location/commit. Mount persistent writable evidence storage and exercise recreate recovery. Additionally, upload rename lacks directory fsync required by §3.2. Container recreation and power-cut were not performed.

## Spec

### P1 — P1: Temporary FFmpeg timeout becomes terminal evidence failure

apps/edge/evidence.py:90–93 classifies every SubprocessError as terminal, including TimeoutExpired. Lines 77–78 skip failed requests on later reconciliation. Isolated fake-recorder reproduction: first finalize timeout marks failed; second reconcile never retries (finalize call count remains 1), despite retained media. Contracts:59 says temporary I/O errors remain retryable. Distinguish transient subprocess failures from irrecoverable media failure.

### P2 — P1: Continuous RTSP recording does not prune the ring

apps/edge/recorder.py:357 prunes on ingest exit; publication at 391–420 does not prune. apps/edge/rtsp_recorder.py:157–167 neither advances a watermark nor releases pins during idle continuous recording. With no events, published segments accumulate until stop instead of obeying the ten-minute ring in contracts:37. Storage eventually fills. Trigger retention during publication with the existing pin/cleanup synchronization. Structural finding; no live-camera soak performed.

### P3 — P1: Tracker and incident state grow throughout a session

apps/edge/tracker.py:86 appends active history without trimming; :249 retains every new track, and :251–263 marks removed tracks without retiring them. apps/edge/incident.py:56–61 retains ended state. Isolated reproduction created/removed 1,000 tracks and retained all 1,000. Pipeline clearing inactive history does not remove these objects. Per-frame scans and active-track history costs grow with session duration. implementation-plan:184 requires bounded TrackSnapshots; system-architecture:140 requires bounded history. Trim history by time and retire ended state under an explicit bounded policy.

### P4 — P2: Standing recovery during cooldown can suppress later falls indefinitely

apps/edge/incident.py:69–72 returns early before standing recovery clears triggered at :81–87. Reproduction: alert at 4.1s, stands at 10s, falls at 20s, remains lying at 35s => no event and triggered remains true after cooldown. tests/test_tracking_incident.py:339 documents another authentic fall after cooldown/re-standing. Update observation/recovery state during cooldown while suppressing emission.

### P5 — P2: Dataset evidence does not preserve the reviewed snapshot

apps/server/store.py:428–432 joins every current evidence manifest for the event; it does not select the evidence IDs/versions recorded by the review. export_dataset_records includes those manifests next to the exact reviewed event revision. A clip added or replaced after review therefore appears as if it belonged to the reviewed dataset record, especially with include_ambiguous=True. Ticket #20:16 requires exact reviewed event/evidence versions, not a current join. Persist/select immutable manifest snapshots matching the viewed version map. Source-verified; no additional end-to-end export reproduction was run.

### P6 — P2: Dashboard polling destroys active evidence playback

apps/server/static/index.html:130 clears every event DOM node; :303 repeats refresh every three seconds. Evidence video nodes are rebuilt at :237–242 (and the declared-request branch). Playback/buffering and expanded audit details are lost on the next successful poll. This defeats ticket #08 evidence playback during review. Preserve stable keyed nodes or pause structural refresh during playback. Source-verified; no browser run was performed.

## Validation and limitations

- .venv-oracle/bin/python -m unittest discover -s tests: 246 tests, OK, 76.315 seconds. Full captured output: /tmp/ai-camera-review-tests.log. Initial verbose run completed too, but tool output truncation obscured its summary; the recorded run resolved that verification gap.
- Deprecation and unclosed-MongoClient ResourceWarnings were emitted; no test failed. Existing tests do not cover the reproduced immutable-upload/freshness scenarios.
- Upload/path reproductions used mock store plus real filesystem. Freshness reproduction used a disposable Mongo DB, dropped afterward. Timeout/tracker/cooldown reproductions were isolated and did not alter repository code.
- No fixes, dependency installation, Docker image build/recreation, browser QA, live-camera soak, power-cut, target or production acceptance. Passing tests do not establish deployment readiness.
- Findings: Standards 5 (worst: P1 default Docker startup, immutable evidence and durability); Spec 6 (worst: P1 recovery/retention/bounded-state failures). No cross-axis reranking.
