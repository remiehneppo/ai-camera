# 49: Nghiệm thu person-down pilot readiness G4a

Status: ready-for-human
Execution: not-started
Owner: QA/operations + Product/security; chưa claim.

**What to build:** Reproduce báo cáo lab và fault/security/UI proofs để quyết định có đủ điều kiện bắt đầu person-down field pilot.

**Blocked by:** [#19: Nghiệm thu vertical slice G1 trên lab](19-nghiem-thu-vertical-slice-g1-tren-lab.md); [#28: Negative audit và quality regression G2](28-negative-audit-va-quality-regression-g2.md); [#31: Capacity target dưới record/upload/pose load](31-capacity-target-duoi-record-upload-pose-load.md); [#36: WAN outage giữ event/evidence rồi resume](36-wan-outage-giu-event-evidence-roi-resume.md); [#37: Power-cut kiểm chứng local durability](37-power-cut-kiem-chung-local-durability.md); [#39: Provisioning và watchdog tái tạo được](39-provisioning-va-watchdog-tai-tao-duoc.md); [#40: Synthetic probe báo operational fault riêng](40-synthetic-probe-bao-operational-fault-rieng.md); [#41: Malformed storm không ăn hết state reserve](41-malformed-storm-khong-an-het-state-reserve.md); [#43: Central retention và backup/restore có proof](43-central-retention-va-backup-restore-co-proof.md); [#44: UI sản phẩm cho review và annotation](44-ui-san-pham-cho-review-va-annotation.md); [#45: UI fleet, retrieval và audit](45-ui-fleet-retrieval-va-audit.md).

**Conditional blockers (deployment đã chọn):** [#56: Orin NX actual baseline conformance](56-orin-nx-actual-baseline-conformance.md) khi deploy Orin NX; [#54: RF-DETR candidate](54-rf-detr-candidate-qua-detection-event-evidence.md) khi deploy RF-DETR; [#55: ViTPose candidate](55-vitpose-candidate-qua-pose-event-evidence.md) khi deploy ViTPose. Không áp dụng cho ứng viên chưa chọn/disabled.

## Acceptance criteria

- [ ] G4a trước field data có privacy/license/production infra/restore/operator protocol và đủ fault/soak proofs, named owner ký.
- [ ] Notification chỉ nếu được bật/duyệt ticket42, vehicle chỉ nếu đạt48; unresolved hoặc thiếu evidence không pass, có pause/rollback protocol.

- [ ] G3 trên target đã chọn có conformance/capacity; ONNX path không cần #29/#30, RKNN path bắt #30. Gate không miễn hardware/fault/soak vì backend deferred.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Delta requirement được duyệt — 2026-10-20

- [ ] G4a chỉ ký profile deployment được chọn: actual target/SKU, camera/site/ODD, exact engines và manifest module enabled phải khớp quality/capacity/fault/UI/privacy evidence; không kéo toàn catalog nhóm mới làm blocker person-down.
- [ ] Conditional deployment gates: Orin NX cần [#56: Orin NX actual baseline conformance](56-orin-nx-actual-baseline-conformance.md), RF-DETR cần [#54: RF-DETR candidate qua detection/event/evidence](54-rf-detr-candidate-qua-detection-event-evidence.md), ViTPose cần [#55: ViTPose candidate qua pose/event/evidence](55-vitpose-candidate-qua-pose-event-evidence.md) chỉ khi được chọn dùng; disabled/deferred không phải pass. Giữ #42 conditional notification và #48 conditional vehicle; không bỏ G3 actual target.

## Traceability

Task nguồn: F03, F06, T01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Cần named owners ký privacy/model/data clearance, production topology/SLA và G4a readiness. Nếu bật notification cần #42; nếu bật vehicle cần #48. Hai edge này có điều kiện, không chặn person-down khi nhánh tương ứng disabled.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.
