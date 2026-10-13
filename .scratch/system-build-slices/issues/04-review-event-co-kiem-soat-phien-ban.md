# 04: Review event có kiểm soát phiên bản

Status: ready-for-agent
Execution: done
Owner: Codex (Backend/UI)

**What to build:** Reviewer mở detail, xác nhận/false_positive/resolve qua API và thấy kết quả audit trên demo.

**Blocked by:** [#01: Event synthetic xuất hiện trên dashboard](01-event-synthetic-xuat-hien-tren-dashboard.md), [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md).

## Acceptance criteria

- [x] Hai reviewer cùng expected version có một conflict rõ; UI refetch và chờ thao tác mới.
- [x] Review không sửa AI confidence hoặc bị AI revision reset; unauthorized/invalid transition bị reject.

- [x] Review action lưu viewed event/evidence versions; stale meaningful content conflict; needs_re_review giữ quyết định cũ và bắt buộc explicit reopen trước action mới; correction/reopen có quyền, reason và audit.
- [x] Evidence manifest đổi availability/completeness/integrity kích hoạt re-review đúng semantic; metadata upload trung gian không kích hoạt.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: W01, UI02, S02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-12: Claim implementation scope: versioned reviewer auth, MongoDB review state/audit, conflict/staleness semantics, dashboard actions, and focused tests. Preserve AI event snapshots; review writes remain a separate collection/contract.

- 2026-10-12: Done. Unit suite 22/22 passed; Docker MongoDB 7.0.43 + server HTTP smoke verified concurrent version conflict (one 200/one 409), reviewer auth, valid/invalid transitions, audit, harmless AI revision preservation, and `needs_re_review` on changed severity. Smoke rows were tagged `review-smoke` and removed afterward. Details: [implementation log](../../../docs/logs/2026-10-12-ticket-04.md). Evidence version comparison currently covers versions carried by the event snapshot; standalone evidence manifest lifecycle remains in later evidence tickets.
- 2026-10-12: Follow-up review found a stale `resolve` could clear `needs_re_review`. API now requires explicit `reopen` before any new decision after meaningful content changes; the dashboard exposes only that action while stale. Added a regression test. Execution is partial until #08 provides manifest lifecycle state for availability/completeness/integrity freshness; the earlier Done note is superseded.
- 2026-10-13: Hoàn thành khép nối Ticket #04 cùng #08: `record_evidence()` tự động kích hoạt `needs_re_review = True` khi evidence manifest chuyển sang available/complete trên event đã có quyết định confirmed/reviewed; cập nhật metadata trung gian không kích hoạt re-review. Kiểm chứng qua `tests/test_server_evidence.py`. Execution: `done`. Chi tiết: [evidence dispatch log](../../../docs/logs/2026-10-13-evidence-dispatch.md).
