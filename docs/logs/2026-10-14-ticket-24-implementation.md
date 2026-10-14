# Implementation & Review Log — Ticket #24 (2026-10-14)

## Context & Objectives
Triển khai Ticket #24: **Pose scheduling và degradation có coverage** thuộc luồng Person-down (Task nguồn: P02, P04, O03, O02).
- Lập lịch công bằng (fairness & anti-starvation) cho 3 nhánh: `fast_fall` (nguy cơ ngã nhanh), `slow_collapse` (hạ thấp dần dần), `persistent_lying` (nằm bất động trên đường).
- Đo lường chi tiết theo từng nhánh: `scheduled`, `attempted`, `skipped`, `failed`, `stale` và `coverage`.
- Cơ chế suy thoái (degradation) khi quá tải: xả tải (shedding) việc ưu tiên thấp trước, chuyển trạng thái `degraded` kèm lý do cụ thể.
- Cơ chế phục hồi có độ trễ (Hysteresis recovery ramp): yêu cầu số chu kỳ bình ổn liên tiếp để tránh flapping.
- Tích hợp `PerceptionPipeline` và ghi nhận metadata quan sát.

## Implementation Details
1. **`apps/edge/pose.py`**:
   - Thêm `BranchMetrics` tính toán coverage và số lượng request theo từng nhánh.
   - Thêm `PoseScheduler`:
     - Phân loại `classify_track` theo kinematics và aspect ratio.
     - Phân bổ ngân sách `schedule_batch` đảm bảo `min_shares` cho cả 3 nhánh.
     - Xả tải có thứ tự: bỏ `persistent_lying` -> giảm `slow_collapse`.
     - Chuyển `capability_status="degraded"` kèm lý do (`overload_shedding_routine_pose`, `queue_near_capacity`).
     - Hysteresis phục hồi với `recovery_cycles=3`.
     - Prune dictionary `_last_scheduled_time` định kỳ chống rò rỉ bộ nhớ.
   - Tích hợp `PoseManager` đồng bộ outcome và queue bounds.
2. **`apps/edge/pipeline.py`**:
   - Tự động nhận diện và lên lịch ứng viên qua `PoseScheduler`.
   - Cung cấp `status()`, `get_pose_capability()`, `get_pose_metrics()` và gắn vào observation metadata.
3. **`tests/test_pose.py`**:
   - 12 test cases mới kiểm thử toàn diện: phân loại nhánh, burst anti-starvation, metrics coverage, degradation shedding, hysteresis recovery và pipeline integration.

## OpenCodeReview (OCR) Findings & Remediation
- Review bằng `ocr review` với model `Gemini 3.8 Flash (High)`:
  1. *Pose capability shadow*: Đảo thứ tự kiểm tra `pose_manager` trước `pose_scheduler` trong `get_pose_capability` để phản ánh đúng khi `estimator is None`.
  2. *Epoch synchronization*: Đồng bộ `set_epoch` khi `pose_scheduler` là instance độc lập.
  3. *Duplicate terminal outcomes*: Khử việc gọi `.extend(shed_outcomes)` hai lần trong `process_pending`.
  4. *Preserve degradation reason*: Bảo toàn `degraded_reason` khi có nhiều nguyên nhân suy thoái.
  5. *Memory pruning*: Cắt tỉa `_last_scheduled_time` định kỳ khi kích thước > 1000.
  6. *Pre-dispatch queue count for hysteresis*: Tính toán trạng thái bình ổn `calm` trên số lượng phần tử trước khi rút batch (`initial_queue_count`), tránh đánh giá sai thành calm khi tải cao.
  7. *Targeted shed outcomes collection*: Chỉ đưa vào `_terminal_outcomes` khi `submit_request` trả về `False` (bị drop ngay lúc enqueue), giúp `schedule_batch` ghi nhận đầy đủ việc xả tải trong chu kỳ.
  8. *Synchronize scheduler in pipeline*: Đồng bộ `self.pose_manager.scheduler = pose_scheduler` và kiểm tra `pose_manager.get_metrics()` trước `pose_scheduler`.

## Verification Evidence
- `tests.test_pose`: 24/24 tests passed (0.565s).
- Full regression suite: 72 tests passed (16.373s).
- Mypy: 0 errors trên toàn bộ file liên quan.
