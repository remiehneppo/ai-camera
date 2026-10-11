# 09: Khôi phục event/evidence sau process crash

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Restart edge/server giữa các bước commit và upload; detail phản ánh đúng clip còn, thiếu, partial hoặc corrupt.

**Blocked by:** [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md); [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md).

## Acceptance criteria

- [ ] Inject pending/temp/final/orphan/missing/corrupt và uploading unknown response; reconcile có expected state.
- [ ] Không DB complete giả khi file thiếu; không orphan tăng vô hạn, dữ liệu protected giữ và faults rõ.

- [ ] Crash event commit→pin, recorder ACK→edge receipt và recorder reboot đều reconcile được theo request ID; không unowned pin hoặc pending vô hạn khi ring đã hết.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: J04, R03, E02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
