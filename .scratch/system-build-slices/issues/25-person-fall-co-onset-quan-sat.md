# 25: Person fall có onset quan sát

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Replay ca ngã nhanh/chậm có onset qua pose/history thành suspected person_fall và evidence/review flow.

**Blocked by:** [#14: Pipeline baseline biến observations thành event](14-pipeline-baseline-bien-observations-thanh-event.md); [#24: Pose scheduling và degradation có coverage](24-pose-scheduling-va-degradation-co-coverage.md).

## Acceptance criteria

- [ ] Pure FSM durations/hysteresis theo event-time; unsupported/unknown không kết luận chắc.
- [ ] Positive/hard-negative/occlusion/reset sequences có expected transitions; event rule/model/config provenance giữ.

## Traceability

Task nguồn: I02, I05.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
