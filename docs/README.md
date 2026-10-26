# Tài liệu hệ thống AI Camera

Cập nhật requirement 2026-10-20. Có mã/lệnh thử nghiệm software lab và các ghi chú implementation; tiến độ runtime/partial/blockers theo tracker, không coi mô tả kiến trúc là đã triển khai. README gốc có phần mở đầu cũ và ghi chú runtime mới chưa hoàn toàn đồng nhất; không dùng chúng để tuyên bố nghiệm thu. Benchmark target, chất lượng từng nhóm và pilot chưa nghiệm thu. [Research §14](../traffic-ai-camera-research/report.md#14-cập-nhật-theo-implementation-và-thử-nghiệm-15-10-2026) phân biệt mã hiện có, log test và gate còn mở. Bắt đầu ở đây thay vì đọc log theo thời gian.

## Đọc theo nhu cầu

| Cần biết | Tài liệu chuẩn |
|---|---|
| Hệ thống làm gì, các thuật ngữ | [CONTEXT](../CONTEXT.md) |
| Định nghĩa 13 nhóm an toàn đô thị + nhánh phá hoại, tham số/pending, hard negatives và gates | [Requirement tình huống](requirements/urban-safety-scenarios.md) |
| Module, dependency và fault boundary | [Kiến trúc hệ thống](architecture/system-architecture.md) |
| API semantic, identity, pin/receipt, review, replay | [Hợp đồng tích hợp](architecture/contracts.md) |
| Quyết định kiến trúc và lý do | [ADR-0001 pipeline](adr/0001-feature-pipeline-boundaries.md), [ADR-0002 downstream](adr/0002-server-downstream-event-publishing.md), [ADR-0003 backend](adr/0003-fastapi-mongodb-backend.md), [ADR-0004 contracts](adr/0004-integration-contracts.md) |
| Phase, ownership, 89 task phạm vi | [Plan triển khai](architecture/implementation-plan.md) |
| Chọn và theo dõi công việc | [Tracker thực thi](../.scratch/system-build-slices/PRD.md) và [Index mở rộng](../.scratch/system-build-slices/requirements-expansion-index.md) — nguồn duy nhất của Execution/blockers |
| Dataset video để chạy thử và đánh giá (đã kiểm, có license + lệnh chạy) | [Sổ đăng ký dataset](datasets/video-datasets.md) |
| Chi tiết nghiệm thu theo module | [18 checklist module](implementation-checklists/README.md) |
| Cross-module failure tests và release | [Integration/G0–G5](implementation-checklists/integration-release.md) |
| Facts/ODD/sizing/benchmark còn cần | [Deployment readiness](architecture/deployment-readiness.md) |
| Số đo benchmark thực tế pipeline trên video 1080p | [Báo cáo Benchmark Pipeline](reports/2026-10-21-pipeline-benchmark-report.md) |
| Nghiên cứu model/camera/data/chi phí và phản biện bước tiếp theo | [Research](../traffic-ai-camera-research/README.md) — cập nhật implementation15-10; giá giữ ngày quan sát, không là quote hiện tại |

## Nguồn chuẩn và cập nhật

ADR/quyết định accepted xác định lựa chọn; requirements định nghĩa phạm vi nghiệp vụ; architecture/contracts đặc tả hành vi; plan xác định scope/owner; tracker slices xác định thứ tự và tiến độ; checklist xác định bằng chứng nghiệm thu. Nếu chúng mâu thuẫn phải sửa các tài liệu chịu ảnh hưởng, không dùng log hoặc research để âm thầm ghi đè quyết định.

Chỉ claim/cập nhật Execution ở ticket slices. Module checklist giữ task IDs và link evidence; không claim/đóng như một backlog thứ hai. Gate chỉ accepted khi report và owner sign-off đủ; thiết kế được duyệt không phải runtime đã pass.

Các điểm còn mở gồm facts/site/target/protocol production trong readiness và mục 15 kiến trúc, cùng ngưỡng/gate từng nhóm và kiểm thử policy evidence theo loại trong requirement tình huống (Q36 giữ baseline person-down). Không hỏi lại event ring, MongoDB hoặc native C++ P1 đã chốt. RKNN là nhánh theo target; G3 conformance/capacity vẫn bắt buộc cho mọi target.
