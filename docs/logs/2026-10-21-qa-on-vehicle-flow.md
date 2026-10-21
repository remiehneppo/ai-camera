# Ticket #27 — QA integration flow cho on-vehicle (2026-10-21)

## Phạm vi

Integration test suite cho lát cắt #27 trong `tests/test_on_vehicle_flow.py` (6 test):
association `on_vehicle` chỉ hạ ưu tiên chứ không suppress, danger override giữ ưu tiên bình thường,
và flow pipeline → outbox → server ingest → review → dataset export.

Fixture là frame/track deterministic trong software lab; không phải bằng chứng hardware, ODD,
field hay production capacity.

## Kịch bản

1. `test_on_vehicle_stationary_upright_emits_low_severity` — xe máy đỗ thẳng, người nằm chồng lên:
   vẫn emit `person_on_stationary_vehicle`, `severity=low`, anchor `first_qualifying_observation`,
   `vehicle_track_id` được giữ; bbox IoU thực sự > ngưỡng nên không phải suppress do overlap.
2. `test_danger_override_falling_onset_with_vehicle` — người đứng rồi hạ nhanh trên xe đỗ:
   `person_fall`, `severity=critical`, `anchor_kind=onset`, không có `vehicle_track_id`.
3. `test_danger_override_fallen_vehicle` — xe đã đổ (AR 3.5) và xe lật sau onset:
   cả hai đều `person_lying_persistent`, `severity=high`, không có `vehicle_track_id`.
4. `test_late_or_moving_vehicle_not_on_vehicle` — xe xuất hiện sau khi người đã nằm, và xe còn
   chạy rồi mới dừng đè lên người: không association, emit `person_lying_persistent` high.
5. `test_observation_gap_resets_vehicle_and_person_continuity` — `observation_gap()` xoá
   `_vehicle_states` và reset track state; gap timestamp > `max_observation_gap` không tái sử dụng
   vehicle state cũ và không trigger sớm; window lying được tính lại từ sau gap.
6. `test_e2e_pipeline_to_outbox_server_review_and_dataset_export` — `PerceptionPipeline` +
   `EventOutbox` sinh event low; POST `/v1/events` nhận receipt; GET `/v1/events` (và filter
   `severity=low`, `taxonomy=...`) trả `review_priority=low`; review `confirm` ghi audit low;
   export dataset (có/không filter taxonomy) giữ lineage, taxonomy, severity, review_priority.

## Kiểm chứng

```bash
.venv-oracle/bin/python -m pytest tests/test_on_vehicle_flow.py -v
# 6 passed, 6 subtests passed in 0.82s

.venv-oracle/bin/python -m pytest \
  tests/test_on_vehicle_flow.py tests/test_tracking_incident.py \
  tests/test_review_priority.py tests/test_pose_outcomes_flow.py -q
# 56 passed, 6 subtests passed in 4.63s
```

Mongo lab dùng qua `tests/test_server_evidence.server_env` (`192.168.96.2:27017`, replica set),
database tạm theo `uuid4` và drop trong cleanup.

## Ghi chú / giới hạn

- Test gap timestamp cho reconnect không có vehicle observation trong frame đầu, nên
  `_update_vehicle_states` prune state xe cũ. Nếu xe được observe lại ngay trong frame sau gap,
  `_VehicleState.stationary_since` hiện vẫn có thể sống qua gap (chỉ `observation_gap()` clear
  `_vehicle_states`); đây là điểm cần siết nếu muốn “gap luôn phá stationarity” ở mọi path.
- Chưa đo association quality/ODD thực địa; chưa có notification consumer thật (lab outbox
  `ineligible`).
