# Tài liệu hệ thống AI Camera

Cập nhật 2026-10-11. Trạng thái hiện tại: thiết kế/backlog đã duyệt; runtime, benchmark và pilot chưa nghiệm thu. Bắt đầu ở đây thay vì đọc log theo thời gian.

## Đọc theo nhu cầu

| Cần biết | Tài liệu chuẩn |
|---|---|
| Hệ thống làm gì, các thuật ngữ | [CONTEXT](../CONTEXT.md) |
| Module, dependency và fault boundary | [Kiến trúc hệ thống](architecture/system-architecture.md) |
| API semantic, identity, pin/receipt, review, replay | [Hợp đồng tích hợp](architecture/contracts.md) |
| Quyết định kiến trúc và lý do | [ADR-0001 pipeline](adr/0001-feature-pipeline-boundaries.md), [ADR-0002 downstream](adr/0002-server-downstream-event-publishing.md), [ADR-0003 backend](adr/0003-fastapi-mongodb-backend.md), [ADR-0004 contracts](adr/0004-integration-contracts.md) |
| Phase, ownership, 89 task phạm vi | [Plan triển khai](architecture/implementation-plan.md) |
| Chọn và theo dõi công việc | [50 ticket thực thi](../.scratch/system-build-slices/PRD.md) — nguồn duy nhất của Execution/blockers |
| Chi tiết nghiệm thu theo module | [18 checklist module](implementation-checklists/README.md) |
| Cross-module failure tests và release | [Integration/G0–G5](implementation-checklists/integration-release.md) |
| Facts/ODD/sizing/benchmark còn cần | [Deployment readiness](architecture/deployment-readiness.md) |
| Nghiên cứu model/camera/data/chi phí | [Research](../traffic-ai-camera-research/README.md) — giá có ngày quan sát, không là quote hiện tại |

## Nguồn chuẩn và cập nhật

ADR/quyết định accepted xác định lựa chọn; architecture/contracts đặc tả hành vi; plan xác định scope/owner; tracker slices xác định thứ tự và tiến độ; checklist xác định bằng chứng nghiệm thu. Nếu chúng mâu thuẫn phải sửa các tài liệu chịu ảnh hưởng, không dùng log hoặc research để âm thầm ghi đè quyết định.

Chỉ claim/cập nhật Execution ở ticket slices. Module checklist giữ task IDs và link evidence; không claim/đóng như một backlog thứ hai. Gate chỉ accepted khi report và owner sign-off đủ; thiết kế được duyệt không phải runtime đã pass.

Các quyết định còn mở chỉ gồm facts/site/target/protocol production được nêu trong readiness và mục 15 kiến trúc. Không hỏi lại event ring, MongoDB hoặc native C++ P1 đã chốt. RKNN là nhánh theo target; G3 conformance/capacity vẫn bắt buộc cho mọi target.

## Lịch sử

[Nhật ký](logs/README.md) và [review 2026-10-11](architecture/design-review-2026-10-11.md) giữ lý do thay đổi, không dùng làm spec hiện hành. [Breakdown cũ](implementation-checklists/ticket-breakdown-draft.md) chỉ dẫn tới tracker, không duy trì bản sao 50 ticket.
