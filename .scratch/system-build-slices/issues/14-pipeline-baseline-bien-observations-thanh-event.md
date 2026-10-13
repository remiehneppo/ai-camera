# 14: Pipeline baseline biến observations thành event

Status: ready-for-agent
Execution: done
Owner: Edge / AI Pipeline

**What to build:** Observation metadata đi qua feature factory và pure IncidentEngine để event xuất hiện trên dashboard có pipeline provenance.

**Blocked by:** [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md); [#07: Event pin được clip pre/post từ ring](07-event-pin-duoc-clip-pre-post-tu-ring.md); [#13: Native tracks có time và session semantics](13-native-tracks-co-time-va-session-semantics.md).

## Acceptance criteria

- [x] Per-camera/session/pipeline state riêng, chia sẻ perception tương thích; synthetic fixture chưa coi là person-down quality.
- [x] Queue/deadline/cancel bounded; slow consumer không chặn recorder, valid events không drop như frames.

- [x] Consumer chỉ nhận PerceptionPipeline observations; event commit gắn durable pin request và full snapshot/origin theo contract.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: O01, O02, I01, C03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-13: Hoàn thành implementation qua `PerceptionPipeline` (`apps/edge/pipeline.py`), tích hợp `OracleDetector` -> `ByteTracker` -> `IncidentEngine` -> `FileRecorder` -> `EventOutbox` -> `EdgeUploader`. Event commit tuân thủ `domain.event_contract.validate_event`, origin `"live"`, taxonomy `"person_fall"`, gắn evidence request onset `[-10s, +20s]`, pin ring buffer và enqueue outbox nguyên tử. Đã nghiệm thu end-to-end với server upload và dashboard hiển thị clip qua `tests/test_rtsp_pipeline.py`.
