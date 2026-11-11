## ADDED Requirements

### Requirement: Authenticated media control API

Deployment SHALL yêu cầu credential riêng cho control API và MUST áp dụng xác thực với cả client loopback. Credential MUST được cấp ngoài source code; thiếu cấu hình bắt buộc SHALL làm preflight thất bại rõ ràng.

#### Scenario: Missing deployment credentials
- **WHEN** người vận hành kiểm tra cấu hình Compose mà chưa cấp credential media bắt buộc
- **THEN** preflight SHALL thất bại thay vì dùng credential mặc định

#### Scenario: Unauthenticated media request
- **WHEN** một client không có credential hợp lệ gọi route media HTTP
- **THEN** control API SHALL từ chối bằng HTTP 401

#### Scenario: Authorized media request
- **WHEN** adapter gửi credential đúng tới origin media đã cấu hình
- **THEN** control API SHALL phục vụ route media được phép

### Requirement: Restricted browser and administrative access

Deployment SHALL giữ published API port trên loopback, MUST NOT bật wildcard origin và SHALL chỉ công bố route media cần thiết. Route thoát tiến trình, khởi động lại và sửa cấu hình MUST NOT truy cập được qua published API.

#### Scenario: Foreign WebSocket origin
- **WHEN** một WebSocket request có credential đúng nhưng Origin khác với origin API
- **THEN** control API SHALL từ chối nâng cấp kết nối

#### Scenario: Administrative route requested
- **WHEN** client gọi route thoát, khởi động lại hoặc sửa cấu hình qua published API
- **THEN** route SHALL không được đăng ký, kể cả khi request có credential đúng

### Requirement: Credential confinement in the media adapter

Adapter SHALL gửi credential bằng Authorization header tới origin cấu hình, MUST NOT nhúng credential vào URL hoặc chuyển tiếp credential qua redirect.

#### Scenario: Cross-origin redirect
- **WHEN** endpoint cấu hình trả redirect tới origin khác
- **THEN** adapter SHALL không gửi credential tới origin đích và SHALL trả lỗi hoặc trạng thái unavailable theo đường xử lý lỗi hiện có

### Requirement: Reproducible local media runtime

Deployment SHALL pin release go2rtc chính thức có các kiểm soát trên. Fixture source SHALL dùng đường dẫn khớp mount đã khai báo; cấu hình SHALL không chứa đường dẫn tương đối phụ thuộc working directory của image.

#### Scenario: Fixture paths and runtime pin
- **WHEN** người vận hành chạy cấu hình media đã kiểm tra với dữ liệu fixture có sẵn
- **THEN** source SHALL tham chiếu `/app/data/benchmark/` và runtime SHALL không dùng tag `latest`
