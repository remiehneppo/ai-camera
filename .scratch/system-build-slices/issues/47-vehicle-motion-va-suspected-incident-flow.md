# 47: Vehicle motion và suspected-incident flow

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Tracks/time/ground quality thành motion/risk features và vehicle pipeline event vào cùng evidence/review flow.

**Blocked by:** [#46: Calibration valid đi xuyên tới observations](46-calibration-valid-di-xuyen-toi-observations.md).

## Acceptance criteria

- [ ] Variable Δt/jitter/gaps/epoch và predicted/measured không tạo acceleration giả.
- [ ] Near-miss/red-light stop/jam/crash fixtures; TTC/overlap không proof collision, state độc lập person-down.

## Traceability

Task nguồn: M01, M02, I06.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
