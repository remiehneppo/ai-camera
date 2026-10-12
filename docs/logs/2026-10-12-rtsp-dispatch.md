# RTSP camera configuration and live-path dispatch — 2026-10-12

## User-confirmed decisions

- User supplied a lab RTSP URL and asked to use it in project config, then continue decomposing and delegating work.
- Credential handling: store the URI only in ignored `.env.local`; never put it in tracked config, docs, task text, logs, test output, or commit. Add a placeholder/example without credential.
- User permits a direct camera probe if reachable, with bounded timeout and no secret leakage.
- User selected live RTSP end-to-end integration as the intended target, not merely local config. This target exceeds the current executable code path and remains gated by dependencies below.

## Code and hardware evidence

- CodeGraph scoped to `/home/tieubaoca/AI/AI-Camera-OC`: `apps/edge` currently includes file/replay recorder and oracle labs; no RTSP live adapter/startup path was found. `FileRecorder.replay` takes a local `str | Path` and constructs `Path(source)`.
- `.scratch/system-build-slices/issues/15-camera-rtsp-live-giu-correlation-voi-recorder.md` is `needs-info`, `not-started`; blocked by #02 and #14. Acceptance requires a probe-informed stream ADR/topology and real session/discontinuity/time-correlation proof.
- #02 facts/profile was completed as workstation inventory but explicitly had no camera facts then; its field/site, ODD, recovery and capacity signoffs remain open.
- #14 observation-to-event pipeline is not started and its bounded queue/durable pin/event contract remains open.
- Direct read-only probe used `ffprobe -rtsp_transport tcp -timeout 5000000`, output filtered through redaction: camera reachable; video H.264 Main 1920x1080 15fps, audio AAC LC. No session concurrency, reconnect behavior, timestamp mapping, ownership, or recorder/analytics correlation was tested.
- Do not mark #15 done, claim live E2E, change its blockers, or treat probe output as target/field acceptance.

## Confirmed public test seams

- User approved (1) a loader reading `CAMERA_RTSP_URL` from `.env.local`/environment and validating without echoing secrets; (2) a probe wrapper accepting URL + timeout and returning codec/resolution/FPS while redacting URI in errors. Automated tests must fake subprocess; live probe is a separate manual operation.

## Dispatch plan

1. Safe local configuration: protect `.env.local` via `.gitignore`, write supplied URI locally only after ignore protection is in place, add a non-secret example/sample config and a small non-network config/probe interface with redacted errors; add focused public-interface tests. This is a bounded preparatory vertical slice, not live ingest.
2. RTSP integration gap report: read-only assessment of current recorder and observation/event seams; map prerequisite work, acceptance evidence, and non-overlapping future tasks for #14/#15. No source edits.
3. Lead reviews source/config diff and evidence; ensure local credential file is ignored and absent from git diff/status. Update #02 factual probe record and #15 handoff with secret-free evidence while retaining blocked status. Run focused tests; full suite only if change footprint warrants and at final acceptance.

## Implementation and independent assessment

- RTSP config/probe module and fake-subprocess tests were produced by the implementation agent in `apps/edge/rtsp.py` and `tests/test_rtsp.py`; independent verification by dispatcher: `python3 -m unittest tests.test_rtsp` → 16 tests passed. Agent reported `python3 -m unittest discover -s tests` → 108 passed, 22 skipped; `.venv-oracle/bin/python -m mypy apps/edge/rtsp.py tests/test_rtsp.py` → no issues in those files. (Another agent reported a different full-suite count while testing a concurrent tree snapshot; numbers not identical, therefore only dispatcher-run focused result is relied upon here.)
- Agent reported not editing `rtsp.py` because it was already present and a concurrent writer changed `tests/test_rtsp.py` mid-turn. Working tree currently has the two files untracked; treat provenance/history as uncertain. No commit.
- Config records URL only in ignored `.env.local`, whose ignore rule is verified; `.env.local.example` is placeholder-only. Unit tests use synthetic credentials only. The `ffprobe` URL remains visible in local process arguments while executing; this is a local-host trust limitation. Automated tests mock subprocess; no real camera probe by this implementation agent.
- Independent static analysis identified a structural live-ring gap: `FileRecorder.record_file()` only publishes finalized segments after EOF, and replay enumerates whole frame inventory. User chose new ticket #51 depending on #06 rather than widening #06. Ticket #15 now depends on #02/#14/#51 and remains `needs-info` / not-started.
- Earlier dispatcher direct probe, with bounded `ffprobe` timeout and redacted output, observed H.264 Main 1920×1080 15fps plus AAC. It did not test session concurrency, reconnect, timestamp correlation, firmware, topology, or acceptance; do not treat it as satisfying #15/F04.
- User-approved ticket decomposition: #51 (`ready-for-agent`, `not-started`) for live-capable segment publication/streaming replay, blocked by #06. #15 now has #51 as an additional blocker. Updated PRD tracker and docs index count to 51; #15 comment records evidence without endpoint/credentials. Static standards review requested this tracker reconciliation and append-only ticket history; both now applied.

## Worktree constraint

Initial status contained pre-existing untracked `.codegraph/` and `AGENTS.md`; these are not part of this task and must not be committed.
