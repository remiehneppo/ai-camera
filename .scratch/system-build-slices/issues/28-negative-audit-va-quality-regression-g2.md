# 28: Negative audit và quality regression G2

Status: ready-for-agent
Execution: done (software lab)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; claimed & completed (software lab).

**What to build:** Lấy mẫu no-alert trước ring expiry, review độc lập rồi xuất report recall/FP/coverage/review load có uncertainty.

**Blocked by:** [#20: Feedback review thành nhãn dataset có lineage](20-feedback-review-thanh-nhan-dataset-co-lineage.md); [#27: On-vehicle vẫn review với ưu tiên riêng](27-on-vehicle-van-review-voi-uu-tien-rieng.md).

## Acceptance criteria

- [x] Sampling probability/site-time-weather/rights/budget/coverage lưu được; expected-count fixture và held-out splits pass.
- [x] Reports golden+event regression versioned; G2 cần target/sample/owner đủ, alerts-only không được báo recall.
- [x] Matching window/denominator/minimum samples/uncertainty được pin; weighted sampling dùng inclusion probability, không cộng raw counts của các strata khác tỷ lệ; báo missing coverage.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Delta requirement được duyệt — 2026-10-20

- [x] Protocol và báo cáo tái sử dụng được theo capability × site × workload: positives từng nhánh, hard negatives, unknown/coverage, bỏ sót, FP/camera/giờ, latency từ diễn biến đủ điều kiện đến cảnh báo và tải review; pin version/denominator/uncertainty và owner phê duyệt ngưỡng trước sign-off.
- [x] G2 person-down được nghiệm thu trên profile person-down đã chọn, không chờ định nghĩa/triển khai/nghiệm thu toàn danh mục 13 nhóm và phá hoại; mỗi capability mở sau có report/gate riêng, không thừa hưởng chất lượng từ G2 person-down.

## Traceability

Task nguồn: D03, D04, D05, I05, R04.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

- **Domain Quality Evaluation Engine (`domain/quality_eval.py`):**
  - Định nghĩa `Stratum`, `SamplingPlan`, `evaluate_quality_metrics`.
  - Phân tầng lấy mẫu có xác suất bao hàm `inclusion_probability` $p_h$, tính toán trọng số nghịch đảo Horvitz-Thompson $w_i = \frac{1}{p_h}$, không cộng dồn raw counts giữa các strata khác tỷ lệ lấy mẫu.
  - Hard guardrail: khi không có mẫu negative được review (`counts["negative_samples_reviewed"] == 0`), báo cáo gán `verdict = "BLOCKED"` và cấm tuyệt đối việc suy diễn recall từ alerts-only.
  - Tính toán khoảng tin cậy 95% Wilson score trên cỡ mẫu hiệu dụng Kish (`_kish_effective_size`).
  - Báo cáo chi tiết theo 3 nhánh person-down (`person_fall`, `person_lying_persistent`, `person_on_stationary_vehicle`), FP/camera-hour, FP/camera-day, review load và latency.
- **Edge Negative Audit Sampler (`apps/edge/audit_sampler.py`):**
  - Lấy mẫu các đoạn video no-alert trước khi ghi đè ring buffer của `FileRecorder`.
  - Quyết định lấy mẫu dựa trên băm xác định SHA-256 đối chiếu với $p_h$ của stratum.
  - Lưu trữ manifest `samples.jsonl` tại `<evidence_dir>/audit_samples` với đầy đủ metadata: `sample_id`, `stratum_id`, `inclusion_probability`, `start_time`, `end_time`, `duration_seconds`, `rights_cleared`, `status="pending_review"`.
- **Quality Report CLI Tool (`tools/negative_audit_report.py`):**
  - Đọc reviewed alerts và reviewed negative samples, đối chiếu sampling plan và ngưỡng mục tiêu G2.
  - Xuất báo cáo versioned định dạng JSON và Markdown, tích hợp mẫu phê duyệt và ký duyệt của Owner.
- **Test suite (`tests/test_negative_audit_flow.py`):**
  - 47/47 passed (8 subtests passed) trong 0.15s bao phủ toàn bộ 6 nhóm kịch bản: alerts-only rejection, Horvitz-Thompson weighting, Wilson CI / sample sufficiency, per-branch person-down metrics, edge audit sampler, và CLI report generation.
  - Toàn bộ test suite dự án đạt **519 passed, 126 subtests passed** (100% test xanh).

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.
- 2026-10-21: Hoàn tất triển khai Ticket #28 trong software lab. 47 test cases trong `test_negative_audit_flow.py` và 519 test cases toàn dự án đạt xanh 100%.
