# 05: Retry và revision không làm mất hoặc lùi event

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Edge retry sau mất response; dashboard vẫn giữ một lịch sử event đúng và current view mới nhất.

**Blocked by:** [#01: Event synthetic xuất hiện trên dashboard](01-event-synthetic-xuat-hien-tren-dashboard.md).

## Acceptance criteria

- [ ] Duplicate/reorder/cùng revision khác hash được xử lý rõ; crash sau server commit trước response không tạo duplicate side effect.
- [ ] Downstream intent bền vững nhưng disabled ở lab; pending chỉ cho eligible intent; không no-op delivered hoặc notification synthetic.

- [ ] Nhận 3→1→2 hoặc chỉ revision3 vẫn dựng current đúng; camera/session/origin substitution bị reject; retry đổi sent_at không đổi content hash.
- [ ] Disabled/ineligible là terminal eligibility decision, khác pending eligible; bật provider không tự phát backlog.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: J02, S01, S02, C03, W02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
