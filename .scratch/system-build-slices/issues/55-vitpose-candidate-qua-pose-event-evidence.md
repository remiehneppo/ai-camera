# 55: ViTPose candidate qua pose/event/evidence

Status: needs-info
Execution: not-started
Owner: Edge/Domain/ML + QA/Backend/UI theo lát cắt; chưa claim.

**What to build:** Dùng exact ViTPose candidate qua pose request/response thật và consumer #53 đến person-down event/raw evidence/detail/review. Đối chiếu pose baseline trên cùng inputs; không bắt buộc RF-DETR.

**Blocked by:** [#22](22-pose-request-tra-keypoints-dung-frame-va-track.md); [#53](53-pose-outcomes-di-vao-person-down-flow.md).

## Acceptance criteria

- [ ] Pin variant/weights/hash, license code/checkpoint/data, crop/resize/normalization, keypoint order/confidence và runtime; mapping canonical và provenance frame/track/session/deadline rõ.
- [ ] Conformance keypoint semantics/tolerances được phê duyệt; success/failed/stale/skipped/unsupported vào consumer thật, không biến missing thành negative.
- [ ] E2E video/ROI → ViTPose → outcomes consumer #53 → suspected person-down event → raw evidence/detail → review; held-out positives/hard negatives so baseline, có unknown và report event regression.
- [ ] Giữ fairness/coverage/degradation và anchor baseline onset/first qualifying observation 10/20. Không mở lại #22/#24 done hoặc gán pose đơn lẻ là nhận diện ẩu đả/tự gây hại.
- [ ] Không hard dependency RF-DETR #54, Orin #56, calibration metric hoặc signed activation; target khác cần conditional conformance đúng runtime đã chọn.

## External inputs và chuyển ready

ML cung cấp exact ViTPose/artifact/keypoint mapping/export/runtime; legal/privacy cấp quyền weights/data; QA/Product cung cấp held-out/ODD và tolerances/quality targets. Pending → needs-info. Chuyển ready-for-agent sau pin đầy đủ inputs cho candidate, quyền dùng rõ và hard deps đạt. Unit/mocked keypoints chỉ integration, không ký pose/person-down quality hoặc capacity.

## Release boundary

Ticket này không tự ký production/field acceptance. Giữ activation person-down G2 → vehicle G4b → nhóm mở rộng; đây không là hard chain cho việc implement/integration hoặc dependency ngược vào #49. Candidate chỉ gate cho đường chạy thực sự chọn nó.

## Traceability

[requirement](../../../docs/requirements/urban-safety-scenarios.md): US09 và quality/evidence cho person-down; [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md); [contracts §3](../../../docs/architecture/contracts.md); [index đối chiếu](../requirements-expansion-index.md). Hard deps là prerequisite lát cắt, không yêu cầu hoàn thành toàn module nguồn.

## Evidence và handoff

Ghi command/fixture/video thật, expected/actual, source/model/data/config/build/SDK hashes, observation/event/request/manifest IDs và review versions. Unit/mock hoặc synthetic chỉ chứng minh integration, không thay held-out/ODD/quality hoặc actual hardware proof. Không tự điền số recall/FP/latency/camera/FPS, không stage hay ghi runtime done từ việc publish ticket. Report gate thiếu dữ liệu là blocked/not-run.

## Comments

- 2026-10-20: Publish T3 đã duyệt; chưa claim/implement/test. Giữ lịch sử và Status/Execution #01–52 nguyên ngoài scope update riêng.
