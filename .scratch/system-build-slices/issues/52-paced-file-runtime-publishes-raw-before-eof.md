# 52: Paced file runtime publishes raw before EOF

Status: needs-triage
Execution: blocked
Owner: unassigned

**What to build:** Extend the currently fast-only independent file recorder/ONNX detector runtime with truthful paced ingest that publishes raw segments before source EOF. Do not equate paced input with incremental ring availability.

**Blocked by:** #06 runtime baseline; investigation of downstream FIFO probing/buffering and public ingest support.

## Acceptance criteria

- [ ] Public runtime accepts realtime only once actual incremental raw publication is supported; fast defaults/callers remain unchanged.
- [ ] Real cleared six-second file fixture, recorder still alive around two wall seconds; controlled analytics worker termination does not unwind recorder ownership.
- [ ] Raw range/segment end-time advances before source EOF while recorder remains alive (current diagnostic target: by five wall seconds for six-second fixture; lab tolerance, not signed target SLA).
- [ ] Final complete/partial coverage is truthful; no post-EOF burst presented as real-time availability.
- [ ] Graceful/forced cleanup reaps owned producer/decoder/recorder processes, with bounded stop configuration and explicit storage limits.
- [ ] Default recorder behavior and existing replay/clip regressions pass; no RTSP/hardware/capacity claims from software fixtures.

## Evidence and decisions

- 2026-10-13: User Q9 approved review/commit of verified fast-only runtime instead of indefinite realtime debugging. New runtime/config reject realtime explicitly; existing oracle replay remains unchanged.
- Actual RED: realtime progress-before-EOF assertion `advanced unexpectedly None` in authorized runtime suite; first four fast/isolation tests passed. First progress-only test was insensitive (passed unpaced ingest); strengthened independent wall/content timing exposed the gap.
- Paced FIFO stream-copy producer took ~5.8s for six-second content. Producer byte arrivals at0.03s/0.53s/1.03s confirmed early input. Default and tested minimal analyze/probe/flush controls still yielded no first sidecar while producer alive. Final direct-buffer attempt failed FFmpeg183. All ineffective recorder options reverted; no workaround retained as a guarantee.
- See docs/logs/2026-10-13-runtime-dispatch.md and docs/logs/2026-10-13-runtime-runtime.md. This ticket is a follow-up blocker, not implemented or accepted.
