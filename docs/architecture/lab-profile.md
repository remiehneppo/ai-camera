# Hồ sơ phòng lab và protocol kiểm thử

**Cập nhật:** 2026-10-30 · **Trạng thái:** Hồ sơ thực tế của workstation phát triển & kiểm chứng phần mềm tham chiếu; chưa phải hồ sơ phần cứng nhúng tại hiện trường.

---

## 1. Cấu hình máy trạm Lab hiện tại (Probed Workstation Facts)

| Hạng mục | Thông số thực tế trên máy Lab | Giới hạn suy diễn |
|---|---|---|
| **Hệ điều hành / Kernel** | Ubuntu Linux `x86_64`, kernel `7.0.0-38-generic` | Không đại diện cho Linux for Tegra (JetPack) hoặc BSP ARM nhúng |
| **CPU / RAM** | `Intel Core i5-12400F` (6 nhân / 12 luồng), `31 GiB` RAM | Chỉ dùng làm mốc tham chiếu phần mềm CPU; không dùng ký capacity thiết bị biên |
| **GPU trên máy trạm** | `NVIDIA GeForce RTX 5060 Ti` (`16 GiB`, driver `595.84`) | Các bài test conformance và benchmark phần mềm hiện chạy trên `CPUExecutionProvider` để giữ tính tất định |
| **Runtime Python ghim cố định** | `.venv-oracle`: Python `3.12.3`, `onnxruntime 1.20.1` (CPU), `numpy 1.26.4`, `opencv-python-headless 4.10.0.84` | Đã khóa SHA-256 cho `YOLOX-Tiny` và `RTMPose-Tiny` manifests |
| **Dịch vụ Backend Lab** | FastAPI + MongoDB `7.0.43` (1-node replica set qua Docker Compose, hỗ trợ ACID transactions & `$setWindowFields`) | Topology phát triển cục bộ; không phải cụm HA sản xuất |
| **Độ phủ kiểm thử tự động** | **896 unit & integration tests** (`188` subtests) pass; **`mypy` 72 source files** không lỗi | Kiểm chứng hợp đồng, logic 5 module Edge, snapshot, semantic replay, SQLite WAL, signed config, WAN outage và review API |

---

## 2. Kết quả đo tham chiếu trong Software Lab

1. **ONNX Oracle Conformance (`#11`, [log](../logs/2026-10-12-ticket-11.md)):**
   - Manifest và attribution lưu tại `models/yolox-tiny/`, golden fixtures tại `fixtures/oracle/`. Kiểm chứng tiền xử lý BGR thô và hậu xử lý NMS khớp tất định trên `CPUExecutionProvider`.
2. **Thông lượng Pipeline trên CPU x86 (`tools/run_benchmark.py`, [báo cáo](../reports/2026-10-21-pipeline-benchmark-report.md)):**
   - Đo trên 2 clip đô thị 1080p chẩn đoán (`shibuya_crossing_1080p.mp4`, `intersection_traffic_1080p.mp4` — **chỉ dùng đo tải tính toán, không thuộc cohort ODD cố định**):
   - **Baseline (`YOLOX-Tiny` + `ByteTrack` + `IncidentEngine` + `FileRecorder`):** `16.35 – 20.10 FPS` (P50 `44.79 – 56.25 ms`, RSS đỉnh `266.7 – 334.9 MB`).
   - **Full Pipeline + `RTMPose-Tiny` (17 keypoints SimCC):** `8.84 – 15.88 FPS` tùy mật độ người (chi phí `RTMPose-Tiny` P50 `3.73 – 4.11 ms/người`, RSS đỉnh `519.8 – 530.7 MB`).
3. **Replay đa kịch bản trước camera thật ([log 2026-10-30](../logs/2026-10-30-pre-camera-dataset-replay.md)):**
   - Cả 3 công cụ `tools/eval_clip.py`, `tools/eval_vehicle.py`, `tools/eval_all_scenarios.py` đều chạy qua `PerceptionPipeline.process_frame` ([ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md)) và `apps/edge/snapshot.py` ([ADR-0005](../adr/0005-incident-snapshot-ownership.md)).
   - Đã hoàn tất replay 17 clip cục bộ, phát hiện và vá triệt để lỗi gán nhầm nhãn xuyên lớp đối tượng trong `ByteTracker` cũng như lỗi gom cụm không gian trong `CrowdIncidentEngine` ([chi tiết truy vết `fall_0005`](../logs/2026-10-30-fall-0005-anomaly-trace.md)).

---

## 3. Ranh giới giữa Tham số mục tiêu (Preliminary Targets) và Nghiệm thu

| Hạng mục | Cấu hình / Mục tiêu hiện tại | Điều kiện để được ký nghiệm thu |
|---|---|---|
| **ODD Camera** | Camera giao thông gắn cố định ngoài trời, `1280×720` đến `1920×1080` | Xác minh thực tế góc lắp, chiều cao pixel người tối thiểu và độ ổn định nền của từng camera |
| **Cửa sổ Evidence** | Ring `10 phút`; `pre-roll 10s`, `post-roll 20s`; giữ clip server `7 ngày`; ngân sách mất WAN `24 giờ` | Đo với bitrate/GOP thực và tần suất sự kiện thực tại site; không xóa clip chưa ACK khi quá 24 giờ |
| **Chính sách Anchor (`contracts.md §3`)** | `person_down`: `onset` hoặc `first_qualifying_observation`; 4 module còn lại: `alert_condition` | Phân biệt rạch ròi `evidence_anchor_kind` và `policy_version`; clip 30s không đồng nghĩa bao phủ toàn bộ sự kiện kéo dài |
| **Độ trễ LAN tới Dashboard** | Mục tiêu sơ bộ P95 `≤ 5 giây` từ lúc commit event bền vững tại Edge tới khi hiển thị trên Dashboard | Chỉ ký khi có đồng bộ đồng hồ (NTP/PTP), đo sai số clock và kiểm chứng trình duyệt thực ở `G1` |
| **Ứng viên nâng cấp phần cứng/mô hình** | `RF-DETR`, `ViTPose`, `NVIDIA Jetson Orin NX` ([chi tiết](../requirements/technology-candidates.md)) | Hiện là ứng viên đánh giá; không thay thế baseline `YOLOX-Tiny` + `RTMPose-Tiny` cho tới khi vượt conformance + `G2` + `G3` |

---

## 4. Protocol tối thiểu cho mỗi đợt chạy kiểm chứng (`G1` → `G4`)

Trước mỗi lần chạy nghiệm thu, bắt buộc ghi nhận mã commit, cấu hình OS/SDK/runtime, mã băm SHA-256 của model/config/dataset, phiên bản schema/policy và người chịu trách nhiệm khôi phục.

| Kịch bản kiểm thử | Thao tác thực hiện | Kết quả & Bằng chứng bắt buộc | Gate |
|---|---|---|---|
| **Replay tất định** | Chạy cùng video fixture với cấu hình và thời gian nguồn cố định | Danh sách sự kiện, anchor, snapshot fields và provenance khớp lặp lại 100% | `G0/G1` |
| **Đứt / kết nối lại luồng Camera** | Ngắt và nối lại luồng RTSP từ camera thật | Phát `operational_fault`/degraded rõ ràng, tăng `stream_session_id`, không nối nhầm track cũ, đo chính xác khoảng hở segment | `G1` |
| **Đĩa chậm hoặc chạm trần Quota** | Giả lập đầy quota hoặc lỗi ghi trên phân vùng thử nghiệm | Không ACK giả; clip đã ghim/chưa ACK được bảo toàn; trạng thái lỗi giới hạn và tự phục hồi khi giải phóng | `G1/G4a` |
| **Mất kết nối WAN kéo dài** | Cô lập kết nối Server, tiếp tục phát sinh sự kiện rồi mở lại mạng | Event/evidence bền vững trên SQLite WAL + đĩa, giải tỏa idempotent không trùng/mất sự kiện | `G4a` |
| **Đánh giá Chất lượng AI theo ODD** | Chạy trên tập CCTV cố định 720p–1080p held-out có nhãn độc lập (gồm ngày/đêm/mưa và hard negatives) | Báo cáo đầy đủ mẫu số, recall, false alerts/camera-day, độ trễ phát hiện và khối lượng phút review | `G2` |
| **Hoán đổi Model / Backend suy luận** | Ghim artifact mới, chạy golden conformance và event regression | Bảo toàn hợp đồng ngữ nghĩa và kết quả sự kiện trong ngưỡng dung sai được duyệt | `G1/G2` |
| **Tải toàn hệ thống trên Phần cứng Đích** | Chạy đồng thời decode + 5 module/pipeline được bật + recorder + upload trong 24–72h trên đúng SKU đích | Đạt ngưỡng P95/P99 frame age, 0 lỗi rò rỉ RAM/WAL, không sụt hiệu năng do nhiệt | `G3` |
| **Mất điện đột ngột (Power-cut)** | Chỉ chạy trên thiết bị lab chỉ định đã có bản sao lưu và người trực khôi phục | Tổn thất nằm trong RPO/RTO đã duyệt; startup reconcile dọn sạch file tạm mồ côi mà không hỏng DB | `G4a` |
