# Review #44 — dev-demo re-review reasons (HEAD a169002)

Verdict: ACCEPT as dev-demo-only slice. Ticket #44 stays open (docs/logs/2026-10-27-ticket-44-demo-rereview-reasons.md agrees).

## Missing / partial
- "Đội UI tích hợp API thật thành queue person-down/on-vehicle/ambiguous và annotation feedback" — not built; only the static dev demo (user-scoped out).
- "Label correction/version/conflict/audit độc lập AI, missing/expired evidence và auth states rõ." — untouched by diff.
- "Operator workload, keyboard/responsive/accessibility theo scope được review; dev demo không thay sign-off UI sản phẩm." — no browser/a11y/keyboard run; reasons render as plain <p> with no aria.
- Delta "Queue/detail hỗ trợ các nhãn liên kết cùng diễn biến..." — reasons shown in list only, not in detail/evidence panel.
- Delta "Hiển thị requested/actual clip ranges, mốc anchor theo loại Q36, provenance, observation duration và gaps/partial/missing" — ranges/anchors/partial already pre-existing (index.html:229, 248); provenance, observation duration and gaps still absent.
- "metadata-only update không gây bão review" — holds, not from this diff: domain/review_contract.py:67 hashes only taxonomy/severity/evidence_versions; store.py:504 tuples completeness/actual_range/file_status.

## Scope creep
None. +6 lines in apps/server/static/index.html, no new API, no taxonomy correction, tracker untouched. Only extra artifact is untracked docs/logs note (process log, still untracked).

## Implemented but wrong
- Reasons are raw codes (event_content_changed, evidence_changed) — displays a reason but not operator-readable.
- Redundant: index.html:170 already prints "· needs re-review", new block repeats "Re-review required:".
- Sentence-length text styled as pill (badge badge-pending) — cosmetic misfit.
- Fallback verified necessary/reachable: store.py:617-626 legacy path sets needs_re_review without reasons.

## Evidence checked
git diff --check exit 0; .venv-oracle/bin/python -m pytest tests/test_review_api.py -q -> 8 passed; /v1/events (main.py:458) -> store.list_current projects full review doc, so needs_re_review/re_review_reasons are API-backed (tests/test_review_api.py:104,131).
