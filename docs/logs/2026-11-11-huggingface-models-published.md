# 2026-11-11 — Công bố Bộ 3 Model CiviWatch Giao Thông Việt Nam lên Hugging Face Hub

## 1. Thông tin Repository trên Hugging Face
- **Repo ID:** [`tieubaoca/CiviWatch-Traffic-Models`](https://huggingface.co/tieubaoca/CiviWatch-Traffic-Models)
- **Repo Type:** `model`
- **Commit SHA:** `5078231822e8383ecca01749d82cb00fd60f3cf3`
- **Mã nguồn tương ứng:** GitHub `remiehneppo/ai-camera` (branch `civi-watch`)

## 2. Cấu trúc Tệp & Artifacts đã Đẩy Lên
```text
tieubaoca/CiviWatch-Traffic-Models/
├── README.md                                # Model Card, hướng dẫn cài đặt, license, bảng benchmark
├── reports/
│   ├── three-models-benchmark-comparison.md # Báo cáo chi tiết đối chuẩn 4 model
│   └── yolo26s-hcmc-training-results.md     # Báo cáo huấn luyện 15 epochs YOLO26s
├── yolox-tiny-416/                          # [Apache-2.0] Model siêu nhẹ cho CPU / Edge Box giá rẻ
│   ├── yolox_tiny_civiwatch_416.onnx        # ONNX export (20.2 MB)
│   ├── yolox_tiny_civiwatch_416.pth         # PyTorch weights (39 MB)
│   ├── manifest.json                        # Cấu hình CiviWatchDetector (yolox_grid)
│   └── civiwatch_yolox_tiny_416_exp.py      # Megvii YOLOX Experiment script
├── yolox-s-640/                             # [Apache-2.0] Model thương mại sạch 100% cho GPU/NPU
│   ├── yolox_s_civiwatch_640.onnx           # ONNX export (35.8 MB)
│   ├── yolox_s_civiwatch_640.pth            # PyTorch weights (69 MB)
│   ├── manifest.json                        # Cấu hình CiviWatchDetector (yolox_grid)
│   └── civiwatch_yolox_s_640_exp.py         # Megvii YOLOX Experiment script
└── yolo26s-640/                             # [AGPL-3.0] Model độ chính xác tối đa, NMS-free
    ├── yolo26s_civiwatch_640.onnx           # ONNX export [1, 300, 6] (38.2 MB)
    ├── yolo26s_civiwatch_640.pt             # Ultralytics weights (20.3 MB)
    ├── manifest.json                        # Cấu hình CiviWatchDetector (nms_free)
    ├── results.csv                          # Nhật ký loss & metrics 15 epochs
    ├── results.png                          # Biểu đồ training loss & mAP
    ├── BoxPR_curve.png                      # Đường cong Precision-Recall
    └── confusion_matrix_normalized.png      # Ma trận nhầm lẫn chuẩn hóa 6 lớp
```

## 3. Lệnh Tải Về & Khởi Chạy Nhanh
```bash
# Tải toàn bộ repository về thư mục models/hf-civiwatch:
huggingface-cli download tieubaoca/CiviWatch-Traffic-Models --local-dir models/hf-civiwatch

# Chạy live edge pipeline với YOLOX-Tiny HCMC (Apache-2.0):
.venv-oracle/bin/python run_edge.py --module-config fixtures/sample_module_config.json \
    --source file --file sample.mp4 \
    --manifest models/hf-civiwatch/yolox-tiny-416/manifest.json \
    --model models/hf-civiwatch/yolox-tiny-416/yolox_tiny_civiwatch_416.onnx
```
