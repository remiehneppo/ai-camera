# Tài liệu hệ thống AI Camera

**Cập nhật hệ thống: 2026-10-27.** Toàn bộ 823 unit & integration tests toàn dự án xanh. Hiện tại 29 tickets đã hoàn thành (`done`) và 9 tickets đang chạy thử nghiệm (`partial`) trong software lab. 4 nhóm tính năng nhận diện chính trên Edge đã hoạt động: Person-down (US09), Tai nạn giao thông (US08), Đỗ xe sai vùng/giờ (US05), và Tập trung đông người / gây rối (US06).

ODD phần cứng được khóa cứng: **100% camera CCTV giao thông cố định, độ nét từ HD (720p) đến 2MP (1080p)**; loại bỏ camera hành trình (dashcam) và camera độ nét thấp (< 720p).

## Đọc theo nhu cầu

| Cần biết | Tài liệu chuẩn |
|---|---|
| Hệ thống làm gì, các thuật ngữ domain chuẩn | [CONTEXT](../CONTEXT.md) |
| Định nghĩa các nhóm an toàn đô thị, tham số, hard negatives và gates | [Requirement tình huống](requirements/urban-safety-scenarios.md) |
| Module, dependency, ODD camera cố định và fault boundary | [Kiến trúc hệ thống](architecture/system-architecture.md) |
| Hợp đồng API, anchor alert_condition, signed config, rollback, WAN outage và retention | [Hợp đồng tích hợp](architecture/contracts.md) |
| Quyết định kiến trúc cốt lõi | [ADR-0001 pipeline](adr/0001-feature-pipeline-boundaries.md), [ADR-0002 downstream](adr/0002-server-downstream-event-publishing.md), [ADR-0003 backend](adr/0003-fastapi-mongodb-backend.md), [ADR-0004 contracts](adr/0004-integration-contracts.md) |
| Phase, ownership, phân bổ trách nhiệm | [Plan triển khai](architecture/implementation-plan.md) |
| Theo dõi tiến độ và chọn việc | [Tracker thực thi](../.scratch/system-build-slices/PRD.md) và [Index mở rộng](../.scratch/system-build-slices/requirements-expansion-index.md) |
| Sổ đăng ký dataset video (CCTV 720p–1080p, quy tắc loại bỏ dashcam) | [Sổ đăng ký dataset](datasets/video-datasets.md) |
| Công cụ tải video CCTV cố định chuẩn ODD từ Hugging Face | [fetch_traffic_cctv_dataset.py](../tools/fetch_traffic_cctv_dataset.py) |
| Đánh giá đa kịch bản nhận diện trên video (Person-down, Xe, Đỗ xe, Đám đông) | [eval_all_scenarios.py](../tools/eval_all_scenarios.py) |
| Chi tiết nghiệm thu theo module | [18 checklist module](implementation-checklists/README.md) |
| Cross-module failure tests và release gates | [Integration/G0–G5](implementation-checklists/integration-release.md) |
| Facts/ODD/sizing và benchmark CPU 28–45 FPS | [Deployment readiness](architecture/deployment-readiness.md) |
| Baseline đã kiểm chứng vs Ứng viên tương lai (RF-DETR/ViTPose/Orin NX) | [Ứng viên công nghệ](requirements/technology-candidates.md) |

## Nguồn chuẩn và cập nhật

ADR/quyết định accepted xác định lựa chọn; requirements định nghĩa phạm vi nghiệp vụ; architecture/contracts đặc tả hành vi; plan xác định scope/owner; tracker slices xác định thứ tự và tiến độ; checklist xác định bằng chứng nghiệm thu. Nếu chúng mâu thuẫn phải sửa các tài liệu chịu ảnh hưởng, không dùng log hoặc research để âm thầm ghi đè quyết định.

Chỉ claim/cập nhật Execution ở ticket slices. Module checklist giữ task IDs và link evidence; không claim/đóng như một backlog thứ hai. Gate chỉ accepted khi report và owner sign-off đủ; thiết kế được duyệt không phải runtime đã pass.

Các điểm còn mở gồm facts/site/target/protocol production trong readiness và mục 15 kiến trúc, cùng ngưỡng/gate từng nhóm và kiểm thử policy evidence theo loại trong requirement tình huống (Q36 giữ baseline person-down). Không hỏi lại event ring, MongoDB hoặc native C++ P1 đã chốt. RKNN là nhánh theo target; G3 conformance/capacity vẫn bắt buộc cho mọi target.
