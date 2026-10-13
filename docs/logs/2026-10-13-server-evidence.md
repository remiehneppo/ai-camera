# Server Evidence Storage, Range Streaming API & Dashboard Playback UI — 2026-10-13

## Summary

Implemented Server Evidence Storage, HTTP Range streaming media API, and Dashboard playback UI for Task-3, fulfilling Ticket #08 and Ticket #04 contracts.

## Changes by Component

### 1. Configuration (`apps/server/config.py`)
- Added `evidence_dir: str` to `ServerConfig` dataclass.
- Loaded from environment `EVIDENCE_DIR` with default `/tmp/ai-camera-evidence`.
- Validates that `EVIDENCE_DIR` is non-empty.
- Included `evidence_dir` in `public_config` so configuration changes deterministically affect `config_hash`.

### 2. Event Store (`apps/server/store.py`)
- Created `evidence_manifests` collection with unique index on `(device_id, event_id, request_id)`.
- Implemented `record_evidence(device_id, event_id, request_id, manifest_data, file_path)`:
  - Upserts evidence manifest, file path, and storage timestamp inside a replica-set snapshot transaction.
  - Automatically triggers `needs_re_review = True` on confirmed/reviewed records per contracts §5 when new evidence becomes available.
- Implemented `get_evidence(device_id, event_id, request_id)`:
  - Returns evidence manifest document and filesystem path, or `None` if not found.
- Updated `list_current(limit)`:
  - Queries `evidence_manifests` for active events and attaches `evidence: list[dict]` to each returned row, enabling the dashboard to display clip status without extra N+1 round trips.

### 3. Server Endpoints (`apps/server/main.py`)
- `PUT /v1/evidence/{device_id}/{event_id}/{request_id}`:
  - Verifies device bearer authentication matching the path `device_id` (401 on missing/invalid token, 403 on device ID mismatch).
  - Validates `X-Evidence-Sha256` (64-char hex) and `X-Evidence-Metadata` (JSON object) headers (400 on missing or invalid format).
  - Computes payload SHA-256 and verifies match with header and metadata `size_bytes` (422 on checksum/size mismatch).
  - Performs atomic filesystem commit: writes to temporary file `.{request_id}.{uuid}.tmp`, flushes and `fsync`s, then `os.replace` to `EVIDENCE_DIR/{device_id}/{event_id}/{request_id}.mkv`.
  - Persists record in `EventStore`.
  - Returns 200 JSON receipt:
    ```json
    {
      "request_id": "<request_id>",
      "sha256": "<computed_sha256>",
      "size_bytes": <length>,
      "location": "/v1/evidence/{device_id}/{event_id}/{request_id}/media",
      "status": "committed"
    }
    ```
- `GET /v1/evidence/{device_id}/{event_id}/{request_id}`:
  - Requires dashboard or reviewer bearer authentication.
  - Returns 200 with stored manifest JSON (or 404 if not found).
- `GET /v1/evidence/{device_id}/{event_id}/{request_id}/media`:
  - Supports dashboard or reviewer authentication via Bearer header or `?token=` query parameter (for native HTML5 `<video>` tag playback).
  - Returns 200 OK with full file when no `Range` header is present (`Accept-Ranges: bytes`, `Content-Type: video/x-matroska`).
  - Supports HTTP 206 Partial Content for byte range requests (`bytes=start-end`, `bytes=start-`, `bytes=-suffix`), returning accurate `Content-Range: bytes start-end/total` and `Content-Length`.
  - Returns HTTP 416 Range Not Satisfiable with `Content-Range: bytes */total` for invalid or out-of-range requests.

### 4. Dashboard Playback UI (`apps/server/static/index.html`)
- Added Evidence section with CSS styling (`.evidence-section`, `.evidence-item`, `.badge-pending`, `.badge-complete`, etc.).
- Displays `Pending upload for <request_id>` with requested interval when evidence is requested but not yet uploaded.
- Embeds `<video controls preload="metadata">` with source `/v1/evidence/{device_id}/{event_id}/{request_id}/media?token={token}` when clip is uploaded.
- Includes "Download clip" link and completeness / actual range badges.

### 5. Testing & Verification (`tests/test_server_evidence.py`)
- Followed TDD (red then green) workflow.
- Tests written:
  - `ServerEvidenceConfigTests`: default value, override, empty validation, config hash.
  - `ServerEvidenceStoreTests`: recording manifest, retrieval, re-review trigger on confirmed review.
  - `ServerEvidenceApiTests`:
    - Atomic PUT upload, checksum verification, receipt payload.
    - Checksum and size mismatch rejection (422).
    - Unauthorized and device mismatch rejection (401, 403).
    - Manifest retrieval (200, 404).
    - Range streaming (200 full, 206 slice, 206 suffix, 416 out-of-bounds, query param token auth).
    - Dashboard UI static delivery and event listing evidence integration.
- Full test suite run with `.venv-oracle/bin/python`: 178 tests passed (100% green).
