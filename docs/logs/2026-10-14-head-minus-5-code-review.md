# Two-axis committed code review

## Scope and decisions

- User selected `HEAD~5` and confirmed review against local tickets #17, #18, #24, excluding uncommitted changes; no code fixes.
- Baseline: `fdb6d4543a80a4b76de8344c7ea4cbb5b36c5937`.
- Head: `882d8435291324683f557d133d0e5a9e7c787999`.
- Diff: `git diff fdb6d4543a80a4b76de8344c7ea4cbb5b36c5937...882d8435291324683f557d133d0e5a9e7c787999` (15 files, 2550 insertions, 81 deletions).
- Working tree was already dirty in evidence, health, live_pipeline, quota, implementation log and untracked files. Review uses `git show` pinned committed contents, not those edits.

## Actions

1. Verified baseline, nonempty diff, five-commit log and working status.
2. Used CodeGraph file exploration; Markdown query returned no indexed files. Used tracked Git file list and local tracker instructions to find specs and standards.
3. Read local ticket specs and architecture/ADR standards. No tracked CODING_STANDARDS.md or CONTRIBUTING.md located.
4. User confirmed scope. Planned independent Standards and Spec reviews plus dispatcher evidence verification.
5. Explicit parallel foreground subagents on `n9router/ag/gemini-3.8-flash-high` timed out at the 600-second program deadline without reports. No background jobs remained available to retrieve.
6. Retried read-only reviews using durable teammates `standards-review` and `spec-review`, with shared tasks task-1 and task-2. They inherit the configured teammate route; no model override supplied.

## Results

Both independent reviewers returned evidence-backed reports. Dispatcher verified their cited locations with pinned `git show` output and searched committed application callers with `git grep`.

### Standards — 2 P1 documented-contract breaches

1. `apps/edge/quota.py:72–93,326–378`: active-pin read is separate from deletion; inspection failure returns an empty mapping. Deletion does not share recorder's SQLite write lock. Violates atomic pin/cleanup contract (`docs/architecture/contracts.md:52`); concurrent pin ACK or failed ownership inspection can lose protected evidence. Recorder's existing pruning holds `BEGIN IMMEDIATE` across lookup/deletion (`apps/edge/recorder.py:728–737`).
2. `apps/edge/quota.py:309–323,334–345`: wildcard temporary-file cleanup lacks ownership checks and finalization lock. Violates unknown-file preservation and known-pin locked cleanup (`docs/architecture/contracts.md:59`). Finalization uses the same scratch suffixes under SQLite write lock (`apps/edge/recorder.py:170–171,212–229`).

### Spec — 4 High findings

1. #17: monitor remains starting; `mark_started()` has no committed application caller. `health.py:261–274` gates camera-stall checks on started state; `live_pipeline.py:372–391` starts without marking it.
2. #18: pipeline constructs `EvidenceLifecycle` without quota manager (`pipeline.py:62`), with no quota constructor parameter. Quota checks are bypassed on the normal path.
3. #18: state reserve rejection occurs after event enqueue (`evidence.py:36–45`), leaving an event committed even when reserve is exhausted. Existing quota test asserts failed evidence rather than refusing event persistence (`tests/test_quota.py:335–341`).
4. #18: SQLite pin inspection errors become empty ownership (`quota.py:83–93`), allowing protected unACK segments to be deleted (`326–378`).

Spec reviewer reported in-memory reproductions using committed module source for starting-state, enqueue-before-rejection, and pin-query failure. Dispatcher verification was static source/caller verification, not an independent test execution. No full suite or hardware/field acceptance run. CodeGraph review context returned unrelated project symbols; committed Git source was authoritative. No source fixes performed; only this review log written. Overlap between axes deliberately retained.
