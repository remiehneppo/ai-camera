# 48: Nghiệm thu vehicle riêng G4b

Status: ready-for-human
Execution: not-started
Owner: QA/ML + Product/operations; chưa claim.

**What to build:** Chạy vehicle E2E và report recall/FP/evidence/review load theo từng nhánh/site/ODD và dataset riêng; calibration chỉ bắt buộc khi nhánh dùng metric geometry.

**Blocked by:** [#47: Vehicle motion và suspected-incident flow](47-vehicle-motion-va-suspected-incident-flow.md).

**Conditional blockers (metric geometry):** [#46: Calibration valid đi xuyên tới observations](46-calibration-valid-di-xuyen-toi-observations.md).

## Acceptance criteria

- [ ] Dataset/provenance/threshold/uncertainty đủ và ký G4b theo use case được bật.
- [ ] Vehicle disabled ghi deferred; không chặn person-down pilot, không suy G2 person-down thành vehicle đạt.

## Delta requirement được duyệt — 2026-10-20

- [ ] Nghiệm thu theo từng nhánh vehicle thực sự enabled (xe–xe, xe–người, xe tự ngã/lật/đâm vật cố định), site/ODD ngày/đêm/mưa có version và dữ liệu/rights; report positives/hard negatives, unknown, bỏ sót/FP, latency đủ điều kiện→cảnh báo, evidence và review load với owner ký.
- [ ] #46 chỉ là conditional gate cho nhánh dùng metric geometry; nhánh ảnh không dùng metric không cần calibration nhưng vẫn cần quality/ODD/capacity tương ứng. Không lấy một nhánh đạt làm toàn US08 đạt, không lấy G2 person-down làm vehicle acceptance.

## Traceability

Task nguồn: M03, D04.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Chỉ nghiệm thu khi vehicle được bật, có site dataset/thresholds/ODD và người ký G4b; calibration là conditional prerequisite cho nhánh dùng metric geometry. Disabled ghi deferred, không coi pass.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.
