# 07: Event pin được clip pre/post từ ring

Status: ready-for-agent
Execution: partial
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Event synthetic yêu cầu interval và nhận manifest clip có requested/actual ranges, complete hoặc partial.

**Blocked by:** [#01: Event synthetic xuất hiện trên dashboard](01-event-synthetic-xuat-hien-tren-dashboard.md); [#06: Recorder file replay giữ raw ring độc lập](06-recorder-file-replay-giu-raw-ring-doc-lap.md).

## Acceptance criteria

- [x] Pin ACK atomic với cleanup, overlap/duplicate/release không làm mất segment còn chủ (recorder pin registry, xem #06).
- [ ] Pending→temp→fsync file→rename→fsync dir→DB finalize; hiện có atomic finalized manifest, nhưng chưa có clip copy/worker recovery; đủ dữ liệu giữ pre10/post20, gap là partial.

- [ ] Event/outbox/evidence request intent cùng transaction; recorder persist pin owner/receipt trước ACK; duplicate request query lại, khác interval conflict.
- [ ] Pre/post theo onset hoặc first qualifying lying observation; trigger t=15/onset t=0 vẫn yêu cầu [-10,20]. Ring budget bao gồm verification/handoff/recovery; quá budget partial/missing.
- [ ] Build finalized, completeness partial và transfer acknowledged cùng tồn tại; request đổi range có ID mới/supersedes, không sửa artifact đã finalized.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: R02, R03, C03, I01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-12: Implement `FileRecorder.finalize_pin`: manifest bất biến theo request ID ghi atomic (fsync file/dir rồi DB receipt), có requested/actual ranges, gaps/completeness và segment size/SHA-256; pin finalize chỉ khi post-roll đủ, hoặc caller kết thúc partial tường minh. Execution partial: chưa có event/outbox/evidence-intent transaction, pre/post anchor wiring, clip assembly/handoff hoặc orphan reconciliation sau crash. Không chạy test theo chỉ thị phiên làm việc.
