# 2026-11-10 — Kích hoạt Huấn luyện YOLO26s (640×640) trên Toàn bộ Dataset Giao thông TP.HCM

## 1. Môi trường & Hạ tầng GPU
- **Virtualenv:** `/home/tieubaoca/ai_venv` (Python 3.10.20, PyTorch `2.11.0+cu128`, Ultralytics `8.4.208`, ONNX `1.23.2`, onnxslim `0.1.99`).
- **GPU:** NVIDIA GeForce RTX 5060 Ti (16GB VRAM, CUDA 12.8/13.2).
- **Cập nhật kỹ thuật trước train:**
  - Sửa `apps/edge/oracle_detector.py`: hỗ trợ tiền xử lý theo `manifest["preprocess"]["color"]` (`RGB` cho Ultralytics YOLO26 vs `BGR` cho YOLOX) và `scale` (`1/255.0` vs `1.0`).
  - Sửa `tools/train_civiwatch_detector.py`: cấu hình đúng tên tensor xuất của Ultralytics (`output0`, shape `[1, 300, 6]` NMS-free), chuẩn RGB + scale `1/255.0`, sử dụng `workers=4, cache=False, device=0`.
  - Sửa `tools/prepare_mixed_traffic_dataset.py`: bổ sung `--pseudo-label-model` dùng `data/yolo26s.pt` chạy GPU gắn nhãn tự động lớp `person` (`0`) và `obstacle_object` (`5`) trực tiếp trên ảnh `AIC_HCMC_2020`.

## 2. Kết quả Chuẩn bị Dataset (`data/mixed_traffic/`)
- **Tổng ảnh huấn luyện (`train`):** `22,119` ảnh (`21,919` ảnh TP.HCM + `200` ảnh cân bằng người đi bộ).
  - Ground-truth từ `AIC_HCMC_2020`: `153,198` `two_wheeler`, `37,265` `car`, `6,604` `bus`, `16,764` `truck`.
  - Pseudo-labels từ `yolo26s.pt`: `39,767` `person`, `793` `obstacle_object`.
- **Tổng ảnh kiểm chuẩn (`val`):** `3,858` ảnh.
  - Ground-truth từ `AIC_HCMC_2020`: `27,086` `two_wheeler`, `6,346` `car`, `1,214` `bus`, `3,037` `truck`.
  - Pseudo-labels từ `yolo26s.pt`: `6,952` `person`, `131` `obstacle_object`.

## 3. Trạng thái Quá trình Huấn luyện
- **Job ID:** `bash-c32fe61c6a5741f4` (đang chạy nền).
- **Lệnh thực thi:** `/home/tieubaoca/ai_venv/bin/python tools/train_civiwatch_detector.py --model yolo26s --imgsz 640 --epochs 15 --batch 16`
- **Tốc độ quan sát thực tế ở Epoch 1:** ~8.3 it/s (~132 ảnh/giây), chiếm `4.91 GB` VRAM. Dự kiến hoàn tất 15 epochs và tự động xuất file `models/civiwatch-640/yolo26s_civiwatch_640.onnx` + `models/civiwatch-640/manifest.json` sau ~35–40 phút.
- **Mức Recall baseline trước khi train (đo trên 100 ảnh val `AIC_HCMC_2020`):**
  - `YOLOX-Tiny (416×416)`: 22.7% overall (`14.2%` xe máy, `4.8%` ban đêm).
  - `YOLO26s pretrained (640×640)`: 37.3% overall (`27.2%` xe máy, `16.1%` ban đêm).
