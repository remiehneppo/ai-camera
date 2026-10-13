# 06: Recorder file replay giữ raw ring độc lập

Status: ready-for-agent
Execution: partial
Owner: Codex (Edge recorder/replay baseline); target/hardware acceptance chưa claim.

**What to build:** Chạy recorder từ file cleared theo thời gian nội dung; dừng analytics vẫn query được raw segments và actual ranges.

**Blocked by:** [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md).

## Acceptance criteria

- [x] File replay tạo compressed stream-copy segments có codec/keyframe/PTS/session metadata, queryable raw ring, watermark và actual range; raw không overlay.
- [x] Actual range báo `missing_preroll`, `missing_postroll` và continuity gaps trên metadata segment.
- [ ] Pin/post-roll lifecycle và software recovery có bằng chứng ở #07; RTSP camera test vẫn chưa nghiệm thu.

- [x] Semantic file replay dùng fixed PTS sampling/virtual event time, synchronous consumer backpressure và monotonic watermark; fixture fast/realtime có cùng PTS.
- [ ] Cùng domain outcomes cần analytics consumer; realtime stress/drop/coverage cần runtime workload, hiện chưa có để kiểm.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: V01, R01, C01, C03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-13 docs sync: #51 hardening (`ea3c808`) adds configurable probe timeouts and preserves media on system/unknown failures; software replay CSV measurements show callbacks before EOF in 12/12 runs, not a production memory bound. #06 remains partial: domain outcomes, runtime workload, RTSP and hardware acceptance are unchanged. See [hardening log](../../../docs/logs/2026-10-13-ticket-51-hardening.md).

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
- 2026-10-12: Bổ sung recorder pin registry bền vững cho request ID/owner/interval; cùng request trả receipt cũ, nội dung khác conflict, cleanup giữ segment giao với pin active, release idempotent. Restart recorder vẫn đọc ownership; `pin_status` cập nhật coverage theo segment hiện có. Execution tiếp tục `partial`: chưa có finalized clip/post-roll manifest và reconciliation file/DB crash; RTSP, analytics consumer, realtime workload và hardware chưa nghiệm thu. Chi tiết: [implementation log](../../../docs/logs/2026-10-12-ticket-06.md).

- 2026-10-12 follow-up: User duyệt software lab harness/report và public seams replay/raw coverage, delayed pin/outbox reconciliation. Thêm CLI `apps.edge.replay_lab`, regression sau raw pruning thực và immutable requested interval. Full suite 43/43 pass; semantic traces không thay analytics/domain parity, realtime queue/drop stress hoặc maximum verification/handoff/recovery sizing proof. Execution giữ partial; #08 vẫn blocked. Evidence: [follow-up log](../../../docs/logs/2026-10-12-ticket-06-07-followup.md).

- Follow-up dispatch wave (baseline `162a850`): thêm synchronous ONNX observation-consumer và detector–recorder diagnostic CLI; fast/paced fixture thực cùng 3 observations ×13 detections, raw coverage complete. Lead full suite94/94 và mypy3 changed modules pass. Detector-stage parity không thay domain/event parity, realtime stress hoặc concurrent recorder isolation; Execution vẫn partial. Evidence: [dispatch log](../../../docs/logs/implementation-dispatch-next-wave.md).
- 2026-10-12: Ticket #51 adds a separate `FileRecorder.ingest()` software seam that publishes closed segments and supports truthful pin/post-roll collection during ingest, crash-window reconciliation, and incremental frame timestamp replay. This does not change #06's RTSP/hardware acceptance: #06 remains partial; no RTSP source, recorder/analytics topology, camera reconnect, target performance, or G1 evidence was tested. See [#51](51-live-ring-publish-segments-during-ingest.md) and [ticket #51 implementation log](../../../docs/logs/2026-10-12-ticket-51.md).
- 2026-10-13 runtime isolation wave: Bổ sung `apps/edge/runtime.py` (`EdgeRuntime`) chạy độc lập recorder và ONNX detector worker trên hai process spawn riêng biệt; lỗi khởi tạo analytics, worker chết bất ngờ hoặc SIGKILL không làm dừng recorder; raw segments vẫn được ghi nhận đầy đủ. Socketpair framed JSON bounded không treo khi analytics chết dở chừng; cleanup descendants an toàn qua pidfd; immediate stop an toàn và đóng sạch socket fds. Chế độ realtime pre-EOF bị hoãn sang ticket #52 sau khi chẩn đoán FIFO producer cần khảo sát thêm cơ chế ingest probe; runtime hiện từ chối rõ ràng mode realtime và hoạt động ở fast mode đã kiểm chứng. Toàn bộ full suite 156/156 pass. Execution tiếp tục `partial`: domain parity, full PerceptionPipeline, RTSP và target hardware acceptance vẫn chưa nghiệm thu. Chi tiết: [dispatch log](../../../docs/logs/2026-10-13-runtime-dispatch.md).
