# 38: Native crash recovery đạt RTO

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Inject native segfault/hang/restart loop, analytics reset session và recorder tiếp tục trong fault boundary.

**Blocked by:** [#16: Startup/shutdown giữ recorder và state đúng](16-startup-shutdown-giu-recorder-va-state-dung.md); [#17: Health phản ánh khả năng quan sát thực](17-health-phan-anh-kha-nang-quan-sat-thuc.md); [#31: Capacity target dưới record/upload/pose load](31-capacity-target-duoi-record-upload-pose-load.md).

## Acceptance criteria

- [ ] Fault không healthy, stale results bị reject, RTO/gaps đo theo signed target.
- [ ] Chỉ mở ADR/process isolation nếu evidence cần; nếu đổi IPC rerun semantic/timeout/restart/capacity, không mặc định shared memory.

## Traceability

Task nguồn: T06, R06, O02.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
