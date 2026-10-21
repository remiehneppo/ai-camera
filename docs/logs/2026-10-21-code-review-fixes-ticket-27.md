# Nhật ký Sửa lỗi sau Code Review Ticket #27 — 2026-10-21

## 1. Bối cảnh
Sau khi hoàn thành đợt triển khai ban đầu của Ticket #27 (`eb4a951`), quy trình Code Review hai trục (**Standards** và **Spec**) đã được thực hiện bởi hai sub-agent độc lập và đưa ra các phát hiện cần chấn chỉnh.

## 2. Các vấn đề được phát hiện & Biện pháp khắc phục

### A. Trục Spec (Nghiệp vụ & Quy tắc An toàn)
1. **Phát hiện xe đang chạy rồi dừng đột ngột (Sudden Stop Danger Override):**
   - *Vấn đề:* Spec yêu cầu *"Dấu hiệu xe đang chạy rồi dừng đột ngột ... hoặc chuyển động đột ngột → ưu tiên bình thường"*.
   - *Khắc phục:* `_VehicleState` được bổ sung `last_high_speed_time`. Khi xe vừa chạy tốc độ cao và dừng gấp trong vòng 2.0s trước khi người nằm, hệ thống kích hoạt **danger override** (`danger = True`), ngăn chặn việc hạ xuống ưu tiên thấp và giữ nguyên phân loại nguy hiểm `person_lying_persistent` (`severity="high"`). Đã bổ sung unit test `test_sudden_stopping_vehicle_triggers_danger_override` để chứng minh.
2. **Khắc phục lỗi tiềm ẩn đối với xe 4 bánh (Car):**
   - *Vấn đề:* Spec `system-architecture.md:321` chỉ định nghĩa tư thế người nằm trên yên xe 2 bánh (`motorcycle`/`bicycle`). Việc đưa `"car"` vào `_VEHICLE_LABELS` khiến ô tô lật có thể bị demote nhầm thành on-vehicle.
   - *Khắc phục:* Thu hẹp `_VEHICLE_LABELS = {"motorcycle", "bicycle"}` đúng theo phạm vi xe hai bánh.
3. **Bổ sung độ bất định liên kết (`association_uncertainty`):**
   - *Vấn đề:* Tiêu chí AC1 yêu cầu *"Association có uncertainty/history, không suppress vì bbox overlap"*.
   - *Khắc phục:* `IncidentEngine` tính toán và đính kèm `association_uncertainty = {"method": "2d_bbox_overlap", "overlap_iou": round(float(iou), 3)}` vào incident và truyền tải đầy đủ vào payload của event snapshot.

### B. Trục Standards (Kiến trúc & Code Smells)
1. **Khắc phục vi phạm phân tầng kiến trúc (Architecture Layering):**
   - *Vấn đề:* Hàm chính sách nghiệp vụ `review_priority_for`, cùng danh hằng `LOW_PRIORITY_TAXONOMIES` và `SEVERITY_VALUES` bị đặt tại tầng persistence `apps/server/store.py`.
   - *Khắc phục:* Chuyển toàn bộ các định nghĩa chính sách review này về `domain/review_contract.py` (tầng Domain thuần túy không I/O). Tầng server (`store.py`, `main.py`, `dataset.py`) chỉ import từ `domain.review_contract`.
2. **Đồng bộ hợp đồng tài liệu (`docs/architecture/contracts.md`):**
   - Bổ sung định nghĩa các trường tùy chọn `vehicle_track_id` và `association_uncertainty` vào đặc tả payload tại mục §2 của `contracts.md`.
3. **Loại bỏ Code Smells:**
   - Đổi tên biến nhập nhằng: `lie_start_time` → `lying_onset_time`.
   - Trích xuất hàm tái sử dụng `_reset_vehicle_association(state)` để xóa bỏ trùng lặp mã tại 3 vị trí reset trạng thái người ngả xe.
   - Làm sạch giao diện Web Dashboard (`index.html`): Chỉ hiển thị badge `On-vehicle (Low priority)` và `Emergency priority` khi cần thiết, không hiển thị tràn lan badge "Standard" gây rối mắt.

## 3. Kiểm chứng
- Toàn bộ 472 unit & integration test cases đều đạt xanh 100%:
  ```text
  472 passed, 204 warnings, 118 subtests passed in 115.83s
  ```
- Không có lỗi type checking mới từ `mypy`.
- Kiểm tra `git diff --check`: Không có lỗi định dạng hay khoảng trắng thừa.
