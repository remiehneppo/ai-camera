# 01: Event synthetic xuất hiện trên dashboard

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Gửi một event synthetic từ edge lab, lưu event cùng delivery intent bền vững, server commit rồi hiển thị metadata trên demo.

**Blocked by:** None (can start immediately).

## Acceptance criteria

- [ ] Mongo replica set lab có persistent volume và readiness transaction; device auth/schema limits có ngay trong luồng đầu.
- [ ] SQLite event/outbox và Mongo revision/current/downstream intent atomic; receipt chỉ sau commit; synthetic không notification.

## Traceability

Task nguồn: C01, C03, B01, J01, S01, UI01.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
