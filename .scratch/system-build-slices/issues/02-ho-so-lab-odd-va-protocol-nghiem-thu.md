# 02: Hồ sơ lab, ODD và protocol nghiệm thu

Status: ready-for-agent
Execution: not-started
Owner: Product/operations + Edge + ML; chưa claim.

**What to build:** Probe môi trường hiện có và tạo hồ sơ facts/workload/ODD/sizing/failure protocol dùng để quyết định các nhánh live và hardware.

**Blocked by:** None (can start immediately).

## Acceptance criteria

- [ ] Facts có nguồn probe, camera chưa có/board chưa chọn/threshold chưa duyệt ghi pending, không bịa capacity.
- [ ] Target Q6/Q16, quyền samples/model và owner/gap/RPO/RTO/quality/review protocol được phân biệt với số đo.

## Traceability

Task nguồn: F01, F02, F03, F04, F05, F06, D01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
