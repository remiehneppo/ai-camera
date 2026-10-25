# 40: Synthetic probe báo operational fault riêng

Status: ready-for-agent
Execution: partial (probe + health surfacing + synthetic notification guard; pin-gap injection và scheduler còn mở)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Probe đi qua decode/inference/journal/server và báo lỗi khi capability hoặc delivery ngừng tiến triển.

**Blocked by:** [#17: Health phản ánh khả năng quan sát thực](17-health-phan-anh-kha-nang-quan-sat-thuc.md); [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md).

## Acceptance criteria

- [x] Synthetic origin immutable qua revisions/retry, notification guard trước outbox; fault route không rescue.
- [ ] Metric/window/threshold/owner/runbook/recovery và secret/cardinality budgets được kiểm bằng injected deadlock/pin gap.

- [x] origin=synthetic bất biến, taxonomy nghiệp vụ riêng; mode/device authorization và mọi revision không được vượt notification guard.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: H02, W02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-24: Implement software lab cho probe + guard, giữ bullet 2 unchecked.
  `domain/probe_contract.py` — `STAGES = decode/inference/journal/delivery` (closed enum), `FAULT_CATALOG` mỗi stage
  có `metric/window_seconds/threshold_seconds/owner/runbook/recovery`, `ProbeLedger` bounded (per-stage checkpoint,
  correlation ring, `reset()` sau recovery). Stage chưa từng progress cũng là fault (age `None`) ⇒ im lặng từ đầu
  không bị coi là khoẻ. `taxonomy = operational_fault`.
  `apps/edge/probe.py` — `SyntheticProbe` chạy 4 stage injected theo thứ tự, dừng ở stage lỗi, report gồm
  `stopped_at/stages/faults`; reason chỉ là **exception type**, không phải message (test chèn `/etc/shadow` và assert
  không leak). Probe module không import outbox/incident/transport — test parse AST để khoá.
  Health: `EdgeHealthMonitor.record_probe_faults()` fold fault code vào `operational_faults` (snapshot có
  `probe_fault_count`/`probe_faults`), nên capability/delivery ngừng tiến triển ⇒ health degraded, không tạo incident.
  Guard: `EventStore` đánh `ineligible` với reason `synthetic_or_replay_origin` cho **mọi** revision synthetic;
  revision đổi origin bị `EventIdentityConflict`; `validate_event(probe_report)` raise ⇒ fault route không thể thành
  event. Fixture synthetic giữ taxonomy nghiệp vụ riêng `synthetic_demo`.
  Evidence: `pytest tests/test_probe.py tests/test_probe_guard.py -q` ⇒ **19 passed**; full suite ⇒ **665 passed,
  126 subtests** (baseline 643); `mypy domain/probe_contract.py apps/edge/probe.py apps/edge/health.py` ⇒ sạch.
  Còn mở: bullet 2 (mới inject deadlock, **chưa inject pin gap**); chưa có scheduler chạy probe định kỳ trong
  `EdgeRuntime`; owner/runbook trong catalog là placeholder; chưa có metric exporter.
