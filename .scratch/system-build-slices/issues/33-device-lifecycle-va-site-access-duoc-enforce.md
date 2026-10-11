# 33: Device lifecycle và site access được enforce

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Enroll/rotate/quarantine/revoke thiết bị và giới hạn reviewer/raw/export theo site/camera xuyên API.

**Blocked by:** [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md); [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md); [#17: Health phản ánh khả năng quan sát thực](17-health-phan-anh-kha-nang-quan-sat-thuc.md).

## Acceptance criteria

- [ ] Cross-site/cross-device/read/upload/review/export deny tests; revoked credentials không còn hoạt động.
- [ ] Trust/privacy/license hồ sơ có owner/phạm vi; approval thật trước field data, checklist không tự cấp clearance.

## Traceability

Task nguồn: T01, F05.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
