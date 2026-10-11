# 26: Persistent lying khi thiếu onset

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Người nằm bền vững trong ROI vẫn vào review khi onset bị mất hoặc không quan sát được.

**Blocked by:** [#25: Person fall có onset quan sát](25-person-fall-co-onset-quan-sat.md).

## Acceptance criteria

- [ ] Missing onset/ID switch/gaps/lying from first frame có fixtures; không rơi vào khoảng trống fall-only.
- [ ] Taxonomy/severity/duration riêng, evidence coverage và uncertainty được hiển thị; không chẩn đoán y khoa.

## Traceability

Task nguồn: I02, I05.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
