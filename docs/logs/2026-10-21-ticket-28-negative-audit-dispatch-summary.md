# Nhật ký Điều phối & Tích hợp Ticket #28 — 2026-10-21

## 1. Mục tiêu và Phạm vi
- **Ticket #28:** Negative audit và quality regression G2.
- **Phân loại độ phức tạp:** L2 (tích hợp xuyên suốt Domain Quality Evaluation, Edge Negative Sampler, G2 Report CLI và bộ Integration Test Suite).
- **Mô hình thực thi:** Subagent delegation (`deepseek-official/deepseek-flash`) + Dispatcher review, khắc phục lỗi phân tầng và nghiệm thu toàn diện.

## 2. Các Thành phần Triển khai

### 1. Domain Quality & Sampling Engine (`domain/quality_eval.py`)
- Định nghĩa cấu trúc `Stratum` và `SamplingPlan`:
  - Mỗi stratum gắn liền với xác suất bao hàm `inclusion_probability` $p_h \in (0, 1]$, camera/site, khung giờ và điều kiện thời tiết.
  - Phân tầng lấy mẫu có trọng số nghịch đảo Horvitz-Thompson: $w_i = \frac{1}{p_h}$. Cấm cộng dồn số đếm thô (raw counts) giữa các strata có tỷ lệ lấy mẫu khác nhau.
- Hàm đánh giá chất lượng `evaluate_quality_metrics`:
  - **Quy tắc chặn nghiêm ngặt (Hard Rule):** Khi không có mẫu negative nào được review (`counts["negative_samples_reviewed"] == 0`), báo cáo gán `verdict = "BLOCKED"` và cấm tuyệt đối việc suy diễn recall từ alerts-only.
  - Ước lượng Recall có trọng số: $\widehat{R} = \frac{\text{TP}}{\text{TP} + \widehat{\text{FN}}}$, trong đó $\widehat{\text{FN}} = \sum_{i \in \text{missed}} \frac{1}{p_i}$.
  - Tính toán khoảng tin cậy 95% Wilson interval trên cỡ mẫu hiệu dụng Kish (`_kish_effective_size`).
  - Phân tích chi tiết theo 3 nhánh person-down (`person_fall`, `person_lying_persistent`, `person_on_stationary_vehicle`).
  - Ước lượng số giờ camera quan sát thực tế theo Horvitz-Thompson để tính tỷ lệ báo giả FP/camera-hour và FP/camera-day.
  - Tính toán tải review (review load) và độ trễ phát hiện (latency).
  - Kiểm tra điều kiện đủ mẫu (sample sufficiency) và đối chiếu với ngưỡng mục tiêu G2 (recall >= 90%, lower bound >= 80%, FP <= 2.0/ngày).

### 2. Edge Negative Audit Sampler (`apps/edge/audit_sampler.py`)
- `NegativeAuditSampler`:
  - Hoạt động cùng `FileRecorder` lấy mẫu các đoạn video không có cảnh báo (no-alert segments) trước khi ring buffer bị ghi đè.
  - Quyết định lấy mẫu dựa trên băm xác định SHA-256 từ `salt | plan_version | stratum | camera | start | end` đối chiếu với $p_h$.
  - Lưu trữ manifest `samples.jsonl` tại `<evidence_dir>/audit_samples` cùng bản chụp băm `plan.json` (`plan_sha256`) và trạng thái `pending_review`.

### 3. G2 Quality Report CLI Tool (`tools/negative_audit_report.py`)
- Công cụ dòng lệnh phân tích kết quả review và xuất báo cáo:
  - Nhận tham số `--alerts`, `--negatives`, `--plan`, `--capability`, `--site`, `--min-recall`, `--max-fp-per-day`, `--strict`.
  - Xuất báo cáo định dạng JSON và Markdown có phiên bản.
  - Hỗ trợ chế độ `--strict` (thoát mã lỗi 1 khi FAIL, 2 khi BLOCKED).
  - Tích hợp khung chữ ký và điều kiện phê duyệt của Owner (owner sign-off block).

### 4. Integration Test Suite (`tests/test_negative_audit_flow.py`)
- 47 test cases bao phủ toàn diện 6 nhóm tình huống:
  1. `TestAlertsOnlyForbidsRecall`: Ngăn chặn tuyệt đối việc suy diễn recall từ alerts-only.
  2. `TestWeightedSamplingDisparity`: Kiểm chứng ước lượng Horvitz-Thompson 1/p đối lập với số đếm thô khi các tầng có $p_h$ lệch nhau (ví dụ: tầng ngày $p=0.5$ và tầng đêm $p=0.1$).
  3. `TestConfidenceIntervalsAndSampleSufficiency`: Kiểm tra khoảng tin cậy Wilson, cỡ mẫu hiệu dụng và cảnh báo khi thiếu mẫu.
  4. `TestPerBranchPersonDownMetrics`: Kiểm tra phân rã metrics theo từng nhánh con của person-down.
  5. `TestEdgeAuditSampler`: Kiểm tra sampler xác định, không bao giờ lấy mẫu đoạn có alert, lưu trữ manifest chuẩn.
  6. `TestCliReportGeneration`: Kiểm tra CLI chạy thực tế với file và thư mục, định dạng JSON và Markdown, cùng cờ `--strict`.

## 3. Hoạt động Review & Chỉnh sửa của Dispatcher
- **Khắc phục lỗi kiểu dữ liệu mypy:**
  - Sửa lỗi ép kiểu `Any | None` trong `Stratum.from_dict` và `SamplingPlan.from_dict`.
  - Bổ sung kiểm tra `is not None` trước phép so sánh `false_positives["per_camera_day"] > max_fp_per_day` trong `evaluate_quality_metrics`.
  - Khai báo kiểu tường minh cho `negatives: list[dict[str, Any]]` trong `negative_audit_report.py`.
  - Đảm bảo `camera_id` được chuyển đổi thành chuỗi hợp lệ trong `sample_segment`.
- **Kiểm định toàn diện:**
  - `mypy` trên cả 3 file đạt `Success: no issues found in 3 source files`.
  - 47/47 tests trong `tests/test_negative_audit_flow.py` passed.
  - Toàn bộ 519 test cases toàn dự án (`pytest -q`) đạt **519 passed, 126 subtests passed** (100% test xanh).

## 4. Cập nhật Tracker
- `.scratch/system-build-slices/issues/28-negative-audit-va-quality-regression-g2.md`: Chuyển `Execution: done (software lab)` và tích đầy đủ các tiêu chí acceptance criteria.
- `.scratch/system-build-slices/PRD.md`: Cập nhật bảng và snapshot tiến độ #28 hoàn tất trong software lab.
