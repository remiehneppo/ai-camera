# 34: Config local và signed activation giữ LKG

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Stage config local rồi nhận signed bundle hợp lệ; activate tại boundary với desired/observed versions và trust sequence durable.

**Blocked by:** [#03: Doctor và config fail-fast qua đường chạy lab](03-doctor-va-config-fail-fast-qua-duong-chay-lab.md); [#16: Startup/shutdown giữ recorder và state đúng](16-startup-shutdown-giu-recorder-va-state-dung.md); [#33: Device lifecycle và site access được enforce](33-device-lifecycle-va-site-access-duoc-enforce.md).

## Acceptance criteria

- [ ] Canonical bytes/target/hash/length/expiry/trusted keys được verify; bad/expired/old/uncertain-clock reject.
- [ ] Local config sai giữ LKG; high-water mark survives reboot, event snapshot/reset semantics đúng, recorder tiếp tục.

## Delta requirement được duyệt — 2026-10-20

- [ ] Local config có version/provenance theo module × camera cho enabled, ROI/lịch/ngưỡng/ngoại lệ; activate/reset state tại boundary và desired/observed version rõ, config lỗi giữ LKG, không dùng trạng thái degraded để bỏ qua validation.
- [ ] Local validation/activation và signed remote activation là hai lát cắt riêng: local config không chờ signed bundle/trust infrastructure; nhánh remote khi bật vẫn phải verify chữ ký/target/expiry và high-water mark durable, không làm yếu LKG/recorder isolation.

## Traceability

Task nguồn: B04, T02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.
