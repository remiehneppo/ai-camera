# 14: Pipeline baseline biến observations thành event

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Observation metadata đi qua feature factory và pure IncidentEngine để event xuất hiện trên dashboard có pipeline provenance.

**Blocked by:** [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md); [#07: Event pin được clip pre/post từ ring](07-event-pin-duoc-clip-pre-post-tu-ring.md); [#13: Native tracks có time và session semantics](13-native-tracks-co-time-va-session-semantics.md).

## Acceptance criteria

- [ ] Per-camera/session/pipeline state riêng, chia sẻ perception tương thích; synthetic fixture chưa coi là person-down quality.
- [ ] Queue/deadline/cancel bounded; slow consumer không chặn recorder, valid events không drop như frames.

## Traceability

Task nguồn: O01, O02, I01, C03.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
