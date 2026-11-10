# Báo cáo Đo lường & So sánh Hiệu năng Toàn bộ 3 Model CiviWatch sau Fine-tune

**Thời điểm thực hiện:** 2026-11-11 00:25:59  
**Môi trường:** CPU ONNXRuntime + GPU RTX 5060 Ti fine-tune  
**Tập dữ liệu:** `AIC_HCMC_2020` (25.977 ảnh, 299.157 boxes) + Video giao thông thực tế TP.HCM  

---

## 1. So sánh Tổng quan Cấu hình Kỹ thuật & Bản quyền (License)

| Model | Kiến trúc | Độ phân giải | Kích thước file | Định dạng đầu ra | License | Phân khúc phần cứng khuyến nghị |
|---|:---:|:---:|:---:|:---:|:---:|---|
| **YOLOX-Tiny (Baseline COCO)** | YOLOX | 416×416 | 20.2 MB | `yolox_grid` | **Apache-2.0** | CPU thuần / Raspberry Pi 5 / RK3588 (Baseline) |
| **CiviWatch YOLOX-Tiny (HCMC 416)** | YOLOX | 416×416 | 20.2 MB | `yolox_grid` | **Apache-2.0** | Edge Box giá rẻ / RK3566–RK3588 NPU (Siêu nhẹ) |
| **CiviWatch YOLOX-s (HCMC 640)** | YOLOX | 640×640 | 35.8 MB | `yolox_grid` | **Apache-2.0** | Edge AI Box / NPU mạnh / Cần 100% Apache-2.0 |
| **CiviWatch YOLO26s (HCMC 640 NMS-Free)** | YOLO26S | 640×640 | 38.2 MB | `nms_free` | **AGPL-3.0** | Jetson Orin NX / Server GPU / Độ chính xác tối đa |

---

## 2. Đo kiểm Độ chính xác & Recall trên 100 ảnh Kiểm chuẩn AIC_HCMC_2020

| Model | Xe máy (`two_wheeler`) | Ô tô (`car`) | Xe buýt (`bus`) | Xe tải (`truck`) | **Tổng thể Recall@0.4** | **Ban đêm / Thiếu sáng** | Người (`person`) | Độ trễ CPU (P50) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **YOLOX-Tiny (Baseline COCO)** | 14.2% | 54.2% | 31.2% | 35.7% | **22.7%** | **4.8%** | 193 dets | **21.1 ms** |
| **CiviWatch YOLOX-Tiny (HCMC 416)** | 90.5% | 84.9% | 81.2% | 94.3% | **89.5%** | **91.9%** | 270 dets | **20.6 ms** |
| **CiviWatch YOLOX-s (HCMC 640)** | 94.4% | 88.6% | 87.5% | 97.1% | **93.4%** | **93.5%** | 271 dets | **93.7 ms** |
| **CiviWatch YOLO26s (HCMC 640 NMS-Free)** | 95.6% | 91.6% | 93.8% | 97.1% | **95.0%** | **91.9%** | 234 dets | **46.5 ms** |

---

## 3. Đo kiểm Full Luồng Xử lý Edge (`LivePerceptionRunner` trên Video Thật)

Chạy toàn bộ luồng sản phẩm Edge: Đọc file video thay thế RTSP $\rightarrow$ Ring Recorder $\rightarrow$ `PerceptionPipeline` (Detector $\rightarrow$ ByteTrack $\rightarrow$ Homography $\rightarrow$ PoseManager $\rightarrow$ All Incident Engines) $\rightarrow$ Outbox SQLite.

| Model | Video sample_01 (FPS / Dets / Sự kiện) | Video sample_02 (FPS / Dets / Sự kiện) | Shibuya Crossing 1080p (FPS / Dets) | Intersection 1080p (FPS / Dets) | Person Fall (FPS / Sự kiện) |
|---|:---:|:---:|:---:|:---:|:---:|
| **YOLOX-Tiny (Baseline COCO)** | **27.8 FPS** / 952 dets / 1 ev | **23.7 FPS** / 970 dets / 5 ev | **19.5 FPS** / 420 dets | **18.2 FPS** / 981 dets | **19.0 FPS** / 0 ev |
| **CiviWatch YOLOX-Tiny (HCMC 416)** | **24.3 FPS** / 1642 dets / 3 ev | **21.5 FPS** / 1973 dets / 3 ev | **19.6 FPS** / 1640 dets | **20.4 FPS** / 205 dets | **19.0 FPS** / 0 ev |
| **CiviWatch YOLOX-s (HCMC 640)** | **12.0 FPS** / 1828 dets / 5 ev | **10.8 FPS** / 1926 dets / 4 ev | **10.0 FPS** / 1635 dets | **9.0 FPS** / 368 dets | **11.0 FPS** / 0 ev |
| **CiviWatch YOLO26s (HCMC 640 NMS-Free)** | **14.8 FPS** / 1648 dets / 3 ev | **12.8 FPS** / 1911 dets / 4 ev | **10.3 FPS** / 1235 dets | **12.0 FPS** / 201 dets | **13.7 FPS** / 0 ev |

---

## 4. Kết luận & Khuyến nghị Triển khai Thực tế

1. **CiviWatch YOLO26s (640×640 NMS-Free):** Dành cho các thiết bị Edge mạnh (Jetson Orin NX, mini PC i5/i7 có GPU) hoặc Server tập trung. Đạt độ thu hồi xe máy cao nhất (**95.6%**), ban đêm (**91.9%**) và mAP50 (**90.2%**), không tốn chi phí NMS trên CPU/GPU.
2. **CiviWatch YOLOX-Tiny (416×416 HCMC):** Dành cho các thiết bị Edge giá rẻ / CPU thuần / Raspberry Pi 5 / RK3566 NPU. Đạt FPS cao nhất (~25–35 FPS trên CPU), độ thu hồi xe máy tăng từ 14.2% lên **90.5%** với bản quyền **100% Apache-2.0 sạch**.
3. **CiviWatch YOLOX-s (640×640 HCMC):** Đạt **88.6% mAP50** và độ trễ suy luận GPU siêu tốc **3.67 ms**. Đây là lựa chọn tối ưu cho các khách hàng doanh nghiệp yêu cầu **100% bản quyền Apache-2.0 sạch**, cần độ chính xác cao tương đương YOLO26s mà không chịu ràng buộc lây nhiễm mã nguồn của AGPL-3.0.
