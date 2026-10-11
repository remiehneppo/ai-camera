# 41: Malformed storm không ăn hết state reserve

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Flood payload sai schema và theo dõi bounded forensic samples/counters/truncation ở edge/health.

**Blocked by:** [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md); [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md).

## Acceptance criteria

- [ ] Duplicate compact nhưng valid incident/revision không compact; unique storm có truncation/degraded rõ.
- [ ] Quota/limits/rate/counters/retention được kiểm; media không ghi được thì không hứa giữ forensic fact vô hạn.

## Traceability

Task nguồn: J04, H01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
