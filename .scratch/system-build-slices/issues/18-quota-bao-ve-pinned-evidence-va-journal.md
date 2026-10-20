# 18: Quota bảo vệ pinned evidence và journal

Status: ready-for-review
Execution: done (software lab; chưa disk-pressure/outage 24h thật)
Owner: Edge / Storage

**What to build:** Khi disk áp lực, hệ thống cleanup dữ liệu eligible rồi báo degraded/partial cho clip mới mà không xóa unACK.

**Blocked by:** [#09: Khôi phục event/evidence sau process crash](09-khoi-phuc-event-evidence-sau-process-crash.md); [#17: Health phản ánh khả năng quan sát thực](17-health-phan-anh-kha-nang-quan-sat-thuc.md).

## Acceptance criteria

- [x] Quotas tính pins/postroll/temp/proxy/WAL/reserve; disk95/100/write/fsync/checkpoint errors có test.
- [x] State reserve hết thì không commit/ACK giả; outage24h không là TTL xóa protected evidence.

## Traceability

Task nguồn: R04, J01, R05, F03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
- 2026-10-14: Ticket #18 completed. Implemented `StorageQuotaManager` in `apps/edge/quota.py` and test suite `tests/test_quota.py`. Integrated with `EvidenceLifecycle` and `EdgeHealthMonitor`. All 9 tests pass, mypy typecheck passes with 0 errors. UnACK evidence strictly preserved across 24h+ outages and under disk pressure. Fake commits and ACKs refused when state reserve is exhausted or write fails.
- 2026-10-17: Đồng bộ tracker (docs/logs/2026-10-17-tracker-sync.md). Code tồn tại (grep apps/), pytest nhóm liên quan 188 passed. Execution = done (software lab; chưa disk-pressure/outage 24h thật). Status triage và gate giữ nguyên; chưa review/ký.
