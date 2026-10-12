# 11: ONNX oracle xuất detection có provenance

Status: ready-for-agent
Execution: done
Owner: Dispatcher + oracle-manifest / oracle-detector / oracle-facts / oracle-artifacts — nghiệm thu software lab oracle; production weights/data/privacy clearance vẫn mở.

**What to build:** Replay mẫu cleared qua detector oracle, xuất canonical detections/timing/transform để đối chiếu deployment.

**Blocked by:** [#02: Hồ sơ lab, ODD và protocol nghiệm thu](02-ho-so-lab-odd-va-protocol-nghiem-thu.md).

## Acceptance criteria

- [x] Software lab: exact official ONNX SHA/size, labels, corrected raw-BGR preprocessor source, postprocessor/runtime pins; original-coordinate boxes, `ok_empty` khác `failed`; production rights không được suy từ lab authorization.
- [x] Versioned independent golden fixture/source/pixel hashes and approved bbox1e-3px/score1e-6 tolerances; real CPU ORT run, no board/target SDK. Original13 detections/10person, crop9/7, authored black0.

## Traceability

Task nguồn: N02, C05, V01, F05.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-12: Implement #11 sau user duyệt model/fixture/numeric policy/public seams; phân rã4nhánh agents. Model release0.1.1rc0 actual SHA427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7; independent diagnostics phát hiện mismatch old normalized source, user duyệt rawBGR source6ddff4824372906469a7fae2dc3206c7aa4bbaee, provenance hybrid tường minh. Manifest defaultlab exact pin, generated numeric tests riêng identity/rights/pin. Pixel replay real RGB/PTS và independent goldens; full pinned85/85pass no skips, baseline85tests OK18skips; typecheck5modules/pass, Standards+Spec PASS sau correction/re-review. Execution done chỉ software lab; chưa production weights/training-data/privacy clearance, native/tracker/pose/target/field quality. Evidence/commands: [log](../../../docs/logs/2026-10-12-ticket-11.md). Không đổi gates #06/#07/#08.
