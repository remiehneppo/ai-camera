# 20: Feedback review thành nhãn dataset có lineage

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Reviewer correction được lưu như nhãn có version/audit rồi export dataset được phép với exact event/clip/model/config revision.

**Blocked by:** [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md); [#04: Review event có kiểm soát phiên bản](04-review-event-co-kiem-soat-phien-ban.md); [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md).

## Acceptance criteria

- [ ] API/export kiểm scope, ambiguous labels rõ; correction không overwrite nhãn gốc/AI outputs.
- [ ] Split site-camera-time và quyền dữ liệu được kiểm; sensitive data không commit vào repo.

- [ ] Dataset label gắn exact reviewed_event_revision/evidence versions; correction/reopen giữ audit, không join current thay dữ liệu đã được xem.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: D01, D02, UI03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
