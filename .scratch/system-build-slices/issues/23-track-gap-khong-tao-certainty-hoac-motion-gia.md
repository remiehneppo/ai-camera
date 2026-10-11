# 23: Track gap không tạo certainty hoặc motion giả

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Replay occlusion/ID switch/variable FPS từ dataset và xuất history/association uncertainty đáng tin cho consumers.

**Blocked by:** [#13: Native tracks có time và session semantics](13-native-tracks-co-time-va-session-semantics.md); [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md).

## Acceptance criteria

- [ ] Report fragmentation/ID switch theo ODD; nối history thận trọng, không dùng track ID làm danh tính.
- [ ] Expected sequences qua epoch/gaps và pose association có regression, không hard-code nối bằng bbox proximity.

## Traceability

Task nguồn: K03, D01.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
