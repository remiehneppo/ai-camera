# 16: Startup/shutdown giữ recorder và state đúng

Status: ready-for-review
Execution: done (software lab; chưa SIGKILL/hardware thực)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Người vận hành restart analytics, delivery và recorder theo lifecycle; pre-roll chưa đủ/boot mới hiển thị đúng.

**Blocked by:** [#09: Khôi phục event/evidence sau process crash](09-khoi-phuc-event-evidence-sau-process-crash.md); [#14: Pipeline baseline biến observations thành event](14-pipeline-baseline-bien-observations-thanh-event.md).

## Acceptance criteria

- [ ] Reconcile trước analytics, graceful drain có timeout, forced kill vẫn recover và reset epoch.
- [ ] Kill/hang analytics không dừng recorder; đo gaps theo protocol, không gắn config sai thành runtime recovery.

## Traceability

Task nguồn: B03, R06, N01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
- 2026-10-14: Triển khai và kiểm thử hoàn tất cho startup outbox reconciliation, graceful drain trước forced kill, session/epoch reset và recorder independence khi analytics bị SIGKILL/fault. Unit test `test_edge_runtime` (12 tests) và mypy đạt. Ghi nhận tại `docs/logs/2026-10-14-tickets-16-26-implementation.md`.
- 2026-10-17: Đồng bộ tracker (docs/logs/2026-10-17-tracker-sync.md). Code tồn tại (grep apps/), pytest nhóm liên quan 188 passed. Execution = done (software lab; chưa SIGKILL/hardware thực). Status triage và gate giữ nguyên; chưa review/ký.
