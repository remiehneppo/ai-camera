# 29: Build artifact target reproducible

Status: needs-info
Execution: not-started
Owner: ML + Edge; chưa claim.

**What to build:** Sau khi chọn board, convert ONNX→RKNN offline và xuất target manifest/report có thể tái tạo.

**Blocked by:** [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md); [#11: ONNX oracle xuất detection có provenance](11-onnx-oracle-xuat-detection-co-provenance.md).

**Activation:** Chỉ thực hiện khi target RK3588/RKNN được chọn; target ONNX ghi deferred, không bắt conversion.

## Acceptance criteria

- [ ] Pin SDK/runtime/operator/quantization data/terms/hashes; unsupported conversion có lỗi rõ.
- [ ] No startup conversion; chưa chọn target/weights clearance thì chưa target release, baseline lab vẫn độc lập.

## Traceability

Task nguồn: A01, F05.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Cần chọn board/OS/runtime target và artifact/quantization data phù hợp từ facts #02; baseline ONNX không bị chặn bởi lựa chọn này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
