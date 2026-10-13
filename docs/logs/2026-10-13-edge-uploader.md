# Edge Evidence Uploader Implementation — 2026-10-13

## Overview
Implemented the **Edge Evidence Uploader Client (Ticket #08)** in `apps/edge/uploader.py` and comprehensive test suite in `tests/test_edge_uploader.py`.
Adhered strictly to TDD (red -> green), Karpathy guidelines (simple, surgical, verifiable), and write-scope isolation (did not modify any server files or unrelated modules).

## Contract & Seam Agreement
Coordinated with `server-evidence-owner`:
- **Endpoint**: `PUT /v1/evidence/{device_id}/{event_id}/{request_id}`
- **Headers**:
  - `Authorization: Bearer <device_token>`
  - `X-Evidence-Sha256: <sha256>`
  - `X-Evidence-Metadata: JSON string with {actual_range, completeness, ...}`
  - `Content-Type: video/x-matroska`
  - `Content-Length: <size_bytes>`
- **Body**: Raw binary video stream read directly from disk in chunks.
- **Server 200 Receipt**:
  ```json
  {
    "request_id": "<request_id>",
    "sha256": "<sha256>",
    "size_bytes": 12345,
    "location": "/v1/evidence/{device_id}/{event_id}/{request_id}/media",
    "status": "committed"
  }
  ```
- **Recorder & Outbox Reconciliation**:
  - On 200 OK receipt verification:
    1. Calls `FileRecorder.acknowledge_transfer(request_id, receipt)`.
    2. Updates `evidence_requests` in `EventOutbox` SQLite DB: transitions `state` to `'acknowledged'`, updates `receipt_json` with transfer details, and clears `last_error`.

## Implementation Details

### `apps/edge/uploader.py`
1. **`EdgeUploader` Class**:
   - Initialized with `outbox` (`EventOutbox` or path), `recorder` (`FileRecorder` or path), `server_url`, `device_token`, `timeout_seconds`, `max_retries`, and `backoff_base`.
   - Validates `server_url` (requires HTTPS or local loopback HTTP; rejects embedded credentials, query params, fragments, or path components).
2. **`upload_pending(batch_size=10) -> int`**:
   - Queries `self.outbox.evidence_requests()` where `state` in `{"fulfilled", "partial"}`.
   - Respects `batch_size` limit.
   - Invokes `upload_single_request` for each candidate item.
3. **`upload_single_request(request_id: str) -> dict | None`**:
   - **Idempotency check**: If already acknowledged in `recorder.pin_status()`, syncs outbox state and returns existing transfer receipt without re-uploading.
   - **Missing file handling**: If artifact file is missing on disk, does not crash; logs warning and marks outbox request `state='failed'` with `last_error="clip file missing: ..."`.
   - **Pre-upload integrity verification**:
     - Computes local SHA-256 via `hashlib.file_digest` and verifies byte size.
     - If mismatch detected, halts upload, logs warning, and records error in outbox without sending bad data.
   - **Metadata serialization**: Prepares compact JSON metadata including actual range, completeness, gaps, codec, and anchor policies.
   - **Streaming PUT upload**: Streams binary video bytes directly via `urllib.request.urlopen` with `Content-Length`.
   - **Retry & backoff logic**:
     - Retries on HTTP 503, 429, 502, 504 and transient network errors (`URLError`, `TimeoutError`, `OSError`).
     - Exponential backoff: `delay = backoff_base * (2 ** (attempt - 1))`.
     - Non-retryable errors (e.g. HTTP 400, 401) record error immediately without useless retries.
   - **Receipt verification**: Validates that server response contains matching `request_id`, `sha256`, `size_bytes`, and valid non-empty `location`.
   - **Atomic acknowledgment**: Calls `recorder.acknowledge_transfer()` and transitions outbox state to `'acknowledged'`.

## TDD Process & Verification

### RED Phase
- Created test suite in `tests/test_edge_uploader.py` before implementing `apps/edge/uploader.py`.
- Execution output:
  ```
  ImportError: Failed to import test module: test_edge_uploader
  ModuleNotFoundError: No module named 'apps.edge.uploader'
  FAILED (errors=1)
  ```

### GREEN Phase
- Implemented `apps/edge/uploader.py`.
- All 13 tests passed:
  ```
  Ran 13 tests in 7.353s
  OK
  ```

### Test Cases Covered in `tests/test_edge_uploader.py`:
1. `test_successful_upload`: Verifies headers, body streaming, receipt validation, outbox status transition to `acknowledged`, and recorder `transfer_state`.
2. `test_sha256_verification_mismatch_aborts`: Pre-upload SHA-256 integrity check halts upload before network call.
3. `test_file_size_mismatch_aborts`: Verifies size mismatch is caught before network call.
4. `test_missing_clip_file_does_not_crash`: Missing clip file logs warning and transitions to `failed` without crashing.
5. `test_503_retry_with_backoff_succeeds`: Transient 503 retries with backoff and succeeds on subsequent attempt.
6. `test_503_retries_exhausted_records_error_without_crash`: Boundedly retries on persistent 503, records error, keeps request unacknowledged.
7. `test_non_retryable_400_client_error`: Client errors abort immediately without retrying.
8. `test_idempotent_replay`: Re-running `upload_pending()` does not re-upload acknowledged items; replaying single request returns existing receipt idempotently.
9. `test_partial_evidence_upload`: Correctly handles `partial` completeness evidence requests.
10. `test_batch_size_limits_uploaded_count`: Bounded batch size processing.
11. `test_server_receipt_validation_mismatch`: Rejects server receipts with invalid checksums or locations.
12. `test_uploader_initialized_with_str_and_path_objects`: Verifies path-based initialization.
13. `test_invalid_server_url_rejected`: Rejects URLs with credentials, queries, or insecure non-loopback schemes.

### Type Check (Mypy)
```bash
.venv-oracle/bin/mypy --follow-imports=silent apps/edge/uploader.py tests/test_edge_uploader.py
```
Output:
```
Success: no issues found in 2 source files
```

### Full Edge Test Suite Run
```bash
.venv-oracle/bin/python -m unittest tests/test_edge_uploader.py tests/test_event_delivery.py tests/test_recorder.py tests/test_edge_runtime.py tests/test_edge_config.py
```
Output:
```
Ran 79 tests in 37.725s
OK
```

## Files Touched
- `apps/edge/uploader.py` (New module)
- `tests/test_edge_uploader.py` (New test module)
- `docs/logs/2026-10-13-edge-uploader.md` (This log)
No server files or existing modules were modified.
