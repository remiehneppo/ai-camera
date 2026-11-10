---
status: accepted
---

# ADR-0008: Kiến trúc CiviWatch v2 — Hybrid VLM Temporal Storyboard, 14 Kịch bản Đô thị & Zero-Plumbing Media

Ngày: 2026-11-09. Phân loại: Kiến trúc tổng thể (Clean-Slate v2 & Hard Rebrand). Trạng thái: accepted; đã triển khai và kiểm chứng trên nhánh `civi-watch` (918 tests pass, 79 source files `mypy` clean).

## 1. Bối cảnh (Context)

Hệ thống ban đầu (`AI-Camera-OC` / `camera_lab`) có độ lệch giữa thiết kế và thực thi:
1. Chỉ mới bao phủ 5/14 nhóm kịch bản an toàn đô thị (`US05`, `US06`, `US08`, `US09`, `US10`) bằng các luật 2D bounding-box đơn lẻ; 9 nhóm còn lại (`US01` cháy/khói, `US02` ngập nước, `US03` đổ trộm rác, `US04` lấn chiếm vỉa hè, `US07` ẩu đả, `US11` vật bỏ quên, `US12` cây đổ, `US13` đèn đường hỏng, `US14` phá hoại tài sản) chưa có cơ chế nhận diện và lọc báo giả (hard negatives) thống nhất.
2. Vận tốc/gia tốc đang tính trên không gian pixel 2D phụ thuộc mạnh vào phối cảnh gần/xa của camera; tiền xử lý/hậu xử lý YOLOX và suy luận RTMPose tuần tự từng người gây tốn CPU khi khung hình đông người.
3. Định danh hệ thống phân mảnh giữa `AI-Camera-OC`, `camera_lab`, `ai_camera`, và `OneChain`.

## 2. Quyết định Kỹ thuật (Decisions)

### 2.1. Hard Rebrand 100% sang `CiviWatch` (`civi-watch`)
- Toàn bộ định danh thương hiệu, API, UI, CLI, Docker Compose và hằng số mặc định được chuyển cứng sang **CiviWatch**:
  - Database mặc định: `MONGO_DATABASE = "civi_watch"`.
  - Thư mục bằng chứng mặc định: `EVIDENCE_DIR = "/tmp/civi-watch-evidence"`.
  - API: `FastAPI(title="CiviWatch API", version="2.0.0")`.
  - Giao diện điều hành: **CiviWatch Operations Center** (`civi_watch_dash_token`, `civi_watch_rev_token`).

### 2.2. Kiến trúc 4 Tầng CiviWatch v2
1. **Tầng 1 — Zero-Plumbing Media & Evidence Engine (`infra/go2rtc.yaml`, `apps/edge/media_engine.py`):**
   - Sử dụng `go2rtc` (`Go2RtcMediaEngine`) để kéo luồng RTSP một lần duy nhất, phân phối sang WebRTC (`<300ms`), MJPEG, RTSP relay và MP4 stream-copy, kết hợp fallback `FileRecorder` cục bộ khi chạy độc lập.
2. **Tầng 2 — High-Speed Vectorized Perception & Ground-Plane Homography:**
   - **Vectorized YOLOX (`apps/edge/oracle_detector.py`):** Tiền tính toán lưới stride `_grid_xy` / `_grid_strides` một lần khi khởi tạo; chỉ chạy NMS trên tập `active_classes` có ứng viên vượt ngưỡng; mở tùy chọn `strict_runtime=False` và `providers` cho GPU/TensorRT.
   - **Dynamic Batching RTMPose (`apps/edge/pose.py`):** Bổ sung `RtmposeEstimator.estimate_batch(rgb, bboxes)` chạy suy luận một lượt trên tensor `[N, 3, 256, 192]`.
   - **Ground-Plane Homography (`apps/edge/homography.py`):** Chuyển đổi điểm tiếp đất `(foot_u, foot_v)` sang tọa độ mặt đường thực tế `(X_m, Y_m)` tính bằng mét qua ma trận phối cảnh $H \in \mathbb{R}^{3\times 3}$, cung cấp vận tốc ($\text{m/s}$) và gia tốc ($\text{m/s}^2$) bất biến phối cảnh.
3. **Tầng 3 — Hybrid VLM Temporal Storyboard Verifier & Phủ trọn 14 Kịch bản (`US01`–`US14`):**
   - **Danh mục 14 kịch bản chuẩn (`domain/urban_scenarios.py`):** Mở rộng `ALLOWLISTED_FACTORIES` và `URBAN_SAFETY_TAXONOMIES` lên đủ 14 nhóm `US01–US14` (15 allowlisted factories bao gồm `urban_safety_vlm`).
   - **2×3 Temporal Storyboard Grid (`apps/edge/vlm_verifier.py`):** `StoryboardBuilder` trích xuất 6 keyframes tại các mốc `[-5s, -2s, 0s, +1s, +2s, +3s]` quanh thời điểm neo sự kiện, vẽ khung Set-of-Mark và ghép thành lưới `2×3`.
   - **Tier-2 VLM Verifier (`VLMVerifier`):** Hỗ trợ gọi endpoint OpenAI/vLLM/Ollama Vision (`Qwen2.5-VL-3B-Instruct` / `InternVL3`) với JSON Schema output hoặc chạy `LocalVisualVerifier` tất định khi offline, đính kèm kết quả vào `payload.vlm_verification` (`status`, `model_id`, `confidence`, `hard_negative_class`, `reasoning`).
   - **Unified Scenario Engine (`apps/edge/urban_safety_engine.py`):** Triển khai `UrbanSafetyScenarioEngine` xử lý trọn vẹn 9 nhóm mở rộng (`US01`, `US02`, `US03`, `US04`, `US07`, `US11`, `US12`, `US13`, `US14`) cùng 5 engine chuyên biệt hiện hữu.
4. **Tầng 4 — CiviWatch Operations Center (`apps/server/static/index.html`):**
   - Hỗ trợ lọc và hiển thị đầy đủ 14 kịch bản `US01–US14` cùng thông tin hậu kiểm `vlm_verification`, giữ nguyên hợp đồng chống XSS (`createElement` + `textContent`) và quy trình review có kiểm soát phiên bản.

## 3. Hệ quả (Consequences)

- Giữ nguyên toàn bộ hợp đồng bất biến của [ADR-0001](0001-feature-pipeline-boundaries.md), [ADR-0004](0004-integration-contracts.md), [ADR-0005](0005-incident-snapshot-ownership.md) và [ADR-0006](0006-semantic-replay-pipeline-reuse.md): mỗi module vẫn giữ state/config độc lập theo `module × camera`, `build_incident_snapshot` vẫn là chủ sở hữu duy nhất tạo full snapshot, và chính sách neo bằng chứng Q36 (`[-10s, +20s]`) không thay đổi.
- Khi VLM server bên ngoài không cấu hình hoặc lỗi mạng, hệ thống không bao giờ chặn luồng cảnh báo mà chuyển sang `LocalVisualVerifier` hoặc ghi nhận `status="failed"` (giữ nguyên nguyên tắc *"Observation missing/failed không biến thành negative"*).
