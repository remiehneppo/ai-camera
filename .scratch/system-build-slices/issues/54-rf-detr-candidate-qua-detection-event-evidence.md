# 54: RF-DETR candidate qua detection/event/evidence

Status: needs-info
Execution: not-started
Owner: Edge/Domain/ML + QA/Backend/UI theo lát cắt; chưa claim.

**What to build:** Đưa một exact RF-DETR candidate qua adapter detector đang tiêu thụ, canonical observations và một person-down replay kiểm soát đến event/raw evidence/detail/review; đối chiếu baseline detector. Không thay baseline mặc định hoặc xây nhiều backend đồng thời.

**Blocked by:** [#11](11-onnx-oracle-xuat-detection-co-provenance.md); [#14](14-pipeline-baseline-bien-observations-thanh-event.md).

## Acceptance criteria

- [ ] Pin variant/checkpoint/hash, source/license code+weights+dataset, export/runtime/pre-postprocess và class mapping; startup chọn candidate rõ, lỗi unsupported fail-fast, không silent fallback.
- [ ] Golden/native-oracle detector conformance trên positives/hard negatives đã cấp quyền; transforms/source time/track semantics giữ tương thích. Candidate event regression có report so baseline, không lấy inference FPS làm event quality.
- [ ] E2E video → RF observations → feature/module → durable event → requested/actual raw evidence → detail/review; bản không phát hiện cũng có negative audit, không chỉ demo ca đẹp.
- [ ] Giữ baseline person-down onset/first qualifying anchor 10/20; disabled/candidate failure không làm mất recorder và phải báo capability reason.
- [ ] Không hứa hỗ trợ cháy/ngập/action bằng detector người; phạm vi acceptance chỉ capability/class/ODD được chứng minh. Không phụ thuộc hard vào #55 hoặc #56.

## External inputs và chuyển ready

ML cung cấp exact artifact/runtime/export và mapping được duyệt; pháp chế/privacy xác nhận quyền code/weights/data; QA/Product cung cấp held-out/ODD/tolerances và targets event regression. Hiện pending nên needs-info. Chuyển ready-for-agent khi inputs cho candidate cụ thể đủ và hard deps đạt; không chọn checkpoint/license hộ chủ dự án. Hardware capacity/field quality là gate riêng #31/#28, không kết quả của export chạy được.

## Release boundary

Ticket này không tự ký production/field acceptance. Giữ activation person-down G2 → vehicle G4b → nhóm mở rộng; đây không là hard chain cho việc implement/integration hoặc dependency ngược vào #49. Candidate chỉ gate cho đường chạy thực sự chọn nó.

## Traceability

[requirement](../../../docs/requirements/urban-safety-scenarios.md): US09 và quality/evidence cho person-down; [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md); [contracts §3](../../../docs/architecture/contracts.md); [index đối chiếu](../requirements-expansion-index.md). Hard deps là prerequisite lát cắt, không yêu cầu hoàn thành toàn module nguồn.

## Evidence và handoff

Ghi command/fixture/video thật, expected/actual, source/model/data/config/build/SDK hashes, observation/event/request/manifest IDs và review versions. Unit/mock hoặc synthetic chỉ chứng minh integration, không thay held-out/ODD/quality hoặc actual hardware proof. Không tự điền số recall/FP/latency/camera/FPS, không stage hay ghi runtime done từ việc publish ticket. Report gate thiếu dữ liệu là blocked/not-run.

## Comments

- 2026-10-20: Publish T3 đã duyệt; chưa claim/implement/test. Giữ lịch sử và Status/Execution #01–52 nguyên ngoài scope update riêng.
