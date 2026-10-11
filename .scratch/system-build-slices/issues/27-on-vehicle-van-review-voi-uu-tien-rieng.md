# 27: On-vehicle vẫn review với ưu tiên riêng

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Người ngả trên xe đã stationary/upright tạo event review ưu tiên thấp; xe đổ/ngã cạnh xe có danger override.

**Blocked by:** [#26: Persistent lying khi thiếu onset](26-persistent-lying-khi-thieu-onset.md).

## Acceptance criteria

- [ ] Association có uncertainty/history, không suppress vì bbox overlap hoặc kết luận ngủ/bất tỉnh.
- [ ] Lab không notification khẩn; product protocol chưa ký vẫn lưu/review event, chưa bật hazard scope ngoài yêu cầu.

## Traceability

Task nguồn: I03, I04, UI03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
