# Nhật ký Điều phối & Tích hợp Ticket #53 — 2026-10-21

## 1. Mục tiêu và Phạm vi
- **Ticket #53:** Pose outcomes đi vào person-down flow.
- **Phân loại độ phức tạp:** L2 (tích hợp xuyên module giữa edge perception, incident engine, event contract, outbox, server store, review API và dataset export).
- **Mô hình thực thi:** Subagent delegation (`deepseek-official/deepseek-flash`) + Dispatcher review, khắc phục sự cố hạ tầng và nghiệm thu cuối cùng.

## 2. Phân rã công việc & Điều phối Subagents

### Subagent 1: Triển khai Edge Perception & Incident Engine (`apps/edge/incident.py`, `apps/edge/pipeline.py`)
- Mở rộng `IncidentEngine.process_tracks` hỗ trợ tham số `pose_outcomes` (tương thích ngược hoàn toàn).
- `_TrackIncidentState`: bổ sung `last_valid_pose` (chỉ cập nhật khi `status == "ok"`) và `last_pose_outcome` (cập nhật status, reason, branch, executed_at).
- Loại trừ hoàn toàn việc tạo keypoint giả hoặc suy diễn negative khi pose request bị skipped/failed/cancelled.
- `_create_incident`: đính kèm `pose_evidence` nguyên vẹn vào incident dict.
- `PerceptionPipeline._process_frame`: chuyển tiếp `pose_outcomes` từ `pose_manager.process_pending()` sang `incident_engine.process_tracks`.
- `PerceptionPipeline._handle_incident`: bổ sung `pose_evidence` vào payload và cập nhật `model_lineage` thêm entry `{"role": "pose_estimator", "version": "rtmpose-tiny-256x192"}`.
- Đảm bảo `validate_event` tuân thủ 100% schema và giới hạn dung lượng payload (64 KB).

### Subagent 2: Bộ Integration Fixtures Xác định (`tests/test_pose_outcomes_flow.py`)
- Xây dựng 5 kịch bản tích hợp kiểm thử chặt chẽ theo acceptance criteria của issue:
  1. `test_pose_outcome_success_reaches_incident_and_event`: Mô hình RTMPose thật + chuỗi ngã xác định → phát `person_fall` có `pose_evidence` (17 keypoint COCO), anchor giữ onset, outbox & event payload lưu đầy đủ lineage.
  2. `test_pose_outcome_skipped_and_failed_do_not_create_false_negative_or_fake_keypoints`: Quá hạn deadline hoặc lỗi inference trả về `keypoints=[]`, cảnh báo ngã không bị triệt tiêu (no false negative suppression).
  3. `test_track_gap_and_clock_jump_resets_pose_evidence_without_false_certainty`: Gap lớn hơn `max_observation_gap` hoặc bước nhảy thời gian lùi (clock jump) lập tức reset toàn bộ state pose cũ, chuyển taxonomy sang `person_lying_persistent` mà không mang theo certainty giả.
  4. `test_overload_shedding_and_recovery_flow`: Hàng đợi quá tải kích hoạt overload shedding (`skipped`/`queue_full`), ghi nhận trạng thái `degraded`, sau đó khôi phục `full` qua chu kỳ hysteresis.
  5. `test_e2e_pose_outcomes_through_outbox_to_server_and_review`: Luồng E2E từ pipeline → outbox → API server `/v1/events` → xác nhận review qua `/v1/events/{device_id}/{event_id}/review` → export dataset `/v1/dataset/export` bảo toàn trọn vẹn cả `model_lineage` và `pose_evidence`.

## 3. Hoạt động Review & Fix Issues của Dispatcher
- **Khắc phục lỗi MongoDB connection limit (`compose.yaml`):**
  - Trong quá trình chạy test đồng thời với khối lượng lớn database tạm thời từ pytest, MongoDB container gặp lỗi `DBException::TooManyFilesOpen: error in creating eventfd: Too many open files, errno: 24` và từ chối kết nối mạng.
  - Dispatcher đã điều chỉnh `compose.yaml` cấu hình `ulimits.nofile: soft: 65536, hard: 65536` cho service `mongo`, tái tạo container và giải quyết triệt để tình trạng nghẽn file descriptor.
- **Kiểm định test suite:**
  - `tests/test_pose_outcomes_flow.py` đạt 5/5 passed.
  - `tests/test_server_evidence.py` đạt 13/13 passed.
  - Toàn bộ test suite dự án (`pytest -q`) đạt **450 passed, 180 warnings, 112 subtests passed** (100% test xanh).

## 4. Cập nhật Tracker
- `.scratch/system-build-slices/issues/53-pose-outcomes-di-vao-person-down-flow.md`: Tích toàn bộ 5 tiêu chí acceptance, chuyển `Execution: done (software lab)`, ghi nhận bằng chứng đầy đủ.
- `.scratch/system-build-slices/PRD.md`: Cập nhật tiến độ #53 hoàn tất trong software lab và tổng số 450 tests xanh.
