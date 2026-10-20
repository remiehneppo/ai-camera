# 24: Pose scheduling và degradation có coverage

Status: ready-for-review
Execution: done (software lab; pose outcomes chưa vào IncidentEngine, chưa đo coverage thật)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Fast-fall, slow-collapse và lying được sampling công bằng; overload giảm công việc có capability reason tới dashboard.

**Blocked by:** [#21: Quality và ODD đi xuyên tới event/detail](21-quality-va-odd-di-xuyen-toi-event-detail.md); [#22: Pose request trả keypoints đúng frame và track](22-pose-request-tra-keypoints-dung-frame-va-track.md); [#23: Track gap không tạo certainty hoặc motion giả](23-track-gap-khong-tao-certainty-hoac-motion-gia.md).

## Acceptance criteria

- [x] Đo scheduled/attempted/skipped/failed/stale và coverage từng nhánh, không chỉ trigger y spike.
- [x] Burst/deadline/fairness/hysteresis/recovery test; recorder tiếp tục và mất capability không báo healthy/negative.

## Traceability

Task nguồn: P02, P04, O03, O02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
- 2026-10-14: Triển khai hoàn tất PoseScheduler trong `apps/edge/pose.py` và tích hợp `PerceptionPipeline` trong `apps/edge/pipeline.py`:
  - Phân loại 3 nhánh: `fast_fall` (priority 1), `slow_collapse` (priority 2), `persistent_lying` (priority 3) với per-branch min-shares và anti-starvation.
  - Đo lường metrics đầy đủ: scheduled, attempted, skipped, failed, stale, và coverage per branch.
  - Hỗ trợ overload shedding (shedding persistent_lying trước, rồi slow_collapse), báo `capability_status="degraded"` với lý do cụ thể.
  - Cơ chế hồi phục Hysteresis (3 calm cycles liên tiếp) chống flapping.
  - 24/24 tests trong `tests/test_pose.py` passed; mypy đạt 0 lỗi; code review OCR đạt chuẩn. Ghi log tại `docs/logs/2026-10-14-ticket-24-implementation.md`.
- 2026-10-17: Đồng bộ tracker (docs/logs/2026-10-17-tracker-sync.md). Code tồn tại (grep apps/), pytest nhóm liên quan 188 passed. Execution = done (software lab; pose outcomes chưa vào IncidentEngine, chưa đo coverage thật). Status triage và gate giữ nguyên; chưa review/ký.
