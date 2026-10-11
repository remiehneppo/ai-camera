# 44: UI sản phẩm cho review và annotation

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Đội UI tích hợp API thật thành queue person-down/on-vehicle/ambiguous và annotation feedback phục vụ người trực.

**Blocked by:** [#20: Feedback review thành nhãn dataset có lineage](20-feedback-review-thanh-nhan-dataset-co-lineage.md); [#27: On-vehicle vẫn review với ưu tiên riêng](27-on-vehicle-van-review-voi-uu-tien-rieng.md); [#28: Negative audit và quality regression G2](28-negative-audit-va-quality-regression-g2.md).

## Acceptance criteria

- [ ] Label correction/version/conflict/audit độc lập AI, missing/expired evidence và auth states rõ.
- [ ] Operator workload, keyboard/responsive/accessibility theo scope được review; dev demo không thay sign-off UI sản phẩm.

## Traceability

Task nguồn: UI03, D02, I04.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
