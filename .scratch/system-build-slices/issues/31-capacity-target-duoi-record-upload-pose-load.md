# 31: Capacity target dưới record/upload/pose load

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Profile rồi soak workload thực trên BOM để ký camera/FPS/pose envelope và headroom.

**Blocked by:** [#30: RKNN thay engine giữ event semantics](30-rknn-thay-engine-giu-event-semantics.md); [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md).

## Acceptance criteria

- [ ] 24–72h có per-camera P95/P99/gaps/fsync/WAL/outbox/thermal/power/copies và actual workload manifest.
- [ ] Tối ưu bottleneck đo được, shared runtime serialization/fairness; không ký camera capacity từ detector FPS riêng.

## Traceability

Task nguồn: A04, A05, O04, P04.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
