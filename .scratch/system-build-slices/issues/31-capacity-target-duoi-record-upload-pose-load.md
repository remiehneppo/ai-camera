# 31: Capacity target dưới record/upload/pose load

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Profile rồi soak workload thực trên BOM để ký camera/FPS/pose envelope và headroom.

**Blocked by:** [#28: Negative audit và quality regression G2](28-negative-audit-va-quality-regression-g2.md); [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md).

**Conditional blockers (RKNN):** [#30: RKNN thay engine giữ event semantics](30-rknn-thay-engine-giu-event-semantics.md).

Target ONNX dùng C05/N05/P03/I05 và actual-target conformance; target chưa chọn hoặc thiếu report thì acceptance chưa đạt.

## Acceptance criteria

- [ ] 24–72h có per-camera P95/P99/gaps/fsync/WAL/outbox/thermal/power/copies và actual workload manifest.
- [ ] Tối ưu bottleneck đo được, shared runtime serialization/fairness; không ký camera capacity từ detector FPS riêng.

- [ ] Trên target ONNX: native/oracle detector/pose/tracker/event conformance và actual decode/buffer tests trước soak; target khác baseline phải rerun. RKNN thêm #30, không bỏ G3 khi deferred RKNN.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: A04, A05, O04, P04.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
