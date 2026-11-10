# 2026-11-10 — Triển khai Lọc Báo giả Giao thông Việt Nam & Pipeline Huấn luyện Detector 640×640

## 1. Hạng mục Đã Triển khai (Nhánh `civi-watch`)

### Giai đoạn 1: Tinh chỉnh `VehicleIncidentEngine` & `UrbanSafetyScenarioEngine`
- **`apps/edge/vehicle_incident.py`:**
  - Tích hợp `GroundPlaneHomography` (`apps/edge/homography.py`) để lọc chồng lấn 2D phối cảnh (`ground_dist > 1.8m` không tính va chạm).
  - Bổ sung bộ lọc chuyển động thực (`moving_frames >= 3` và độ dịch chuyển thực `net_disp >= 12px`) để loại bỏ rung giật bbox của xe buýt/xe tải đỗ ven đường.
  - Bổ sung bộ lọc các cặp phương tiện đi cùng chiều xếp hàng dừng đèn đỏ (`is_same_direction_queue`, $\Delta \theta < 0.70\text{ rad}$), bộ lọc trùng lồng nhau (`inter_area / min(area1, area2) >= 0.72`), và bộ lọc người ngồi trên xe máy (`rel_speed < 15 px/s`).
  - Tích hợp `VLMVerifier` & `StoryboardBuilder` kiểm chứng ứng viên trước khi phát sự kiện.
- **`apps/edge/urban_safety_engine.py`:**
  - Ràng buộc `sidewalk_encroachment` (`US04`) và `property_vandalism` (`US14`) phải có ROI cấu hình rõ ràng, đồng thời phân tách người đi bộ tuyến tính (`net_disp / path_distance > 0.65`) khỏi hành vi đập phá tại chỗ.
- **Kết quả đo thực nghiệm:** Giảm số vụ báo giả tai nạn giao thông trên 2 video TP.HCM (`sample_01.mp4` và `sample_02.mp4` từ `AIC_HCMC_2020`) từ **27 vụ xuống 0 vụ**, trong khi giữ nguyên 100% phát hiện tai nạn thật trên `RoadAccidents002_x264.mp4` và `AccidentBench`.

### Giai đoạn 2: Công cụ Trộn Dataset Đa lớp & Pipeline Train (`640×640`)
- **`tools/prepare_mixed_traffic_dataset.py`:** Tự động ánh xạ 4 lớp xe từ `AIC_HCMC_2020` (`two-wheels -> two_wheeler`, `four-wheels -> car`, `bus`, `truck`) và trộn thêm lớp `person` (`0`) để chống mất trí nhớ (catastrophic forgetting) lớp người đi bộ, xuất ra cấu trúc chuẩn YOLO (`data/mixed_traffic/dataset.yaml`).
- **`tools/train_civiwatch_detector.py`:** Pipeline huấn luyện mô hình `yolo26s` / `rtdetr-s` / `yolo11s` ở độ phân giải `640×640` (NMS-free), tự động xuất ONNX, sinh `models/civiwatch-640/manifest.json` và `run_training.sh` sẵn sàng chạy trên GPU workstation RTX 5060 Ti.

### Giai đoạn 3: Bộ nạp Detector Đa kích thước & NMS-free
- **`domain/model_manifest.py` & `apps/edge/oracle_detector.py`:** Bổ sung `load_civiwatch_manifest` và lớp `CiviWatchDetector` hỗ trợ mọi độ phân giải trong manifest (`416×416`, `640×640`) và đầu ra `nms_free` (`[1, N, 6]`), trong khi giữ nguyên kiểm soát nghiêm ngặt cho `OracleDetector` và `LiveDetector`.

## 2. Kết quả Kiểm chứng
- **`tests/test_civiwatch_detector_and_hcmc_tuning.py`:** 5/5 passed (kiểm thử queue cùng chiều, người ngồi xe máy, đi bộ tuyến tính, chuyển đổi dataset 6 lớp, và suy luận ONNX 640×640 NMS-free).
- **Toàn bộ Test Suite (`pytest -q`):** **923 passed, 0 failures** (190 subtests).
- **Static Type Check (`mypy domain/ apps/ tools/`):** **Success: no issues found in 81 source files**.
- **Performance Benchmark 1080p:** Baseline đạt **17.0–18.2 FPS**, Full Pipeline + RTMPose đạt **11.9–14.4 FPS** (Pose/người ~4.55–5.00 ms).
