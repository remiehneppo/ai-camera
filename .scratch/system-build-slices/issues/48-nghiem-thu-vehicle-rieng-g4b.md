# 48: Nghiệm thu vehicle riêng G4b

Status: ready-for-human
Execution: not-started
Owner: QA/ML + Product/operations; chưa claim.

**What to build:** Chạy vehicle E2E và report recall/FP/evidence/review load trên site calibration/dataset riêng.

**Blocked by:** [#47: Vehicle motion và suspected-incident flow](47-vehicle-motion-va-suspected-incident-flow.md).

## Acceptance criteria

- [ ] Dataset/provenance/threshold/uncertainty đủ và ký G4b theo use case được bật.
- [ ] Vehicle disabled ghi deferred; không chặn person-down pilot, không suy G2 person-down thành vehicle đạt.

## Traceability

Task nguồn: M03, D04.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Chỉ nghiệm thu khi vehicle được bật, có calibration/site dataset/thresholds và người ký G4b; disabled ghi deferred, không coi pass.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
