# 19: Nghiệm thu vertical slice G1 trên lab

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Reproduce file/live event→clip→server→review và ký report latency/completeness/recovery của lab.

**Blocked by:** [#04: Review event có kiểm soát phiên bản](04-review-event-co-kiem-soat-phien-ban.md); [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md); [#15: Camera RTSP live giữ correlation với recorder](15-camera-rtsp-live-giu-correlation-voi-recorder.md); [#16: Startup/shutdown giữ recorder và state đúng](16-startup-shutdown-giu-recorder-va-state-dung.md); [#17: Health phản ánh khả năng quan sát thực](17-health-phan-anh-kha-nang-quan-sat-thuc.md); [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md).

## Acceptance criteria

- [ ] Case X01–X19 và baseline X27/X31 có manifest/results; browser API thật, metadata trước clip.
- [ ] P95 durable edge commit→render ≤5s trên LAN có sample count/clock uncertainty; không ký AI quality/hardware capacity.

## Traceability

Task nguồn: F06, C05, UI01, R06.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
