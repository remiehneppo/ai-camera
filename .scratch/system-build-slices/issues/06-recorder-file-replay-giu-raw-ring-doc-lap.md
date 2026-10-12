# 06: Recorder file replay giữ raw ring độc lập

Status: ready-for-agent
Execution: partial
Owner: Codex (Edge recorder/replay baseline); target/hardware acceptance chưa claim.

**What to build:** Chạy recorder từ file cleared theo thời gian nội dung; dừng analytics vẫn query được raw segments và actual ranges.

**Blocked by:** [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md).

## Acceptance criteria

- [x] File replay tạo compressed stream-copy segments có codec/keyframe/PTS/session metadata, queryable raw ring, watermark và actual range; raw không overlay.
- [x] Actual range báo `missing_preroll`, `missing_postroll` và continuity gaps trên metadata segment.
- [ ] Pin/post-roll lifecycle và recovery chưa có; chưa có RTSP camera test.

- [x] Semantic file replay dùng fixed PTS sampling/virtual event time, synchronous consumer backpressure và monotonic watermark; fixture fast/realtime có cùng PTS.
- [ ] Cùng domain outcomes cần analytics consumer; realtime stress/drop/coverage cần runtime workload, hiện chưa có để kiểm.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: V01, R01, C01, C03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
- 2026-10-12: Bổ sung recorder pin registry bền vững cho request ID/owner/interval; cùng request trả receipt cũ, nội dung khác conflict, cleanup giữ segment giao với pin active, release idempotent. Restart recorder vẫn đọc ownership; `pin_status` cập nhật coverage theo segment hiện có. Execution tiếp tục `partial`: chưa có finalized clip/post-roll manifest và reconciliation file/DB crash; RTSP, analytics consumer, realtime workload và hardware chưa nghiệm thu. Chi tiết: [implementation log](../../../docs/logs/2026-10-12-ticket-06.md).
