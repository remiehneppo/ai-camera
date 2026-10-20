# 46: Calibration valid đi xuyên tới observations

Status: ready-for-human
Execution: not-started
Owner: Site operations + Domain/ML; chưa claim.

**What to build:** Khi mở nhánh vehicle dùng metric geometry, survey/calibrate contact-point projection và xuất validity/uncertainty tới pipeline/detail; không ép nhánh quan sát ảnh phụ thuộc calibration.

**Blocked by:** [#28: Negative audit và quality regression G2](28-negative-audit-va-quality-regression-g2.md).

## Acceptance criteria

- [ ] Mốc held-out/multi-plane/PTZ/occluded contact points được kiểm; invalid trả unknown.
- [ ] Camera shift invalidate geometry, không auto-restore do compensation; không m/s giả khi uncalibrated.

## Delta requirement được duyệt — 2026-10-20

- [ ] Calibration chỉ bắt buộc cho nhánh sử dụng metric geometry như ground projection/tốc độ/khoảng cách/TTC có đơn vị; nhánh quan sát ảnh không dùng metric không bị ép phụ thuộc calibration, không suy m/s từ pixel.
- [ ] Giữ activation sau G2 person-down và prerequisites khảo sát/human cho nhánh calibrated; thiếu/invalid calibration làm outputs metric unknown, không nâng các dấu hiệu ảnh thành metric đã hiệu chuẩn.

## Traceability

Task nguồn: G01, G02, QL03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Nhánh vehicle dùng metric geometry có điều kiện, mở sau G2 person-down. Cần site operations khảo sát/mốc đo/calibration/PTZ facts; không suy geometry từ dữ liệu thiếu. Nhánh ảnh không dùng metric không cần gate calibration này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.
