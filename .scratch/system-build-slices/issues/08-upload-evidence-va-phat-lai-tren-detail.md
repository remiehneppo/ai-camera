# 08: Upload evidence và phát lại trên detail

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Clip edge upload tới server, người trực xem/download qua detail kể cả event metadata đến trước clip.

**Blocked by:** [#07: Event pin được clip pre/post từ ring](07-event-pin-duoc-clip-pre-post-tu-ring.md).

## Acceptance criteria

- [ ] Upload retry/resume cùng evidence identity, verify hash/size trước receipt; metadata/clip ACK tách.
- [ ] Server kiểm object ownership/authz, range/content type; pending/failed rõ, H.265 có playback path được kiểm hoặc lỗi rõ.

- [ ] Partial clip upload/ACK vẫn partial; expired/corrupt location không bị receipt lịch sử làm available; hash/bytes finalized bất biến.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: J03, E01, E02, UI01, UI02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
