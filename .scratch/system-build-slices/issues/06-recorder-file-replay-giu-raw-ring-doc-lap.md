# 06: Recorder file replay giữ raw ring độc lập

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Chạy recorder từ file cleared theo thời gian nội dung; dừng analytics vẫn query được raw segments và actual ranges.

**Blocked by:** [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md).

## Acceptance criteria

- [ ] Compressed segments có codec/keyframe/PTS/session metadata và ring lifecycle; raw không overlay.
- [ ] Fast/realtime giữ semantic time; pre-roll chưa có báo rõ, không giả RTSP camera test đã chạy.

- [ ] Semantic replay dùng fixed sampling/virtual clock và watermark recorder–consumer; paced/fast cùng input cho cùng outcome. Realtime stress kiểm drops/coverage, không ép cùng event set.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: V01, R01, C01, C03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
