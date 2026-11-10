# Báo cáo Huấn luyện & Đánh giá Model Detector CiviWatch v2 (YOLO26s 640×640 trên AIC_HCMC_2020)

**Thời điểm hoàn tất:** 2026-11-10 21:50:00 (Asia/Saigon)  
**Nhánh:** `civi-watch`  
**Môi trường:** `/home/tieubaoca/ai_venv`, NVIDIA GeForce RTX 5060 Ti (16GB VRAM), PyTorch 2.11.0+cu128, Ultralytics 8.4.208, ONNX 1.23.2, onnxslim 0.1.99  
**Tập dữ liệu:** `data/mixed_traffic/` (25.977 ảnh, 299.157 boxes — 22.119 train, 3.858 val)  
**Tệp mô hình xuất:**
- `models/civiwatch-640/yolo26s_civiwatch_640.onnx` (36.4 MB, NMS-free output `[1, 300, 6]`)
- `models/civiwatch-640/manifest.json` (chuẩn CiviWatchDetector)
- `models/civiwatch-640/runs/yolo26s_hcmc/weights/best.pt` (20.3 MB)

---

## 1. Kết quả Huấn luyện 15 Epochs trên RTX 5060 Ti

Quá trình huấn luyện hoàn thành sau **51.6 phút** (~3.4 phút/epoch).

| Epoch | Train Box Loss | Train Cls Loss | Precision | Recall (All) | mAP50 (All) | mAP50-95 (All) | Val Cls Loss |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 1.612 | 1.297 | 0.758 | 0.787 | 0.829 | 0.563 | 0.989 |
| 3 | 1.528 | 0.914 | 0.790 | 0.790 | 0.853 | 0.590 | 0.822 |
| 5 | 1.468 | 0.829 | 0.793 | 0.826 | 0.866 | 0.611 | 0.775 |
| 8 | 1.388 | 0.723 | 0.863 | 0.789 | 0.880 | 0.630 | 0.701 |
| 10 | 1.346 | 0.677 | 0.807 | **0.857** | 0.889 | 0.641 | 0.656 |
| 13 | 1.295 | 0.626 | 0.839 | 0.847 | 0.899 | 0.663 | 0.626 |
| **15 (Best)** | **1.267** | **0.599** | **0.836** | **0.850** | **0.902** | **0.665** | **0.614** |

---

## 2. Đo đạc Đối chiếu Trực tiếp trên 100 ảnh Kiểm chuẩn AIC_HCMC_2020

Chạy kiểm chứng thực nghiệm bằng engine `CiviWatchDetector` nạp file ONNX xuất xưởng:

| Hạng mục đối chiếu | Baseline cũ (YOLOX-Tiny 416×416 COCO) | YOLO26s Pretrained (640×640 zero-shot) | **CiviWatch YOLO26s Fine-Tuned (640×640 NMS-free)** |
|---|:---:|:---:|:---:|
| **Thu hồi xe máy (`two_wheeler`)** | 14.2% (107 / 754) | 27.2% (205 / 754) | **95.6% (721 / 754) [Tăng +81.4%]** |
| **Thu hồi ô tô (`car`)** | 54.2% (90 / 166) | 71.1% (118 / 166) | **91.6% (152 / 166) [Tăng +37.4%]** |
| **Thu hồi xe buýt (`bus`)** | 31.2% (10 / 32) | 50.0% (16 / 32) | **93.8% (30 / 32) [Tăng +62.6%]** |
| **Thu hồi xe tải (`truck`)** | 35.7% (25 / 70) | 60.0% (42 / 70) | **97.1% (68 / 70) [Tăng +61.4%]** |
| **Độ thu hồi phương tiện tổng thể** | **22.7%** (232 / 1022) | **37.3%** (381 / 1022) | **95.0% (971 / 1022) [Tăng +72.3%]** |
| **Độ thu hồi ban đêm / thiếu sáng** | **4.8%** (3 / 62) | **16.1%** (10 / 62) | **91.9% (57 / 62) [Tăng +87.1%]** |
| **Bảo toàn nhận diện người (`person`)** | 193 detections | 312 detections | **234 detections (Chống forgetting thành công)** |
| **Độ trễ suy luận (ONNX Runtime CPU)** | ~14.8 ms (416×416) | ~75.0 ms (640×640) | **~73.7 ms (640×640 NMS-Free)** |
