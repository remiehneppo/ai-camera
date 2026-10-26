# Triển khai Hoàn tất Ticket #47: Vehicle Motion & Suspected-Incident Flow (US08) — 2026-10-27

Thực hiện theo lựa chọn Hướng 3 (Trục nghiệp vụ xe và va chạm US08) của người dùng:
Triển khai toàn bộ Task M01, M02, và I06 thuộc Ticket #47 (`.scratch/system-build-slices/issues/47-vehicle-motion-va-suspected-incident-flow.md`).

## 1. Xuất phát điểm
- HEAD: `d2543af`, 714 tests pass.
- Ticket #47 là lát cắt nghiệp vụ đầu tiên mở rộng ngoài person-down, nhắm tới tình huống an toàn đô thị US08 (tai nạn có xe tham gia).
- Q36: Nhóm mới sử dụng neo nguồn thời gian mốc đủ điều kiện cảnh báo (`evidence_anchor_kind = "alert_condition"`) với khoảng trích xuất raw cố định [-10s, +20s].

## 2. Chi tiết triển khai

### A. domain/evidence_contract.py
- Mở rộng `validate_evidence_request` tại dòng 35 cho phép `evidence_anchor_kind` nhận giá trị `"alert_condition"` (bên cạnh `"onset"`, `"first_qualifying_observation"`, `"synthetic"`).
- Bảo đảm interval bất biến: `requested_start = anchor - 10`, `requested_end = anchor + 20`, `policy_version = "lab-pre10-post20-v1"`.

### B. domain/vehicle_motion.py (Tasks M01 & M02)
- Module domain thuần túy, 0 phụ thuộc I/O hay framework ngoài.
- `KinematicState`: Dataclass bất biến chứa vị trí `(cx, cy)`, vận tốc `(vx, vy)`, tốc độ scalar `speed`, vector gia tốc `(ax, ay)`, gia tốc tiếp tuyến có dấu `acceleration` (`< 0` biểu thị phanh/hạ tốc), `scalar_acceleration`, góc hướng `heading` (radian trong `[-pi, pi]`), và cờ `is_stationary`.
- `KinematicsTracker`: Bộ làm mịn quỹ đạo và phái sinh thời gian thực thích ứng:
  - Miễn dịch với biến thiên thời gian thực `dt`, jitter mili-giây, và track gap (`> max_observation_gap`). Không tự sinh gia tốc giả khi có gap hoặc jitter.
  - Tự động reset bộ đệm khi đổi epoch hoặc đứt quãng phiên quan sát.
  - Quan sát dự đoán (`is_predicted=True`) ngoại suy vị trí theo vận tốc cũ với gia tốc bằng 0.
- `compute_pairwise_risk` & `PairwiseInteractionRisk`: Tính toán tương tác cặp vật thể trong không gian ảnh 2D:
  - Khoảng cách, vector vị trí/vận tốc tương đối, tốc độ thu hẹp (closing speed), IoU của bounding box và tốc độ giãn nở IoU (expansion rate).
  - Phân loại 4 mức rủi ro TTC: `"none"`, `"low"`, `"high"`, `"critical"`.
  - Tuân thủ nghiêm ngặt nguyên tắc: TTC hay IoU riêng lẻ tuyệt đối KHÔNG chứng minh va chạm (`is_collision_proven` luôn là `False`).
- `check_collision_evidence`: Nhận diện chữ ký động học va chạm thực tế (gia tốc giảm đột ngột vượt ngưỡng, dừng xe sau va chạm hoặc lệch hướng đột ngột).

### C. apps/edge/vehicle_incident.py (Task I06)
- `VehicleIncidentEngine`: Engine cảnh báo sự cố phương tiện độc lập theo module × camera (factory `"vehicle_incident"`), hoàn toàn tách rời `apps/edge/incident.py`.
- Nhận diện phương tiện (`car`, `motorcycle`, `bicycle`, `bus`, `truck`) và người đi bộ trong vùng lòng đường (`point_in_polygon`).
- Triển khai đủ 3 nhánh US08:
  1. `vehicle_vehicle`: Hai xe chuyển động hội tụ kèm phanh gấp, dừng lại sau va chạm hoặc lệch hướng.
  2. `vehicle_pedestrian`: Xe và người đi bộ hội tụ ở cự ly gần kèm giảm tốc đột ngột hoặc người ngã/chấn động.
  3. `vehicle_rollover_or_barrier`: Xe tự ngã/lật (đảo tỉ lệ khung hình của xe hai bánh hoặc ô tô lật) hoặc đâm vật cản/dải phân cách dừng đột ngột.
- Loại trừ triệt để 4 hard negatives:
  1. Dừng đèn đỏ / kẹt xe: giảm tốc êm vào trạng thái đứng thẳng, không có xung va chạm.
  2. Near-miss: hai xe hội tụ với tốc độ cao nhưng lướt qua nhau êm đềm, không dừng lại hay va đập.
  3. Chồng lấn phối cảnh: bounding box overlap từ xa do góc nhìn camera nhưng không có vận tốc hội tụ hay biến đổi chuyển động.
  4. Xe đứng yên từ trước: không tự suy thành tai nạn.
- Tạo snapshot sự kiện chuẩn qua `domain.event_contract.validate_event`:
  - `pipeline_id`: `"vehicle-incident-pipeline-v1"`
  - `pipeline_version`: `"1"`
  - `payload["taxonomy"]`: `"vehicle_incident"`
  - `payload["interaction_type"]`: `"vehicle_vehicle"` | `"vehicle_pedestrian"` | `"vehicle_rollover_or_barrier"`
  - `payload["severity"]`: `"critical"` hoặc `"high"`
  - `payload["evidence_requests"]` neo `evidence_anchor_kind = "alert_condition"`.

## 3. Bằng chứng kiểm thử và nghiệm thu
- `mypy domain/evidence_contract.py domain/vehicle_motion.py apps/edge/vehicle_incident.py tests/test_vehicle_incident_flow.py` ⇒ **Success: no issues found in 4 source files**.
- `pytest -v tests/test_vehicle_incident_flow.py` ⇒ **23 passed in 0.03s**.
- Toàn bộ Test Suite toàn dự án:
  `pytest -q` ⇒ **737 passed, 126 subtests passed** trong 154.21s (0 regression, +23 tests mới so với 714).
