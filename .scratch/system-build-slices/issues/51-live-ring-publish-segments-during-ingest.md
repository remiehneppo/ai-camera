# 51: Live ring publish segments during ingest

Status: ready-for-agent
Execution: partial
Owner: Edge/platform; chưa claim.

**What to build:** Cho phép recorder công bố segment đã đóng trong khi nguồn còn tiếp tục ingest, để segment/range queryable và event pin có thể bao phủ pre/post-roll trước EOF; giữ semantics hiện có của file replay.

**Blocked by:** [#06: Recorder file replay giữ raw ring độc lập](06-recorder-file-replay-giu-raw-ring-doc-lap.md).

## Acceptance criteria

- [x] Segment hoàn tất được finalize và công bố trong khi ingest tiếp tục; metadata sidecar là điểm commit hiển thị atomic, `segments()`/`actual_range()` không chờ EOF.
- [x] `pin()` trong lúc ingest đang chạy trả receipt theo coverage thật, không ACK post-roll chưa tới; `finalize_pin()` yêu cầu đủ post-roll trừ khi được yêu cầu finalize partial.
- [x] Kill/timeout ingest giữ segment đã finalize, bỏ part dở, không tạo receipt hoàn tất giả; crash giữa rename media và sidecar được `reconcile()` xử lý idempotent.
- [x] Replay đọc timestamp ffprobe tăng dần, không giữ list frame phía Python; callback synchronous giữ backpressure, subprocess dọn khi callback lỗi. `ffprobe -show_frames` vẫn có thể buffer JSON nội bộ, nên chưa khẳng định hard bound tổng bộ nhớ probe.
- [x] File replay/ring/pin regression giữ semantics; synthetic FIFO tests chứng minh query/pin trước EOF, kill/restart và replay khi ffprobe producer vẫn chạy.

## Non-goals and gates

- Ticket này không chọn dual-session hay recorder-owned relay; không mở analytics upstream session. Stream ownership/topology cần probe-based ADR trong #15/F04.
- Fixture/lavfi test không thay live RTSP acceptance; reconnect, codec change, PTS↔wallclock uncertainty và camera session limit vẫn gated bởi #02/#15.
- Không dùng camera credential trong test/fixture/log.

## Traceability

Discovered while decomposing user-requested live RTSP recorder+analytics path. Existing #06 acceptance covers file replay and RTSP camera acceptance remains open, but its finalize-after-EOF behavior prevents a live ring/pin; this prerequisite is explicitly separated here.

## Evidence and handoff

Ghi focused regression commands, concurrent-ingest query/pin receipt, mid-ingest termination/reconcile evidence và memory behavior; cập nhật #06/#15 handoff khi đạt. Unit tests không đóng #15 hoặc G1 live acceptance.

## Comments

- 2026-10-12: Tạo theo quyết định người dùng: blocker live-ring được theo dõi bằng ticket riêng phụ thuộc #06, không mở rộng acceptance file-replay #06. Căn cứ: `apps/edge/recorder.py` công bố segment sau EOF và `_frames()` materialize toàn bộ nguồn trước replay; xem `docs/logs/2026-10-12-rtsp-dispatch.md`.
- 2026-10-12: Software slice implemented with synthetic FIFO sources only. `FileRecorder.ingest()` publishes closed segments as ingest continues; `pin()`/outbox retain honest collecting/post-roll status until coverage is complete; `reconcile()` repairs crash window between media rename and metadata sidecar; `replay()` streams ffprobe frame timestamps incrementally without retaining a Python frame list (ffprobe itself may buffer internally; no process-wide memory bound claimed). Focused recorder suite 36 pass; related replay/oracle suites 22 pass, 4 skipped; full suite 133 pass, 22 skipped; targeted mypy for `apps/edge/recorder.py` clean. Acceptance is software-only; RTSP/session topology, camera reconnect/codec change/time correlation, concurrency limits and G1 live remain untested and #15 stays blocked. See [implementation log](../../../docs/logs/2026-10-12-ticket-51.md).
