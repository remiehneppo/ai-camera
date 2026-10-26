# 47: Vehicle motion và suspected-incident flow

Status: ready-for-agent
Execution: done (software lab; M01 kinematics/smoothing + M02 TTC/overlap risk + I06 US08 3 branches & hard negatives rejection pass)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Tracks/time/ground quality thành motion/risk features và vehicle pipeline event vào cùng evidence/review flow.

**Blocked by:** [#14: Pipeline baseline biến observations thành event](14-pipeline-baseline-bien-observations-thanh-event.md); [#07: Event pin được clip pre/post từ ring](07-event-pin-duoc-clip-pre-post-tu-ring.md).

**Conditional blockers (metric geometry):** [#46: Calibration valid đi xuyên tới observations](46-calibration-valid-di-xuyen-toi-observations.md).

**Activation gate:** Vehicle chỉ mở sau G2 person-down; calibration chỉ bắt buộc với nhánh dùng metric geometry.

## Acceptance criteria

- [x] Variable Δt/jitter/gaps/epoch và predicted/measured không tạo acceleration giả.
- [x] Near-miss/red-light stop/jam/crash fixtures; TTC/overlap không proof collision, state độc lập person-down.

## Delta requirement được duyệt — 2026-10-20

- [x] US08 bao phủ xe–xe, xe–người và xe tự ngã/lật/đâm vật cố định, mỗi nhánh có temporal positives/hard negatives; xe đứng yên hoặc người nằm gần xe thiếu diễn biến chỉ là dấu hiệu nguy hiểm/chưa rõ, không tự kết luận va chạm hay trách nhiệm.
- [x] Pipeline vehicle có state/config module × camera độc lập; Q36 nhóm mới lấy source-time mốc đủ điều kiện cảnh báo cho raw pre10/post20, giữ anchor-kind/policy version, request lineage và giới hạn clip; không đổi anchor baseline person-down.
- [x] Chỉ nhánh dùng metric geometry cần #46; nhánh quan sát ảnh vẫn phải chứng minh temporal/quality đủ, không giả metric. Activation vehicle sau G2 person-down; implementation scaffolding/fixtures không phải đã được bật hoặc nghiệm thu.

## Traceability

Task nguồn: M01, M02, I06.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.
- 2026-10-27: Hoàn thành triển khai software lab cho #47.
  `domain/evidence_contract.py`: Cập nhật `validate_evidence_request` cho phép neo `"alert_condition"` theo Q36 (interval cố định anchor - 10s đến anchor + 20s).
  `domain/vehicle_motion.py`: Module domain thuần túy không I/O; `KinematicsTracker` làm mịn quỹ đạo và phái sinh thời gian thực, miễn dịch với biến thiên dt, jitter và track gap; `compute_pairwise_risk` tính toán tốc độ thu hẹp (closing speed), IoU expansion rate, TTC không gian ảnh 2D, và bảo đảm không coi TTC/overlap riêng lẻ là bằng chứng va chạm đã xác định.
  `apps/edge/vehicle_incident.py`: `VehicleIncidentEngine` cấu hình độc lập theo module × camera (factory: `"vehicle_incident"`), bao phủ đủ 3 nhánh US08 (`vehicle_vehicle`, `vehicle_pedestrian`, `vehicle_rollover_or_barrier`), loại bỏ triệt để 4 hard negatives (dừng đèn đỏ, kẹt xe, near-miss, chồng lấn phối cảnh), sinh event snapshot chuẩn qua `validate_event` với Q36 alert-condition anchor.
  Evidence: `pytest tests/test_vehicle_incident_flow.py -v` ⇒ **23 passed**; `mypy` sạch trên cả 4 tệp.