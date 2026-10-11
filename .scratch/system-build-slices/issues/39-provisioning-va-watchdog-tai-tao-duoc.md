# 39: Provisioning và watchdog tái tạo được

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Provision thiết bị sạch, deploy service least privilege, upgrade/restore theo runbook và kiểm watchdog thực.

**Blocked by:** [#35: Canary và rollback có authorization mới](35-canary-va-rollback-co-authorization-moi.md); [#38: Native crash recovery đạt RTO](38-native-crash-recovery-dat-rto.md).

## Acceptance criteria

- [ ] Build/SBOM/provenance pinned; runtime/device node/recorder ACL được kiểm trên target.
- [ ] Watchdog có heartbeat thật; resource limits không phá recorder/native access, restore lặp lại được.

## Traceability

Task nguồn: T05.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
