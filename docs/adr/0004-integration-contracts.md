---
status: accepted
---

# Khóa các hợp đồng tích hợp và gate theo target

Ngày 2026-10-11, người dùng yêu cầu áp dụng các đề xuất review và đồng bộ toàn bộ tài liệu. Quyết định này cụ thể hóa ADR-0001–0003; không đổi stack hoặc bổ sung service.

- Application dùng PerceptionPipeline chung cho native/reference; detector/tracker/pose là stage nội bộ, không chạy lặp ở Python.
- AI revision là full snapshot, identity/origin bất biến. Evidence request intent đi cùng transaction event/outbox; recorder persist receipt trước ACK, retry/query idempotent.
- Evidence có anchor/range và các chiều build/completeness/transfer/availability/integrity riêng. MVP pin khi persist event và sizing ring gồm verification/recovery, không mặc định thêm candidate hold.
- Review lưu viewed revisions, cờ cần xem lại và correction/reopen có audit. Downstream disabled/ineligible không thành pending khi bật provider; không tự backfill notification.
- Semantic replay khác realtime stress. G3 luôn kiểm target conformance/capacity thực; RKNN conversion chỉ bắt khi chọn RK3588.

Hành vi, failure cases và trường dữ liệu nằm tại [contracts](../architecture/contracts.md); không nhân bản protocol trong ADR. Policy site/threshold, target selection và pilot sign-off vẫn cần bằng chứng theo readiness. Accepted thiết kế không phải implementation hoặc test đã đạt.
