# 44: UI sản phẩm cho review và annotation

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Đội UI tích hợp API thật thành queue person-down/on-vehicle/ambiguous và annotation feedback phục vụ người trực.

**Blocked by:** [#04: Review event có kiểm soát phiên bản](04-review-event-co-kiem-soat-phien-ban.md); [#20: Feedback review thành nhãn dataset có lineage](20-feedback-review-thanh-nhan-dataset-co-lineage.md); [#27: On-vehicle vẫn review với ưu tiên riêng](27-on-vehicle-van-review-voi-uu-tien-rieng.md).

## Acceptance criteria

- [ ] Label correction/version/conflict/audit độc lập AI, missing/expired evidence và auth states rõ.
- [ ] Operator workload, keyboard/responsive/accessibility theo scope được review; dev demo không thay sign-off UI sản phẩm.

- [ ] Queue hiển thị needs_re_review/lý do khi clip mới complete, severity/taxonomy đổi hoặc evidence đã xem corrupt/missing; metadata-only update không gây bão review.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Delta requirement được duyệt — 2026-10-20

- [ ] Queue/detail hỗ trợ các nhãn liên kết cùng diễn biến và chống lặp theo nhóm; không ép một nhãn duy nhất hoặc tự hợp nhất danh tính liên camera. Severity/ưu tiên độc lập AI confidence và review decision, có policy site rõ.
- [ ] Hiển thị requested/actual clip ranges, mốc anchor theo loại Q36, provenance, observation duration và gaps/partial/missing; complete clip không nghĩa full episode, metadata không thay video hoặc bảo đảm xem được onset ngoài clip.
- [ ] #28 là gate quality/operator-workload sign-off theo capability/site trước nghiệm thu UI vận hành, không phải blocker để xây UI/API integration; prototype/demo không thay operator acceptance.

## Traceability

Task nguồn: UI03, D02, I04.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.
