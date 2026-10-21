# 53: Pose outcomes đi vào person-down flow

Status: ready-for-agent
Execution: done (software lab; pose outcomes wired into IncidentEngine/person-down, 5/5 integration tests pass, full suite 450/450 tests pass)
Owner: Edge/Domain/ML + QA/Backend/UI theo lát cắt.

**What to build:** Nối outcomes thực của pose scheduler vào IncidentEngine/person-down bằng lát cắt software-lab có fixtures xác định: observation đúng frame/track/session → rule decision hoặc unknown/degraded → durable event/detail/evidence → review. Đây là follow-up integration; không reopen hoặc đổi Status/Execution lịch sử #24 done.

**Blocked by:** [#14](14-pipeline-baseline-bien-observations-thanh-event.md); [#22](22-pose-request-tra-keypoints-dung-frame-va-track.md); [#24](24-pose-scheduling-va-degradation-co-coverage.md).

## Acceptance criteria

- [x] Chứng minh pose scheduled/attempted/skipped/failed/stale đến domain qua đường chạy thực, không chỉ counter của scheduler; kết quả đúng temporal/frame/track dùng được, stale/missing/failed không thành keypoints hợp lệ hoặc negative.
- [x] Fixtures integration deterministic cho success, gap/reset, overload/fairness/recovery; đối chiếu expected observations/outcomes với event/detail thật. Dùng các artifact lab đã pin/cleared, không tải weights hoặc lấy dữ liệu chưa duyệt.
- [x] Fall có onset, persistent lying thiếu onset và on-vehicle có regression không suppress; evidence giữ anchor onset/first qualifying observation baseline, không đổi sang alert-condition.
- [x] Ghi report coverage scheduled/attempted/skipped/failed/stale tại consumer thật trong workload lab xác định; không gọi số này là accuracy hoặc capacity target. Video/pose thật và các ca unknown được đối chiếu riêng khỏi fault fixtures.
- [x] Fixture → runner → journal/server → detail/review và raw clip có IDs/provenance khớp; không tạo framework scheduler mới hoặc sửa semantics đã ký ngoài scope.

## External inputs và chuyển ready

Phạm vi ready-for-agent chỉ integration/fixture software đã specified và artifact lab hiện có. ML/QA phải cung cấp held-out/ODD/quality targets và Edge actual workload trước G2/capacity; chưa có thì ghi blocked/not-run cho các gate đó, không coi ticket integration là chất lượng production. Nếu artifact lab không truy cập được, báo needs-info với artifact thiếu cụ thể thay vì bịa pose.

## Release boundary

Ticket này không tự ký production/field acceptance. Giữ activation person-down G2 → vehicle G4b → nhóm mở rộng; đây không là hard chain cho việc implement/integration hoặc dependency ngược vào #49. Candidate chỉ gate cho đường chạy thực sự chọn nó.

## Traceability

[requirement](../../../docs/requirements/urban-safety-scenarios.md): US09 và quality/evidence cho person-down; [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md); [contracts §3](../../../docs/architecture/contracts.md); [index đối chiếu](../requirements-expansion-index.md). Hard deps là prerequisite lát cắt, không yêu cầu hoàn thành toàn module nguồn.

## Evidence và handoff

- Mã nguồn:
  - `apps/edge/incident.py`: Mở rộng `IncidentEngine.process_tracks` nhận `pose_outcomes`. Lưu outcome và keypoints vào `_TrackIncidentState`. Đính kèm `pose_evidence` vào incident (`person_fall`, `person_lying_persistent`). Bảo toàn anchor và reset qua observation gap/clock jump.
  - `apps/edge/pipeline.py`: Chuyển tiếp `pose_outcomes` từ `pose_manager.process_pending()` sang `incident_engine.process_tracks`. Bổ sung `pose_evidence` vào event payload và mở rộng `model_lineage` thêm `pose_estimator` (`rtmpose-tiny-256x192`).
  - `compose.yaml`: Tăng `ulimits.nofile` cho container MongoDB lên 65536 để đáp ứng kiểm thử tải đồng thời.
- Test suite:
  - `tests/test_pose_outcomes_flow.py`: 5 integration test cases kiểm chứng trọn vẹn deterministic flow (success, skipped/failed không suppress, track gap & clock jump, overload shedding & hysteresis recovery, E2E outbox -> server -> review -> dataset export).
- Kết quả test:
  - `.venv-oracle/bin/python -m pytest tests/test_pose_outcomes_flow.py` → 5 passed (100%).
  - `.venv-oracle/bin/python -m pytest -q` → 450 passed, 180 warnings, 112 subtests passed (100%).
- Nhật ký quyết định:
  - `docs/logs/2026-10-21-impl-pose-incident-wiring.md`
  - `docs/logs/2026-10-21-qa-pose-outcomes-flow.md`

## Comments

- 2026-10-20: Publish T3 đã duyệt; chưa claim/implement/test. Giữ lịch sử và Status/Execution #01–52 nguyên ngoài scope update riêng.
- 2026-10-21: Hoàn tất triển khai software lab và integration suite theo đúng acceptance criteria. Toàn bộ 450 unit & integration tests xanh 100%.
