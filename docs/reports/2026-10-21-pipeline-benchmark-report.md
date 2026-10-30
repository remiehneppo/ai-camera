# Báo cáo Benchmark Hiệu năng Edge AI Camera Pipeline

**Ngày thực hiện:** 2026-10-21 12:15:58
**Môi trường:** Ubuntu Linux x86_64, Intel Core i5-12400F, ONNX Runtime (CPUExecutionProvider)
**Mô hình:**
- Detector: `YOLOX-Tiny` (ONNX, 416x416, COCO 80 classes)
- Tracker: `ByteTrack` (Python reference implementation)
- Incident Engine: `IncidentEngine` (behavioral fall / dwell / cooldown analysis)
- Pose Estimator: `RTMPose-Tiny` (ONNX, 256x192, 17 keypoints SimCC)
- Storage & Outbox: `FileRecorder` (segment ring buffer) & `EventOutbox` (SQLite WAL)
- **Phạm vi báo cáo:** Số đo thông lượng & độ trễ phần mềm tham chiếu trên CPU x86 (`120` frames, `sample_fps=10.0`). Hai clip đô thị 1080p dưới đây có zoom/reframing nên chỉ dùng để đo tải tính toán (compute profiling), **không** dùng làm bộ kiểm định chất lượng ODD camera giao thông cố định (xem [video-datasets.md](../datasets/video-datasets.md)).
---

## 1. Bảng so sánh tổng hợp

| Video kịch bản | Cấu hình | Độ phân giải | Số frame | Thời gian (s) | Throughput (FPS) | Detections/frame | Peak RAM (MB) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `shibuya_crossing_1080p.mp4` | **Baseline (YOLOX + ByteTrack)** | 1920x1080 | 120 | 6.71s | **17.88** | 4.7 | 273.5 MB |
| `shibuya_crossing_1080p.mp4` | **Full Pipeline + RTMPose** | 1920x1080 | 120 | 8.852s | **13.56** | 4.7 | 520.1 MB |
| `intersection_traffic_1080p.mp4` | **Baseline (YOLOX + ByteTrack)** | 1920x1080 | 120 | 6.196s | **19.37** | 10.1 | 336.1 MB |
| `intersection_traffic_1080p.mp4` | **Full Pipeline + RTMPose** | 1920x1080 | 120 | 7.558s | **15.88** | 10.1 | 530.7 MB |

---

## 2. Chi tiết độ trễ từng công đoạn (Latency Breakdown in ms)

| Kịch bản & Cấu hình | Công đoạn | P50 (Median) | P90 | P95 | Max | Mean |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **shibuya_crossing_1080p.mp4 (Base)** | **Tổng Pipeline** | **44.73** | **52.96** | **108.86** | 175.75 | 52.45 |
| shibuya_crossing_1080p.mp4 (Base) | Decode & RGB | 1.46 | 1.79 | 1.82 | 40.66 | 1.88 |
| shibuya_crossing_1080p.mp4 (Base) | YOLOX Preprocess | 10.63 | 12.85 | 13.63 | 16.51 | 10.73 |
| shibuya_crossing_1080p.mp4 (Base) | YOLOX Inference | 14.37 | 15.94 | 16.52 | 25.97 | 14.77 |
| shibuya_crossing_1080p.mp4 (Base) | YOLOX Postprocess | 2.15 | 2.35 | 2.41 | 3.29 | 2.18 |
| **shibuya_crossing_1080p.mp4 (Pose)** | **Tổng Pipeline** | **53.25** | **73.9** | **88.82** | 124.83 | 57.63 |
| shibuya_crossing_1080p.mp4 (Pose) | Decode & RGB | 2.17 | 5.16 | 5.29 | 7.79 | 2.99 |
| shibuya_crossing_1080p.mp4 (Pose) | YOLOX Preprocess | 13.96 | 18.71 | 19.98 | 26.96 | 14.5 |
| shibuya_crossing_1080p.mp4 (Pose) | YOLOX Inference | 15.74 | 29.56 | 39.06 | 53.93 | 19.31 |
| shibuya_crossing_1080p.mp4 (Pose) | YOLOX Postprocess | 2.26 | 3.42 | 3.59 | 5.47 | 2.48 |
| shibuya_crossing_1080p.mp4 (Pose) | **RTMPose / người** | **3.87** | **5.76** | **7.83** | 23.17 | 4.4 |
| **intersection_traffic_1080p.mp4 (Base)** | **Tổng Pipeline** | **44.77** | **55.44** | **56.28** | 61.75 | 47.12 |
| intersection_traffic_1080p.mp4 (Base) | Decode & RGB | 1.61 | 1.79 | 1.93 | 3.3 | 1.6 |
| intersection_traffic_1080p.mp4 (Base) | YOLOX Preprocess | 10.36 | 12.15 | 13.36 | 17.55 | 10.82 |
| intersection_traffic_1080p.mp4 (Base) | YOLOX Inference | 14.62 | 23.02 | 23.05 | 26.09 | 16.13 |
| intersection_traffic_1080p.mp4 (Base) | YOLOX Postprocess | 2.27 | 2.85 | 3.52 | 3.75 | 2.42 |
| **intersection_traffic_1080p.mp4 (Pose)** | **Tổng Pipeline** | **54.27** | **56.72** | **61.67** | 72.83 | 54.16 |
| intersection_traffic_1080p.mp4 (Pose) | Decode & RGB | 1.74 | 5.66 | 7.25 | 9.24 | 2.74 |
| intersection_traffic_1080p.mp4 (Pose) | YOLOX Preprocess | 11.82 | 16.49 | 18.63 | 24.37 | 12.86 |
| intersection_traffic_1080p.mp4 (Pose) | YOLOX Inference | 22.02 | 23.16 | 23.66 | 32.62 | 19.59 |
| intersection_traffic_1080p.mp4 (Pose) | YOLOX Postprocess | 2.59 | 2.84 | 3.52 | 4.27 | 2.59 |
| intersection_traffic_1080p.mp4 (Pose) | **RTMPose / người** | **3.93** | **4.68** | **4.99** | 11.17 | 4.23 |

---

## 3. Thống kê nhận diện đối tượng & Keypoints

### Kịch bản: `shibuya_crossing_1080p.mp4` — Baseline (YOLOX + ByteTrack)
- **Tổng detections:** 568 (trung bình 4.7/frame, cao nhất 10/frame)
- **Phân loại đối tượng ghi nhận:**
  - `person`: 301
  - `bus`: 137
  - `car`: 39
  - `truck`: 36
  - `traffic light`: 36
  - `motorcycle`: 19

### Kịch bản: `shibuya_crossing_1080p.mp4` — Full Pipeline + RTMPose
- **Tổng detections:** 568 (trung bình 4.7/frame, cao nhất 10/frame)
- **Phân loại đối tượng ghi nhận:**
  - `person`: 301
  - `bus`: 137
  - `car`: 39
  - `truck`: 36
  - `traffic light`: 36
  - `motorcycle`: 19
- **Lượt trích xuất RTMPose:** 301 lượt
- **Lượt pose được scheduler kích hoạt:** 10

### Kịch bản: `intersection_traffic_1080p.mp4` — Baseline (YOLOX + ByteTrack)
- **Tổng detections:** 1215 (trung bình 10.1/frame, cao nhất 15/frame)
- **Phân loại đối tượng ghi nhận:**
  - `car`: 671
  - `traffic light`: 390
  - `person`: 62
  - `truck`: 48
  - `bicycle`: 26
  - `bus`: 9
  - `motorcycle`: 9

### Kịch bản: `intersection_traffic_1080p.mp4` — Full Pipeline + RTMPose
- **Tổng detections:** 1215 (trung bình 10.1/frame, cao nhất 15/frame)
- **Phân loại đối tượng ghi nhận:**
  - `car`: 671
  - `traffic light`: 390
  - `person`: 62
  - `truck`: 48
  - `bicycle`: 26
  - `bus`: 9
  - `motorcycle`: 9
- **Lượt trích xuất RTMPose:** 62 lượt
- **Lượt pose được scheduler kích hoạt:** 16

---

## 4. Đánh giá & Kết luận

1. **Thông lượng tham chiếu trên CPU x86 (`Intel Core i5-12400F`):**
   - **Baseline (`YOLOX-Tiny` + `ByteTrack`):** Đạt **17.88–19.37 FPS** trên luồng 1080p (P50 toàn pipeline **51.50–54.27 ms/frame**).
   - **Full Pipeline + `RTMPose-Tiny`:** Chi phí suy luận `RTMPose-Tiny` đạt P50 **3.93–4.11 ms/người**; tổng thông lượng đạt **13.56–15.88 FPS** tùy mật độ người và phương tiện trong khung hình.
2. **Bộ nhớ RAM (RSS):**
   - Đỉnh bộ nhớ đạt **273.5–336.1 MB** cho cấu hình Baseline và **520.1–530.7 MB** khi nạp đồng thời session ONNX của `RTMPose-Tiny`, giữ ổn định nhờ ring buffer và cache có giới hạn kích thước.
3. **Giới hạn suy diễn sang phần cứng nhúng:**
   - Kết quả trên CPU x86 là mốc tham chiếu phần mềm trong lab, **không** thay thế bài đo conformance, nhiệt độ và capacity dài hạn (`G3`) trên thiết bị đích (Jetson Orin NX / TensorRT hoặc SBC ARM/RKNN).
