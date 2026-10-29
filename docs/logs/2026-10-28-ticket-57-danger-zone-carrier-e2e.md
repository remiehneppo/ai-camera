# Ticket #57 — Carrier Vertical: Vùng nguy hiểm & Hợp nhất Đa Module E2E — 2026-10-28

> Đây là snapshot triển khai ban đầu tại `fefeeba`: 15 tests chuyên biệt, 859 tests toàn bộ. Các mốc sau là 16/860 tại `f44a442` và 21/865 tại `b66e78c`; không dùng số 859 làm trạng thái mới nhất. Xem [log bổ sung ngày 2026-10-29](2026-10-29-review-fixes-dataset-evaluation-and-label-gates.md) cho sửa review, sửa timestamp evaluator, kết quả dataset đã đính chính và quyết định chờ nhãn đối chứng. Ticket #57 vẫn `partial`, chưa nghiệm thu held-out video.

## 1. Mục tiêu & Phạm vi
- Triển khai **Ticket #57 (US10 — Carrier vertical: module × camera E2E)** để thiết lập seam hợp nhất đa tính năng chuẩn cho toàn bộ các module nhận diện an toàn đô thị (#57–#68).
- Cài đặt `DangerZoneIncidentEngine` (`apps/edge/danger_zone.py`) theo allowlisted factory `"danger_zone"`.
- Hợp nhất điều phối đa module tại `PerceptionPipeline` (`apps/edge/pipeline.py`): chia sẻ một lần giải mã video và suy luận detector/tracker, liên kết nhãn sự kiện độc lập (linked labels), không làm mất hoặc ghi đè sự kiện của module khác.
- Chuẩn hóa ranh giới tọa độ ROI giữa `RegionOfInterest` chuẩn hóa $[0, 1]$ và không gian điểm ảnh pixel trên nhiều độ phân giải (720p, 1080p).
- Bảo toàn tính liên tục thời gian: ngắt kết nối dwell khi mất dấu (lost track/ok_empty), ra khỏi ROI, hoặc ngoài lịch kích hoạt; ngăn chặn đếm gian lận thời gian đứng yên qua khoảng ngắt quãng.
- Đồng bộ thông tin nguồn gốc (provenance): gắn chính xác `model_id`, `model_sha256` và `calibration_version` thực tế của detector vào mọi sự kiện của các module, giữ nguyên định danh module và phiên bản cấu hình riêng (`config_version`).

## 2. Các thay đổi thực hiện

1. **`apps/edge/geometry.py`**:
   - Bổ sung `is_normalized_polygon(polygon)` để kiểm tra polygon có tọa độ chuẩn hóa $[0, 1]$.
   - Bổ sung `scale_roi_to_pixels(polygon, width, height)` để ánh xạ đa giác chuẩn hóa sang tọa độ pixel tương ứng với kích thước khung hình nguồn.

2. **`apps/edge/danger_zone.py` (Mới)**:
   - Cài đặt `DangerZoneIncidentEngine` với factory `"danger_zone"`.
   - Quản lý trạng thái theo dõi `_DangerZoneTrackState`: `first_entered_time`, `last_seen_time`, `consecutive_frames`, `triggered`, `last_alert_time`.
   - `in_roi(track, frame_dimensions)`: Hỗ trợ cả đa giác pixel và đa giác chuẩn hóa $[0, 1]$ qua `frame_dimensions`.
   - `is_in_schedule(timestamp)`: Lọc theo lịch `ScheduleWindow` với múi giờ cấu hình.
   - Khi thỏa mãn điều kiện vào vùng/duy trì: tạo sự kiện đầy đủ (`danger_zone_intrusion`, mức độ nghiêm trọng `critical`), gắn yêu cầu bằng chứng với neo `evidence_anchor_kind = "alert_condition"` khoảng [-10s, +20s] theo hợp đồng Q36.
   - Phá vỡ tính liên tục (break continuity): Khi đối tượng vắng mặt khỏi khung hình hiện tại (`tid not in observed_ids`), rời khỏi ROI hoặc ngoài lịch, lập tức gọi `reset_dwell()` (xóa `first_entered_time`, đặt `consecutive_frames = 0`, bảo tồn `last_alert_time` cho cooldown).

3. **`apps/edge/pipeline.py`**:
   - `create_incident_engine`: Factory khởi tạo cho toàn bộ 5 allowlisted factories (`person_down`, `danger_zone`, `illegal_parking`, `crowd_incident`, `vehicle_incident`).
   - Tích hợp `AlertModuleRegistry` và `module_configs`: Ánh xạ module name tùy biến (ví dụ `zone_north`) sang factory tương ứng và bảo toàn `config_version` riêng của từng module.
   - Hỗ trợ danh sách module rỗng/disabled rõ ràng: Chỉ cài đặt mặc định `IncidentEngine` khi không truyền tham số module nào; khi truyền cấu hình camera mà tất cả module đều bị disable, `incident_engines = []` và không tự ý chạy suy luận không mong muốn.
   - Tự động gắn lineage thực tế của pipeline (`camera_id`, `device_id`, `stream_session_id`, `origin`) và thông tin detector thực tế (`model_lineage`, `model_artifact_hash`, `calibration_version`) vào mọi sự kiện trước khi persist vào `outbox`.
   - Đánh giá chất lượng camera: Tích hợp `assess_capability_quality` khi có `capability_policies`, hoặc kế thừa chất lượng đo đạc của pipeline khi không cấu hình riêng.

4. **`apps/edge/parking_incident.py`, `apps/edge/crowd_incident.py`, `apps/edge/vehicle_incident.py`, `apps/edge/incident.py`**:
   - Hỗ trợ `frame_dimensions` và `is_normalized_polygon` trong kiểm tra `in_roi`.
   - Bổ sung `module_name` vào constructor để lưu vết định danh module đăng ký.

5. **`tests/test_danger_zone_flow.py` (Mới)**:
   - 15 test cases bao phủ toàn diện:
     - Person ngoài ROI $\rightarrow$ 0 alert.
     - Person trong ROI đủ điều kiện $\rightarrow$ Critical alert với neo `alert_condition` [-10s, +20s].
     - Kiểm soát spam bằng `cooldown_seconds`.
     - Lọc theo lịch `ScheduleWindow`.
     - Tọa độ chuẩn hóa $[0, 1]$ đối chiếu chính xác trên cả 720p (1280×720) và 1080p (1920×1080).
     - Regression: Mất dấu (ok_empty/lost track) phá vỡ tính liên tục dwell.
     - Regression: Rời khỏi ROI rồi quay lại khởi động lại dwell từ 0.
     - Regression: Nằm trong ROI lúc ngoài lịch chỉ bắt đầu tính dwell khi lịch kích hoạt.
     - E2E Carrier: Người vào vùng nguy hiểm rồi ngã $\rightarrow$ Cả 2 sự kiện `danger_zone_intrusion` và `person_fall` đều được tạo và lưu trữ bền vững trong `outbox`, không sự kiện nào ghi đè sự kiện kia, session ID khớp hoàn toàn với pipeline.
     - Camera bị disable module $\rightarrow$ không sinh sự kiện và không ghi outbox, bộ ghi video độc lập vẫn hoạt động.
     - Đăng ký module định danh tùy biến `zone_north` với `north-v2.1` qua `AlertModuleRegistry`.
     - Truyền nhận provenance thực tế của detector (`model_id`, `model_sha256`) vào sự kiện.

## 3. Kết quả Kiểm chứng
- `mypy domain/ apps/ tools/ tests/test_danger_zone_flow.py`: **Success: no issues found in 71 source files**.
- `pytest tests/test_danger_zone_flow.py`: **15 passed in 0.60s**.
- Toàn bộ Test Suite dự án: `pytest -q`: **859 passed, 360 warnings, 126 subtests passed in 152.91s** (0 regressions, tăng từ 844 lên 859 tests).

## 4. Trạng thái Còn mở
- Held-out video thực tế cho vùng nguy hiểm (field dataset) cần quyền dữ liệu và ground truth ngoài software lab.
