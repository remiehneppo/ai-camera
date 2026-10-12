# #51 hardening — 2026-10-13

## Confirmed decisions

User selected hardening #51 before camera-live/native work and explicitly confirmed shared understanding of acceptance before implementation. Public test seams: FileRecorder.ingest/replay/reconcile. Probe timeout/system failure must clean up boundedly and preserve unclassified media. Only proven malformed/incomplete parts may be discarded. Verify first replay delivery before EOF and measure Python/ffprobe memory on longer synthetic fixtures. These are software-lab observations, not production SLOs or a process-wide memory guarantee. No camera contact or credentials; no RTSP/G1 gate changes.

## Plan and ownership

- Recorder executor exclusively owns apps/edge/recorder.py and tests/test_recorder.py (additional focused test file permitted). TDD at confirmed public seams; regression and type-check evidence required.
- Independent assessor owns no tracked files: temporary fixture measurements of incremental replay and Python/child memory; source review read-only.
- Dispatcher owns tracker/README/log updates, final review and acceptance. Pre-existing untracked .codegraph/ and AGENTS.md excluded.

## Baseline

HEAD e747b55; tracked worktree clean before this log. CodeGraph was queried with explicit projectPath, but line mappings appear stale; source reads are authoritative. Existing _probe treats all ffprobe stderr/nonzero exits as IncompleteSegment; reconcile may consequently delete valid media on system failure. Probe subprocess waits and publisher.join need bounded-failure inspection. Replay uses ffprobe CSV, so prior claims of internal JSON buffering require empirical correction rather than speculation.

## Implementation and verification

- Configurable keyword-only `probe_timeout_seconds=30` is a software safety budget, not a production SLO. Metadata/closed-segment probes use per-call wall-time limits. Replay CSV uses bounded binary chunks and read-inactivity/post-EOF wait limits; callbacks and realtime pacing are excluded.
- System/unknown stderr, negative probe exit, timeout and other operational errors preserve unclassified media for retry. Only all-recognized premature-EOF/EBML-header/invalid-input diagnostics allow removal. Preserved parts remain unpublished and are not valid ring data.
- Lead verified RED timeout test (unsupported constructor keyword), then GREEN. Operational-error RED covered five misclassified subcases; lead GREEN confirmed preservation. First full recorder regression exposed two unclassified trailing-header cases; actual ffprobe diagnostics justified narrowly adding malformed-header categories rather than broad deletion.
- Lead verification: `.venv-oracle/bin/python -m unittest tests.test_recorder tests.test_oracle_replay tests.test_replay_lab tests.test_pin_budget_lab tests.test_oracle_recorder_lab -q`: 63 tests OK. `.venv-oracle/bin/python -m unittest discover -s tests -q`: 138 tests OK (no skipped tests reported), with existing importlib/ONNX warnings. Targeted mypy recorder clean; diff-check clean.
- Standards review: no documented violations; two optional duplication smells (CSV record construction and test probe setup), not blocking. Spec review: no blocker in confirmed probe-failure scope; independent five new public-seam tests pass. Executor corrected diagnostic docstring; no broad refactoring.

## Incremental replay and memory evidence

Ubuntu ffmpeg/ffprobe 6.1.1-3ubuntu5, Python 3.12.3, Linux 7.0.0-31-generic x86_64. Synthetic gray H.264/libx264 ultrafast CRF28 yuv420p GOP60 threads1 MKV, 320x180 at 30 FPS, durations 10/100/1000/10000 seconds. Fast replay with sample_fps=30 and non-retaining consumer; empty ring. Three independent processes per duration.

All 12 final runs delivered first callback before observed CSV EOF with the actual frame ffprobe still alive. Across these runs, sampled peak RSS: Python 21,320–22,316 KiB, ffprobe 50,612–53,324 KiB, simultaneous RSS sum 71,996–74,712 KiB. At 10,000 seconds, first callback 0.084763–0.091768s versus EOF 6.201533–6.569099s. Lead parsed final JSON results and independently confirmed all 12 incrementality checks.

No duration-proportional RSS growth observed in this fixture family across 1000x duration; this is not a hard memory bound. RSS samples at nominal 1ms may miss spikes; summed RSS double-counts shared pages. Callback allocations, nonempty rings, resolution/codec/content/GOP, concurrent recording and target hardware were not measured. Metadata probing separately captures JSON per segment; keyframe constraints can make segments exceed nominal duration. Requested 30 sample FPS yields 20 callbacks/s on 1/1000 timestamp grid under existing sampling semantics; these measurements do not assert every frame was delivered.

Evidence snapshot recorder SHA256 0220a32da9fa5d825cc9a9a2d5645595955ad5e4564fea75970145daff7cea06; final docstring-only update SHA256 b63037c5ed78e58b3a02ae5ca7e0b62679906a6e9e76ad4516df8a3b8161b8c1. Temporary harness/results under `.scratch/replay-measurements/` are not committed. Reproduce while retained with `bash .scratch/replay-measurements/reproduce.sh`; fixture generation uses `ffmpeg -f lavfi -i color=c=gray:s=320x180:r=30 -t <duration> -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p -g 60 -threads 1 <fixture.mkv>`. Harness wraps only subprocess observation (actual ffprobe), polls /proc VmRSS and counts callback/EOF timing, storing snapshot checksum per row.

## Residual limits and handoff

Publisher join has a budget after producer exit, scaling with remaining parts; it cannot cancel arbitrary filesystem/fsync stalls. `_reap` can wait while both stalled publisher and producer remain alive; a daemon publisher may outlive failed ingest and later publish. Therefore no universal ingest deadline/storage cancellation/thread-cleanup guarantee is claimed. Normal ongoing ingestion intentionally has no whole-session deadline. Partial-byte trickle is capped by line size but read deadlines reset per read, not a whole-frame deadline. #51 remains partial; RTSP/G1/native gates unchanged.

Executor initially reported a test sandbox denial; no alternate retry of denied operation authorized. Lead ran that exact command successfully without a denial. Independent assessor reported no denials. Only intended source/tests/docs are delivery candidates; temporary measurement outputs, AGENTS.md and .codegraph remain excluded.
