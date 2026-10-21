# Ticket #28 — negative audit / G2 quality regression test evidence

Date: 2026-10-21 (Asia/Saigon)
Scope: acceptance tests for `domain/quality_eval.py`, `apps/edge/audit_sampler.py`,
`tools/negative_audit_report.py`. New file only: `tests/test_negative_audit_flow.py`.
No source, schema or config changes.

## Commands and results

- `.venv-oracle/bin/python -m pytest tests/test_negative_audit_flow.py -v`
  → **47 passed, 8 subtests passed** (0.14s), rerun twice with identical result.
- `.venv-oracle/bin/python -m pytest tests/ -q`
  → **519 passed, 126 subtests passed**, 0 failures (119.89s).

## Contract facts verified against real behaviour

- Alerts-only (`negatives` missing or `[]`) → `verdict=BLOCKED`, `blocking_gaps` and
  `verdict_reasons` contain `alerts_only`, `sample_sufficiency.sufficient=False`.
  Note: the numeric `recall.estimate` (1.0) is still computed from census alerts, so
  the "cannot report recall" guarantee is enforced by the gate + sufficiency blocks,
  not by `recall is None`. `recall is None` only when no recall units exist at all.
- HT weights: p=0.5 miss (weight 2) + p=0.1 miss (weight 10) → `weighted_missed_units=12`
  versus `missed_units=2` raw; estimate 10/22 instead of the naive 10/12.
- Interview interval: 95% Wilson on Kish effective n brackets the estimate; small
  samples are flagged insufficient and block the verdict even at perfect recall.
- Per-branch: `person_fall` 10/14, `person_lying_persistent` 1.0 (1 FP), 
  `person_on_stationary_vehicle` 5/7; branch units reconcile with overall recall.
- Sampler: noise is sha256-based (stable across instances, salt-sensitive), selection
  rate 0.50/0.12 for p=0.50/0.10 over 400 windows, alert windows never sampled,
  manifest carries `sample_id/stratum_id/inclusion_probability/rights_cleared/...`,
  `plan.json` snapshots `plan_sha256 == plan.content_hash()`.
- Rights: sampler still records a non-cleared window, and the evaluator blocks the
  report with `rights_not_cleared:1` — the guard lives in the report layer.
- CLI: PASS/FAIL/BLOCKED JSON + Markdown with targets and `owner_signoff`; `--strict`
  exits 0/1/2; directory + JSONL inputs accepted; missing input exits 2.

## Mutation checks (source restored byte-identical after each)

1. Negatives lose `1/p_h` weight → 8 tests fail.
2. `alerts_only` gate + verdict branch removed → 5 tests fail.
3. Sampler `should_sample` returns `True` always → selection-rate test fails.
4. `--strict` no longer returns 1 on FAIL → strict exit-code test fails.

## Not covered here

Field/hardware acceptance, real reviewer throughput, holder rights clearance and
signed owner sign-off remain open G2 gates; this file is software test evidence only.
