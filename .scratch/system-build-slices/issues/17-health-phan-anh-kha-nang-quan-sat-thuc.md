# 17: Health phản ánh khả năng quan sát thực

Status: ready-for-review
Execution: completed
Owner: Edge

**What to build:** Dashboard/health API cho biết starting/degraded/unavailable và lý do, frame age/outbox/disk/recorder thay vì chỉ process running.

**Blocked by:** [#14: Pipeline baseline biến observations thành event](14-pipeline-baseline-bien-observations-thanh-event.md).

## Acceptance criteria

- [x] Logs correlation/secret masking, bounded labels/spool; không event/frame ID làm metric label.
- [x] Inject deadlock/queue stall/record gap có fault, thiếu clock mapping báo receive age thay capture age giả.

## Traceability

Task nguồn: H01, UI01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

- Test commands:
  - `.venv-oracle/bin/python -m unittest tests.test_health`: 16 passed
  - `.venv-oracle/bin/python -m mypy --follow-imports=silent apps/edge/health.py apps/edge/live_pipeline.py apps/edge/pipeline.py`: zero issues
  - `.venv-oracle/bin/python -m unittest tests.test_live_pipeline tests.test_pose tests.test_health`: 50 passed
- Implemented: `EdgeHealthMonitor` in `apps/edge/health.py`, hooks in `PerceptionPipeline` and `LivePerceptionRunner`.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
- 2026-10-14: Implemented EdgeHealthMonitor and unit test suite tests/test_health.py fulfilling H01. State transitions, fault injection, truthful clock mapping metrics, secrets masking, and bounded spool/labels verified.
