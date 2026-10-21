# 21: Quality và ODD đi xuyên tới event/detail

Status: ready-for-agent
Execution: partial
Owner: Edge / AI Pipeline

**What to build:** Blur/dark/freeze/missing/camera-moved được native đo, domain áp policy và event/detail hiển thị uncertainty.

**Blocked by:** [#17: Health phản ánh khả năng quan sát thực](17-health-phan-anh-kha-nang-quan-sat-thuc.md).

## Acceptance criteria

- [x] Cảnh tĩnh khác frozen (SHA-256 frame hash signature); metrics missing/stale không negative (tri-state `odd_supported`: True/False/None). (Đo native C++ còn mở ở #10/#12).
- [x] Site thresholds có version (`DEFAULT_ODD_POLICY` version), recovery reason rõ ràng (`recovered_from_low_light`,...). (Camera-moved P2 chưa triển khai).
- [x] Quality/ODD đi xuyên tới event payload (`validate_event` contract validation) và UI indicator trên dashboard (ODD supported / not supported / unverified).

## Delta requirement được duyệt — 2026-10-20

- [ ] Quality/ODD được biểu diễn theo capability × camera/site và config version: ngày/đêm/mưa chỉ hỗ trợ trong bounds đã kiểm thử của capability đó; thiếu hình ảnh/continuity hoặc ngoài ODD là unknown/degraded/unsupported phù hợp, không negative.
- [ ] Một camera có thể đủ quan sát cho tính năng này nhưng không đủ cho tính năng khác; event/detail giữ reason/coverage/recovery riêng, không suy một quality flag chung là mọi module đã hỗ trợ.

## Traceability

Task nguồn: QL01, QL02, QL03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.

- 2026-10-21: Cập nhật tiến độ software lab: `assess_quality()` hỗ trợ low_light, glare, low_contrast, blur (Laplacian), freeze (SHA-256 frame hash). Đã fix các issue P1/P2 về reset freeze state khi có gap/session reset và đính kèm quality cho stale frames. 14/14 tests pass trong `tests/test_quality_odd.py`. Execution: `partial` (đo native C++ và camera-moved pending).
