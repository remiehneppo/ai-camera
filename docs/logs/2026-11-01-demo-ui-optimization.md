# Tối ưu giao diện Web Dashboard Demo — 2026-11-01

## 1. Mục đích
Nâng cấp và chuẩn hóa giao diện web demo (`apps/server/static/index.html`) nhằm phản ánh đầy đủ, trực quan toàn bộ năng lực hệ thống và 5 kịch bản cảnh báo an toàn đô thị đã triển khai, đồng thời tuân thủ tiêu chuẩn bảo mật (chống XSS) và giao diện OneChainUI.

## 2. Chi tiết các hạng mục tối ưu

### 2.1. Quản lý trạng thái hệ thống & Token xác thực
- **System Health & Storm Guard**: Tích hợp tự động thăm dò `/healthz` và `/v1/ingest/guard` mỗi 5 giây, hiển thị trạng thái server (`OK`/`Degraded`) và ngân sách bảo vệ chống tràn request (`Guard: X left (Y used)`).
- **Persistent Auth Toolbar**: Cho phép nhập `Dashboard Token` và `Reviewer Token`, tự động lưu vào `sessionStorage` / `localStorage` và hỗ trợ nạp trực tiếp qua query params (`?token=...&reviewer_token=...`). Loại bỏ hoàn toàn việc gọi `window.prompt` liên tục gây phiền toái cho người vận hành.

### 2.2. Trình phát luồng trực tiếp (Live Camera Stream)
- Giữ nguyên tích hợp MJPEG stream `/v1/live/stream` và polling `/v1/live/status`.
- Hiển thị đầy đủ các chỉ số: Nguồn luồng (`RTSP` / `Fallback`), `FPS` thực tế, và số lượng `Detections` tức thời.
- Nút bấm Start / Pause Stream với khung xem tối ưu kích thước.

### 2.3. Thanh công cụ lọc & Điều hướng hàng đợi (Queue Filters)
- Tích hợp các tham số truy vấn của `/v1/events`:
  - **Mức độ (Severity)**: Tất cả, Critical, High, Medium, Low.
  - **Kịch bản (Taxonomy)**: Tất cả, Person Fall, Persistent Lying, On-vehicle, Vehicle Incident, Illegal Parking, Crowd, Disorder, Danger Zone.
  - **Giới hạn (Limit)**: 25, 50, 100 sự kiện.
  - **Tự động làm mới (Auto-refresh)**: Chu kỳ 3 giây, tự động tạm dừng khi người dùng đang phát video bằng chứng.

### 2.4. Bảng thông số đặc thù theo từng kịch bản (Scenario Domain Facts)
Mỗi thẻ sự kiện hiển thị khối thông số kỹ thuật (Facts Grid) tương ứng:
- **Person-down (US09)**: Onset time, anchor time, trạng thái tư thế RTMPose (SimCC keypoints count/status), phương tiện gắn kết.
- **Vehicle Incident (US08)**: Kiểu tương tác (`vehicle_vehicle`, `vehicle_pedestrian`, `rollover_or_barrier`), danh sách track tham gia, TTC (Time-to-collision), Closing speed, IoU rate.
- **Illegal Parking (US05)**: Track xe, loại xe, thời gian đứng yên (`dwell_seconds` vs ngưỡng), mã vùng cấm (`roi_id`), khung giờ (`schedule_id`).
- **Crowd & Disorder (US06)**: Số lượng người tụ tập, thời gian duy trì, tốc độ phân tán (`dispersal_rate`), đột biến gia tốc (`acceleration_spike`).
- **Danger Zone Intrusion (US10)**: Track người, thời gian trong vùng, mã vùng nguy hiểm, trạng thái lịch hiệu lực.

### 2.5. Quy trình Review & Truy hồi bằng chứng (Evidence Retrieval)
- Hiển thị huy hiệu trạng thái review (`UNREVIEWED`, `CONFIRMED`, `FALSE_POSITIVE`, `RESOLVED`, `NEEDS_RE_REVIEW`).
- Hộp thoại nhập lý do review chuẩn bằng thẻ `<dialog>` thay thế popup native.
- Lịch sử audit trail chi tiết (phiên bản, người duyệt, hành động, thời gian, lý do).
- Trình phát video bằng chứng kèm thẻ trạng thái (`complete`, `partial`, `available`, `pending`), mốc thời gian thực tế, link tải về file MKV/MP4 có dung lượng KB/MB.
- Nút bấm **"Truy hồi từ Edge" (Request Retrieval)** tích hợp endpoint `/v1/evidence/{device}/{event}/{req}/retrieval` cho các clip đang pending hoặc lưu trữ trên biên.

### 2.6. Bảo mật & Tiêu chuẩn hiển thị (OneChainUI & Secure Coding)
- **Chống XSS sink tuyệt đối**: Tuân thủ `oc-secure-coding` và `oc-guard-raw-html`, 100% phần tử DOM được khởi tạo qua `document.createElement`, gán nội dung qua `textContent` và `setAttribute`, không sử dụng bất kỳ `innerHTML` hay `outerHTML` nào.
- **Chủ đề màu (Theme Tokens)**: Tự động tương thích Light / Dark theme theo `prefers-color-scheme` qua CSS Variables.
- **Bảo toàn hợp đồng kiểm thử**: Đảm bảo toàn bộ chuỗi kiểm thử contract (`evidence-section`, `Download clip`, `Pending upload`) giữ nguyên vẹn.

## 3. Bằng chứng kiểm thử & Xác nhận
1. **Kiểm thử giao diện thực tế (Visual Inspection)**: Dùng headless Firefox dựng trang, render thành công ảnh chụp màn hình kiểm tra trực quan (`demo-events-screenshot.png`) trên tập 5 kịch bản domain.
2. **Kiểm thử chức năng**:
   - `tests/test_server_evidence.py`: 14 passed.
   - Toàn bộ suite server/evidence/review/live (`test_review_api.py`, `test_live_stream.py`, `test_retrieval_api.py`, `test_storm_api.py`, `test_server_evidence.py`): 176 passed, 0 failures.
3. **Kiểm tra kiểu tĩnh (Static Type Check)**: `mypy domain/ apps/ tools/` sạch 100% trên toàn bộ 72 source files.
