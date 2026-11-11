## Context

Đây là sửa permission boundary của media engine hiện hữu theo ADR-0008, không phải service mới. Người dùng đã yêu cầu thực hiện qua `fix all`; checkpoint triển khai là yêu cầu đó. Dùng kiểm soát native của release go2rtc được pin, không thêm proxy hoặc thư viện.

![Hình: Adapter đi qua xác thực native và allowlist route; origin ngoài bị từ chối](../../../docs/adr/diagrams/H03-media-control-auth.drawio)

## Decisions

1. **Volume:** giả định lab hiện tại 1-2 stream, tối đa 14 capability mỗi camera; chưa có số liệu production. Không thêm queue, cache hoặc xử lý theo frame vào auth.
2. **Ownership / atomicity:** Compose và file go2rtc sở hữu cấu hình media; adapter chỉ đọc media. Backend vẫn là owner của event/review và không tham gia giao dịch media.
3. **Concurrency:** cấu hình được nạp khi khởi động; không thêm read-modify-write hoặc store trạng thái dùng chung.
4. **Failures:** thiếu credential làm preflight thất bại; HTTP 401/403 và redirect bị từ chối đi theo đường unavailable/fallback hiện có, không dùng credential giả hoặc bỏ qua auth.
5. **Retry / idempotency:** giữ timeout hữu hạn hiện có; không thêm retry. Các thao tác adapter là đọc, không phát lệnh administrative.
6. **Compatibility:** API backend `/v1`, event wire contract và DB không đổi. Client control API trước đây không xác thực phải cấp credential; đây là thay đổi T2 được nêu rõ trong runbook.
7. **Isolation:** media không sở hữu dữ liệu tenant có thẩm quyền; không đổi tenant/RBAC backend. Local HTTP regression chứng minh credential không rời origin, container smoke chứng minh 401/200, WS origin và route administrative bị chặn.
8. **Rollout / rollback:** kiểm tra Compose với credential fixture, sau đó chạy container cô lập `--network none` không có dữ liệu camera thật. Khi rollback, dừng media hoặc giữ các hạn chế bảo mật; không khôi phục wildcard origin hay API không xác thực. Không triển khai lên môi trường dùng chung trong tác vụ này.

## Verification

- `tests/test_media_auth.py`: hành vi adapter với HTTP fixture cục bộ, credential hợp lệ và redirect.
- Container smoke có các case `unauthenticated-media`, `authorized-media`, `foreign-websocket-origin`, `administrative-route-denied`; chỉ in status, không in credential. Version pin và kết quả thực tế được ghi trong log remediation.
- Compose preflight dùng `--env-file /dev/null` và credential tổng hợp, có case thiếu credential.
- Kiểm tra cấu hình fixture/pin và `openspec validate fix-civiwatch-media-control-auth --strict`.

Các đường camera thật, browser riêng của người vận hành, TLS ngoài host và triển khai production chưa được chứng minh bởi các phép kiểm tra này.
