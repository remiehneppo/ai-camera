# 35: Canary và rollback có authorization mới

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Canary bundle, theo dõi observed version rồi rollback artifact cũ bằng authorization sequence mới.

**Blocked by:** [#34: Config local và signed activation giữ LKG](34-config-local-va-signed-activation-giu-lkg.md); [#30: RKNN thay engine giữ event semantics](30-rknn-thay-engine-giu-event-semantics.md).

## Acceptance criteria

- [ ] Failed activation giữ LKG; state/schema/model compatibility policy rõ, không trộn lineage im lặng.
- [ ] Rollback không bypass signature/downgrade trust sequence; retry và reboot giữa activation có tests.

## Traceability

Task nguồn: T04, B04.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
