# 28: Negative audit và quality regression G2

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Lấy mẫu no-alert trước ring expiry, review độc lập rồi xuất report recall/FP/coverage/review load có uncertainty.

**Blocked by:** [#20: Feedback review thành nhãn dataset có lineage](20-feedback-review-thanh-nhan-dataset-co-lineage.md); [#27: On-vehicle vẫn review với ưu tiên riêng](27-on-vehicle-van-review-voi-uu-tien-rieng.md).

## Acceptance criteria

- [ ] Sampling probability/site-time-weather/rights/budget/coverage lưu được; expected-count fixture và held-out splits pass.
- [ ] Reports golden+event regression versioned; G2 cần target/sample/owner đủ, alerts-only không được báo recall.

- [ ] Matching window/denominator/minimum samples/uncertainty được pin; weighted sampling dùng inclusion probability, không cộng raw counts của các strata khác tỷ lệ; báo missing coverage.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Delta requirement được duyệt — 2026-10-20

- [ ] Protocol và báo cáo tái sử dụng được theo capability × site × workload: positives từng nhánh, hard negatives, unknown/coverage, bỏ sót, FP/camera/giờ, latency từ diễn biến đủ điều kiện đến cảnh báo và tải review; pin version/denominator/uncertainty và owner phê duyệt ngưỡng trước sign-off.
- [ ] G2 person-down được nghiệm thu trên profile person-down đã chọn, không chờ định nghĩa/triển khai/nghiệm thu toàn danh mục 13 nhóm và phá hoại; mỗi capability mở sau có report/gate riêng, không thừa hưởng chất lượng từ G2 person-down.

## Traceability

Task nguồn: D03, D04, D05, I05, R04.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.
