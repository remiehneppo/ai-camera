# Công cụ Đánh giá Tai nạn Xe thực tế: eval_vehicle & Bounded Memory Fix — 2026-10-27

Ghi chép hành động và quyết định cho công cụ `tools/eval_vehicle.py` và các sửa đổi sau review:

## 1. Công cụ `tools/eval_vehicle.py`
- Đọc video, decode qua OpenCV, chạy bộ phát hiện `OracleDetector (YOLOX-Tiny)`, cập nhật `ByteTracker`, và đánh giá sự cố qua `VehicleIncidentEngine`.
- Chuẩn hóa bbox (`bbox_xyxy` -> `bbox`) bảo đảm tương thích với tracker.
- Bọc tài nguyên video trong `try...finally: cap.release()` tránh rò rỉ file descriptor.

## 2. Bounded Memory trong `VehicleIncidentEngine`
- `apps/edge/vehicle_incident.py`: Bổ sung cơ chế dọn dẹp `self._pairs` khi bất kỳ track nào trong cặp rời khỏi khung hình hoặc bị gỡ bỏ, bảo đảm không bị rò rỉ bộ nhớ dài hạn trên luồng chạy 24/7.
- Kiểm tra trạng thái đứng thẳng ban đầu của người đi bộ (`initial_is_upright` cho `PEDESTRIAN_LABELS`), loại bỏ triệt để cảnh báo sai khi xe chạy ngang qua người đã nằm từ trước mà không có diễn biến va chạm/giảm tốc đột ngột.
