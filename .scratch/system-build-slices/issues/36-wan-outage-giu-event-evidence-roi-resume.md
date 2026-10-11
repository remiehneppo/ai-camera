# 36: WAN outage giữ event/evidence rồi resume

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Ngắt WAN/central theo budget lab và workload đã sizing, phục hồi upload/retrieval mà không mất dữ liệu protected trái policy.

**Blocked by:** [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md); [#32: Retained evidence truy hồi có authorization](32-retained-evidence-truy-hoi-co-authorization.md).

## Acceptance criteria

- [ ] 24h target được đo autonomy/time-to-full/backlog, quá budget báo degraded, không TTL unACK.
- [ ] Metadata ưu tiên clip, receipt/retry/dedup đúng và report RPO/RTO trong scope; không hứa chịu disk loss.

## Traceability

Task nguồn: J05, J03, R05.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
