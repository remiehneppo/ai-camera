# Tài liệu hệ thống AI Camera

**Cập nhật hệ thống: 2026-10-30.** Toàn bộ 893 unit & integration tests (188 subtests) và kiểm tra kiểu tĩnh `mypy` (72 source files) toàn dự án xanh. Hiện tại 29 tickets đã hoàn thành (`done`) và 10 tickets đạt mức thử nghiệm (`partial`) trong software lab. 5 nhóm tính năng nhận diện trên Edge đã hoạt động trong software lab: Person-down (US09), Tai nạn giao thông (US08), Xâm nhập vùng nguy hiểm (US10 / #57), Đỗ xe sai vùng/giờ (US05), và Tập trung đông người / gây rối (US06).

ODD phần cứng được khóa cứng: **100% camera CCTV giao thông cố định, độ nét từ HD (720p) đến 2MP (1080p)**; loại bỏ camera hành trình (dashcam) và camera độ nét thấp (< 720p).

## Đọc theo nhu cầu

| Cần biết | Tài liệu chuẩn |
|---|---|
| Hệ thống làm gì, các thuật ngữ domain chuẩn | [CONTEXT](../CONTEXT.md) |
| Định nghĩa các nhóm an toàn đô thị, tham số, hard negatives và gates | [Requirement tình huống](requirements/urban-safety-scenarios.md) |
| Module, dependency, ODD camera cố định và fault boundary | [Kiến trúc hệ thống](architecture/system-architecture.md) |
| Hợp đồng API, anchor alert_condition, signed config, rollback, WAN outage và retention | [Hợp đồng tích hợp](architecture/contracts.md) |
| Quyết định kiến trúc cốt lõi | [ADR-0001 pipeline](adr/0001-feature-pipeline-boundaries.md), [ADR-0002 downstream](adr/0002-server-downstream-event-publishing.md), [ADR-0003 backend](adr/0003-fastapi-mongodb-backend.md), [ADR-0004 contracts](adr/0004-integration-contracts.md) |
| Snapshot và semantic replay Python reference | [ADR-0005 snapshot](adr/0005-incident-snapshot-ownership.md), [ADR-0006 replay](adr/0006-semantic-replay-pipeline-reuse.md), [OpenSpec design](../openspec/changes/deepen-incident-snapshots-and-replay/design.md), [Tiến độ và kiểm chứng](../openspec/changes/deepen-incident-snapshots-and-replay/tasks.md), [Log triển khai](logs/2026-10-29-architecture-deepening-review.md#implementation-authorized--2026-10-30) |
| Phase, ownership, phân bổ trách nhiệm | [Plan triển khai](architecture/implementation-plan.md) |
| Theo dõi tiến độ và chọn việc | [Tracker thực thi](../.scratch/system-build-slices/PRD.md) và [Index mở rộng](../.scratch/system-build-slices/requirements-expansion-index.md) |
| Sổ đăng ký dataset video (CCTV 720p–1080p, quy tắc loại bỏ dashcam) | [Sổ đăng ký dataset](datasets/video-datasets.md) |
| Công cụ tải video CCTV cố định chuẩn ODD từ Hugging Face | [fetch_traffic_cctv_dataset.py](../tools/fetch_traffic_cctv_dataset.py) |
| Đánh giá đa kịch bản nhận diện trên video (Person-down, Xe, Đỗ xe, Đám đông) | [eval_all_scenarios.py](../tools/eval_all_scenarios.py) |
| Đối chiếu replay dataset trước khi có camera thật & truy vết/sửa lỗi `fall_0005` | [Replay pre-camera](logs/2026-10-30-pre-camera-dataset-replay.md), [Truy vết & sửa T1 fall_0005](logs/2026-10-30-fall-0005-anomaly-trace.md) |
| Chi tiết nghiệm thu theo module | [18 checklist module](implementation-checklists/README.md) |
| Cross-module failure tests và release gates | [Integration/G0–G5](implementation-checklists/integration-release.md) |
| Facts/ODD/sizing và benchmark CPU 28–45 FPS | [Deployment readiness](architecture/deployment-readiness.md) |
| Baseline đã kiểm chứng vs Ứng viên tương lai (RF-DETR/ViTPose/Orin NX) | [Ứng viên công nghệ](requirements/technology-candidates.md) |

## Nguồn chuẩn và cập nhật

ADR/quyết định accepted xác định lựa chọn; requirements định nghĩa phạm vi nghiệp vụ; architecture/contracts đặc tả hành vi; plan xác định scope/owner; tracker slices xác định thứ tự và tiến độ; checklist xác định bằng chứng nghiệm thu. Nếu chúng mâu thuẫn phải sửa các tài liệu chịu ảnh hưởng, không dùng log hoặc research để âm thầm ghi đè quyết định.

Chỉ claim/cập nhật Execution ở ticket slices. Module checklist giữ task IDs và link evidence; không claim/đóng như một backlog thứ hai. Gate chỉ accepted khi report và owner sign-off đủ; thiết kế được duyệt không phải runtime đã pass.

Các điểm còn mở gồm facts/site/target/protocol production trong readiness và mục 15 kiến trúc, cùng ngưỡng/gate từng nhóm và kiểm thử policy evidence theo loại trong requirement tình huống (Q36 giữ baseline person-down). Không hỏi lại event ring, MongoDB hoặc native C++ P1 đã chốt. RKNN là nhánh theo target; G3 conformance/capacity vẫn bắt buộc cho mọi target.
