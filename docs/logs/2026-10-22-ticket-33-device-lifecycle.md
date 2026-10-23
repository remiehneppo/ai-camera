# Nhật ký Triển khai Ticket #33 — 2026-10-22

## 1. Mục tiêu và Phạm vi
- **Ticket #33:** Device lifecycle và site access được enforce.
- **Phân loại độ phức tạp:** L2 (tích hợp quản lý vòng đời thiết bị, kiểm soát quyền truy cập cross-site và cross-device trên toàn bộ API server).
- **Mô hình thực thi:** Thiết kế hợp đồng domain `domain/device_contract.py`, tích hợp quản lý trạng thái tại server backend (`store.py`, `main.py`, `config.py`, `dataset.py`), xây dựng bộ test tích hợp `tests/test_device_lifecycle_flow.py`.

## 2. Các Thành phần Triển khai

### 1. Hợp đồng Domain Vòng đời Thiết bị (`domain/device_contract.py`)
- Trạng thái thiết bị: `active` (hoặc `enrolled`), `quarantined`, `revoked`.
- Ràng buộc chuyển đổi trạng thái (`ALLOWED_TRANSITIONS`):
  - `active` <-> `quarantined`
  - `active` | `quarantined` -> `revoked`
  - `revoked` là trạng thái kết thúc (terminal state), không thể chuyển đổi tiếp.
- Mô hình dữ liệu `DeviceRecord` và `ReviewerAccessRecord`:
  - `DeviceRecord`: quản lý `device_id`, `site_id`, `status`, `allowed_cameras`, lý do cách ly (`quarantine_reason`) và lý do thu hồi (`revocation_reason`).
  - `ReviewerAccessRecord`: quản lý `reviewer_id`, `allowed_sites` (danh sách site được phép truy cập, rỗng = toàn quyền).
- Hàm thực thi chính sách:
  - `check_device_access(device, camera_id)`: từ chối thiết bị revoked (`device_credential_revoked`), quarantined (`device_quarantined`) hoặc camera không thuộc `allowed_cameras` (`camera_not_allowed_for_device`).
  - `check_reviewer_site_access(reviewer, event_site_id)`: từ chối reviewer truy cập ngoài phạm vi site được cấp quyền.

### 2. Cấu hình & Lưu trữ (`apps/server/config.py`, `apps/server/store.py`)
- `ServerConfig`: nạp cấu hình ánh xạ `device_sites` (`DEVICE_SITES`) và phân quyền site reviewer `reviewer_sites` (`REVIEWER_SITES`).
- `EventStore`:
  - Khởi tạo collection `devices` trong MongoDB.
  - Các phương thức: `get_device`, `enroll_device`, `quarantine_device`, `reactivate_device`, `revoke_device`.

### 3. Thực thi Chính sách trên API Backend (`apps/server/main.py`, `apps/server/dataset.py`)
- **Ingestion (`POST /v1/events`):**
  - Kiểm tra trạng thái thiết bị và danh sách camera cho phép. Thiết bị revoked hoặc quarantined trả về HTTP 403 Forbidden. Camera không được phép trả về HTTP 403.
- **Upload Bằng chứng (`PUT /v1/evidence/...`):**
  - Kiểm tra trạng thái thiết bị: thiết bị revoked hoặc quarantined bị từ chối với HTTP 403.
- **Review Sự kiện (`POST /v1/events/{device_id}/{event_id}/review`):**
  - Đối chiếu `site_id` của sự kiện với `allowed_sites` của reviewer. Reviewer khác site bị từ chối với HTTP 403 ("cross-site review access denied").
- **Xuất Dữ liệu (`GET /v1/dataset/export`):**
  - Reviewer bị giới hạn site chỉ có thể xuất dữ liệu thuộc site của mình. Truy cập cross-site trả về HTTP 403 ("cross-site export access denied").
- **Endpoint Quản trị Vòng đời Thiết bị:**
  - `GET /v1/devices/{device_id}`
  - `POST /v1/devices/{device_id}/quarantine`
  - `POST /v1/devices/{device_id}/reactivate`
  - `POST /v1/devices/{device_id}/revoke`

## 3. Kiểm định & Xác nhận Kết quả

- **Tích hợp kiểm thử tự động (`tests/test_device_lifecycle_flow.py`):**
  - `test_revoked_device_is_denied_on_ingest`: Thiết bị revoked bị từ chối 403.
  - `test_quarantined_device_is_denied_and_can_be_reactivated`: Thiết bị bị cách ly từ chối 403, tái kích hoạt thành công 200.
  - `test_disallowed_camera_for_device_is_denied`: Camera ngoài danh sách cho phép bị từ chối 403.
  - `test_cross_site_review_access_is_denied`: Reviewer khác site bị từ chối 403, reviewer đúng site thực hiện review thành công.
  - `test_cross_site_dataset_export_is_denied`: Reviewer khác site bị từ chối xuất 403, đúng site xuất thành công.
- **Kết quả Test Suite:**
  - `tests/test_device_lifecycle_flow.py`: 5/5 passed.
  - Toàn bộ test suite server (`test_server_evidence.py`, `test_review_api.py`, `test_review_priority.py`): 32/32 passed.
  - Toàn dự án: **524 passed, 126 subtests passed**.
- **Type Checking:**
  - `mypy domain/device_contract.py --ignore-missing-imports` đạt Success không có lỗi.
