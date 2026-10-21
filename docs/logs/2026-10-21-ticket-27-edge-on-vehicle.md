# Ticket #27 — Edge on-vehicle association + danger override (2026-10-21)

## Phạm vi

Lát cắt edge cho `person_on_stationary_vehicle`:

- `apps/edge/incident.py`: nhánh association người nằm trên xe đã stationary/upright từ trước,
  hạ ưu tiên review nhưng **không suppress**; danger override cho falling onset và xe đổ/lật.
- `apps/edge/pipeline.py`: cho phép emit/validate `person_on_stationary_vehicle`, giữ
  `severity=low`, `anchor_kind=first_qualifying_observation`, thêm metadata `vehicle_track_id`.
- `tests/test_tracking_incident.py`: regression test edge-level cho các nhánh trên.

Không đổi contract event/evidence (taxonomy/severity là payload tự do; anchor kind đã có sẵn
`first_qualifying_observation`). Server review priority, notification và dataset export thuộc
lát cắt server/QA tương ứng (#42/#44), không nằm trong log này.

## Quyết định

1. **Snapshot association tại thời điểm bắt đầu lying bout.** `_TrackIncidentState` giữ
   `lie_start_time`, `on_vehicle_track_id`, `vehicle_danger`. Xe phải có
   `stationary_since < lie_start_time` và window ổn định tối thiểu
   (`vehicle_stable_duration=1.0s` hoặc `vehicle_min_stable_frames=2`). Xe đến sau, xe còn chạy,
   hoặc xe không upright tại onset → không association.
2. **Association 2D có uncertainty**: IoU > `vehicle_overlap_iou=0.1` hoặc tâm/điểm đáy người
   nằm trong bbox xe. Không dùng overlap để suppress.
3. **Danger override**:
   - Falling onset (nhánh `in_fall_candidate` hiện hữu) giữ `person_fall` / `critical` / `onset`;
     on-vehicle không thể hạ ưu tiên nhánh này.
   - Xe 2 bánh đổ/lật (`aspect_ratio >= 1.2` hoặc `>= 1.15` kèm `aspect_ratio_change >= 0.35`
     trong 1.5s), xe mất stationarity/upright sau onset, hoặc người không còn nằm trên xe →
     `person_lying_persistent` với `persistent_lying_severity` (mặc định `high`), không có
     `vehicle_track_id`.
4. **Gap an toàn**: `observation_gap()` xoá toàn bộ `_vehicle_states`; gap/clock jump per-vehicle
   restart stable window thay vì bắc cầu stationarity trước gap. Missing observation không được
   đọc là negative.
5. **Anchor/severity**: on-vehicle dùng `first_qualifying_observation` + `anchor_time =
   state.first_qualifying_time`; pipeline giữ `severity=low` và evidence request pre10/post20
   quanh anchor đó.

## Kiểm chứng (chạy thật)

```bash
.venv-oracle/bin/python -m pytest tests/test_tracking_incident.py tests/test_pose_outcomes_flow.py -q
# 44 passed, 5 warnings

.venv-oracle/bin/python -m pytest tests/test_tracking_incident.py \
  tests/test_pose_outcomes_flow.py tests/test_on_vehicle_flow.py -q
# 50 passed, 6 subtests passed

.venv-oracle/bin/python -m mypy apps/edge/incident.py apps/edge/pipeline.py --ignore-missing-imports
# Success: no issues found in 2 source files

.venv-oracle/bin/python -m pytest -q
# 471 passed, 118 subtests passed in 113.83s
```

Coverage mới trong `tests/test_tracking_incident.py`: on-vehicle low + `vehicle_track_id`;
falling onset trên xe đỗ vẫn `person_fall/critical`; xe đổ sẵn không hạ ưu tiên; xe chạy/đến sau
không association; xe lật sau onset kích hoạt danger override; pipeline emit event low và
`validate_event` pass (evidence anchor `first_qualifying_observation`).

`tests/test_on_vehicle_flow.py` (lát cắt QA) chạy pass trên implementation này, gồm cả flow
pipeline → outbox → server ingest → review → dataset export.

## Giới hạn / chưa chạy

- Toàn bộ là software lab với fixture deterministic; chưa phải bằng chứng hardware, ODD, field
  hay capacity. Association dựa trên bbox 2D nên còn nhiễu; low priority là routing review,
  không phải kết luận ngủ/bất tỉnh và không phải suppression.
- Chưa có ngưỡng/notification policy do stakeholder ký; lab chỉ đảm bảo event vẫn được lưu/review.
- Góc camera thấp/gần ngang vẫn cần ODD `degraded` theo kiến trúc, chưa đo trong log này.
