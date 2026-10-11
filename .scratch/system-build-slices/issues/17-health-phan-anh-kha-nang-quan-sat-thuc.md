# 17: Health phản ánh khả năng quan sát thực

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Dashboard/health API cho biết starting/degraded/unavailable và lý do, frame age/outbox/disk/recorder thay vì chỉ process running.

**Blocked by:** [#14: Pipeline baseline biến observations thành event](14-pipeline-baseline-bien-observations-thanh-event.md).

## Acceptance criteria

- [ ] Logs correlation/secret masking, bounded labels/spool; không event/frame ID làm metric label.
- [ ] Inject deadlock/queue stall/record gap có fault, thiếu clock mapping báo receive age thay capture age giả.

## Traceability

Task nguồn: H01, UI01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
