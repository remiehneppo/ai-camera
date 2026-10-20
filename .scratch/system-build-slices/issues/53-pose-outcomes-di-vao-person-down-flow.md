# 53: Pose outcomes đi vào person-down flow

Status: ready-for-agent
Execution: not-started
Owner: Edge/Domain/ML + QA/Backend/UI theo lát cắt; chưa claim.

**What to build:** Nối outcomes thực của pose scheduler vào IncidentEngine/person-down bằng lát cắt software-lab có fixtures xác định: observation đúng frame/track/session → rule decision hoặc unknown/degraded → durable event/detail/evidence → review. Đây là follow-up integration; không reopen hoặc đổi Status/Execution lịch sử #24 done.

**Blocked by:** [#14](14-pipeline-baseline-bien-observations-thanh-event.md); [#22](22-pose-request-tra-keypoints-dung-frame-va-track.md); [#24](24-pose-scheduling-va-degradation-co-coverage.md).

## Acceptance criteria

- [ ] Chứng minh pose scheduled/attempted/skipped/failed/stale đến domain qua đường chạy thực, không chỉ counter của scheduler; kết quả đúng temporal/frame/track dùng được, stale/missing/failed không thành keypoints hợp lệ hoặc negative.
- [ ] Fixtures integration deterministic cho success, gap/reset, overload/fairness/recovery; đối chiếu expected observations/outcomes với event/detail thật. Dùng các artifact lab đã pin/cleared, không tải weights hoặc lấy dữ liệu chưa duyệt.
- [ ] Fall có onset, persistent lying thiếu onset và on-vehicle có regression không suppress; evidence giữ anchor onset/first qualifying observation baseline, không đổi sang alert-condition.
- [ ] Ghi report coverage scheduled/attempted/skipped/failed/stale tại consumer thật trong workload lab xác định; không gọi số này là accuracy hoặc capacity target. Video/pose thật và các ca unknown được đối chiếu riêng khỏi fault fixtures.
- [ ] Fixture → runner → journal/server → detail/review và raw clip có IDs/provenance khớp; không tạo framework scheduler mới hoặc sửa semantics đã ký ngoài scope.

## External inputs và chuyển ready

Phạm vi ready-for-agent chỉ integration/fixture software đã specified và artifact lab hiện có. ML/QA phải cung cấp held-out/ODD/quality targets và Edge actual workload trước G2/capacity; chưa có thì ghi blocked/not-run cho các gate đó, không coi ticket integration là chất lượng production. Nếu artifact lab không truy cập được, báo needs-info với artifact thiếu cụ thể thay vì bịa pose.

## Release boundary

Ticket này không tự ký production/field acceptance. Giữ activation person-down G2 → vehicle G4b → nhóm mở rộng; đây không là hard chain cho việc implement/integration hoặc dependency ngược vào #49. Candidate chỉ gate cho đường chạy thực sự chọn nó.

## Traceability

[requirement](../../../docs/requirements/urban-safety-scenarios.md): US09 và quality/evidence cho person-down; [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md); [contracts §3](../../../docs/architecture/contracts.md); [index đối chiếu](../requirements-expansion-index.md). Hard deps là prerequisite lát cắt, không yêu cầu hoàn thành toàn module nguồn.

## Evidence và handoff

Ghi command/fixture/video thật, expected/actual, source/model/data/config/build/SDK hashes, observation/event/request/manifest IDs và review versions. Unit/mock hoặc synthetic chỉ chứng minh integration, không thay held-out/ODD/quality hoặc actual hardware proof. Không tự điền số recall/FP/latency/camera/FPS, không stage hay ghi runtime done từ việc publish ticket. Report gate thiếu dữ liệu là blocked/not-run.

## Comments

- 2026-10-20: Publish T3 đã duyệt; chưa claim/implement/test. Giữ lịch sử và Status/Execution #01–52 nguyên ngoài scope update riêng.
