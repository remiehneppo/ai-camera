# Nhật ký Điều phối & Tích hợp Ticket #27 — 2026-10-21

## 1. Mục tiêu và Phạm vi
- **Ticket #27:** On-vehicle vẫn review với ưu tiên riêng (nhánh US09 trong kịch bản person-down).
- **Phân loại độ phức tạp:** L2 (tích hợp xuyên suốt Edge IncidentEngine, PerceptionPipeline, Server Event Store, Review API, Outbox, Dataset Export, Dashboard UI và bộ Integration Test Suite).
- **Mô hình thực thi:** Subagent delegation (`deepseek-official/deepseek-flash`) + Dispatcher review, khắc phục lỗi gap continuity và nghiệm thu toàn diện.

## 2. Phân rã công việc & Điều phối Subagents

### Subagent 1: Triển khai Edge IncidentEngine & PerceptionPipeline (`apps/edge/incident.py`, `apps/edge/pipeline.py`)
- Mở rộng `IncidentEngine`:
  - Theo dõi trạng thái phương tiện 2 bánh (`motorcycle`, `bicycle` và `car`) qua `_VehicleState`: `is_stationary`, `is_upright` (aspect_ratio < 1.15), `is_fallen` (aspect_ratio >= 1.2 hoặc đổi độ nghiêng nhanh >= 0.35).
  - Yêu cầu xe phải đứng yên và đứng thẳng từ trước khi người bắt đầu ngả/nằm (>= 1.0s hoặc 2 frame ổn định).
  - Tính toán association giữa track người và track xe dựa trên IoU (> 0.1) hoặc tâm/chân người nằm trong bounding box xe.
  - Khi người nằm trên xe đỗ đứng thẳng từ trước: phát `taxonomy="person_on_stationary_vehicle"`, `severity="low"`, `anchor_kind="first_qualifying_observation"`, anchor_time = first qualifying time.
  - **Danger Overrides:**
    1. Người có pha falling onset (hạ thấp nhanh / va chạm) qua xe đứng yên → giữ nguyên `person_fall` với `severity="critical"`.
    2. Xe bị đổ/nghiêng (`is_fallen`) hoặc đổ sau khi người nằm → override về `person_lying_persistent` với `severity="high"`.
    3. Xe đến sau hoặc đang di chuyển → không gắn `person_on_stationary_vehicle`, giữ `person_lying_persistent` (`severity="high"`).
    4. Observation gap / clock jump: xóa continuity xe và người, không demote sai.
- Trong `PerceptionPipeline`:
  - Bổ sung `person_on_stationary_vehicle` vào danh sách sự kiện được xử lý và chuyển giao sang outbox.
  - Lưu trữ `vehicle_track_id` vào event payload nếu có association.
  - Bổ sung 6 unit tests trực tiếp vào `tests/test_tracking_incident.py`.

### Subagent 2: Server Review Queue Prioritization & Low-Severity Handling (`apps/server/store.py`, `main.py`, `dataset.py`, `export_dataset.py`, `static/index.html`)
- `apps/server/store.py`:
  - Thêm `LOW_PRIORITY_TAXONOMIES = frozenset({"person_on_stationary_vehicle"})`.
  - Hàm `review_priority_for(payload)`: phân loại `urgent` (high/critical - danger override), `low` (on-vehicle hoặc low severity), và `standard`.
  - `list_current`: hỗ trợ query filter theo `severity` và `taxonomy`, trả về `review_priority` cho từng row.
  - Outbox lab insert: lưu trữ `taxonomy`, `severity`, `review_priority`, giữ `eligibility="ineligible"` (không phát sinh notification khẩn trong lab).
  - `record_review`: lưu trữ audit trail và review state đầy đủ (`reviewed_taxonomy`, `reviewed_severity`, `reviewed_review_priority`).
- `apps/server/main.py`:
  - Endpoint `/v1/events` và `/v1/dataset/export` hỗ trợ query parameters `severity` và `taxonomy` có validation chặt chẽ (422 khi giá trị không hợp lệ).
- `apps/server/static/index.html`:
  - Hiển thị badge `On-vehicle (Low priority)` (`badge-priority-low`) và badge `Emergency priority` / `Standard priority` cho từng thẻ sự kiện.
- Viết mới bộ test `tests/test_review_priority.py` (6 tests).

### Subagent 3: Bộ Integration Fixtures & Test Suite E2E (`tests/test_on_vehicle_flow.py`)
- Xây dựng 6 kịch bản kiểm thử toàn diện theo acceptance criteria của Ticket #27:
  1. `test_on_vehicle_stationary_upright_emits_low_severity`: Xe máy đỗ đứng thẳng từ trước + người ngả nằm → phát `person_on_stationary_vehicle` severity `low`, anchor giữ first qualifying observation, không bị suppress vì bbox overlap.
  2. `test_danger_override_falling_onset_with_vehicle`: Người có pha ngã nhanh qua xe đứng yên → danger override phát `person_fall` severity `critical`.
  3. `test_danger_override_fallen_vehicle`: Xe máy bị đổ hoặc lật nghiêng sau khi người nằm → danger override phát `person_lying_persistent` severity `high`.
  4. `test_late_or_moving_vehicle_not_on_vehicle`: Xe máy đến sau khi người đã nằm hoặc xe đang chạy → không gắn on-vehicle, phát `person_lying_persistent` severity `high`.
  5. `test_observation_gap_resets_vehicle_and_person_continuity`: Bước nhảy thời gian hoặc gap xóa bỏ hoàn toàn continuity của cả xe và người.
  6. `test_e2e_pipeline_to_outbox_server_review_and_dataset_export`: Chuỗi E2E từ edge pipeline → outbox → API server `/v1/events` → lọc theo review priority `low` → xác nhận review → xuất dataset `/v1/dataset/export`.

## 3. Hoạt động Review & Sửa lỗi của Dispatcher
- **Khắc phục lỗi Gap Continuity cho Phương tiện trong `apps/edge/incident.py`:**
  - Qua review báo cáo phát hiện từ Subagent 3: Khi có timestamp gap (`ts - last_timestamp > max_observation_gap`) hoặc clock jump (`ts < last_timestamp`), person state được reset nhưng vehicle state trong `_vehicle_states` nếu vẫn xuất hiện cùng track ID ở frame ngay sau gap có thể giữ lại `stationary_since` cũ từ trước gap.
  - Dispatcher đã trực tiếp sửa `apps/edge/incident.py`: phát hiện `gap_or_clock_jump` trong `_update_vehicle_states`, lập tức reset `stationary_since = ts` và `stable_frames = 1` nếu đang đứng yên/thẳng, hoặc xóa nếu không đứng yên. Điều này đảm bảo tính toàn vẹn tuyệt đối của continuity: mọi bước nhảy thời gian đều yêu cầu tích lũy lại thời lượng ổn định từ đầu.

## 4. Kết quả nghiệm thu
- **Kiểm định test suite:**
  - `tests/test_on_vehicle_flow.py`: 6/6 passed (6 subtests passed).
  - `tests/test_review_priority.py`: 6/6 passed.
  - `tests/test_tracking_incident.py`: 36/36 passed.
  - Toàn bộ test suite dự án (`pytest -q`): **471 passed, 204 warnings, 118 subtests passed** trong 114s (100% test xanh).
- **Cập nhật Tracker:**
  - `.scratch/system-build-slices/issues/27-on-vehicle-van-review-voi-uu-tien-rieng.md`: Tích cả 2 tiêu chí acceptance, chuyển `Execution: done (software lab)`.
  - `.scratch/system-build-slices/PRD.md`: Cập nhật bảng và snapshot tiến độ #27 hoàn tất trong software lab.
