# 26: Persistent lying khi thiếu onset

Status: ready-for-review
Execution: done (software tests verified)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Người nằm bền vững trong ROI vẫn vào review khi onset bị mất hoặc không quan sát được.

**Blocked by:** [#25: Person fall có onset quan sát](25-person-fall-co-onset-quan-sat.md).

## Acceptance criteria

- [ ] Missing onset/ID switch/gaps/lying from first frame có fixtures; không rơi vào khoảng trống fall-only.
- [ ] Taxonomy/severity/duration riêng, evidence coverage và uncertainty được hiển thị; không chẩn đoán y khoa.

- [ ] Không biết onset dùng first qualifying observation làm anchor và ghi rõ loại; không giả có onset, missing pre-roll vẫn partial.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: I02, I05.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
- 2026-10-14: Triển khai phát hiện persistent lying khi thiếu onset / ID switch, taxonomy `person_lying_persistent`, anchor_kind `first_qualifying_observation` (anchor - 10s đến + 20s, không gọi là onset), severity và duration riêng. Unit test `test_tracking_incident` (24 tests) và mypy đạt. Ghi nhận tại `docs/logs/2026-10-14-tickets-16-26-implementation.md`.
