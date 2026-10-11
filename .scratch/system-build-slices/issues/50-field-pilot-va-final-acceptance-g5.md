# 50: Field pilot và final acceptance G5

Status: ready-for-human
Execution: not-started
Owner: Product/operations + ML/QA; chưa claim.

**What to build:** Thu observations field theo ODD, đánh giá quality/review load và ký final SLO cùng quyết định scale.

**Blocked by:** [#49: Nghiệm thu person-down pilot readiness G4a](49-nghiem-thu-person-down-pilot-readiness-g4a.md).

## Acceptance criteria

- [ ] Ngày/đêm/mưa/occlusion/camera-days/sampling đủ theo protocol; reports có uncertainty, missed events và operator workload.
- [ ] Central restore/revoke/canary drills theo SLA, TCO dùng số đo; đổi site/camera/engine ngoài envelope cần tái kiểm, chưa đủ mẫu không ký scale.

## Traceability

Task nguồn: D04, D05, F03.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Cần lịch/site pilot được cho phép, operator/reviewer và protocol đủ camera-days/samples/ODD; named owner ký final acceptance và quyết định scale. Thiếu dữ liệu chưa ký G5.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
