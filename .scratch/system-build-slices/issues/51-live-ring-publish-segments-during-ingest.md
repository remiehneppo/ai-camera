# 51: Live ring publish segments during ingest

Status: ready-for-agent
Execution: not-started
Owner: Edge/platform; chưa claim.

**What to build:** Cho phép recorder công bố segment đã đóng trong khi nguồn còn tiếp tục ingest, để segment/range queryable và event pin có thể bao phủ pre/post-roll trước EOF; giữ semantics hiện có của file replay.

**Blocked by:** [#06: Recorder file replay giữ raw ring độc lập](06-recorder-file-replay-giu-raw-ring-doc-lap.md).

## Acceptance criteria

- [ ] Segment hoàn tất được finalize và công bố nguyên tử ngay trong khi ingest tiếp tục; `segments()`/`actual_range()` phản ánh watermark/coverage tới hiện tại, không chờ EOF.
- [ ] `pin()` trong lúc ingest đang chạy trả receipt theo coverage thật và không ACK phần post-roll chưa tới; finalize/reconcile sau watermark cho ra completeness đúng.
- [ ] Kill/timeout ingest giữa chừng giữ được segment đã finalize, không để `.part` thành dữ liệu hợp lệ, không tạo receipt hoàn tất giả; kiểm tra restart/reconcile trong phạm vi được hỗ trợ.
- [ ] Replay frame decode/delivery tăng dần, không giữ toàn bộ timeline/frame list trong RAM; backpressure/error có bound và behavior rõ.
- [ ] Existing file replay/ring/pin tests giữ nguyên semantics; concurrency regression chứng minh query/pin trong lúc producer chạy bằng synthetic finite/live-like source, không bắt buộc camera thật.

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
