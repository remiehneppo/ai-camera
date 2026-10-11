# 03: Doctor và config fail-fast qua đường chạy lab

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Người triển khai kiểm config/artifact rồi start analytics; enabled config sai dừng rõ, disabled có reason và không lộ secrets.

**Blocked by:** [#01: Event synthetic xuất hiện trên dashboard](01-event-synthetic-xuat-hien-tren-dashboard.md).

## Acceptance criteria

- [ ] Allowlisted factories và immutable config hash/provenance; wrong artifact/backend/field làm startup nonzero.
- [ ] Doctor báo capability thực; không silent fallback, recorder độc lập không bị stop vì analytics config sai.

## Traceability

Task nguồn: B01, B02, F05.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
