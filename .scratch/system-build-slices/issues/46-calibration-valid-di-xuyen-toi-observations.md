# 46: Calibration valid đi xuyên tới observations

Status: ready-for-human
Execution: not-started
Owner: Site operations + Domain/ML; chưa claim.

**What to build:** Khi mở vehicle scope, survey/calibrate contact-point projection và xuất validity/uncertainty tới pipeline/detail.

**Blocked by:** [#28: Negative audit và quality regression G2](28-negative-audit-va-quality-regression-g2.md).

## Acceptance criteria

- [ ] Mốc held-out/multi-plane/PTZ/occluded contact points được kiểm; invalid trả unknown.
- [ ] Camera shift invalidate geometry, không auto-restore do compensation; không m/s giả khi uncalibrated.

## Traceability

Task nguồn: G01, G02, QL03.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Nhánh vehicle có điều kiện, mở sau G2. Cần site operations khảo sát/mốc đo/calibration/PTZ facts; không suy geometry từ dữ liệu thiếu.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
