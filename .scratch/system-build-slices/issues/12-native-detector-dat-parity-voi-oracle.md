# 12: Native detector đạt parity với oracle

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** C++ decode/preprocess/ORT/postprocess xuất metadata detection đúng semantic kit.

**Blocked by:** [#10: File replay đi qua native boundary an toàn](10-file-replay-di-qua-native-boundary-an-toan.md); [#11: ONNX oracle xuất detection có provenance](11-onnx-oracle-xuat-detection-co-provenance.md).

## Acceptance criteria

- [ ] Golden tolerance và inverse transform/color/NMS đạt; không double normalize.
- [ ] ASan/UBSan phù hợp cùng slow consumer/drop/cancel/restart không leak/use-after-free; timings từng stage có report.

## Traceability

Task nguồn: N03, N04, C05.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
