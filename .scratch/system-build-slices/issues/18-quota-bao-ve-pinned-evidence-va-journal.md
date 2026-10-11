# 18: Quota bảo vệ pinned evidence và journal

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Khi disk áp lực, hệ thống cleanup dữ liệu eligible rồi báo degraded/partial cho clip mới mà không xóa unACK.

**Blocked by:** [#09: Khôi phục event/evidence sau process crash](09-khoi-phuc-event-evidence-sau-process-crash.md); [#17: Health phản ánh khả năng quan sát thực](17-health-phan-anh-kha-nang-quan-sat-thuc.md).

## Acceptance criteria

- [ ] Quotas tính pins/postroll/temp/proxy/WAL/reserve; disk95/100/write/fsync/checkpoint errors có test.
- [ ] State reserve hết thì không commit/ACK giả; outage24h không là TTL xóa protected evidence.

## Traceability

Task nguồn: R04, J01, R05, F03.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
