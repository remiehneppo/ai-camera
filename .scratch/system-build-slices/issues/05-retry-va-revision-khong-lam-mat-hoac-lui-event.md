# 05: Retry và revision không làm mất hoặc lùi event

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Edge retry sau mất response; dashboard vẫn giữ một lịch sử event đúng và current view mới nhất.

**Blocked by:** [#01: Event synthetic xuất hiện trên dashboard](01-event-synthetic-xuat-hien-tren-dashboard.md).

## Acceptance criteria

- [ ] Duplicate/reorder/cùng revision khác hash được xử lý rõ; crash sau server commit trước response không tạo duplicate side effect.
- [ ] Downstream intent bền vững nhưng disabled/pending ở lab; không no-op delivered hoặc notification synthetic.

## Traceability

Task nguồn: J02, S01, S02, C03, W02.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
