# 32: Retained evidence truy hồi có authorization

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Người có quyền yêu cầu clip edge/server qua outbound command và thấy pending/offline/expired/completed.

**Blocked by:** [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md); [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md).

## Acceptance criteria

- [ ] Long-poll ID/auth/target/expiry/replay guard, retry idempotent; không remote shell/arbitrary executable.
- [ ] Cleanup/download/retrieval race được kiểm; metadata ACK không release clip, retention/delete scope rõ.

## Traceability

Task nguồn: R05, T03, UI04.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
