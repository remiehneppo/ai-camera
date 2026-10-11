# 37: Power-cut kiểm chứng local durability

Status: ready-for-human
Execution: not-started
Owner: QA/operations + Edge; chưa claim.

**What to build:** Cắt điện BOM lab tại commit/temp/rename/checkpoint rồi recover và đối chiếu IDs/hashes.

**Blocked by:** [#09: Khôi phục event/evidence sau process crash](09-khoi-phuc-event-evidence-sau-process-crash.md); [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md); [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md).

## Acceptance criteria

- [ ] Protocol lab/hardware/restore được owner thống nhất; power-cut thật, kill-9 không thay bằng chứng.
- [ ] Committed metadata/finalized clips có report RPO/RTO/gaps và storage flush/media assumptions; target chưa có giữ blocked.

## Traceability

Task nguồn: J05, R03, J01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Cần người vận hành thiết bị lab, BOM/storage thật, protocol cắt điện/khôi phục và RPO/RTO được thống nhất; agent hỗ trợ harness/đối chiếu, không tự thao tác nguồn điện.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
