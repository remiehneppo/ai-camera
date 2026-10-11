# 40: Synthetic probe báo operational fault riêng

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Probe đi qua decode/inference/journal/server và báo lỗi khi capability hoặc delivery ngừng tiến triển.

**Blocked by:** [#17: Health phản ánh khả năng quan sát thực](17-health-phan-anh-kha-nang-quan-sat-thuc.md); [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md).

## Acceptance criteria

- [ ] Synthetic taxonomy immutable qua revisions/retry, notification guard trước outbox; fault route không rescue.
- [ ] Metric/window/threshold/owner/runbook/recovery và secret/cardinality budgets được kiểm bằng injected deadlock/pin gap.

## Traceability

Task nguồn: H02, W02.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
