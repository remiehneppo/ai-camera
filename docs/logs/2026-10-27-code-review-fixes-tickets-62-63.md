# Code Review Fixes (#62 & #63) — 2026-10-27

Xử lý triệt để toàn bộ các phát hiện từ đợt Code Review hai trục (Standards & Spec) trên các tính năng nhận diện Edge #62 và #63 (commit `a0a9d8e`).

## 1. Trục Standards (Coding Standards & Fowler Smells)

| # | Phát hiện | Khắc phục | File tác động |
|---|---|---|---|
| 1 | **Duplicated Code**: Thuật toán ray-casting `point_in_polygon` bị sao chép nguyên văn ở 4 file edge khác nhau. | Tạo module hình học dùng chung `apps/edge/geometry.py` và tái sử dụng ở toàn bộ các engine (`incident.py`, `vehicle_incident.py`, `parking_incident.py`, `crowd_incident.py`). | `apps/edge/geometry.py`, `apps/edge/*.py` |
| 2 | **Data Clumps**: Phương thức `_create_event` trong `crowd_incident.py` nhận tới 9 tham số rời rạc. | Đóng gói thành dataclass `CrowdEventContext`. | `apps/edge/crowd_incident.py` |
| 3 | **ODD Quality State**: Mặc định `quality_state="nominal"` khiến `odd_supported` trả về `None`. | Đặt mặc định chuẩn `quality_state="normal"` để khung hình bình thường được xác thực ODD hợp lệ. | `apps/edge/parking_incident.py`, `apps/edge/crowd_incident.py` |

## 2. Trục Spec (Correctness & Invariant Validation)

| # | Phát hiện | Khắc phục | File tác động |
|---|---|---|---|
| 1 | **Zero-history Stationarity**: Frame đầu tiên hoặc ngay sau track gap bị giả định là đứng yên (`is_stationary=True`). | Bỏ giả định frame 0: frame đầu tiên chỉ khởi tạo mốc vị trí, bắt buộc có ít nhất 2 frame quan sát để tính toán vận tốc trước khi bắt đầu tích lũy `dwell_seconds`. | `apps/edge/parking_incident.py` |
| 2 | **Unused Exceptions**: Tham số `exceptions` được lưu nhưng không kiểm tra. | Bổ sung kiểm tra `exceptions` ở cả 2 engine: xe có giấy phép/ngoại lệ hợp lệ (`permit_*`, `all`) không bị tính đỗ sai; hàng đợi xe buýt/điểm trung chuyển có đăng ký ngoại lệ không bị báo tụ tập đông người. | `apps/edge/parking_incident.py`, `apps/edge/crowd_incident.py` |
| 3 | **Frozen Historical Anchor**: Cảnh báo đông người lặp lại sau cooldown bị đóng băng mốc neo `anchor` ở thời điểm quá khứ xa. | Khi cảnh báo lặp lại sau cooldown, mốc neo cập nhật về thời điểm thỏa mãn điều kiện hiện tại (`ts`). | `apps/edge/crowd_incident.py` |
| 4 | **Tiêu chí nghiệm thu hiện trường**: Checkbox held-out video và bản quyền bị tích `[x]` quá sớm khi mới chạy synthetic lab. | Cập nhật `Execution: partial (software lab ...; real video held-out open)` và giữ `[ ]` cho các tiêu chí ODD/field data theo đúng quy định kỷ luật dự án. | `.scratch/system-build-slices/issues/62-*.md`, `63-*.md` |

## 3. Bằng chứng kiểm thử sau sửa đổi
- `mypy` sạch trên toàn bộ 7 file nguồn/test liên quan:
  `mypy apps/edge/geometry.py apps/edge/incident.py apps/edge/vehicle_incident.py apps/edge/parking_incident.py apps/edge/crowd_incident.py tests/test_parking_incident_flow.py tests/test_crowd_incident_flow.py`
  ⇒ **Success: no issues found in 7 source files**.
- Toàn bộ Test Suite toàn dự án:
  `pytest -q` ⇒ **823 passed, 360 warnings, 126 subtests passed in 142.26s** (0 regressions, +2 tests mới).
