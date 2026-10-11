# 43: Central retention và backup/restore có proof

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Retention/delete/export đúng policy rồi restore Mongo metadata và evidence vào môi trường tách biệt.

**Blocked by:** [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md); [#33: Device lifecycle và site access được enforce](33-device-lifecycle-va-site-access-duoc-enforce.md).

## Acceptance criteria

- [ ] Restore/reconcile pending/missing/corrupt/orphan/hash/scope và immutable receipts; DB/file không transaction chung.
- [ ] Production topology/storage/HA/SLA có decision owner; report RPO/RTO, Mongo one-member lab không coi HA.

## Traceability

Task nguồn: E03, E02.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
