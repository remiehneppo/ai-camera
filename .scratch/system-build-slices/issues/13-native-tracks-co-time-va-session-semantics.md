# 13: Native tracks có time và session semantics

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Detection qua ByteTrack oracle/native, consumer nhận track lifecycle/history bounded theo từng camera.

**Blocked by:** [#12: Native detector đạt parity với oracle](12-native-detector-dat-parity-voi-oracle.md).

## Acceptance criteria

- [ ] Variable FPS/gaps/out-of-order/reset có same policy; measured/predicted rõ và aging theo thời gian.
- [ ] Hai camera/epoch cùng local track ID không trộn state; Python hot path không nhận pixels.

- [ ] Một tracker update/frame trong PerceptionPipeline; late pose chỉ bổ sung observation, không update tracker lần hai; reset loại result epoch cũ.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: K01, K02, N05, C02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
