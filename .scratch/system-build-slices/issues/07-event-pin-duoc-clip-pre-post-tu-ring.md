# 07: Event pin được clip pre/post từ ring

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Event synthetic yêu cầu interval và nhận manifest clip có requested/actual ranges, complete hoặc partial.

**Blocked by:** [#01: Event synthetic xuất hiện trên dashboard](01-event-synthetic-xuat-hien-tren-dashboard.md); [#06: Recorder file replay giữ raw ring độc lập](06-recorder-file-replay-giu-raw-ring-doc-lap.md).

## Acceptance criteria

- [ ] Pin ACK atomic với cleanup, overlap/duplicate/release không làm mất segment còn chủ.
- [ ] Pending→temp→fsync file→rename→fsync dir→DB finalize; đủ dữ liệu giữ pre10/post20, gap là partial.

## Traceability

Task nguồn: R02, R03, C03, I01.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
