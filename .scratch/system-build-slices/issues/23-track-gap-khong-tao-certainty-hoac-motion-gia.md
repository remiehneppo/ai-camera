# 23: Track gap không tạo certainty hoặc motion giả

Status: ready-for-agent
Execution: partial
Owner: Edge / Tracking

**What to build:** Replay occlusion/ID switch/variable FPS từ dataset và xuất history/association uncertainty đáng tin cho consumers.

**Blocked by:** [#13: Native tracks có time và session semantics](13-native-tracks-co-time-va-session-semantics.md); [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md).

## Acceptance criteria

- [x] Track gap và clock jump: `Track.max_gap` (mặc định 1.0s) xóa history và `consecutive_hits=0` khi `ts < last_time` hoặc `gap > max_gap`. `IncidentEngine` reset dwell, onset, standing evidence, speed baseline khi gặp gap hoặc clock jump, chỉ giữ cooldown. Đã có 9 regression tests trong `tests/test_track_gap.py`.
- [ ] Report fragmentation/ID switch theo ODD trên dataset hoàn chỉnh; nối history thận trọng, không dùng track ID làm danh tính.
- [ ] Expected sequences qua epoch/gaps và pose association có regression, không hard-code nối bằng bbox proximity.

## Traceability

Task nguồn: K03, D01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-21: Cập nhật tiến độ software lab: Đã triển khai cơ chế xử lý observation gap và clock jump trong `ByteTracker` (`Track.max_gap`) và `IncidentEngine` (`IncidentEngine.max_observation_gap`) để tránh sinh vận tốc giả và dwell giả. Toàn bộ 9/9 tests pass trong `tests/test_track_gap.py`. Execution: `partial` (báo cáo ID switch/fragmentation trên tập dataset ODD lớn vẫn mở).
