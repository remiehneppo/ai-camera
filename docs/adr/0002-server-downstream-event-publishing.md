---
status: accepted
---

# Server sở hữu phát event downstream sau durable ingestion

Ngày 2026-10-11, người dùng xác nhận edge gửi HTTPS tới server, server durable-commit event cùng downstream outbox intent trước khi worker phát event. EventPublisher là điểm mở rộng phía server cho Kafka, RabbitMQ hoặc WebSocket tương lai; chưa thêm broker vào lab, tránh biến mỗi edge thành broker client và tránh hai nguồn sự thật cho ingestion.

Evidence có upload/receipt riêng; downstream dùng identity/revision/idempotency và retry, không hứa exactly-once consumer processing. Broker ACK/WebSocket send không thay ingestion receipt hoặc xác nhận nghiệp vụ; downstream outage không đảo ngược event đã được server commit. Lab chưa bật notification ngoài dashboard, replay/synthetic không đi notification thật.
