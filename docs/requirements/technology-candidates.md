# Ứng viên công nghệ và điều kiện đánh giá thay thế

**Cập nhật:** 2026-10-30 · **Trạng thái:** Phân định rạch ròi giữa **baseline phần mềm đang vận hành trong lab** và **các ứng viên nâng cấp mô hình / phần cứng nhúng** đang chờ đánh giá conformance (`G1`), chất lượng (`G2`) và tải thực tế (`G3`).

Tài liệu liên quan: [Kiến trúc hệ thống](../architecture/system-architecture.md) · [Hợp đồng tích hợp](../architecture/contracts.md) · [Kế hoạch triển khai](../architecture/implementation-plan.md) · [Danh mục tình huống](urban-safety-scenarios.md) · [Sổ đăng ký dataset](../datasets/video-datasets.md).

---

## 1. Baseline phần mềm hiện hành (Đã triển khai & kiểm chứng trong Lab)

| Thành phần | Công nghệ đang vận hành | Trạng thái & Điểm thực thi | Giới hạn hiện tại |
|---|---|---|---|
| **Detector** | `YOLOX-Tiny` (ONNX `416×416`, 80 lớp COCO) | **Đang hoạt động** (`apps/edge/oracle_detector.py`, ghim SHA-256 tại `models/yolox-tiny/`) | Pretrained trên COCO tổng quát; cần kiểm định và fine-tune cho góc cao CCTV giao thông Việt Nam nếu thiếu recall |
| **Tracker** | `ByteTrack` (có cổng lọc nhóm nhãn thô `person` vs `two_wheeler`/`motor_vehicle`) | **Đang hoạt động** (`apps/edge/tracker.py`) | Cần đo độ phân mảnh ID (`ID-switch`) dưới mật độ xe máy dày đặc trên luồng RTSP dài hạn |
| **Pose Estimator** | `RTMPose-Tiny` (ONNX `256×192`, 17 keypoints SimCC + `PoseScheduler`) | **Đang hoạt động** (`apps/edge/pose.py`, ghim SHA-256 tại `models/rtmpose-tiny/`) | Chỉ chạy trên các bounding box `person` đủ điều kiện ngân sách & chất lượng ảnh |
| **5 Alert Feature Pipelines** | `person_down`, `danger_zone`, `vehicle_incident`, `illegal_parking`, `crowd_incident` + centralized `snapshot.py` | **Đang hoạt động** (`apps/edge/`, [ADR-0001](../adr/0001-feature-pipeline-boundaries.md), [ADR-0005](../adr/0005-incident-snapshot-ownership.md)) | Hoàn tất kiểm thử phần mềm (`896` tests); chưa ký nghiệm thu `G2` trên cohort CCTV cố định |
| **Runtime & Nguồn video Lab** | ONNX Runtime CPU (`1.20.1`) + OpenCV/FFmpeg file replay & semantic evaluators | **Đang hoạt động** (`tools/eval_*.py`, [ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md)) | Đạt `16.35–20.10 FPS` (Baseline) và `8.84–15.88 FPS` (+Pose) trên CPU `i5-12400F` 1080p; chưa đại diện cho thiết bị biên |

---

## 2. Hồ sơ các ứng viên nâng cấp (Chưa thay thế Baseline)

Không được thay đổi mặc định runtime hoặc tuyên bố hỗ trợ sản xuất cho các ứng viên dưới đây khi chưa hoàn tất toàn bộ cột **Điều kiện bắt buộc trước khi chấp nhận**:

| Hạng mục | Ứng viên đề xuất | Lý do đưa vào diện đánh giá | Rủi ro kỹ thuật & vận hành | Điều kiện bắt buộc trước khi chấp nhận |
|---|---|---|---|---|
| **Detector thế hệ mới** | **RF-DETR** | Cải thiện khả năng phát hiện vật thể nhỏ/bị che khuất một phần ở góc máy CCTV lắp cao | Chi phí tính toán cao hơn `YOLOX-Tiny`; cần kiểm chứng xuất TensorRT/ONNX FP16/INT8 và bản quyền từng biến thể trọng số | Ghim SHA-256 checkpoint + giấy phép thương mại; vượt golden conformance, so sánh công bằng với `YOLOX-Tiny` trên cùng cohort CCTV cố định (`G2`) và đạt ngân sách độ trễ trên board đích (`G3`) |
| **Pose Estimator nâng cao** | **ViTPose** (các biến thể nhẹ) | Độ chính xác keypoint cao hơn khi tư thế người nằm co/khuất một phần sau xe | Tải suy luận theo từng ROI người lớn khi khung hình đông người (burst load) | Giữ nguyên hợp đồng 17 keypoints & terminal outcomes của `PoseScheduler`; chứng minh không gây trễ hàng đợi khi burst người trong bài soak `G3` |
| **Phần cứng biên (Edge SoM)** | **NVIDIA Jetson Orin NX** *(8 GB / 16 GB — không dùng Xavier NX)* | Hỗ trợ NVDEC giải mã cứng đa luồng và TensorRT cho phép chạy đồng thời nhiều module cảnh báo trên camera 1080p | Chưa chốt SKU RAM (8 GB vs 16 GB), tản nhiệt vỏ hộp ngoài trời, nguồn cấp và chi phí BOM trên mỗi cụm camera | Khóa SKU RAM + phiên bản JetPack/TensorRT; đo tải toàn hệ thống (NVDEC + AI + `FileRecorder` + SQLite WAL + Upload) liên tục 24–72h đạt ngưỡng nhiệt và FPS (`G3`) |
| **Nhóm tình huống chuyên biệt (`US01–04, US07, US11–14`)** | Các mô hình/nhánh chuyên biệt (lửa/khói, mức ngập, rác/vật bỏ quên, hành động bạo lực/phá hoại) | `YOLOX` + `RTMPose` trên tập lớp COCO không có lớp ngữ nghĩa cho lửa, khói, mặt nước ngập, cây đổ hay đèn đường | Mở đồng loạt sẽ làm phình bộ nhớ/VRAM và phát sinh báo động giả cao nếu thiếu dữ liệu đặc thù | Chỉ mở từng nhóm khi có tập dữ liệu CCTV cố định có nhãn, model/rule chuyên biệt đạt `G2` và vượt cổng mở rộng `G4b` |

---

## 3. Nguyên tắc đánh giá công bằng trên Dữ liệu CCTV Cố định

1. **Tuân thủ tuyệt đối ODD Camera Giao thông Cố định (720p–1080p):** Mọi phép so sánh giữa Baseline (`YOLOX-Tiny` + `RTMPose-Tiny`) và Ứng viên (`RF-DETR` + `ViTPose`) phải chạy trên cùng một tập video **camera giao thông gắn cố định có nhãn sự kiện độc lập** (xem [video-datasets.md](../datasets/video-datasets.md)). Không dùng các clip dashcam (`AccidentBench`, `DAD`, `A3D`), clip có zoom/reframing (`shibuya`, `intersection_traffic_1080p`) hoặc video `< 720p` để kết luận chất lượng mô hình.
2. **Đánh giá ở cấp Sự kiện & Chi phí Vận hành, không chỉ mAP khung hình:** Báo cáo so sánh phải đo qua cùng `PerceptionPipeline` ([ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md)), xuất đủ: tỷ lệ phát hiện đúng sự kiện, số báo động giả trên mỗi camera-ngày, độ trễ từ mốc đủ điều kiện tới lúc phát sự kiện và tổng chi phí tính toán/bộ nhớ.
3. **Bảo toàn hợp đồng biên ([ADR-0004](../adr/0004-integration-contracts.md), [ADR-0005](../adr/0005-incident-snapshot-ownership.md)):** Thay thế mô hình hoặc phần cứng chỉ diễn ra ở tầng adapter và manifest cấu hình; tuyệt đối không phá vỡ định dạng snapshot sự kiện, cơ chế ghim bằng chứng hay luồng xác minh trên Server.
