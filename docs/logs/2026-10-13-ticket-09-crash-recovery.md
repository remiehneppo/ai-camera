# 2026-10-13: Ticket #09 — Khôi phục event/evidence sau process crash

## Overview
Implemented Ticket #09: Crash recovery and reconciliation between Edge (Outbox, FileRecorder, EdgeUploader) and Server (EventStore, API).

## Changes Made

### 1. Edge Crash Reconciliation (`apps/edge/uploader.py`, `apps/edge/outbox.py`)
- Implemented `reconcile_and_cleanup(outbox, recorder)`:
  - Scans and deletes orphaned temporary files (`*.tmp*`, `*.concat`) in `recorder.root` and `manifests/`.
  - For evidence requests in `pending`, `in_progress`, `requested`, `collecting` (and verifying `fulfilled` / `partial`):
    - If clip exists on disk: computes size and SHA-256; if valid, transitions request to `'fulfilled'` ready for upload. If corrupt, transitions request to `'failed'` with error.
    - If clip does not exist on disk: checks `recorder.segments(session_id)`. If segments are expired / pruned past the requested interval, marks request `'failed'` with `last_error='ring segments expired'`, avoiding infinite pending states.
    - If range can still be fulfilled, finalizes pin and transitions to `'fulfilled'`.
- Exposed `EdgeUploader.reconcile_and_cleanup()`.
- Extended `EdgeUploader.upload_pending(batch_size=10, reconcile=False)`:
  - When `reconcile=True`, runs `reconcile_and_cleanup()` before batch upload.
  - Resume upload handles network drops / 503 errors and resumes idempotently with integrity checks.
- Added `EventOutbox.reconcile_and_cleanup(self, recorder)` delegating to `reconcile_and_cleanup`.

### 2. Server Crash Reconciliation (`apps/server/store.py`, `apps/server/main.py`)
- Implemented `cleanup_temp_evidence(evidence_dir)` to sweep stray `.{request_id}.*.tmp` and `*.tmp` files.
- Wired `cleanup_temp_evidence(evidence_dir)` into `create_app` startup event.
- In `get_evidence_manifest` and `get_evidence_media` (`/media`):
  - Checks underlying media file on disk.
  - Returns 404 with descriptive detail if missing or corrupt (size or SHA-256 mismatch). Never serves fake complete or corrupted media bytes.
- Enhanced `EventStore.get_evidence(device_id, event_id, request_id, verify_file=True)` to inspect file existence and mark `manifest["completeness"]` as `'missing'` or `'corrupt'`.

### 3. TDD Test Suite (`tests/test_crash_recovery.py`)
Implemented comprehensive tests:
- `test_orphan_temp_file_cleanup_edge`: Cleans up `.tmp.mkv`, `.json.tmp`, and `.concat` orphan files while retaining legitimate files.
- `test_orphan_temp_file_cleanup_server`: Sweeps stray `.tmp` files in `EVIDENCE_DIR`.
- `test_expired_ring_segments_reconciliation`: Prevents infinite pending when ring segments are pruned; transitions to `failed` with `ring segments expired`.
- `test_mid_flight_crash_and_restart_resuming_valid_clips`: Recovers mid-flight valid clips and uploads to server.
- `test_corrupt_clip_marked_failed`: Detects corrupted clip bytes and transitions to `failed`.
- `test_server_missing_media_file_handling`: Ensures server returns 404 when media file on disk is deleted/missing.
- `test_server_corrupt_media_file_handling`: Ensures server returns 404 and does not stream corrupt media bytes when file on disk is tampered.
- `test_idempotent_upload_resumption_after_network_drop`: Recovers from network failure during upload and idempotently completes upload on retry.

## Verification
- Unit tests: `.venv-oracle/bin/python -m unittest tests/test_crash_recovery.py -v` (8/8 PASSED)
- Regression tests: `.venv-oracle/bin/python -m unittest tests/test_edge_uploader.py tests/test_server_evidence.py` (22/22 PASSED)
- Typecheck: `.venv-oracle/bin/mypy --follow-imports=silent apps/edge/outbox.py apps/edge/uploader.py apps/edge/recorder.py tests/test_crash_recovery.py` (Success: no issues found)
