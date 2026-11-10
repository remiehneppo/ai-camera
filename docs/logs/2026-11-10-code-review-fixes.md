# 2026-11-10 — Khắc phục Toàn bộ 16 Phát hiện từ Two-Axis Code Review (`Standards` & `Spec`)

## 1. Các lỗi thuộc trục `Spec` đã khắc phục
1. **NMS-free `CiviWatchDetector` crash khi `class_id >= 2` (`apps/edge/oracle_detector.py:130`):**
   - Tách điều kiện kiểm tra xác suất `[0, 1]`: ở chế độ `nms_free` chỉ kiểm tra cột `score` (`raw[..., 4:5]`), cho phép cột `class_id` (`raw[..., 5]`) mang giá trị `0..5` (`person`, `two_wheeler`, `car`, `bus`, `truck`, `obstacle_object`).
2. **Đấu nối `RtmposeEstimator.estimate_batch` vào `PoseManager.process_pending` (`apps/edge/pose.py:865-915`):**
   - Gom các `PoseRequest` hợp lệ cùng `frame_key` và gọi `self.estimator.estimate_batch(frame_rgb, [r.bbox for r in reqs])` một lượt duy nhất, có cơ chế fallback sang `estimate()` từng yêu cầu nếu 1 bbox lỗi.
3. **Sửa `US01` khói độc lập, cô lập trạng thái `US01/US02/US13`, cắt ROI môi trường & `transition_grace_seconds` (`apps/edge/urban_safety_engine.py`):**
   - Bỏ điều kiện ép `smoke` phải đi kèm `fire_ratio`; khói tự kích hoạt độc lập (`smoke_suspected`).
   - Tách riêng bộ đếm thời gian `self._env_active_since["US01_fire"]`, `"US01_smoke"`, `"US02"`, `"US13"` để các kịch bản không bao giờ xóa hẹn giờ của nhau trong chế độ `urban_safety_vlm`.
   - Thêm hàm `extract_environmental_signals(rgb, roi_polygon, frame_dimensions)` cắt đúng vùng ROI và hỗ trợ `transition_grace_seconds` cho `US13`.
4. **Sửa `US09.anchor_kind` & Mở rộng `validate_event` (`domain/urban_scenarios.py:198`, `domain/event_contract.py:118-152`):**
   - Sửa `US09.anchor_kind` từ `"person_fall_onset"` thành `"onset"` khớp với `domain/evidence_contract.py`.
   - Kiểm tra đầy đủ `verified` (`bool` nhất quán với `status`), `hard_negative_class`, `reasoning`, và `taxonomy` thuộc `ALL_URBAN_TAXONOMIES` khi sự kiện mang `scenario_id`.
5. **Tích hợp `GroundPlaneHomography.estimate_track_kinematics`, `VLMVerifier` cho cả 3 nhánh `VehicleIncidentEngine`, và `Go2RtcMediaEngine.extract_evidence_clip` (`apps/edge/vehicle_incident.py`, `apps/edge/media_engine.py`, `apps/edge/live_pipeline.py`):**
   - Gắn `metric_kinematics` (`x_m`, `y_m`, `speed_mps`, `accel_mps2`) vào payload khi có `homography`.
   - Áp dụng `_verify_candidate` cho cả 3 nhánh (`vehicle_vehicle`, `vehicle_rollover_or_barrier`, `vehicle_pedestrian`).
   - Bổ sung `extract_evidence_clip` có fallback sang `FileRecorder.pin` và gắn vào `LivePerceptionRunner`.
6. **Bổ sung mẫu lớp `5: obstacle_object` và tạo ONNX blueprint hợp lệ (`tools/prepare_mixed_traffic_dataset.py`, `tools/train_civiwatch_detector.py`):**
   - Bổ sung nhãn lớp `5` (`obstacle_object`) vào mẫu trộn và sinh đồ thị ONNX `[1, 3, 640, 640] -> [1, 300, 6]` hợp lệ thay cho chuỗi byte giả.

## 2. Các lỗi thuộc trục `Standards` đã khắc phục
1. **Tách `rgb` & Network I/O khỏi `process_tracks` (`apps/edge/pipeline.py`, `apps/edge/urban_safety_engine.py`, `apps/edge/vehicle_incident.py`):**
   - `PerceptionPipeline._dispatch_engine_process_tracks` trích xuất trước `environmental_signals` (metadata) truyền vào `process_tracks` thay vì truyền mảng `rgb`.
   - `PerceptionPipeline` quản lý `StoryboardBuilder` và `VLMVerifier` tập trung cho mọi engine; mặc định `VLMVerifier(endpoint_url="")` chạy `LocalVisualVerifier` thuần bộ nhớ, không phát sinh network I/O ngầm.
2. **Tách các ngưỡng thời gian độc lập và dọn các trường thừa trong `UrbanSafetyScenarioEngine`:**
   - Tách riêng `min_persistence_seconds`, `min_dwell_seconds`, `min_interaction_seconds`, `min_unattended_seconds`, `min_dark_duration_seconds`, `min_impact_duration_seconds` và xóa class `_EnvironmentalState` có các trường không dùng.
3. **Pure Domain Validation trong `domain/model_manifest.py`:**
   - Tách hàm thuần `validate_civiwatch_manifest_dict` không chứa I/O.
4. **Chuẩn hóa tên tham số `http_transport` và biến môi trường `CIVIWATCH_AIC_HCMC_DIR`.**

## 3. Kết quả Kiểm chứng
- **Regression Test Suite (`tests/test_civiwatch_detector_and_hcmc_tuning.py`):** 10/10 passed.
- **Toàn bộ Repository Test Suite (`pytest -q`):** **928 passed, 0 failures** (190 subtests).
- **Static Type Check (`mypy domain/ apps/ tools/`):** **Success: no issues found in 81 source files**.
