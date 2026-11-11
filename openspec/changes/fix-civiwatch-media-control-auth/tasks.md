## 1. Permission boundary

- [x] 1.1 Pin release chính thức hỗ trợ auth local và allowlist route; cấu hình external credential, origin policy và fixture paths.
- [x] 1.2 Adapter gửi credential đúng origin, chặn redirect rò credential; thêm regression hành vi HTTP.
- [x] 1.3 Cập nhật hướng dẫn vận hành và giới hạn kiểm chứng; không thay backend RBAC/API.

## 2. Verification

- [x] 2.1 Chạy regression adapter và Compose preflight có/thiếu credential tổng hợp.
- [x] 2.2 Chạy container smoke cô lập cho HTTP 401/200, WebSocket origin và administrative route denied.
- [x] 2.3 Chạy các gate repo được tài liệu hóa (`pytest`, `mypy`) cùng browser smoke của remediation UI; ghi rõ mọi skipped check.
- [x] 2.4 Chạy `openspec validate fix-civiwatch-media-control-auth --strict` và cập nhật log bằng kết quả quan sát được.
