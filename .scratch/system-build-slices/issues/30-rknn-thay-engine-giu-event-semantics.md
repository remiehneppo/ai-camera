# 30: RKNN thay engine giữ event semantics

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Chạy target detector/pose/RGA adapter qua same pipeline, đối chiếu oracle/native và event regression.

**Blocked by:** [#28: Negative audit và quality regression G2](28-negative-audit-va-quality-regression-g2.md); [#29: Build artifact target reproducible](29-build-artifact-target-reproducible.md).

## Acceptance criteria

- [ ] Shape/layout/dtype/color/stride/dequant/transform/lifetime đạt conformance; failures/fallback explicit.
- [ ] Golden+held-out detections/pose/tracks/events trong tolerance; đổi engine startup/restart analytics không dừng recorder.

## Traceability

Task nguồn: A02, A03, C05.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
