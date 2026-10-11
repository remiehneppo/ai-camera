# 24: Pose scheduling và degradation có coverage

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Fast-fall, slow-collapse và lying được sampling công bằng; overload giảm công việc có capability reason tới dashboard.

**Blocked by:** [#21: Quality và ODD đi xuyên tới event/detail](21-quality-va-odd-di-xuyen-toi-event-detail.md); [#22: Pose request trả keypoints đúng frame và track](22-pose-request-tra-keypoints-dung-frame-va-track.md); [#23: Track gap không tạo certainty hoặc motion giả](23-track-gap-khong-tao-certainty-hoac-motion-gia.md).

## Acceptance criteria

- [ ] Đo scheduled/attempted/skipped/failed/stale và coverage từng nhánh, không chỉ trigger y spike.
- [ ] Burst/deadline/fairness/hysteresis/recovery test; recorder tiếp tục và mất capability không báo healthy/negative.

## Traceability

Task nguồn: P02, P04, O03, O02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
