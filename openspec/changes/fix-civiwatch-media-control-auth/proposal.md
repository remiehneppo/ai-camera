## Why

Control API của go2rtc mới được đưa vào CiviWatch đang cho phép mọi origin và chưa yêu cầu thông tin xác thực. Yêu cầu `fix all` sau review ngày 2026-11-11 bao gồm đóng boundary này. Tham chiếu kỹ thuật: ADR-0008 và log `2026-11-11-review-remediation`; chưa có mã issue riêng được cung cấp.

## What Changes

- Bắt buộc cấu hình thông tin xác thực control API từ môi trường, kể cả client loopback; không có mật khẩu mặc định.
- Dùng kiểm tra cùng origin cho WebSocket và không bật wildcard CORS.
- Giới hạn route control API vào các thao tác media cần thiết; không công bố route thoát, khởi động lại hoặc thay đổi cấu hình.
- Adapter media gửi Basic Authorization tới đúng origin cấu hình và không chuyển tiếp credential qua redirect.
- Pin release go2rtc chính thức, giữ port host ở loopback và sửa đường dẫn fixture theo mount `/app/data`.

## Capabilities

### New Capabilities

- `media-control-auth`: bảo vệ control API của media engine bằng xác thực, origin policy và giới hạn route.

### Modified Capabilities

Không đổi capability nghiệp vụ, taxonomy, API backend hoặc cấu trúc event.

## Impact

Thành phần: `compose.yaml`, `infra/go2rtc.yaml`, `apps/edge/media_engine.py`, ví dụ môi trường và runbook. Thay đổi quyền truy cập: control API không còn cho client thiếu credential. API `/v1` của backend, DB/schema, RBAC, tenant và mobile không đổi. Người chạy Compose phải cấp credential riêng; không ghi credential vào Git, URL, log hoặc diagram.

## Out of Scope

Không thêm proxy/service/datastore, không triển khai lên hạ tầng dùng chung, không thay luồng review có thẩm quyền của backend, không chuyển ảnh khách hàng tới dịch vụ ngoài. Các sửa lỗi T1 còn lại của review giữ nguyên phạm vi của log remediation.
