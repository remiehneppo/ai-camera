# Tài liệu kỹ thuật hệ thống AI Camera

**Cập nhật:** 2026-10-30 · **Kiểm chứng hiện tại:** **896 unit & integration tests** (`188` subtests) và **`mypy` trên 72 source files** xanh.  
**Trạng thái thực thi:** Software-lab Python reference hoàn chỉnh cho 5 nhóm cảnh báo trên Edge (`person_down`, `vehicle_incident`, `danger_zone`, `illegal_parking`, `crowd_incident`), snapshot tập trung ([ADR-0005](adr/0005-incident-snapshot-ownership.md)), semantic replay dùng chung pipeline ([ADR-0006](adr/0006-semantic-replay-pipeline-reuse.md)), backend FastAPI/MongoDB, lưu trữ/truy hồi evidence, signed config/canary/rollback và tự chủ WAN 24h. Native C++ core (`#10/#12`), target hardware conformance/capacity (`G3`) và nghiệm thu thực địa (`G4–G5`) đang mở.

**Ràng buộc ODD cố định:** Hệ thống chỉ thiết kế và nghiệm thu cho **camera CCTV giao thông gắn cố định, độ phân giải HD (1280×720) đến Full HD (1920×1080)**. Loại trừ vĩnh viễn camera hành trình (dashcam) và luồng độ phân giải thấp (`< 720p`).

## Bản đồ tài liệu chuẩn

| Nhu cầu tra cứu | Tài liệu chuẩn |
|---|---|
| Từ điển thuật ngữ domain bắt buộc | [CONTEXT.md](../CONTEXT.md) |
| Các quyết định kiến trúc đã chốt (ADR-0001 → ADR-0006) | [Mục lục ADR](adr/README.md) |
| Kiến trúc tổng thể, phân lớp, cấu trúc mã nguồn và fault boundaries | [Kiến trúc hệ thống](architecture/system-architecture.md) |
| Hợp đồng tích hợp: snapshot, evidence anchor/pin, review, probe, signed config, WAN outage | [Hợp đồng tích hợp](architecture/contracts.md) |
| Phân chia trách nhiệm, trạng thái phase P0–P5 và lộ trình gate G0–G5 | [Kế hoạch triển khai](architecture/implementation-plan.md) |
| Điều kiện sẵn sàng triển khai, site profile mẫu và rủi ro trước pilot | [Deployment readiness](architecture/deployment-readiness.md) |
| Cấu hình máy lab, số đo tham chiếu x86 và protocol kiểm thử tối thiểu | [Hồ sơ lab & protocol](architecture/lab-profile.md) |
| Định nghĩa 14 nhóm tình huống an toàn đô thị, tham số và hard negatives | [Requirement tình huống](requirements/urban-safety-scenarios.md) |
| Baseline công nghệ hiện hành và điều kiện đánh giá ứng viên (RF-DETR, ViTPose, Orin NX) | [Ứng viên công nghệ](requirements/technology-candidates.md) |
| Sổ đăng ký video dataset, kết quả rà soát ODD và lệnh replay chuẩn | [Sổ đăng ký dataset video](datasets/video-datasets.md) |
| Hướng dẫn review ranh giới SOLID, ma trận 45 lỗi X01–X45 và release gates | [Mục lục checklist](implementation-checklists/README.md) · [Ranh giới SOLID](implementation-checklists/architecture-analysis.md) · [Integration & G0–G5](implementation-checklists/integration-release.md) |
| Runbook xử lý sự cố vận hành synthetic probe | [Synthetic Probe Runbook](runbooks/synthetic-probe-operational-fault.md) |
| Tracker thực thi theo lát cắt dọc (68 tickets) | [Tracker PRD](../.scratch/system-build-slices/PRD.md) · [Index mở rộng](../.scratch/system-build-slices/requirements-expansion-index.md) |

## Bằng chứng kiểm chứng & nhật ký kỹ thuật trọng tâm

- **Kiến trúc Snapshot & Semantic Replay (2026-10-30):** [OpenSpec design](../openspec/changes/deepen-incident-snapshots-and-replay/design.md) · [Log phê duyệt & triển khai](logs/2026-10-29-architecture-deepening-review.md) · [Log code review & sửa lỗi hậu cutover](logs/2026-10-30-head-minus-3-code-review.md).
- **Tái cấu trúc & làm sạch hệ thống tài liệu (2026-10-30):** [Biên bản refactor & dọn tài liệu lỗi thời](logs/2026-10-30-docs-refactor-and-prune.md).
- **Kiểm định Video Replay & Đính chính ODD trước camera thật (2026-10-30):** [Replay 17 clip & rút phân loại ODD giả](logs/2026-10-30-pre-camera-dataset-replay.md) · [Truy vết & sửa lỗi T1 `fall_0005`](logs/2026-10-30-fall-0005-anomaly-trace.md).
- **Benchmark thông lượng tham chiếu trên CPU x86:** [Báo cáo Benchmark Pipeline](reports/2026-10-21-pipeline-benchmark-report.md) *(đo trên clip đô thị chẩn đoán 1080p, không thay thế nghiệm thu ODD hoặc capacity trên board nhúng đích)*.
