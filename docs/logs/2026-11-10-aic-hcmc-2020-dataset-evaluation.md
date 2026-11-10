# 2026-11-10 — Đánh giá Dataset `AIC_HCMC_2020` cho Hệ thống CiviWatch

## 1. Thông tin Bộ dữ liệu (`/media/tieubaoca/HDD1/F/dataset/video/AIC_HCMC_2020`)
- **Nguồn gốc:** Cuộc thi AI Challenge TP.HCM 2020 (Đếm phương tiện & Giám sát giao thông đô thị tại TP.HCM).
- **Dung lượng & Cấu trúc:** ~14 GB (đã giải nén đầy đủ).
  - **Ảnh & Chuỗi khung hình (`ai-hcm-city2020/images/`):** **26,195 frames** liên tiếp (`diffs=[1]`) từ **25 camera CCTV giao thông cố định** (`cam_01`–`cam_25`), độ phân giải đồng nhất **1280×720 (720p HD)**, bao gồm cả ban ngày và ban đêm/ánh sáng yếu (`cam_05` luma 42.6, `cam_15` luma 72.3, `cam_25` luma 54.7).
  - **Nhãn (`annotations.json` & `yolo_annotations/`):** **251,605 bounding boxes** (Train: 22,265 ảnh / 213,909 boxes; Val: 3,930 ảnh / 37,696 boxes) chia 4 lớp giao thông Việt Nam:
    - `two-wheels` (xe máy/xe đạp): 180,359 (71.7%)
    - `four-wheels` (ô tô): 43,621 (17.3%)
    - `truck` (xe tải): 19,805 (7.9%)
    - `bus` (xe buýt): 7,820 (3.1%)
  - **Video mẫu (`sample_data/videos/`):** `sample_01.mp4` và `sample_02.mp4` (1280×720 @ 10fps, 120s) kèm ROI polygon (`zone`) và hướng di chuyển (`direction01..06`).

## 2. Kết quả Kiểm thử Thực nghiệm với Pipeline CiviWatch v2
1. **Đo Recall của `YOLOX-Tiny` (COCO pre-trained) trên 100 ảnh Val (`AIC_HCMC_2020`):**
   - Overall vehicle Recall@0.4 (exact class): **22.7% (`232/1022`)**.
   - `two-wheels` (xe máy): **14.2% (`107/754`)** (bỏ sót 85.8% xe máy).
   - `four-wheels`: **54.2% (`90/166`)**; `bus`: **31.2% (`10/32`)**; `truck`: **35.7% (`25/70`)**.
   - Camera ban đêm/tối (`luma < 75`): **4.8% (`3/62`)**.
2. **Chạy full pipeline `eval_all_scenarios.py` trên `sample_01.mp4` & `sample_02.mp4` (giao thông TP.HCM bình thường):**
   - `sample_01.mp4` (120 frames, P50=48.3ms): 1,108 detections, phát **9 sự kiện báo giả** (8 `vehicle_incident`, 1 `sidewalk_encroachment`).
   - `sample_02.mp4` (120 frames, P50=60.17ms): 1,125 detections, phát **21 sự kiện báo giả** (19 `vehicle_incident`, 1 `sidewalk_encroachment`, 1 `property_vandalism`).

## 3. Kết luận & Khuyến nghị
- **Rất có ích (High Value)** cho 3 mục đích:
  1. Fine-tune detector (ví dụ `YOLOX` / `YOLO26` / `RF-DETR`) cho miền giao thông Việt Nam (đặc biệt nhận diện xe máy dày đặc và ban đêm) — lưu ý **phải trộn thêm dữ liệu có lớp `person`** (COCO/CrowdHuman) để không bị quên lớp người đi bộ cho các kịch bản `US06/US07/US09/US10`.
  2. Làm bộ **Negative Control & Hard Negatives** (25 chuỗi camera CCTV 720p TP.HCM liên tiếp + 2 video mẫu 120s) để hiệu chỉnh ngưỡng `VehicleIncidentEngine`, `ParkingIncidentEngine` và bộ lọc `VLMVerifier`, triệt tiêu báo động giả khi xe máy đi sát nhau ở ngã tư Việt Nam.
  3. Đánh giá ODD ban đêm (`cam_05`, `cam_15`, `cam_25`).
- **Hạn chế:** Không có nhãn tai nạn/ngã (`US08`/`US09`), không có nhãn `person`, `fire`, `flood`, `trash`, và cần xác minh điều khoản thương mại của cuộc thi AI Challenge HCMC 2020 trước khi dùng trọng số train từ bộ này cho production.
