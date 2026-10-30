# 2026-10-30 — Refactor toàn diện hệ thống tài liệu kỹ thuật & dọn tài liệu lỗi thời

## 1. Bối cảnh và mục tiêu

Sau đợt tập trung hóa quyền dựng snapshot ([ADR-0005](../adr/0005-incident-snapshot-ownership.md)), hợp nhất semantic replay ([ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md)), khóa cổng nhóm nhãn thô trong `ByteTracker` / cụm phân tán trong `CrowdIncidentEngine` và đính chính dữ liệu ODD trước camera thật ([log 2026-10-30](2026-10-30-pre-camera-dataset-replay.md)), nhiều tài liệu kiến trúc và kế hoạch từ giữa tháng 10 vẫn giữ:
- Bản kế hoạch ngang 18 module cũ (`.scratch/system-build/`) và cây thư mục giả định `src/traffic_camera/...` chưa từng tồn tại trong mã nguồn;
- Các ghi chú phỏng vấn trung gian `Q1–Q19` / `Q1–Q36` gây nhiễu khi đọc thiết kế hiện hành;
- Nhận định ODD cũ đã bị rút lại (gọi nhầm tập dashcam `AccidentBench` / `traffic_cctv_hd` và các clip zoom/reframing `shibuya`, `intersection_traffic_1080p` là Fixed CCTV ODD, hoặc ghi nhận chỉ có 4 thay vì 5 module cảnh báo trên Edge);
- Các gói xuất file nhị phân DOCX/PDF trùng lặp (~9,6 MB), bản dump JSON thô của công cụ review tự động và các log đồng bộ trung gian không còn liên kết tham chiếu.

## 2. Các quyết định dọn dẹp (59 tệp lỗi thời đã loại bỏ)

1. **Xóa tracker & prototype đã bị thay thế:**
   - `.scratch/system-build/` (19 tệp — kế hoạch ngang M00–M17 ngày 2026-10-11, đã được thay thế hoàn toàn bởi `.scratch/system-build-slices/`).
   - `.scratch/live-stream/` (2 tệp — bản nháp thử nghiệm cũ không còn liên kết).
2. **Xóa gói báo cáo xuất trùng lặp và báo cáo dữ liệu ngoài ODD trong `docs/reports/`:**
   - `2026-10-16-onechain-design-report/` và `2026-10-16-onechain-reference-layout/` (12 tệp nhị phân DOCX/PDF/PNG trùng lặp; nội dung chuẩn nằm trực tiếp trong `docs/architecture/` và `traffic-ai-camera-research/report.md`).
   - `2026-10-26-urfd-smoke-run.md` (báo cáo chạy trên tập URFD `< 720p` trong nhà ngoài phạm vi ODD) và `2026-10-26-video-dataset-candidates.md` (bản nháp ứng viên cũ đã hợp nhất vào `docs/datasets/video-datasets.md`).
3. **Xóa dump JSON thô và các meta-log đồng bộ cũ không có liên kết tham chiếu trong `docs/logs/`:**
   - 2 tệp `2026-10-15-ocr-review-raw*.json` và 22 tệp log thao tác/đồng bộ trung gian hoặc log chứa nhận định ODD giả đã rút (`2026-10-27-fixed-cctv-dataset-evaluation.md`, `2026-10-27-docs-refactor-and-obsolete-cleanup.md`, `2026-10-28-progress-analysis-and-implementation-roadmap.md`, các log xuất LibreOffice/prune/restart cũ). Toàn bộ 48 tệp log bằng chứng được liên kết từ ticket/ADR cùng các log triển khai theo ticket đều được bảo toàn.

## 3. Các tài liệu cốt lõi đã được tái cấu trúc và chuẩn hóa

- **Mục lục & Ngôn ngữ chung:** Tạo mới [`docs/adr/README.md`](../adr/README.md) tổng hợp ADR-0001 → ADR-0006; viết lại gọn [`docs/README.md`](../README.md), cập nhật [`CONTEXT.md`](../../CONTEXT.md) và [`README.md`](../../README.md) (sửa cả anchor `#synthetic-probe-operational-fault` khớp với `domain/probe_contract.py`).
- **Kiến trúc & Kế hoạch (`docs/architecture/`):**
  - [`system-architecture.md`](../architecture/system-architecture.md): bỏ nhiễu `Q1–Q19`, thay cây `src/traffic_camera/` giả định bằng kiến trúc thư mục thực tế (`domain/`, `apps/edge/`, `apps/server/`, `models/`, `fixtures/`, `tools/`, `tests/`, `openspec/`, `docs/`), cập nhật bảng công cụ thực tế và lộ trình `G0–G5`.
  - [`contracts.md`](../architecture/contracts.md): cập nhật đủ 4 module `alert_condition` (`US10, US08, US05, US06`), chuẩn hóa đánh số mục `§1–§10` và bảo toàn toàn bộ heading anchor đang được code/test kiểm chứng.
  - [`implementation-plan.md`](../architecture/implementation-plan.md): cô đọng từ bản nháp 435 dòng trước khi có code thành kế hoạch chuẩn theo 5 bất biến kiến trúc, phân ranh tầng mã nguồn thực tế, trạng thái `P0–P5` và lộ trình `G0–G5`.
  - [`deployment-readiness.md`](../architecture/deployment-readiness.md) & [`lab-profile.md`](../architecture/lab-profile.md): đồng bộ cấu hình máy lab (`kernel 7.0.0-38-generic`, `896` tests / `188` subtests / `72` files `mypy`), gỡ bỏ toàn bộ số liệu ODD giả trên `AccidentBench`/`Shibuya`.
- **Requirements, Dataset & Checklists:**
  - [`urban-safety-scenarios.md`](../requirements/urban-safety-scenarios.md) & [`technology-candidates.md`](../requirements/technology-candidates.md): ánh xạ rõ 5 module đang hoạt động trên Edge so với 9 nhóm backlog và điều kiện đánh giá `RF-DETR` / `ViTPose` / `Jetson Orin NX`.
  - [`video-datasets.md`](../datasets/video-datasets.md): phân tách rõ quy tắc ODD 720p–1080p CCTV tĩnh, bảng phân loại trung thực các clip cục bộ hiện có và danh sách nguồn CCTV cố định ứng viên cho cổng `G2`.
  - [`docs/implementation-checklists/`](../implementation-checklists/README.md), [`reports/2026-10-21-pipeline-benchmark-report.md`](../reports/2026-10-21-pipeline-benchmark-report.md) và [`.scratch/system-build-slices/`](../../.scratch/system-build-slices/PRD.md): xóa toàn bộ liên kết chết tới `.scratch/system-build/`, bổ sung kiểm tra ranh giới ADR-0005/0006 và cập nhật lệnh kiểm chứng thực tế.
