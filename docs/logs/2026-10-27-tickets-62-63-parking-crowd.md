# Triển khai Hoàn tất Ticket #62 (Đỗ xe sai vùng/giờ US05) và Ticket #63 (Đông người & Gây rối US06) — 2026-10-27

Triển khai hai tính năng nhận diện trọng điểm trên Edge theo yêu cầu của người dùng:
- Ticket #62: Đỗ xe sai vùng/giờ & thời gian dừng đỗ (`.scratch/system-build-slices/issues/62-do-xe-sai-vung-gio-den-review.md` / US05 trong `docs/requirements/urban-safety-scenarios.md`).
- Ticket #63: Tập trung đông người & nghi ngờ gây rối trật tự (`.scratch/system-build-slices/issues/63-dong-nguoi-va-nghi-gay-roi-den-review.md` / US06 trong `docs/requirements/urban-safety-scenarios.md`).

## 1. Xuất phát điểm
- HEAD: `0961419`, 774 tests pass.
- Đã đăng ký thêm 2 factory được phê duyệt trong `domain/alert_module_config.py`: `ALLOWLISTED_FACTORIES = frozenset({"person_down", "vehicle_incident", "danger_zone", "illegal_parking", "crowd_incident"})`.

## 2. Chi tiết triển khai

### A. Ticket #62: Illegal Parking & Dwell Time (US05)
- `apps/edge/parking_incident.py`:
  - `ParkingIncidentEngine` (factory: `"illegal_parking"`): Cấu hình độc lập theo module × camera.
  - Đánh giá các track phương tiện (`"car"`, `"truck"`, `"bus"`, `"motorcycle"`) trong vùng cấm đỗ (`roi_polygon` via `point_in_polygon`) và khung giờ hạn chế (`ScheduleWindow` với các ngày trong tuần và khoảng thời gian `start_second`..`end_second`).
  - Theo dõi thời gian dừng đỗ liên tục (`dwell_seconds`) có bù trừ rung giật phát hiện (jitter tolerance). Khi $T \ge \text{max\_dwell\_seconds}$ (mặc định 30.0s, có thể cấu hình xuống 2.0s trong lab), kích hoạt sự kiện nghi ngờ đỗ xe trái phép.
  - Loại trừ 5 hard negatives:
    1. Xe chạy qua bình thường (tốc độ > ngưỡng dừng).
    2. Dừng chờ đèn đỏ / kẹt xe / xếp hàng theo luồng (xe di chuyển tiếp trước ngưỡng dwell).
    3. Đỗ xe trong khung giờ cho phép ngoài lịch cấm.
    4. Xe đỗ ngoài vùng ROI cấm đỗ.
    5. Đứt quãng quan sát / track gap: reset bộ đếm dwell, không tự suy thời gian dừng qua các khoảng mất dấu.
  - Event snapshot chuẩn hóa theo `domain.event_contract.validate_event`:
    - `pipeline_id`: `"parking-incident-pipeline-v1"`
    - `payload["taxonomy"]`: `"illegal_parking"`
    - `payload["severity"]`: `"low"` hoặc `"medium"` (mặc định Thường theo requirement US05)
    - Neo bằng chứng Q36: `evidence_anchor_kind = "alert_condition"` với khoảng trích xuất [-10s, +20s].
- `tests/test_parking_incident_flow.py`: 22 unit & scenario tests bao phủ toàn diện.

### B. Ticket #63: Crowd Concentration & Suspected Disorder (US06)
- `apps/edge/crowd_incident.py`:
  - `CrowdIncidentEngine` (factory: `"crowd_incident"`): Cấu hình độc lập theo module × camera.
  - Đánh giá các track người đi bộ (`"person"`, `"pedestrian"`) trong vùng ROI quan sát.
  - Phân tách 2 tầng độc lập theo đặc tả US06:
    1. **Tầng 1: Tập trung đông người (`crowd_concentration`)**:
       - Số lượng người trong ROI $N \ge \text{min\_crowd\_count}$ (mặc định 5 người, cấu hình được) duy trì liên tục $T \ge \text{min\_duration\_seconds}$ (mặc định 3.0s).
       - Severity: `"medium"` hoặc `"low"` (mặc định Thường).
    2. **Tầng 2: Nghi ngờ gây rối trật tự (`suspected_disorder`)**:
       - Đám đông có biểu hiện phân tán hoảng loạn (dispersal divergence away from center of mass), xung đột động học vận tốc cao (vận tốc tập thể $\ge 45$ px/s, gia tốc $\ge 60$ px/s$^2$), hoặc biến thiên hướng di chuyển hỗn loạn bất thường ($1 - R \ge 0.6$).
       - Severity: `"high"` (mặc định Cao).
       - Khẳng định: Đám đông tập trung đơn thuần TUYỆT ĐỐI KHÔNG tự động coi là gây rối.
  - Loại trừ 5 hard negatives:
    1. Hàng đợi xe buýt / xếp hàng trật tự: vận tốc thấp, ổn định không kích hoạt gây rối.
    2. Người chạy bộ hoặc vung tay riêng lẻ: một cá nhân không tạo thành tụ tập hay gây rối.
    3. Người đi bộ lướt qua nhau ngắn hạn ($T < \text{min\_duration\_seconds}$): không tạo cảnh báo tụ tập.
    4. Người ngoài vùng ROI: không tính vào ngưỡng đám đông.
    5. Đứt quãng quan sát / track gap: reset bộ đếm thời gian duy trì.
  - Event snapshot chuẩn hóa theo `domain.event_contract.validate_event` với neo Q36 `evidence_anchor_kind = "alert_condition"`.
- `tests/test_crowd_incident_flow.py`: 25 unit & scenario tests bao phủ toàn diện.

## 3. Bằng chứng kiểm thử & Nghiệm thu
- **Mypy**:
  `mypy domain/alert_module_config.py apps/edge/parking_incident.py apps/edge/crowd_incident.py tests/test_parking_incident_flow.py tests/test_crowd_incident_flow.py`
  ⇒ **Success: no issues found in 5 source files**.
- **Pytest (2 module mới)**:
  `pytest tests/test_parking_incident_flow.py tests/test_crowd_incident_flow.py -q`
  ⇒ **47 passed in 0.06s** (22 parking + 25 crowd).
- **Full Workspace Test Suite**:
  `pytest -q`
  ⇒ **821 passed, 360 warnings, 126 subtests passed in 143.04s** (0 regressions, +47 tests mới so với 774).
