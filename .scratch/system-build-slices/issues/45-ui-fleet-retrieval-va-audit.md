# 45: UI fleet, retrieval và audit

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Đội UI hiển thị device offline/revoked, retrieval expiry, desired/observed versions và authorized raw/export audit.

**Blocked by:** [#32: Retained evidence truy hồi có authorization](32-retained-evidence-truy-hoi-co-authorization.md); [#33: Device lifecycle và site access được enforce](33-device-lifecycle-va-site-access-duoc-enforce.md); [#34: Config local và signed activation giữ LKG](34-config-local-va-signed-activation-giu-lkg.md).

## Acceptance criteria

- [ ] API/version/error fixtures handoff; scope deny/revoked/expired raw URLs được browser kiểm.
- [ ] Loading/error/retry và keyboard/responsive/accessibility; business transitions vẫn backend sở hữu.

## Traceability

Task nguồn: UI04, T03, H02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
