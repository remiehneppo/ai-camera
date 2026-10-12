# 07: Event pin được clip pre/post từ ring

Status: ready-for-agent
Execution: partial
Owner: Codex — Edge/Domain software file-replay slice; hardware/RTSP acceptance không thuộc lần chạy này.

**What to build:** Event synthetic yêu cầu interval và nhận manifest clip có requested/actual ranges, complete hoặc partial.

**Blocked by:** [#01: Event synthetic xuất hiện trên dashboard](01-event-synthetic-xuat-hien-tren-dashboard.md); [#06: Recorder file replay giữ raw ring độc lập](06-recorder-file-replay-giu-raw-ring-doc-lap.md).

## Acceptance criteria

- [x] Pin ACK atomic với cleanup, overlap/duplicate/release không làm mất segment còn chủ (recorder pin registry, xem #06).
- [x] Software file replay: pending pin intent→clip temp→fsync file→rename→fsync dir→manifest→DB finalize; clip copy/retry orphan recovery; fixture giữ pre10/post20, gap/thiếu range là partial. Hardware power-cut không được suy ra từ software tests.

- [x] Event/outbox/evidence request intent cùng transaction; recorder persist pin owner/receipt trước ACK; duplicate request query lại, khác interval conflict.
- [ ] Pre/post theo onset hoặc first qualifying lying observation; trigger t=15/onset t=0 vẫn yêu cầu [-10,20]. Ring budget bao gồm verification/handoff/recovery; quá budget partial/missing.
- [x] Build finalized, completeness partial và transfer acknowledged cùng tồn tại; request đổi range có ID mới/supersedes, không sửa artifact đã finalized.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Gate còn mở

- Software anchor/partial behavior đã kiểm thử; chưa có proof ring budget maximum verification/handoff/recovery trên runtime/target. #06 vẫn partial (analytics parity/RTSP). Không đóng #07 hoặc mở #08 bằng unit fixture.

## Traceability

Task nguồn: R02, R03, C03, I01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
- 2026-10-12: Hoàn thiện software slice: independent clip stream-copy, atomic intent event/outbox/evidence, EOF durable, retry/recovery file/DB, anchor policy và supersedes, transfer ACK tách completeness. Full suite 37/37 pass, CLI evidence_finalized=1/pending=1. Review đã sửa concat PTS, recovery và failure isolation; giữ Execution partial vì blocker #06 và ring sizing proof chưa đóng. Xem [log](../../../docs/logs/2026-10-12-ticket-07.md).

- 2026-10-12: Implement `FileRecorder.finalize_pin`: manifest bất biến theo request ID ghi atomic (fsync file/dir rồi DB receipt), có requested/actual ranges, gaps/completeness và segment size/SHA-256; pin finalize chỉ khi post-roll đủ, hoặc caller kết thúc partial tường minh. Execution partial: chưa có event/outbox/evidence-intent transaction, pre/post anchor wiring, clip assembly/handoff hoặc orphan reconciliation sau crash. Không chạy test theo chỉ thị phiên làm việc.
