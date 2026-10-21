# Nhật ký Đồng bộ Tài liệu theo Tiến độ Code Hiện tại — 2026-10-21

## 1. Bối cảnh và mục tiêu

Sau các đợt hoàn thiện mã nguồn và kiểm thử gần nhất:
- Commit `e10e642` giải quyết dứt điểm các lỗi phát hiện qua review (P1 reset quality/freeze khi có gap hoặc đổi session; P2 chữ ký SHA-256 chính xác cho freeze detection; P2 đính kèm quality cho stale frames; P2 phản ánh lỗi operational fault HTTP 413 lên `EdgeHealthMonitor`; P2 sửa lỗi xác thực và định dạng dữ liệu trong test review API; P3 cập nhật test cadence của cooldown ngã). Toàn bộ 445 test cases trong repository đã đạt xanh 100%.
- Bổ sung bộ công cụ tải dữ liệu mẫu giám sát đô thị 1080p chuẩn mở (`tools/fetch_benchmark_dataset.py`, `data/benchmark/manifest.json`).
- Xây dựng công cụ benchmark tự động (`tools/run_benchmark.py`) và thực thi đo đạc hiệu năng thực tế trên 2 kịch bản video 1080p (`shibuya_crossing_1080p.mp4` và `intersection_traffic_1080p.mp4`), ghi nhận báo cáo chi tiết tại `docs/reports/2026-10-21-pipeline-benchmark-report.md`.

Yêu cầu: Đồng bộ toàn bộ tài liệu kiến trúc, hồ sơ lab, deployment readiness, README và tracker slices để phản ánh trung thực, đầy đủ tiến độ mã nguồn hiện có.

## 2. Các tài liệu đã đồng bộ

### 2.1. `README.md` (root)
- **Cập nhật tổng quan các lát cắt software lab:** Liệt kê đầy đủ các module đã hoàn thiện trong lab phần mềm:
  - Synthetic event/dashboard (#01), hồ sơ lab/protocol (#02), review API có kiểm soát phiên bản và audit/re-review triggers (#04), retry/revision delivery (#05), file recorder/replay (#06), pinned evidence (#07), server evidence upload/playback (#08), khôi phục crash (#09), ONNX detector oracle (#11), Python ByteTracker với time/session semantics (#13), end-to-end perception pipeline baseline (#14), live runner (#15 partial), startup/shutdown state (#16), health monitor với operational fault (#17), storage quota protection (#18), dataset feedback lineage (#20), ODD image quality assessment và freeze detection (#21 partial), RTMPose-Tiny pose estimation (#22), track gap và clock jump handling (#23 partial), pose scheduling và degradation (#24), person fall detection (#25), persistent lying (#26).
  - Phân định rõ: Native C++ acceleration (#10/#12), camera hardware RTSP field validation, và production target deployment acceptance (G3–G5) vẫn là các gate đang mở.
- **Bổ sung mục Benchmark Dataset & Pipeline Performance Suite:**
  - Hướng dẫn lệnh tải dataset: `python3 tools/fetch_benchmark_dataset.py`.
  - Hướng dẫn lệnh chạy benchmark tự động: `.venv-oracle/bin/python tools/run_benchmark.py --max-frames 120 --sample-fps 10.0`.
  - Tóm tắt kết quả đo đạc thực tế: Baseline đạt **16.35 – 20.10 FPS** (P50 latency 44.8 – 56.3 ms); Full Pipeline kèm RTMPose đạt **8.84 – 10.56 FPS** (~3.7 – 3.8 ms/người); RAM 266 – 530 MB. Dẫn link tới báo cáo đầy đủ `docs/reports/2026-10-21-pipeline-benchmark-report.md`.
- **Cập nhật mục Kiểm tra (Checks):** Hướng dẫn chạy trọn bộ 445 unit & integration tests với pytest (`.venv-oracle/bin/python -m pytest -q`).

### 2.2. `docs/README.md`
- Cập nhật bảng tra cứu tài liệu: Thêm dòng tham chiếu [Báo cáo Benchmark Pipeline](../reports/2026-10-21-pipeline-benchmark-report.md).
- Cập nhật dòng tham chiếu tracker: Ghi nhận cả PRD thực thi và [Index mở rộng](../../.scratch/system-build-slices/requirements-expansion-index.md).

### 2.3. `docs/architecture/lab-profile.md`
- **Bổ sung mục Thử nghiệm và Benchmark Dataset Thực tế (2026-10-21):**
  - Ghi nhận bộ video 1080p chuẩn mở tại `data/benchmark/` (Shibuya 87.9 MB, Intersection 42.2 MB) cùng mã băm SHA-256 và bản quyền CC BY-SA 4.0.
  - Ghi nhận số liệu đo đạc thông lượng FPS, P50 latency và bộ nhớ RAM đỉnh trên CPU x86 i5-12400F.
  - Cập nhật trạng thái test suite phần mềm đạt **445 passed** (100% test xanh).
  - Khẳng định ranh giới: Số liệu x86 làm tham chiếu kỹ thuật, không thay thế cho target capacity G3 trên Jetson Orin NX thật.

### 2.4. `docs/architecture/deployment-readiness.md`
- Thêm ghi chú tham chiếu kết quả benchmark sơ bộ trên workstation x86 vào mục Sizing & Benchmark.
- Tái khẳng định quy tắc: Kết quả đo đạc phần mềm trên x86 là bằng chứng thông lượng pipeline, nhưng benchmark trên actual hardware SKU (Jetson Orin NX) và thermal soak 24–72h vẫn là gate bắt buộc trước khi ký capacity.

### 2.5. Tracker `.scratch/system-build-slices/PRD.md` và các Issue liên quan
- **Cập nhật bảng tiến độ PRD.md:**
  - Ticket #04: Cập nhật thành `done (software lab; review API, audit trail, re-review reasons, 38/38 tests pass)`.
  - Ticket #21: Cập nhật thành `partial (software lab; ODD assess_quality, low-light/glare/blur/freeze SHA-256, contract validation, 14/14 tests pass)`.
  - Ticket #23: Cập nhật thành `partial (software lab; ByteTracker max_gap, IncidentEngine gap & clock jump reset, 9/9 tests pass)`.
  - Bổ sung dòng Ticket #52 (`partial`) và ghi chú dẫn tới Index mở rộng #53–#68.
  - Cập nhật phần tóm tắt snapshot tiến độ ở đầu trang.
- **Cập nhật trực tiếp `issues/21` và `issues/23`:**
  - `issues/21`: Đổi `Execution: partial`, tích các tiêu chí đã hoàn thành (SHA-256 freeze detection, tri-state `odd_supported`, versioned policy, recovery reasons, contract validation, dashboard UI), giữ mở native C++ và camera-moved; thêm comment ngày 2026-10-21.
  - `issues/23`: Đổi `Execution: partial`, tích tiêu chí xử lý gap và clock jump trong `ByteTracker` và `IncidentEngine` (9 tests pass), giữ mở báo cáo ODD fragmentation; thêm comment ngày 2026-10-21.

## 3. Xác minh tính nhất quán và kiểm tra

- `git diff --check`: Không có lỗi định dạng hay khoảng trắng thừa.
- Liên kết Markdown giữa các tài liệu được kiểm tra hợp lệ.
- Toàn bộ test suite:
  ```text
  445 passed, 176 warnings, 112 subtests passed in 113.63s
  ```
- Không làm thay đổi logic mã nguồn, không vi phạm các ranh giới hợp đồng kiến trúc.
