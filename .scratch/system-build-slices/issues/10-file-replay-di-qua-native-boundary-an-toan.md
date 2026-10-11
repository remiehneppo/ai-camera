# 10: File replay đi qua native boundary an toàn

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Nguồn file qua C++ software decode và binding metadata-only, start/stop/poll/reopen kiểm chứng được.

**Blocked by:** [#03: Doctor và config fail-fast qua đường chạy lab](03-doctor-va-config-fail-fast-qua-duong-chay-lab.md); [#06: Recorder file replay giữ raw ring độc lập](06-recorder-file-replay-giu-raw-ring-doc-lap.md).

## Acceptance criteria

- [ ] Một nguồn struct/enum authoritative, generation/version mismatch/round-trip tests; stride/color/lifetime fixtures.
- [ ] GIL release lúc block, typed error, bounded output và buffer release cả drop/cancel/partial startup.

- [ ] Native và oracle dùng cùng PerceptionPipeline lifecycle/poll/request_pose; stage Detector/Tracker không được application gọi lại.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: C02, C04, N01, V03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
