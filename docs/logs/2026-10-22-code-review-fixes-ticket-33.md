# Nhật ký Sửa lỗi sau Code Review Ticket #33 — 2026-10-22

## 1. Bối cảnh
Sau đợt triển khai ban đầu của Ticket #33 (`8008e71`), phiên Code Review hai trục (**Standards** và **Spec**) đã rà soát toàn bộ diff và đưa ra các phát hiện cần chấn chỉnh.

## 2. Các vấn đề được phát hiện & Biện pháp khắc phục

### A. Trục Standards (Kiến trúc & Chuẩn lưu trữ)
1. **Thiếu Unique Index cho Collection `devices` trong MongoDB:**
   - *Vấn đề:* Quy chuẩn kiến trúc yêu cầu mọi collection trong `EventStore` phải đăng ký index trong `ensure_ready()`.
   - *Khắc phục:* Trong `apps/server/store.py`, bổ sung `self.devices.create_index([("device_id", 1)], unique=True, name="device_identity")` vào `ensure_ready()`.
2. **Đồng bộ Cấu hình Phân quyền Site vào `config_hash`:**
   - *Vấn đề:* `device_sites` và `reviewer_sites` chưa nằm trong từ điển tính `config_hash`.
   - *Khắc phục:* Bổ sung `device_sites` và `reviewer_sites` vào `public_config` trong `apps/server/config.py` để đảm bảo mọi thay đổi phân quyền site đều phản ánh vào chữ ký máy chủ.

### B. Trục Spec (Bảo mật & Phân quyền Truy cập)
1. **Chặn Rò rỉ Video Bằng chứng Cross-site (`GET /v1/evidence/.../media` và manifest):**
   - *Vấn đề:* Reviewer thuộc Site B có thể tải tệp video nhị phân (`/media`) hoặc manifest của Site A nếu biết định danh sự kiện.
   - *Khắc phục:* Bổ sung kiểm tra `check_reviewer_site_access` trong cả hai endpoint `get_evidence_manifest` và `get_evidence_media` trong `apps/server/main.py`. Truy cập sai site lập tức trả về HTTP 403 Forbidden (`cross-site evidence access denied`).
2. **Khắc phục Lỗ hổng Lọc Site khi Xuất Dataset cho Reviewer có Nhiều Site:**
   - *Vấn đề:* Khi reviewer có nhiều hơn 1 site được cấp quyền gọi export không truyền `?site_id=`, code cũ không áp dụng bộ lọc nào.
   - *Khắc phục:* Thêm tham số `allowed_sites` vào `export_dataset_records`. Khi không có `site_id` đơn lẻ, toàn bộ dữ liệu xuất ra được lọc nghiêm ngặt theo tập hợp `allowed_sites`, loại bỏ hoàn toàn nguy cơ rò rỉ các site ngoài thẩm quyền.
3. **Bổ sung Phương thức Xoay vòng Khóa (`rotate_device_token`):**
   - *Vấn đề:* Spec yêu cầu hỗ trợ xoay vòng thiết bị/token.
   - *Khắc phục:* Thêm phương thức `rotate_device_token` trong `EventStore`, cập nhật mốc thời gian và site_id mới (nếu có), từ chối thiết bị đã bị `revoked`.

## 3. Kiểm định chất lượng
- `tests/test_device_lifecycle_flow.py`: 7/7 passed (bổ sung test cross-site evidence read và token rotation).
- Toàn bộ test suite server (`test_server_evidence.py`, `test_review_api.py`, `test_review_priority.py`, `test_device_lifecycle_flow.py`): 34/34 passed.
- `git diff --check`: Sạch sẽ, không có lỗi khoảng trắng thừa.
