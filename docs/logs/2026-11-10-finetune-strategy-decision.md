# 2026-11-10 — Quyết định Chiến lược Fine-tune Model với Dataset `AIC_HCMC_2020`

## 1. Câu hỏi
Có nên fine-tune lại các model hiện đang dùng trong CiviWatch (`YOLOX-Tiny`, `RTMPose-Tiny`, `VLMVerifier`) với bộ dataset `AIC_HCMC_2020` không?

## 2. Phân tích Kỹ thuật & Quyết định
- **`RTMPose-Tiny`:** **KHÔNG fine-tune.** Dataset `AIC_HCMC_2020` chỉ có 4 nhãn phương tiện (`two-wheels`, `four-wheels`, `bus`, `truck`), không có nhãn `person` hoặc keypoints.
- **`VLMVerifier`:** **Chưa fine-tune.** Dùng dữ liệu `AIC_HCMC_2020` (giao thông bình thường) làm bộ đánh giá âm tính (Hard-Negative Evaluation) và prompt few-shot cho lưới `2×3` Storyboard.
- **Object Detector (`YOLOX-Tiny` 416×416):** **KHÔNG nên fine-tune đơn lẻ `YOLOX-Tiny 416×416` trên `AIC_HCMC_2020`** vì 3 lý do kỹ thuật đã chứng minh qua thực nghiệm:
  1. **Catastrophic Forgetting lớp `person`:** Nếu chỉ train bằng 4 lớp xe của `AIC_HCMC_2020`, detector sẽ mất khả năng phát hiện `person` và các vật thể khác (`US09`, `US06`, `US07`, `US10`, `US11`). Phải trộn (mix) dữ liệu đa lớp (COCO/VisDrone/CrowdHuman) hoặc ánh xạ 4 lớp `AIC_HCMC_2020` sang tập nhãn chuẩn kết hợp giữ lại nhãn `person` + vật thể (tổng tối thiểu 6–8 lớp).
  2. **Giới hạn vật lý của input `416×416`:** Trên camera CCTV 720p/1080p, xe máy từ xa chỉ còn ~6×10 px khi thu nhỏ về `416×416`. Nếu bỏ công fine-tune, nên chuyển sang kiến trúc đời mới hơn ở input `640×640` (như `YOLO26s` NMS-free hoặc `RF-DETR-Nano/Small`) thay vì đầu tư vào `YOLOX-Tiny 416×416` (kiến trúc 2021).
  3. **Hiệu ứng bão cảnh báo giả nếu chưa tinh chỉnh Engine:** Trong thí nghiệm trên `sample_02.mp4`, mới phát hiện được một phần xe mà `VehicleIncidentEngine` đã nổ 19 tai nạn giả trong 12 giây. Cần tinh chỉnh `VehicleIncidentEngine` dùng `GroundPlaneHomography` và bật lọc `VLMVerifier` trước/song song khi tăng Recall xe máy.

## 3. Lộ trình Đề xuất (3 Bước)
1. **Bước 1 (Làm ngay trước khi train):** Dùng `sample_01.mp4` / `sample_02.mp4` và 25 chuỗi camera `AIC_HCMC_2020` để hiệu chỉnh `VehicleIncidentEngine` (lọc chồng lấn 2D bbox ở giao lộ đông xe máy bằng vận tốc thực qua `GroundPlaneHomography` và hậu kiểm `VLMVerifier`).
2. **Bước 2 (Chuẩn bị tập dữ liệu trộn & nâng cấp kiến trúc Detector):** Trộn ~26K ảnh `AIC_HCMC_2020` (gắn nhãn `motorcycle`, `car`, `bus`, `truck`) với tập con COCO/VisDrone chứa `person`, `bicycle`, `backpack`/`suitcase`, `fire`/`smoke` để giữ nguyên 14 kịch bản `US01–US14`, sau đó fine-tune **YOLO26s / RT-DETR (640×640)** trên RTX 5060 Ti (16GB) của workstation.
3. **Bước 3 (Giữ nguyên Contract & Conformance):** Xuất model mới ra ONNX/TensorRT kèm `manifest.json` mới và chạy conformance/regression theo [ADR-0001](../adr/0001-feature-pipeline-boundaries.md), giữ `YOLOX-Tiny` làm oracle baseline để đối chiếu.
