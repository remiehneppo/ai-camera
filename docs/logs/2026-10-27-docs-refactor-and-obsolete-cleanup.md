# Refactor Tài liệu Hệ thống & Loại bỏ các Quyết định Lỗi thời — 2026-10-27

Thực hiện theo yêu cầu của người dùng:
1. **Refactor và đồng bộ toàn diện tài liệu hệ thống**: Đồng bộ hóa chính xác trạng thái thực thi hiện tại (823 unit & integration tests pass, 31 tickets hoàn thành/hoạt động).
2. **Loại bỏ dứt điểm các quyết định và giả định kỹ thuật đã lỗi thời**: Tránh gây nhầm lẫn cho đội ngũ phát triển, kiểm thử và vận hành.

## 1. Danh sách 5 Quyết định & Giả định Lỗi thời đã bị Loại bỏ

| # | Giả định / Quyết định lỗi thời | Cập nhật & Khóa Chuẩn mới | Tài liệu chịu ảnh hưởng |
|---|---|---|---|
| 1 | **Neo `alert_condition` là đề xuất tương lai Q36 chưa được code** | Chuyển thành **hợp đồng neo chính thức đang hoạt động**: Cố định khoảng trích xuất raw [-10s, +20s] cho cả 3 engine nhận diện mở rộng (`vehicle_incident`, `illegal_parking`, `crowd_incident`). | `docs/architecture/contracts.md`, `CONTEXT.md` |
| 2 | **Rollback cấu hình có thể hạ sequence number hoặc bỏ qua chữ ký** | Khóa cứng quy tắc an ninh: **Tuyệt đối không hạ sequence / HWM**. Rollback về cấu hình cũ bắt buộc phải ký với `trust_sequence` mới cao hơn HWM hiện tại kèm role `config_signer` hoặc `config_rollback`. | `docs/architecture/contracts.md` (§8) |
| 3 | **Sử dụng dashcam (camera hành trình) và camera độ nét thấp (< 720p) để đánh giá nhận diện** | **Khóa cứng ODD phần cứng**: 100% camera CCTV giao thông CỐ ĐỊNH, độ nét từ HD (720p) đến 2MP (1080p). Loại bỏ vĩnh viễn dashcam (do luồng quang học biểu kiến ego-motion) và camera < 720p (do vỡ nét bounding box sinh gia tốc ảo). Thay thế bằng `AccidentBench HD 720p` và `UniDataPro 1080p`. | `CONTEXT.md`, `docs/requirements/technology-candidates.md`, `docs/datasets/video-datasets.md`, `docs/architecture/system-architecture.md` |
| 4 | **Giả định xe đứng yên ở frame 0 là vi phạm đỗ xe hoặc 2 xe gần nhau là va chạm** | Cập nhật chuẩn động học: Không xét zero-history (cần $\ge 2$ frame để đo vận tốc), đỗ xe đo `dwell_seconds` liên tục loại trừ rung lắc; va chạm xe bắt buộc phải có xung lực giảm tốc đột ngột (`impact_deceleration_threshold`) hoặc chồng lấn sâu kèm lệch hướng. | `CONTEXT.md`, `docs/architecture/system-architecture.md` |
| 5 | **Clip chưa ACK có thể bị xóa bằng TTL sau 24h ngắt mạng WAN** | Khóa nguyên tắc bất biến: **Tuyệt đối không đặt TTL xóa unACK evidence/events** trong thời gian WAN outage. Luôn ưu tiên xả toàn bộ metadata trước khi upload video clip và giải tỏa theo mô hình $T = B / (U - G)$. | `docs/architecture/contracts.md` (§9) |

## 2. Chi tiết các Tài liệu đã được Refactor & Đồng bộ

1. **`CONTEXT.md`**:
   - Bổ sung định nghĩa thuật ngữ chuẩn xác cho: `Vehicle incident`, `Pairwise interaction risk`, `Illegal parking`, `Dwell duration`, `Crowd concentration`, `Suspected public disorder`, và `Fixed CCTV Traffic Camera ODD`.
2. **`docs/architecture/contracts.md`**:
   - Mục 3: Cập nhật bảng neo bằng chứng với `alert_condition` chính thức hoạt động.
   - Mục 4: Bổ sung trạng thái `expired` trong chiều Server Availability (xóa video đĩa nhưng bảo tồn 100% receipt gốc `sha256`, `size_bytes`, ranges).
   - Mục 8 (Mới): Đặc tả chi tiết Signed Configuration & Rollback có thẩm quyền (#34, #35).
   - Mục 9 (Mới): Đặc tả chi tiết WAN Outage Autonomy 24h & Mô hình giải tỏa Backlog $B / (U - G)$ (#36).
3. **`docs/architecture/system-architecture.md`**:
   - Mục 1.1a: Cập nhật trạng thái thực thi của 4 nhóm nhận diện chính trên Edge (US09, US08, US05, US06).
   - Mục 1.3: Khóa ràng buộc ODD camera CCTV cố định 720p–1080p.
   - Mục 2: Cập nhật bảng quyết định (Allowlisted factories, shared geometry `apps/edge/geometry.py`, SQLite WAL+FULL, WanOutageCoordinator).
4. **`docs/architecture/deployment-readiness.md`**:
   - Khóa mục factsheet camera cố định; bổ sung kết quả benchmark CPU đạt 28–45 FPS thời gian thực trên video 720p/1080p.
5. **`docs/requirements/technology-candidates.md`**:
   - Xác nhận `YOLOX-Tiny` + `ByteTrack` + `RTMPose-Tiny` + domain kinematics là baseline sản xuất đã kiểm chứng; RF-DETR/ViTPose/Orin NX là ứng viên nghiên cứu tương lai, không cản trở baseline. Khóa quy chuẩn dataset cố định 720p–1080p.
6. **`docs/datasets/video-datasets.md`**:
   - Khóa vĩnh viễn quy tắc loại bỏ dashcam và camera < 720p; bổ sung 7 bộ dataset CCTV cố định chuẩn ODD và công cụ `tools/fetch_traffic_cctv_dataset.py`.
7. **`README.md` & `docs/README.md`**:
   - Đồng bộ hóa toàn bộ chỉ số: **823 unit & integration tests pass**, 126 subtests pass, cập nhật mục lục tra cứu nhanh theo vai trò.
8. **`.scratch/system-build-slices/PRD.md` & `requirements-expansion-index.md`**:
   - Đồng bộ tiến độ: 29 tickets `done`, 9 tickets `partial` trong software lab, cập nhật trạng thái của #62 và #63.

## 3. Bằng chứng Kiểm thử & Xác minh Toàn vẹn
- `mypy domain/ apps/ tools/` ⇒ **Success: no issues found in 68 source files**.
- Toàn bộ Test Suite toàn dự án: `pytest -q` ⇒ **823 passed, 360 warnings, 126 subtests passed in 150.77s** (0 regressions).
