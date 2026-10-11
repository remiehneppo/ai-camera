# 11: ONNX oracle xuất detection có provenance

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Replay mẫu cleared qua detector oracle, xuất canonical detections/timing/transform để đối chiếu deployment.

**Blocked by:** [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md).

## Acceptance criteria

- [ ] Exact model/hash/label/pre-post/runtime pinned; bbox original coords, empty/invalid output phân biệt.
- [ ] Golden fixture hashes/tolerances có version; chạy không yêu cầu board đích hoặc target SDK.

## Traceability

Task nguồn: N02, C05, V01, F05.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
