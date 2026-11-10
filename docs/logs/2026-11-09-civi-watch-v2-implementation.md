# 2026-11-09 — Triển khai Kiến trúc CiviWatch v2 (Clean-Slate Rebuild & Hard Rebrand)

## 1. Mục tiêu & Phạm vi thực hiện
- Tạo và chuyển sang nhánh Git mới `civi-watch`.
- Thực hiện **Hard Rebrand 100%** toàn bộ hệ thống từ `AI-Camera-OC` / `AI Camera Lab` / `camera_lab` sang **`CiviWatch` (`civi-watch`)**:
  - Database mặc định: `civi_watch` (`apps/server/config.py`, `apps/server/export_dataset.py`, `run_server.py`, `compose.yaml`).
  - Thư mục lưu trữ bằng chứng mặc định: `/tmp/civi-watch-evidence` (`apps/server/config.py`, `Dockerfile`, `compose.yaml`, `run_server.py`).
  - Giao diện trung tâm điều hành: **CiviWatch Operations Center** (`apps/server/static/index.html`) với khóa lưu trữ token `civi_watch_dash_token` và `civi_watch_rev_token`.
  - API Server: `FastAPI(title="CiviWatch API", version="2.0.0")` (`apps/server/main.py`).

## 2. Các nâng cấp kiến trúc cốt lõi (CiviWatch v2 4-Tier Architecture)
1. **Tầng 1 — Media & Evidence Stream Engine (`infra/go2rtc.yaml`, `apps/edge/media_engine.py`, `compose.yaml`):**
   - Tích hợp cấu hình `go2rtc` zero-plumbing hỗ trợ fan-out luồng camera sang WebRTC, RTSP relay, MP4 stream-copy và chụp ảnh nhanh JPEG keyframe.
   - Xây dựng `Go2RtcMediaEngine` cung cấp endpoint định danh theo từng camera và cơ chế fallback an toàn khi chạy độc lập.
2. **Tầng 2 — High-Speed Vectorized Perception & Ground-Plane Homography:**
   - **Vectorized YOLOX Postprocessing (`apps/edge/oracle_detector.py`):** Tiền tính toán lưới tọa độ `_grid_xy` và `_grid_strides` một lần duy nhất lúc khởi tạo model; lọc nhanh tập `active_classes` có xác suất vượt ngưỡng trước khi chạy NMS từng lớp; mở tùy chọn `strict_runtime=False` và `providers` để chạy với `CUDAExecutionProvider` / `TensorRTExecutionProvider`.
   - **Dynamic Batching cho RTMPose (`apps/edge/pose.py`):** Thêm phương thức `RtmposeEstimator.estimate_batch(rgb, bboxes)` gom toàn bộ bounding box người trong khung hình thành một tensor `[N, 3, 256, 192]`.
   - **Ground-Plane Homography (`apps/edge/homography.py`):** Chuyển đổi tọa độ chân đối tượng `(u, v)` trên ảnh sang hệ tọa độ mặt đường thực tế `(X_m, Y_m)` tính theo mét bằng ma trận phối cảnh $3\times 3$, kèm hàm ước lượng vận tốc ($\text{m/s}$) và gia tốc ($\text{m/s}^2$) bất biến theo phối cảnh.
3. **Tầng 3 — Hybrid VLM Temporal Storyboard Verifier & Phủ trọn 14 Kịch bản (`US01`–`US14`):**
   - **`domain/urban_scenarios.py` & `domain/event_contract.py`:** Định nghĩa đầy đủ 14 nhóm kịch bản an toàn đô thị (`US01` Cháy/khói, `US02` Ngập nước, `US03` Đổ trộm rác, `US04` Lấn chiếm vỉa hè, `US05` Đỗ xe sai quy định, `US06` Tụ tập/Gây rối, `US07` Ẩu đả, `US08` Tai nạn giao thông, `US09` Người ngã/nằm đường, `US10` Vùng nguy hiểm, `US11` Vật bỏ quên, `US12` Cây đổ, `US13` Đèn đường hỏng, `US14` Phá hoại tài sản).
   - **`apps/edge/vlm_verifier.py`:** Xây dựng `StoryboardBuilder` ghép 6 khung hình theo mốc thời gian `[-5s, -2s, 0s, +1s, +2s, +3s]` thành ảnh lưới `2x3` có vẽ khung Set-of-Mark, kết hợp `VLMVerifier` (hỗ trợ cả OpenAI/vLLM Vision JSON Schema endpoint và `LocalVisualVerifier` chạy offline).
   - **`apps/edge/urban_safety_engine.py` & `apps/edge/pipeline.py`:** Tích hợp đầy đủ 14 factory kịch bản vào `ALLOWLISTED_FACTORIES` và `PerceptionPipeline`.
4. **Tầng 4 — CiviWatch Operations Center UI (`apps/server/static/index.html`):**
   - Cập nhật bộ lọc 14 kịch bản `US01–US14`, hiển thị bảng thông số kỹ thuật và kết quả hậu kiểm `Tier-2 VLM Storyboard` trên từng thẻ sự kiện, tuân thủ tuyệt đối nguyên tắc chống XSS (`createElement` + `textContent`).
