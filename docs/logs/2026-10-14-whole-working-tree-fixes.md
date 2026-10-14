# Whole working tree remediation — 2026-10-14

## Authorization and scope

User authorized "Fix all" for the 11 findings in
[the review](2026-10-14-whole-working-tree-review.md). Existing uncommitted/untracked
work was retained. No commit, push or deployment was requested or performed.
Used CodeGraph context/callers before editing; current known-file source was
used when index coverage/locations were insufficient. Applied the existing
Ponytail and Karpathy guidance, and browser skill for local UI validation.
Local routing toggle was absent, so no LM Studio worker was invoked.

## Changes and acceptance

| Finding | Change | Verification |
| --- | --- | --- |
| S1 Docker startup | Required NumPy/OpenCV installed; Python 3.12 matches pins; copied source belongs to UID 10001 so private host modes do not prevent imports | Real image build and non-root Uvicorn startup; Mongo readiness and dashboard return 200 |
| S2 immutable evidence | Exclusive hard-link publication prevents overwrite; same bytes retry safely recovers publication-before-DB crash; DB rejects changed artifact hash/size or request identity/interval | Different-content and concurrent uploads, identical receipts, simulated DB outage after publication |
| S3 ownership/path | Validate storage IDs and root containment; resolve declared request from immutable event revision; validate provided owner/session/interval metadata before writing | Unknown event/request, parent path and mismatched metadata rejected without creating evidence files |
| S4 review freshness | Uploaded manifest versions override producer version claims; review/evidence updates share the current-event transaction write guard; identical upload is a no-op; meaningful changes flag re-review | Stale review rejected, concurrent review/upload cannot lose flag, identical and transport-only retries do not set it |
| S5 durability | Persistent server-evidence volume at the original path; non-root ownership; file and directory fsync before DB receipt | Two independent containers write/read the same volume; directory/file paths unchanged |
| Spec P1 retry | Temporary subprocess errors preserve retryability; explicit invalid-media diagnostics become terminal ValueError | Timeout/generic FFmpeg failure retry twice; existing corrupt-clip isolation test remains passing |
| Spec P2 ring | Publisher prunes during ingestion using existing pin/write-lock protection; its probed-path set retires old entries | FIFO producer held open while ring prunes; pinned old segment survives |
| Spec P3 bounded state | Five-second/256-observation motion history; removed tracker objects retired; absent incident state expires after cooldown | 1,000 create/remove cycles leave no removed tracks or incident state; 5,000 observations obey cap |
| Spec P4 cooldown | Continue observing recovery/onset during cooldown; suppress only emission | Second fall starts during cooldown and emits after expiry using its observed onset |
| Spec P5 dataset lineage | Review/audit store exact manifest snapshots; export uses them and includes manifest_version; unknown legacy snapshots are excluded by default or marked ambiguous | Later metadata/evidence does not rewrite reviewed dataset snapshot; internal file paths stripped from nested audit snapshots |
| Spec P6 playback | Pause structural refresh during active playback, including requests already in flight; preserve expanded details; serialize refresh | Real Chromium playback over two polling intervals, details restored, delayed-response race preserved |

Evidence reads now persist missing/corrupt location detection through the same
versioned metadata path, setting freshness without rewriting historical review
snapshots. Integrity checks are centralized in the store rather than hashing
the same file twice in each GET route. A pre-existing missing generic annotation
in server doctor was corrected to make the complete type check pass; no runtime
doctor behavior changed. Legacy dataset fixtures now use integer manifest
versions, and the upload fixture declares the request ID it uploads.

## Commands and evidence

- `.venv-oracle/bin/python -m unittest discover -s tests`: **260 tests, OK**,
  81.454 seconds. Log: `/tmp/ai-camera-fix-tests.log`.
- `.venv-oracle/bin/python -m mypy domain apps tools`: **Success, 36 source files**.
  Log: `/tmp/ai-camera-fix-mypy.log`.
- `git diff --check`: passed.
- `docker build -t ai-camera-oc:review-fixes .`: passed.
  Log: `/tmp/ai-camera-fix-build.log`. Existing stack/image tag was not replaced.
- Isolated non-root image smoke test on loopback port 18767: Uvicorn startup,
  real Mongo readiness, `/healthz` and `/` passed. Disposable
  `review_image_smoke_20261014` database dropped in finally. Log:
  `/tmp/ai-camera-fix-image-smoke.log`.
- Separate `--network none` container read `durable` from the test volume at
  `/tmp/ai-camera-evidence/recreate-check`, proving recreation persistence.
  Test volume: `ai-camera-review-fixes-evidence`.
- `browse` local CLI could not open its session; its installed Playwright
  expected missing Chromium 1243. Used already-installed Chromium 1234 explicitly,
  without downloading dependencies. Headless self-check in
  `/tmp/ai-camera-review-ui.cjs`, served current HTML against a loopback fixture:
  playback time 7.018754s, same video node, playing; details preserved; polling
  resumed; in-flight polling race preserved; no page errors. Log:
  `/tmp/ai-camera-fix-browser.log`.

## Deployment and limits

- **Not deployed.** Before replacing any older server, copy its ephemeral clips
  into the persistent volume. Keeping the original path avoids a Mongo file-path
  migration, but cannot recover clips already lost with an old container.
- Legacy reviews cannot reconstruct a manifest version that was already
  overwritten before this fix. Such unavailable lineage is not silently joined
  to a current artifact; ambiguous export or re-review is required.
- Fixed motion-history limits cover the lab sampling envelope, not arbitrary
  high-FPS acceptance. No real camera soak, target/RKNN, power-cut or pilot checks.
- Image smoke tests validate API/dashboard startup; optional ONNX inference
  still needs its runtime/model assets and was not accepted in this test.
- Existing FastAPI/httpx deprecation and test MongoClient ResourceWarnings
  remain non-failing; they are not claimed fixed by this scope.

## Authorized test-data cleanup

User clarified that all clips are disposable test data and requested cleanup.
Live inspection found the running server's `/tmp/ai-camera-evidence` empty and
the smoke-test volume unused. Removed generated `.scratch/replay-measurements`
H.264 clips, numeric `ring-*` stores and Python caches; `/tmp/ai-camera-ticket07`
clip/recorder/outbox artifacts; the event smoke SQLite file; temporary UI/image
smoke scripts and video; and volume `ai-camera-review-fixes-evidence`.
Kept runtime source/uncommitted changes, measurement scripts/results, validation
logs, pinned ONNX/reference assets and existing MongoDB volumes. No clip migration
is needed for this empty lab evidence store. Smoke script/video/volume paths above
record historical checks and were intentionally removed after verification.

## Local commit preparation

User requested a local commit after cleanup. Commit scope includes the integrated
evidence/perception refactor, all review fixes, regression tests and their docs.
Local AGENTS.md, CodeGraph index, measurement scratch artifacts and raw review.log
remain outside staging. Reused the verified 260-test/type/Docker/browser results;
did not regenerate deleted clips by rerunning tests. Checked the final staged
diff for whitespace errors. No push or deployment is authorized by this request.
