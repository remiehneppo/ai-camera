# 42: Downstream delivery theo protocol được bật

Status: needs-info
Execution: not-started
Owner: Backend + Product/operations; chưa claim.

**What to build:** Khi được cho phép, worker phát downstream từ durable intent, retry/audit/assignment/escalation theo human-review protocol.

**Blocked by:** [#27: On-vehicle vẫn review với ưu tiên riêng](27-on-vehicle-van-review-voi-uu-tien-rieng.md); [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md); [#33: Device lifecycle và site access được enforce](33-device-lifecycle-va-site-access-duoc-enforce.md).

## Acceptance criteria

- [ ] Lab default disabled; provider/broker chỉ thêm khi use case chọn, không fake delivered.
- [ ] Synthetic/replay luôn bị chặn; downstream outage không rollback ingestion, provider thiếu dedup ghi residual duplicate risk.

## Traceability

Task nguồn: W02, I04.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Nhánh có điều kiện: lab vẫn dashboard-only. Cần product/operations cho phép bật downstream, chốt destination/provider và human-review protocol; không thêm broker mặc định.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
