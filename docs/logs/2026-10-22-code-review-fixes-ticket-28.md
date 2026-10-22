# Nhật ký Sửa lỗi sau Code Review Ticket #28 — 2026-10-22

## 1. Bối cảnh
Sau đợt triển khai ban đầu của Ticket #28 (`ee7e1f7`), phiên Code Review hai trục (**Standards** và **Spec**) đã rà soát toàn bộ diff và đưa ra các phát hiện cần chấn chỉnh.

## 2. Các vấn đề được phát hiện & Biện pháp khắc phục

### A. Trục Standards (Kiến trúc & Ràng buộc Hợp đồng)
1. **Ràng buộc `matching_window_seconds` và `plan` ở cấp độ Gate:**
   - *Vấn đề:* `contracts.md` quy định `matching_window_seconds` và `plan` là bắt buộc khi nghiệm thu chất lượng G2; code trước đó chỉ đưa vào `warnings` thay vì chặn gate.
   - *Khắc phục:* Trong `domain/quality_eval.py`, khi `plan is None` hoặc `matching_window_seconds is None`, hệ thống lập tức đưa vào `blocking_gaps` (`sampling_plan_not_provided`, `matching_window_not_pinned`), đảm bảo báo cáo chuyển `BLOCKED` đúng tinh thần fail-fast.
2. **Loại bỏ nhân bản danh mục Taxonomy:**
   - *Vấn đề:* Hằng số `BRANCHES` được khai báo độc lập tại `quality_eval.py` thay vì dùng từ module hợp đồng Domain chuẩn.
   - *Khắc phục:* Khai báo `PERSON_DOWN_TAXONOMIES` trong `domain/event_contract.py` và import vào `domain/quality_eval.py` (`BRANCHES = PERSON_DOWN_TAXONOMIES`).

### B. Trục Spec (Nghiệp vụ & Delta Requirements)
1. **Bổ sung quản lý ngân sách lấy mẫu (`budget_clips`):**
   - *Vấn đề:* Spec yêu cầu lưu trữ `budget` trong `Stratum` (`issues/28:13`).
   - *Khắc phục:* Bổ sung trường `budget_clips: int | None = None` vào `Stratum` và phương thức `to_dict()` / `from_dict()`.
2. **Đo lường và thống kê độ trễ cảnh báo (`alert_latency`):**
   - *Vấn đề:* Delta spec 2026-10-20 yêu cầu tính toán *"latency từ diễn biến đủ điều kiện đến cảnh báo"*.
   - *Khắc phục:* Trong `normalize_alert`, tính toán `latency_seconds` từ `detection_time - anchor_time`. Trong `evaluate_quality_metrics`, thống kê khối `alert_latency` gồm `count`, `mean_seconds`, `min_seconds`, `max_seconds` và đưa vào báo cáo JSON/Markdown.
3. **Cấu hình độc lập ngưỡng chặn dưới khoảng tin cậy (`min_recall_lower_bound`):**
   - *Vấn đề:* Kiểm tra `ci_low < min_recall` làm từ chối kết quả đạt recall cao nhưng có biên sai số tự nhiên của mẫu.
   - *Khắc phục:* Bổ sung tham số tùy chọn `min_recall_lower_bound` (mặc định `None`). Khi được cung cấp, hệ thống kiểm tra `ci_low < min_recall_lower_bound` để chặn `uncertainty_below_target`.
4. **Hỗ trợ phân giải Stratum theo `time_band` và `weather`:**
   - *Khắc phục:* `SamplingPlan.stratum_for` mở rộng nhận `time_band` và `weather`, giải quyết xung đột khi một camera có nhiều tầng theo ca/thời tiết.

## 3. Kiểm định chất lượng
- `mypy domain/quality_eval.py apps/edge/audit_sampler.py tools/negative_audit_report.py domain/event_contract.py --ignore-missing-imports` đạt **Success: no issues found in 4 source files**.
- `pytest tests/test_negative_audit_flow.py` đạt **47/47 passed (8 subtests passed)**.
- `git diff --check` sạch sẽ, không có lỗi định dạng hay khoảng trắng thừa.
