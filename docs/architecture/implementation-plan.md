# Kế hoạch triển khai hệ thống AI Camera giao thông

**Cập nhật:** 2026-10-30 · **Nguồn thực thi chi tiết:** [Tracker slices (`.scratch/system-build-slices/PRD.md`)](../../.scratch/system-build-slices/PRD.md).  
Tài liệu này định nghĩa phạm vi kiến trúc, phân ranh trách nhiệm theo tầng mã nguồn thực tế, trạng thái hoàn thành của từng giai đoạn (`P0–P5`) và điều kiện vượt các cổng nghiệm thu (`G0–G5`).

 Nguồn chuẩn liên quan: [Kiến trúc hệ thống](system-architecture.md) · [Hợp đồng tích hợp](contracts.md) · [Mục lục ADR](../adr/README.md) · [Deployment readiness](deployment-readiness.md).

---

## 1. Phạm vi và bất biến kiến trúc

Hệ thống xây dựng luồng khép kín từ nguồn video camera cố định → nhận thức tại biên (perception & tracking) → phát hiện sự kiện nghi ngờ (`Suspected incident`) → ghim và trích xuất clip bằng chứng gốc có provenance → lưu trữ bền vững tại Edge → đồng bộ lên Server → giao diện người trực xác minh (review).

**Năm bất biến không được phá vỡ khi mở rộng tính năng hoặc chuyển đổi phần cứng:**
1. **Ranh giới feature pipeline ([ADR-0001](../adr/0001-feature-pipeline-boundaries.md)):** Mỗi nhóm tình huống sở hữu FSM, ngưỡng thời gian, ROI/lịch/hiệu chuẩn và policy version riêng; chỉ đăng ký qua factory allowlist tĩnh (`ALLOWLISTED_FACTORIES`), chia sẻ chung kết quả detector/tracker/pose tương thích.
2. **Một điểm sở hữu snapshot sự kiện ([ADR-0005](../adr/0005-incident-snapshot-ownership.md)):** Chỉ `apps/edge/snapshot.py` (`build_incident_snapshot`) được phép ghép `SnapshotFacts` của module với `SnapshotContext` của runtime và gọi `validate_event`.
3. **Độc lập của luồng ghi hình và bằng chứng ([ADR-0004](../adr/0004-integration-contracts.md), `contracts.md §3–§4`):** Analytics treo hoặc cấu hình kích hoạt lỗi không được làm đứt segment ring của `FileRecorder`. Clip đã ghim hoặc chưa được Server ACK không bị xóa bởi vòng quay dung lượng hay ngưỡng tự chủ WAN 24 giờ.
4. **Replay dùng chung đường chạy runtime ([ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md)):** Mọi công cụ đánh giá offline (`tools/eval_*.py`) chạy qua `PerceptionPipeline.process_frame` với cấu hình hiệu lực tường minh; không duy trì bản sao logic lắp ghép detector/tracker/incident thứ hai.
5. **Ràng buộc ODD cố định:** Chỉ hỗ trợ và nghiệm thu trên **camera CCTV giao thông gắn cố định, độ phân giải 720p–1080p**. Không hiệu chỉnh thuật toán theo dashcam hoặc video độ phân giải thấp (`< 720p`).

---

## 2. Phân ranh trách nhiệm theo cấu trúc mã nguồn thực tế

| Tầng / Thư mục | Thành phần chính | Trách nhiệm & Ranh giới |
|---|---|---|
| `domain/` | `event_contract.py`, `evidence_contract.py`, `review_contract.py`, `probe_contract.py`, `config_contract.py`, `geometry_contract.py`, `retention_contract.py`, `alert_module_config.py`, `storm_contract.py`, `retrieval_contract.py` | Hợp đồng dữ liệu thuần (pure domain), schema validation, state machines, phân quyền role và quy tắc bất biến; **không** phụ thuộc I/O, framework web hay runtime AI |
| `apps/edge/` (Perception & Features) | `oracle_detector.py` (`YOLOX-Tiny`), `tracker.py` (`ByteTracker`), `pose.py` (`RTMPose-Tiny`), `quality.py`, `pipeline.py`, `snapshot.py`, `incident.py`, `danger_zone.py`, `vehicle_incident.py`, `parking_incident.py`, `crowd_incident.py` | Tiền xử lý/suy luận ONNX, bám vết có cổng nhóm nhãn thô, đánh giá chất lượng ảnh/freeze, điều phối pose có ngân sách, đánh giá 5 nhóm tình huống và phát hành full snapshot hợp lệ |
| `apps/edge/` (Evidence, Delivery & Ops) | `recorder.py`, `evidence.py`, `outbox.py`, `uploader.py`, `config_store.py`, `canary.py`, `health.py`, `probe.py`, `quota.py`, `live_pipeline.py`, `doctor.py` | Segment ring buffer 10 phút, pin/manifest/finalize nguyên tử trên SQLite WAL (`synchronous=FULL`), retry/revision delivery, signed config/rollback HWM, tự chủ WAN, probe vận hành và giám sát dung lượng |
| `apps/server/` | `main.py`, `store.py`, `evidence.py`, `retrieval.py`, `storm_guard.py`, `live_stream.py`, `config.py`, `doctor.py` | FastAPI + MongoDB replica set: idempotent event ingestion, lưu/phát HTTP Range clip bằng chứng, versioned review & audit trail, storm circuit breaker, hàng đợi truy hồi evidence từ Edge và dashboard |
| `tools/` | `eval_clip.py`, `eval_vehicle.py`, `eval_all_scenarios.py`, `run_benchmark.py`, `oracle_conformance.py`, `negative_audit_report.py`, `fetch_*.py` | Replay ngữ nghĩa trên `PerceptionPipeline`, đo thông lượng/độ trễ tham chiếu, kiểm tra conformance ONNX oracle, lấy mẫu negative audit và xác thực SHA-256 tài nguyên |

---

## 3. Trạng thái các giai đoạn triển khai (`P0` → `P5`)

Trạng thái kiểm chứng phần mềm hiện tại: **896 unit & integration tests (`188` subtests) pass**, **`mypy` 72 source files sạch lỗi**.

| Giai đoạn | Mục tiêu cốt lõi | Trạng thái Software Lab (Python/x86) | Phần việc còn mở (Target / Field) |
|---|---|---|---|
| **P0 — Tracer Bullet & Contracts** | Khóa hợp đồng event/evidence/review, doctor fail-fast, outbox retry/revision, FastAPI + MongoDB + dashboard cơ sở | **Hoàn tất** (`#01–#05`) | — |
| **P1 — Perception, Person-down & Durable Evidence** | `YOLOX-Tiny` oracle, `ByteTracker`, `IncidentEngine` (`person_fall`, `person_lying_persistent`), `FileRecorder` ring + pin/finalize + crash recovery + server upload/playback | **Hoàn tất bản tham chiếu Python** (`#06–#09, #11, #13, #14, #16–#20`, ADR-0005/0006) | Native C++ core & conformance (`#10, #12`), live RTSP camera soak (`#15`, `G1`) |
| **P2 — Pose, ODD Quality & Review Workflow** | `RTMPose-Tiny` + scheduler/outcomes, ODD quality/freeze gate, `person_on_stationary_vehicle` ưu tiên review riêng, negative audit workflow | **Hoàn tất bản tham chiếu Python** (`#21–#28, #44, #53`) | Cohort dữ liệu CCTV cố định có nhãn độc lập và ngưỡng nghiệm thu theo site (`#21/#22`, `G2`) |
| **P3 — Target Hardware & Capacity** | Chạy native core + decode thực + recording/upload đồng thời trên phần cứng nhúng đích | **Chưa mở trên phần cứng đích** (`#29–#31`) | Chọn SKU phần cứng đích (ứng viên Jetson Orin NX / SBC), đo conformance + thermal soak 24–72h (`G3`) |
| **P4 — Fleet Trust, Resilience & Retrieval** | Device identity/expiry, signed config activation, canary rollout & HWM rollback, tự chủ WAN 24h, synthetic probe, storm guard, remote evidence retrieval | **Hoàn tất logic & hợp đồng trong lab** (`#32–#42`) | PKI/secret rotation thực tế, power-cut trên thiết bị lab chỉ định và pilot 1 site (`#43`, `G4a`) |
| **P5 — Mở rộng Nhóm Cảnh báo Đô thị** | Mở các feature pipeline ngoài `person_down` với calibration/ROI/schedule độc lập | **Đã hoàn tất 4 module bổ sung trong lab:** `danger_zone` (`#57`), `vehicle_incident` (`#45–#47`), `illegal_parking` (`#62`), `crowd_incident` (`#63`) | Nghiệm thu chất lượng từng nhóm trên CCTV cố định (`#48`, `G4b`); 9 nhóm danh mục còn lại (`#58–#61, #64–#68`) giữ ở backlog chờ dữ liệu/model chuyên biệt |

---

## 4. Lộ trình cổng nghiệm thu (`G0` → `G5`)

Mọi bằng chứng vượt cổng phải đối chiếu với ma trận 45 kịch bản lỗi `X01–X45` trong [checklist tích hợp & release](../../docs/implementation-checklists/integration-release.md). Test đơn vị hoặc replay file trên máy x86 **không** thay thế bằng chứng tại `G1–G5`.

| Gate | Điều kiện bắt buộc để ký vượt cổng | Trạng thái hiện tại |
|---|---|---|
| **G0 — Contract & Conformance** | Schema validation, deterministic fixtures, golden ONNX oracle conformance (`#01, #11`), `mypy` + full test suite xanh | **Đạt cho phạm vi software-lab** *(còn chờ native C++ conformance `#10/#12`)* |
| **G1 — Edge Reliability (Live Stream)** | Luồng RTSP từ camera cố định thật; analytics treo/crash không tạo lỗ hổng ghi hình; pin recovery sau crash process; kiểm chứng sai số clock/latency LAN | **Đang mở** *(chờ kết nối camera CCTV thật và chạy soak `#15`)* |
| **G2 — AI Quality & ODD Sign-off** | Đánh giá trên tập CCTV cố định 720p–1080p held-out có nhãn độc lập (ngày/đêm/mưa + hard negatives); công bố recall, false alerts/camera-day và chi phí review | **Đang mở** *(đã rút các clip dashcam/zoom/reframing khỏi diện ODD; chờ thu thập & gán nhãn cohort CCTV cố định)* |
| **G3 — Target Hardware Capacity** | Đo P95/P99 latency, queue drop, RAM/I/O/storage/nhiệt độ trong 24–72h soak trên đúng SKU phần cứng đích khi bật đồng thời decode + AI + recorder + upload | **Đang mở** *(chưa khóa SKU phần cứng triển khai)* |
| **G4a — Pilot Readiness (Baseline)** | Vượt `G1–G3` cho `person_down`; kiểm thử mất WAN/drain backlog, quota đầy đĩa, signed config rollback, storm guard, power-cut có chủ đích và clearance pháp lý/quyền dữ liệu | **Đang mở** |
| **G4b — Feature Expansion Gate** | Từng module mở rộng (`danger_zone`, `vehicle_incident`, `illegal_parking`, `crowd_incident`, ...) đạt hiệu chuẩn hình học/ROI, `G2` riêng và không làm vượt ngân sách tải `G3` | **Đang mở** |
| **G5 — Field Pilot Sign-off** | Vận hành thực địa ổn định với người trực thật, báo cáo negative audit định kỳ, xác nhận chi phí review và chữ ký nghiệm thu của chủ bài toán | **Đang mở** |

---

## 5. Quyết định kiến trúc đã khóa và các ADR còn mở trước Pilot

- **Đã khóa (`accepted`):** [ADR-0001](../adr/0001-feature-pipeline-boundaries.md) (ranh giới feature pipeline), [ADR-0002](../adr/0002-server-downstream-event-publishing.md) (server downstream intent), [ADR-0003](../adr/0003-fastapi-mongodb-backend.md) (FastAPI + MongoDB replica set), [ADR-0004](../adr/0004-integration-contracts.md) (hợp đồng tích hợp), [ADR-0005](../adr/0005-incident-snapshot-ownership.md) (tập trung snapshot sự kiện), [ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md) (semantic replay dùng chung pipeline).
- **Cần mở ADR mới khi có dữ liệu thực tế trước Pilot:**
  1. **Camera Stream Ownership ADR:** Chốt phương án đọc RTSP độc lập giữa Recorder và Analytics (dual-stream main/sub hoặc local RTSP relay) dựa trên số phiên đồng thời thực tế của SKU camera.
  2. **Target Hardware & Execution Boundary ADR:** Chốt SKU phần cứng biên (ví dụ Jetson Orin NX / TensorRT hoặc ARM SBC / ONNX-RKNN) và quyết định giữ in-process hay tách tiến trình native perception sau khi đo crash/soak thực tế.
  3. **Production Topology, Security & Licensing Clearance:** Chốt HA cho MongoDB/object storage, PKI phát hành khóa ký cấu hình, chính sách lưu trữ dữ liệu cá nhân theo site và giấy phép thương mại cho trọng số mô hình.
