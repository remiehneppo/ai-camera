# 15: Camera RTSP live giữ correlation với recorder

Status: needs-info
Execution: not-started
Owner: Edge/platform; chưa claim.

**What to build:** Một camera thực đồng thời record và analytics; disconnect/reconnect/codec change vẫn tạo event/clip có time mapping rõ.

**Blocked by:** [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md); [#14: Pipeline baseline biến observations thành event](14-pipeline-baseline-bien-observations-thanh-event.md).

## Acceptance criteria

- [ ] Stream ADR dựa probe firmware/sessions; dual hoặc recorder-owned relay, không analytics-owned upstream.
- [ ] Session/discontinuity/uncertainty và actual ranges đúng; thiếu camera giữ ticket blocked, không thay bằng file demo.

## Traceability

Task nguồn: V02, V03, V04, F04, R01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## External prerequisites / activation gate

Cần camera/firmware/profile thực và endpoint lab được cấp quyền từ facts/probe #02; không ghi credentials vào ticket. Chưa có facts đó thì chưa chạy live acceptance.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
