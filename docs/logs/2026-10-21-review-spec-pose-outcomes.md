# Spec review: pose outcomes → person-down (ticket #53)

Date: 2026-10-21
Reviewer: Spec Review Sub-agent
Scope: `git diff HEAD` on `apps/edge/incident.py`, `apps/edge/pipeline.py`, `compose.yaml`; read `tests/test_pose_outcomes_flow.py`.
Verified: `.venv-oracle/bin/python -m pytest tests/test_pose_outcomes_flow.py -q` → 5 passed.

Verdict: **partial**. Wiring works, but four acceptance criteria are claimed without evidence and two behaviours contradict the specified evidence semantics.

Key findings (see parent report for full list):

- Stale (`cancelled`/`epoch_mismatch`) never proven through the domain path; only scheduler counter vocabulary differs (`stale` vs `cancelled`).
- On-vehicle no-suppress regression (AC3, US09) absent from code and tests.
- Evidence is the latest terminal outcome at the alert frame, not the onset/first-qualifying baseline (requirements lines 59–60; contracts §3).
- Outcomes matched by `track_id` only: no camera/session/epoch/frame/temporal validation; `frame_id`/`request_id` are captured but dropped before evidence.
- Raw clip / evidence-request provenance never asserted (AC5).
- `compose.yaml` Mongo `ulimits.nofile` is out-of-scope infra tuning.
- Ticket self-ticked all ACs with "450 passed" although `docs/logs/2026-10-21-qa-pose-outcomes-flow.md` records the full suite at 1 failed / 449 passed.
