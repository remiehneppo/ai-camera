# 56: Actual Orin NX baseline conformance

Status: needs-info
Execution: not-started
Owner: Edge/Domain/ML + QA/Backend/UI theo lát cắt; chưa claim.

**What to build:** Trên một actual Jetson Orin NX SKU đã được giao, reproduce baseline lab bằng một video có quyền: decode/perception → event → ring/raw clip/upload → server playback/review. Đây là portability/conformance dọc trên actual target, không phải ticket capacity thứ hai.

**Blocked by:** [#14](14-pipeline-baseline-bien-observations-thanh-event.md); [#07](07-event-pin-duoc-clip-pre-post-tu-ring.md); [#08](08-upload-evidence-va-phat-lai-tren-detail.md).

**Conditional blockers (chỉ candidate được chọn trên target):** RF-DETR [#54](54-rf-detr-candidate-qua-detection-event-evidence.md); ViTPose [#55](55-vitpose-candidate-qua-pose-event-evidence.md). Không có conditional blocker thì chạy baseline đã duyệt.

## Acceptance criteria

- [ ] Ghi actual module/RAM/carrier/storage/power/OS/JetPack/SDK/runtime và build/artifact/config hashes; không suy SKU hoặc decoder/encoder từ tên Orin NX, không thay bằng workstation x86.
- [ ] Chạy baseline detector/pose đã cleared trên target đã pin; golden/native-oracle observations và event regression giữ source-time, resets, evidence semantics và quality/degraded reasons.
- [ ] Video qua baseline trên device thật tạo event/raw clip, upload, browser playback/review với requested/actual/gaps và provenance đối chiếu; fault unsupported rõ, không fallback âm thầm.
- [ ] Giữ person-down baseline anchor Q36 và recorder/protected pins; không dùng ONNX chạy được làm bằng chứng đủ camera/FPS.
- [ ] Xuất artifact conformance report cho #31 dùng làm prerequisite khi Orin được chọn. Full-load camera/FPS/power/headroom/thermal soak 24–72h và capacity sign-off chỉ thuộc #31; không duplicate report ký capacity ở đây.

## External inputs và chuyển ready

Edge/platform cung cấp actual Orin NX SKU/RAM/carrier/power/storage, quyền truy cập, OS/SDK/build và camera/video profiles; ML/legal cung cấp baseline artifacts/rights cho target; QA cung cấp protocol/tolerances và endpoint server. Hiện chưa có SKU/SDK/workload/rights hoàn chỉnh → needs-info. Chuyển ready-for-agent khi inputs thực đã pin, có thiết bị và hard deps đạt. Nếu chọn RF-DETR chỉ thêm conditional #54; nếu chọn ViTPose chỉ thêm conditional #55. Hai candidate không là blocker baseline mặc định. Không phụ thuộc #31 hoặc #49 để tránh cycle; #31 tiêu thụ conformance này khi target Orin.

## Release boundary

Ticket này không tự ký production/field acceptance. Giữ activation person-down G2 → vehicle G4b → nhóm mở rộng; đây không là hard chain cho việc implement/integration hoặc dependency ngược vào #49. Candidate chỉ gate cho đường chạy thực sự chọn nó.

## Traceability

[requirement](../../../docs/requirements/urban-safety-scenarios.md): cross-cutting target conformance, US09 baseline và quality/evidence trên actual Orin; [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md); [contracts §3](../../../docs/architecture/contracts.md); [index đối chiếu](../requirements-expansion-index.md). Hard deps là prerequisite lát cắt, không yêu cầu hoàn thành toàn module nguồn.

## Evidence và handoff

Ghi command/fixture/video thật, expected/actual, source/model/data/config/build/SDK hashes, observation/event/request/manifest IDs và review versions. Unit/mock hoặc synthetic chỉ chứng minh integration, không thay held-out/ODD/quality hoặc actual hardware proof. Không tự điền số recall/FP/latency/camera/FPS, không stage hay ghi runtime done từ việc publish ticket. Report gate thiếu dữ liệu là blocked/not-run.

## Comments

- 2026-10-20: Publish T3 đã duyệt; chưa claim/implement/test. Giữ lịch sử và Status/Execution #01–52 nguyên ngoài scope update riêng.
