# Synthetic Probe Operational Fault Runbook

See canonical contract documentation at [docs/architecture/contracts.md#synthetic-probe-operational-fault](../architecture/contracts.md#synthetic-probe-operational-fault).

## Overview
The synthetic probe walks four pipeline stages: `decode -> inference -> journal -> delivery`.
An operational fault (`taxonomy: operational_fault`) is emitted when a stage stops progressing or when a pin gap is detected. It is an operational signal and must never be routed to business incident dispatch.

## Fault Codes & Metrics
- `probe_decode_stalled`: metric `probe_decode_age_seconds`, owner `edge-ops`.
- `probe_inference_stalled`: metric `probe_inference_age_seconds`, owner `edge-ops`.
- `probe_journal_stalled`: metric `probe_journal_age_seconds`, owner `edge-ops`.
- `probe_delivery_stalled`: metric `probe_delivery_age_seconds`, owner `edge-ops`.
- `probe_journal_pin_gap`: metric `probe_journal_pin_gap_seconds`, owner `edge-ops`.
- `probe_delivery_pin_gap`: metric `probe_delivery_pin_gap_seconds`, owner `edge-ops`.

## Recovery Procedure
1. Check `snapshot["stages"][stage]["checkpoints"]` and `observed.last_progress_at`.
2. For `journal` or `delivery` stalls or pin gaps: inspect recorder ring coverage, disk space, and SQLite outbox before restarting.
3. For `decode` or `inference` stalls: inspect video source connection and model engine before restarting the worker.
4. After recovery, clear faults via `ledger.reset()` or stage checkpoints.
