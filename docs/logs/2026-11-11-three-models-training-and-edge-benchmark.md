# 2026-11-11 — Hoàn tất Huấn luyện 3 Model & Đo kiểm Full Luồng Edge (Dataset Video)

## 1. Tổng hợp 3 Mô hình đã Huấn luyện & Xuất ONNX thành công
Tất cả 3 mô hình đều được huấn luyện trên tập trộn **25.977 ảnh / 299.157 hộp nhãn** (`data/mixed_traffic/` & `data/mixed_traffic_coco/`) trên card **NVIDIA GeForce RTX 5060 Ti** qua môi trường `/home/tieubaoca/ai_venv`:

1. **`CiviWatch YOLOX-Tiny (416×416 HCMC)`** — License `Apache-2.0`:
   - File ONNX: `models/yolox-tiny-hcmc/yolox_tiny_civiwatch_416.onnx` (`20.2 MB`) + `models/yolox-tiny-hcmc/manifest.json`
   - Validation COCO trên 3.858 ảnh: **`AP50 = 82.1%`**, `AP50:95 = 54.8%`
   - Độ trễ CPU P50: **`20.6 ms`** | Recall@0.4 tổng thể: **`89.5%`** (xe máy `90.5%`, ban đêm `91.9%`)
2. **`CiviWatch YOLOX-s (640×640 HCMC)`** — License `Apache-2.0`:
   - File ONNX: `models/yolox-s-hcmc/yolox_s_civiwatch_640.onnx` (`35.8 MB`) + `models/yolox-s-hcmc/manifest.json`
   - Validation COCO trên 3.858 ảnh: **`AP50 = 88.6%`**, `AP50:95 = 63.6%`, `AR = 73.0%`, GPU inference `3.67 ms`
   - Độ trễ CPU P50: **`93.7 ms`** | Recall@0.4 tổng thể: **`93.4%`** (xe máy `94.4%`, ban đêm **`93.5%`**)
3. **`CiviWatch YOLO26s (640×640 HCMC NMS-Free)`** — License `AGPL-3.0`:
   - File ONNX: `models/civiwatch-640/yolo26s_civiwatch_640.onnx` (`38.2 MB`) + `models/civiwatch-640/manifest.json`
   - Validation trên 3.858 ảnh: **`mAP50 = 90.2%`**, `mAP50-95 = 66.5%`
   - Độ trễ CPU P50: **`46.5 ms`** (nhanh gấp đôi YOLOX-s nhờ NMS-Free) | Recall@0.4 tổng thể: **`95.0%`** (xe máy **`95.6%`**, ban đêm `91.9%`)

## 2. Xác minh Full Luồng Xử lý Edge (`LivePerceptionRunner` không dùng RTSP)
- Chạy qua file video thật (`sample_01.mp4`, `sample_02.mp4`, `shibuya_crossing_1080p.mp4`, `intersection_traffic_1080p.mp4`, `fall_0001.mp4`) bằng `LivePerceptionRunner(rtsp_url="", fallback_path=...)` -> `RtspRingRecorder` -> `PerceptionPipeline` (`CiviWatchDetector` + `ByteTracker` + `GroundPlaneHomography` + `PoseManager` + `VehicleIncidentEngine` + `UrbanSafetyScenarioEngine`) -> `EventOutbox` SQLite.
- Xác minh cơ chế phát hiện lỗi ẩn trong benchmark trước đó: `frame["event_time"]` phải khớp chính xác phân số `pts * Fraction(time_base)` (đã sửa trong `tools/compare_models_benchmark.py`).
- Xác minh tự động gắn `GroundPlaneHomography.default_urban_cctv` trong `apps/edge/pipeline.py` và `tools/eval_all_scenarios.py`.
- Xác minh phát hiện quan trọng về **Domain Specialization**: Vì 99.1% ảnh huấn luyện đến từ góc camera giao thông trên cao (`AIC_HCMC_2020`), cả 3 model fine-tune đạt độ chính xác đột phá trên giao thông Việt Nam (89.5%–95.0% Recall) nhưng giảm độ nhạy với người trong nhà cận cảnh (`fall_0001.mp4`); do đó khuyến nghị dùng model chuyên biệt theo từng cấu hình camera (`Indoor Fall` giữ model gốc / trộn indoor dataset, `Traffic/Urban CCTV` dùng 3 model CiviWatch HCMC).

## 3. Lưu ý Môi trường Test
- Thêm `pytest.ini` (`testpaths = tests`, `norecursedirs = data .venv-oracle`) để `pytest` không quét nhầm bộ test của `data/YOLOX/tests/` vốn cần `torch`.
- Chi tiết bảng đối chiếu đầy đủ xem tại: `docs/reports/2026-11-10-three-models-benchmark-comparison.md`.
