# Tài liệu kỹ thuật CiviWatch (`civi-watch`)

Đọc tài liệu này để chọn nguồn mô tả code, quyết định thiết kế và bằng chứng còn thiếu. Baseline hiện tại là `17d9a32`, gồm phần v2 tại `9bb70ee` và remediation review. Các log/report giữ ngày và phạm vi đo gốc; chúng không tự thay thế contract hoặc nghiệm thu hiện trường.

## Trạng thái đối chiếu tại `17d9a32`

| Phạm vi | Code và bằng chứng hiện có | Giới hạn cần giữ |
|---|---|---|
| Kiểm tra Python reference | `pytest`: 982 tests và 207 subtests; `mypy`: 84 source files | Kết quả software lab sau đợt deepening, không phải release hoặc nghiệm thu target |
| Registry tình huống | Có định nghĩa US01–US14 và các factory tương ứng | Registry không chứng minh 14 nhóm đã được cấu hình, đánh giá hoặc chấp nhận tại site |
| Replay đa kịch bản | Lượt extended smoke đánh giá 11 nhóm; US04, US10, US14 báo unconfigured | ROI, engine chuyên biệt và policy từng camera vẫn phải cấu hình; zero events không phải negative pass |
| Candidate và snapshot | Pipeline điều phối hậu kiểm/storyboard; feature module giữ state; `snapshot.py` dựng full snapshot | Verifier mặc định của feature chạy offline; `verified` không phải Review confirmation |
| Geometry và pose | Có homography template theo frame và đường xử lý pose | Template không phải hiệu chuẩn site; khả năng batch phụ thuộc artifact/runtime |
| Media lab | go2rtc pin digest, auth local, kiểm origin và route; hai fixture stream đã trả MP4 | Không suy ra quyền sở hữu một phiên RTSP duy nhất, latency WebRTC hoặc failover hiện trường |
| Model và benchmark | Có manifest, công cụ preparation/evaluation và báo cáo đo | Dry-run là blueprint; tên file/log không chứng minh train thành công, quyền production hoặc chất lượng đã nghiệm thu |

Lệnh và kết quả gốc nằm trong [remediation evidence](logs/2026-11-11-review-remediation.md#final-verification-evidence). ODD mục tiêu là CCTV giao thông cố định 720p–1080p; smoke tổng hợp độ phân giải nhỏ chỉ kiểm tra phần mềm, không phải dữ liệu nghiệm thu ODD.

## Đọc theo nhu cầu

| Cần làm | Nguồn chuẩn |
|---|---|
| Hiểu thuật ngữ domain | [Language trong CONTEXT](../CONTEXT.md#language) |
| Chạy lab, chuẩn bị biến môi trường, chạy gate | [README](../README.md), [lab profile](architecture/lab-profile.md) |
| Hiểu quyền sở hữu runtime và luồng dữ liệu hiện tại | [Kiến trúc hệ thống](architecture/system-architecture.md) |
| Đối chiếu event, verification, anchor, evidence và giao nhận | [Hợp đồng tích hợp](architecture/contracts.md) |
| Phân biệt định nghĩa tình huống và trạng thái cấu hình/đánh giá | [Danh mục US01–US14](requirements/urban-safety-scenarios.md) |
| Xác định việc đã triển khai và nghiệm thu còn mở | [Plan triển khai](architecture/implementation-plan.md), [deployment readiness](architecture/deployment-readiness.md) |
| Chọn việc trong tracker | [Tracker thực thi](../.scratch/system-build-slices/PRD.md), [index mở rộng](../.scratch/system-build-slices/requirements-expansion-index.md) |
| Đối chiếu checklist và release gates | [Checklist theo module](implementation-checklists/README.md), [integration/G0–G5](implementation-checklists/integration-release.md) |
| Chọn dataset và hiểu phạm vi phép đo | [Sổ đăng ký dataset](datasets/video-datasets.md), [ứng viên công nghệ](requirements/technology-candidates.md) |
| Xem bản cập nhật được đối chiếu trong lần này | [Log đồng bộ tài liệu](logs/2026-11-11-docs-architecture-sync.md) |

## Quyết định thiết kế và trạng thái

| Tài liệu | Cách sử dụng |
|---|---|
| [ADR-0001](adr/0001-feature-pipeline-boundaries.md), [ADR-0002](adr/0002-server-downstream-event-publishing.md), [ADR-0003](adr/0003-fastapi-mongodb-backend.md), [ADR-0004](adr/0004-integration-contracts.md) | Giữ các quyết định nền về feature, downstream, backend và contract |
| [ADR-0005 snapshot](adr/0005-incident-snapshot-ownership.md) | Accepted: feature trả facts, một module sở hữu construction/validation snapshot |
| [ADR-0006 replay](adr/0006-semantic-replay-pipeline-reuse.md) | Accepted: dùng chung pipeline, giữ policy/sampling của từng caller và fail-fast observation lỗi |
| [ADR-0007 RTSP](adr/0007-rtsp-stream-ownership.md) | Proposed: không tự nâng probe một camera thành quyết định accepted hoặc conformance nhiều camera |
| [ADR-0008 v2](adr/0008-civiwatch-v2-hybrid-vlm-architecture.md) | Accepted design intent: đọc cùng trạng thái triển khai hiện tại, không lấy thống kê cũ hoặc mục tiêu latency làm bằng chứng mới |
| [Thay đổi auth media](../openspec/changes/fix-civiwatch-media-control-auth/proposal.md) | Đã triển khai trên nhánh và có smoke; artifact change chưa phải bằng chứng merge/release production |

## Nguồn chuẩn và quy tắc cập nhật

`CONTEXT.md` giữ thuật ngữ; ADR accepted giữ quyết định; architecture/contracts mô tả code hiện hành; plan và tracker phân biệt việc triển khai với nghiệm thu; checklist dẫn tới evidence và sign-off. Đối chiếu các nguồn này trước khi đổi claim hiện tại. Giữ lịch sử log/report và quyết định ADR; không sửa số đo cũ để trông như đã đo lại.

Chỉ cập nhật Execution trong ticket slices khi có bằng chứng tương ứng. Checklist không phải backlog thứ hai. Không dùng việc một ticket có implementation hoặc một test xanh để tự đóng G0–G5, quyền sử dụng artifact, hiệu chuẩn camera hoặc quyết định stream ownership.

Không mở lại MongoDB, event ring hoặc native C++ P1 đã chốt. Các câu hỏi site/target/protocol production, chất lượng từng nhóm, quyền dữ liệu và conformance vẫn theo [readiness](architecture/deployment-readiness.md). Các cơ hội deepening trong báo cáo HTML tạm thời chỉ là đề xuất chờ chọn, không phải ADR mới.
