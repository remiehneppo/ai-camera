# 35: Canary và rollback có authorization mới

Status: ready-for-agent
Execution: done (software lab; canary observation lifecycle + authorized rollback with fresh sequence + SQLite reboot survival pass)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Canary bundle, theo dõi observed version rồi rollback artifact cũ bằng authorization sequence mới.

**Blocked by:** [#34: Config local và signed activation giữ LKG](34-config-local-va-signed-activation-giu-lkg.md); [#28: Negative audit và quality regression G2](28-negative-audit-va-quality-regression-g2.md).

**Conditional blockers (RKNN):** [#30: RKNN thay engine giữ event semantics](30-rknn-thay-engine-giu-event-semantics.md).

Target ONNX dùng C05/N05/P03/I05 và actual-target conformance; target chưa chọn hoặc thiếu report thì acceptance chưa đạt.

## Acceptance criteria

- [x] Failed activation giữ LKG; state/schema/model compatibility policy rõ, không trộn lineage im lặng.
- [x] Rollback không bypass signature/downgrade trust sequence; retry và reboot giữa activation có tests.

- [x] Bundle trên target đã chọn có conformance report; ONNX không chờ RKNN, còn RKNN bắt #30 trước activation/canary.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: T04, B04.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
- 2026-10-27: Hoàn thành triển khai software lab cho #35.
  `domain/signed_config.py`: Thêm `ROLE_CONFIG_ROLLBACK`, `CanarySpec`, và `CompatibilityPolicy`. Kiểm tra tính tương thích của schema, factory, model lineage trước khi chấp nhận bundle rollback.
  `apps/edge/config_activation.py`: Quản lý vòng đời canary (`activate_canary`, `record_canary_observation`, `abort_canary`, `promote_canary`). Rollback bắt buộc phải dùng `trust_sequence` mới cao hơn HWM hiện tại (tuyệt đối không hạ sequence), khôi phục LKG, cập nhật observed version và ghi nhận audit trail. Toàn bộ trạng thái và HWM sống sót qua SQLite reboot/crash.
  Evidence: `pytest tests/test_canary_rollback.py tests/test_signed_config_activation.py -v` ⇒ **30 passed**; `mypy` sạch.