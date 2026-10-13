# Evidence upload and playback dispatch — 2026-10-13

## Scope and decisions

- User requested implementation of Direction 1: Ticket #08 (Edge evidence upload and server playback) and completing #04 (review re-review triggers).
- L2 complexity, teammate collaboration mode confirmed.
- Q1: Evidence files stored on server filesystem directory (`EVIDENCE_DIR`), metadata/manifest in MongoDB, HTTP Range playback endpoint.
- Q2: Web Dashboard Event Detail renders `<video controls>` tag with HTTP Range streaming, download button, and range/completeness status.
- Q3: `EdgeUploader` reads from outbox SQLite and FileRecorder, uploads via HTTP with verification and idempotent retry, receives receipt.
- Ticket #04 integration: When evidence manifest status transitions (none/pending -> available/complete/partial or corrupt), trigger re-review flag (`needs_re_review = True`) on confirmed/reviewed records.

## Architecture and Seams

### Server Seam (Task 1)
- `apps/server/config.py`: Add `evidence_dir: str = "/tmp/ai-camera-evidence"`.
- `apps/server/store.py`:
  - `save_evidence(device_id, event_id, request_id, manifest_data, file_path)`: updates evidence record, checks if meaningful change triggers `needs_re_review: true`.
  - `get_evidence(device_id, event_id, request_id)`: returns evidence metadata and file path.
- `apps/server/main.py`:
  - `PUT /v1/evidence/{device_id}/{event_id}/{request_id}`:
    - Auth: device bearer token matching `device_id`.
    - Headers: `X-Evidence-Sha256`, `X-Evidence-Metadata` (or JSON body/multipart).
    - Validates SHA-256 and byte length before atomic commit to `EVIDENCE_DIR`.
    - Returns 200 receipt with server commit details.
  - `GET /v1/evidence/{device_id}/{event_id}/{request_id}/media`:
    - Auth: dashboard or reviewer bearer token.
    - Supports HTTP 206 Partial Content (`Range` header) and HTTP 200.
    - Content-Type: `video/x-matroska` or `video/mp4`, Accept-Ranges: `bytes`.
  - `GET /v1/evidence/{device_id}/{event_id}/{request_id}`: returns evidence metadata.
- `apps/server/static/index.html`:
  - Displays pending indicator or `<video controls>` + Download link + actual range and completeness badge.
- `tests/test_server_evidence.py`:
  - TDD tests for upload, Range streaming, authz, hash verification, and re-review trigger.

### Edge Seam (Task 2)
- `apps/edge/uploader.py`:
  - `EdgeUploader`: connects to `EventOutbox` and `FileRecorder`.
  - Identifies fulfilled/partial evidence requests with local manifests and clips.
  - Uploads to server `PUT /v1/evidence/...` with SHA-256 and size verification.
  - Updates outbox evidence state or marks acknowledged.
  - Handles network errors / 503 retry with exponential backoff.
- `tests/test_edge_uploader.py`:
  - TDD tests for clip upload, receipt storage, retry on transient failure, and hash verification.

## Execution and Review Plan
1. Delegate Task 1 (Server Storage, API & UI) to `server-evidence-owner`.
2. Delegate Task 2 (Edge Uploader) to `edge-uploader-owner`.
3. Parallel execution with TDD red-green cycle.
4. Independent verification and code review (Standards + Spec axes).
5. Run full test suite across the repository.
6. Commit to current branch without push.
