# Ticket #40 — Synthetic probe báo operational fault riêng (software lab)

Ngày 2026-10-24. Blocker #17/#05 đã done.

## Phạm vi

| Lát cắt | Nội dung |
|---|---|
| Contract | `domain/probe_contract.py` — `STAGES` cố định, `FAULT_CATALOG` (metric/window/threshold/owner/runbook/recovery), `ProbeLedger` bounded theo stage + correlation ring |
| Runner | `apps/edge/probe.py` — `SyntheticProbe` đi qua 4 stage injected, checkpoint, báo fault, không có đường tới outbox/incident |
| Health | `EdgeHealthMonitor.record_probe_faults()` → fault code vào `operational_faults`, snapshot có `probe_fault_count`/`probe_faults` |
| Guard (test) | Mỗi revision của event synthetic là `ineligible` trong outbox; revision không đổi được origin; probe report không phải event |

## Quyết định thiết kế

1. **Fault là taxonomy riêng, không phải event nghiệp vụ.** Report có `taxonomy: operational_fault`; test
   `validate_event(report)` phải raise ⇒ không thể ingest thành sự kiện, nên "fault route không rescue" là tính chất
   cấu trúc chứ không phải quy ước.
2. **Không có import tới outbox/incident/transport.** Test parse AST của `apps/edge/probe.py` và assert tập import
   đúng bằng `{__future__, time, typing, uuid, domain.probe_contract}` — nếu ai thêm coupling, test đỏ ngay.
3. **Cardinality bounded bằng enumeration.** Stage và fault code là hằng số; correlation id đi vào ring bounded
   (`sample_correlations`), không thành label.
4. **Secret budget.** Reason ghi `type(error).__name__`, không ghi message; test chèn exception chứa
   `/etc/shadow` và assert không xuất hiện trong report.
5. **"Ngừng tiến triển" đo bằng tuổi checkpoint**, không bằng việc lần chạy này có lỗi hay không: stage chưa từng
   progress cũng là fault (age `None`), nên im lặng từ đầu không bị coi là khoẻ.
6. **Guard đặt ở store, không ở client.** `origin` quyết định `eligibility` khi ghi outbox; revision 2 đổi origin bị
   `EventIdentityConflict`, nên mọi revision của cùng event đều ineligible.

## Bằng chứng chạy thật

- `.venv-oracle/bin/python -m pytest tests/test_probe.py tests/test_probe_guard.py -q` ⇒ **22 passed**
  (17 contract/runner/health + 5 server guard).
- Full suite ⇒ **665 passed, 126 subtests** trong 150.02s (baseline 643, +22).
- `mypy domain/probe_contract.py apps/edge/probe.py apps/edge/health.py` ⇒ `no issues found`.
- Đã kiểm: fault payload đủ 7 trường vận hành; mọi stage chưa progress đều fault; progress xoá fault đúng stage;
  budget theo từng stage; correlation ring bounded + `reset()`; injected `TimeoutError` ở journal ⇒
  `stopped_at=journal`, `probe_journal_stalled` vào `all_reasons` và health degraded; synthetic revision 1+2 đều
  `ineligible/synthetic_or_replay_origin`; origin rewrite bị chặn; live trong lab `lab_notifications_disabled`.

## Còn mở

- **Bullet 2 giữ unchecked**: mới inject deadlock; chưa inject **pin gap** (recorder pin hết trước post-roll) cho
  stage `journal`/`delivery`.
- Chưa có scheduler chạy probe định kỳ trong `EdgeRuntime` (hiện là API + injected stage, caller tự gọi).
- Chưa nối fault `probe_*` vào alert/runbook thật (owner "edge-ops" là placeholder trong catalog).
- Chưa có metric exporter (Prometheus) — chỉ snapshot health.
