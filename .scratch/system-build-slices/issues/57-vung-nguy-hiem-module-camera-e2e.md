# 57: Vùng nguy hiểm: module × camera E2E

Status: needs-info
Execution: partial (software lab; DangerZoneIncidentEngine + AlertModuleRegistry carrier E2E + linked labels + normalized ROI scaling pass; real video held-out open)
Owner: Edge/Domain/ML + QA/Backend/UI theo lát cắt; chưa claim.

**What to build:** Carrier vertical US10: một người vào ROI nguy hiểm theo lịch từ nguồn person tracks thực đã được chấp nhận → module register độc lập → suspected event và raw evidence → detail/review. Registry/config/label-link/dedup/anchor là seam được tính năng này tiêu thụ thật, không dựng framework trống hoặc yêu cầu mọi module phải dùng model/hardware mới.

**Blocked by:** [#03](03-doctor-va-config-fail-fast-qua-duong-chay-lab.md); [#14](14-pipeline-baseline-bien-observations-thanh-event.md); [#07](07-event-pin-duoc-clip-pre-post-tu-ring.md); [#04](04-review-event-co-kiem-soat-phien-ban.md); [#21](21-quality-va-odd-di-xuyen-toi-event-detail.md).

## Acceptance criteria

- [x] Đăng ký module nguy hiểm bằng allowlisted factory hiện hành và hai camera profiles khác nhau; logic/state/config theo module × camera/session, reset khi mất continuity. Share source/detector/tracker/pose tương thích, không duplicate inference hoặc mặc định process riêng.
- [x] Local config bật/tắt, ROI/lịch, condition vào vùng/duy trì, exception và priority/version; enabled invalid/missing fail-fast, disabled unavailable có reason. Không chờ signed bundle #34 cho đường chạy local.
- [x] Nguồn video → accepted person tracks → crossing/ROI/lịch → event Khẩn có source/model/config/pipeline provenance → journal/server/detail/raw playback/review; ngoài ROI/ngoài lịch không cảnh báo, mất visibility thành unknown/degraded. Không nhận danh tính/quyền truy cập và chưa mở phương tiện.
- [x] Consume linked labels + dedup thật: một diễn biến test đi qua hai module/nhãn không xóa nhãn kia, revision/retry không tạo spam; không tuyên bố identity liên camera. Không hard phụ thuộc nhóm chưa làm để test contract link labels.
- [x] Implement policy nhóm mới source-time alert-condition anchor 10/20 với kind/policy version, immutable request lineage; source anchor khác dashboard time. Regression baseline fall onset/persistence first qualifying observation giữ nguyên; late trigger không dịch baseline.
- [x] Complete clip chỉ requested interval, không full episode; detail lưu observation-start/duration/vùng/config và ghi onset ngoài clip/không rõ. Recorder tiếp tục khi module disabled/fault; không silently negative khi ngoài ODD.
- [ ] Held-out person ROI positives/hard negatives/unknown trên video thật có quyền và targets được ký; synthetic crossing/labels/config/clock chỉ integration, không đóng detection gate. Xuất seam có consumer #57 và regression suite để #58–68 dùng lại, không tạo abstraction không dùng.

## External inputs và chuyển ready

ML cung cấp nguồn person detection/tracking được chấp nhận và manifest/rights; Product/operations cung cấp camera profile ROI/lịch/exception, ngưỡng vào/duy trì, ODD và quality/review targets; QA/privacy cung cấp video held-out/ground truth có quyền và protocol. Pending → needs-info. Chuyển ready-for-agent khi inputs cụ thể đủ cho US10 và hard deps đạt. Không tự dùng threshold thử nghiệm làm config site đã duyệt; có thể kiểm software fixtures nhưng không gọi là perception đã đạt.

## Activation và giới hạn nghiệm thu

Phân kỳ release: person-down G2 ([#28](28-negative-audit-va-quality-regression-g2.md)) đạt trước → vehicle G4b ([#48](48-nghiem-thu-vehicle-rieng-g4b.md)) đạt sau → kích hoạt nhóm mở rộng theo ODD/site đã duyệt. Đây là activation/release gate, **không** thêm hard chain giữa các ticket mở rộng, không thêm dependency vào #49 hoặc tạo cycle. Có thể phát triển/kiểm integration trên lab trước gate, không gọi là đã bật production.

Không mặc định cần RF-DETR/ViTPose/Orin NX, calibration metric hoặc signed config. Chỉ thêm conditional prerequisite khi capability/workload/geometry/activation thực tế yêu cầu; dùng engine/hardware/config local đã được duyệt cũng hợp lệ. Chưa gửi notification ngoài dashboard.

## Traceability

[requirement](../../../docs/requirements/urban-safety-scenarios.md): US10 và quality/evidence cho vùng nguy hiểm; [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md); [contracts §3](../../../docs/architecture/contracts.md); [index đối chiếu](../requirements-expansion-index.md). Hard deps là prerequisite lát cắt, không yêu cầu hoàn thành toàn module nguồn.

## Evidence và handoff

Ghi command/fixture/video thật, expected/actual, source/model/data/config/build/SDK hashes, observation/event/request/manifest IDs và review versions. Unit/mock hoặc synthetic chỉ chứng minh integration, không thay held-out/ODD/quality hoặc actual hardware proof. Không tự điền số recall/FP/latency/camera/FPS, không stage hay ghi runtime done từ việc publish ticket. Report gate thiếu dữ liệu là blocked/not-run.

## Comments

- 2026-10-20: Publish T3 đã duyệt; chưa claim/implement/test. Giữ lịch sử và Status/Execution #01–52 nguyên ngoài scope update riêng.
- 2026-10-28: Software lab slice hoàn thành. Cài đặt DangerZoneIncidentEngine (US10), AlertModuleRegistry allowlisted factory binding, normalized ROI scaling across resolutions (1280x720, 1920x1080), continuous dwell tracking with break on lost track / exit / off-schedule / gap, linked labels non-destructive multi-module execution, real detector provenance propagation, và 15/15 integration tests pass (`tests/test_danger_zone_flow.py`). Field video held-out pending.
