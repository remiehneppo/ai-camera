# Implementation Log: Storage Resiliency and Quota Improvements

**Date:** 2026-10-15  
**Scope:** Fix P1-03, P1-02, P2-01, P2-02, P2-03 from `docs/logs/2026-10-15-full-flow-code-review.md`.  
**Target Files:**
- `apps/edge/recorder.py`
- `apps/edge/quota.py`
- `apps/edge/evidence.py`
- `tests/test_recorder.py`
- `tests/test_quota.py`
- `tests/test_evidence_lifecycle.py`
- `tests/test_crash_recovery.py`

---

## 1. Objectives & Architectural Context
- **P1-03:** In `apps/edge/recorder.py`, `finalize_pin` must not hold SQLite `BEGIN IMMEDIATE` across ffmpeg concat + sha256. Heavy I/O is moved outside the transaction. Only hold SQLite write lock when checking state and recording final receipt, preserving atomicity and idempotency per `request_id`, without allowing `_prune` to delete pinned segments. Concurrently, `_prune()` must catch `sqlite3.OperationalError` (database is locked), log a warning and skip the cycle, preventing publisher failure from stopping ffmpeg ingest.
- **P1-02:** `cleanup_storage()` must reclaim `manifests/<hash>.mkv|.json` for pins that are `released=1` AND acknowledged via transfer receipt in `transfers`, only when space is needed (`target_bytes` or forced). Must never delete unACKed pins or unknown files. Fail-closed on SQLite query errors. Update `quota.py` `pinned_bytes` accounting accordingly.
- **P2-01:** `evidence.py` must pass `estimated_bytes` (total segment size in actual range) to `can_accept_new_evidence`.
- **P2-02:** `quota._get_active_pins` on error must mark metric degraded instead of returning `{}` silently.
- **P2-03:** Wrap all `sqlite3.connect` calls in `recorder.py` with `contextlib.closing`.

---

## 2. Implementation Decisions & Details

### 2.1 P1-03: finalize_pin transaction splitting & prune resilience
- In `apps/edge/recorder.py`:
  - Added per-pin mutexes (`self._finalize_lock`, `self._pin_locks: dict[str, threading.Lock]`) and in-flight tracking (`self._finalizing: set[str]`).
  - `finalize_pin(request_id)` acquires `pin_lock`. Under the lock, it conducts transaction 1 (check existing manifest/orphan, verify post-roll, gather segments).
  - Heavy I/O (ffmpeg concat `-c:v copy` and sha256 calculation of output clip and constituent segments) runs OUTSIDE SQLite transaction.
  - While heavy I/O is running, `request_id` is tracked in `self._finalizing` so `cleanup_storage()` and `cleanup_evidence_temps()` skip scratch files being actively written.
  - Transaction 2 records the final receipt into SQLite with `BEGIN IMMEDIATE` and verifies pin validity.
  - `release_pin(request_id)` synchronizes on `pin_lock` to ensure in-flight finalization completes before release, preventing `_prune` from unlinking segments during ffmpeg read.
  - In `_prune(session_id, *, timeout=5.0)`: wrapped with `try...except sqlite3.OperationalError as exc: logger.warning(...)`. A locked database logs a warning and skips the cycle; `_publish_closed` will not fail and ffmpeg ingestion will not be terminated.

### 2.2 P1-02: cleanup_storage manifest reclamation & quota accounting
- In `apps/edge/recorder.py:cleanup_storage`:
  - Queries `SELECT request_id FROM transfers` to determine acknowledged pins.
  - Collects `eligible_manifests` for pins where `released == 1` and `request_id in acked_ids`.
  - Cleans scratch first, then unpinned ring segments (FIFO), then eligible released+ACKed manifests if `cleaned_bytes < target_bytes` (or if forced).
  - Preserves unreleased pins (`released == 0`), released but unACKed pins, and all unknown files.
  - Entire inspection and delete loop runs inside the immediate transaction; any SQLite operational error fails closed without deleting files.
- In `apps/edge/quota.py:get_storage_breakdown`:
  - Queries `pins` JOIN `transfers` for pins with `released = 1` to find released and acknowledged hashes.
  - Files in `manifests/` matching released+ACKed hashes are categorized as `ring_bytes` (reclaimable storage).
  - Unreleased, unACKed, or unknown manifests remain classified as `pinned_bytes`.

### 2.3 P2-01: estimated_bytes in can_accept_new_evidence
- In `apps/edge/evidence.py`:
  - Added `_estimate_segment_bytes(request)` to compute total byte size of segments falling within `[requested_start, requested_end]`.
  - Added `_can_accept_evidence(estimated_bytes)` to pass `estimated_bytes` to `self.quota_manager.can_accept_new_evidence(estimated_bytes)` with fallback for parameterless mocks.
  - Both `persist()` and `_reconcile()` compute `estimated_bytes` and pass it before accepting or finalizing evidence requests.

### 2.4 P2-02: degraded metric on SQLite error in quota
- In `apps/edge/quota.py`:
  - Added `degraded: bool = False` and `degraded_reason: str | None = None` to `StorageBreakdown` and `StorageQuotaManager`.
  - `_get_active_pins` sets `self.degraded = True` and records `self.degraded_reason` when catching `(sqlite3.Error, OSError)`.
  - `StorageBreakdown.to_dict()` surfaces `degraded` and `degraded_reason`.

### 2.5 P2-03: contextlib.closing for all sqlite3.connect
- Every single call to `sqlite3.connect` in `apps/edge/recorder.py` (12 sites total) is now enclosed in `with contextlib.closing(sqlite3.connect(...))`.

---

## 3. Test Additions
- `tests/test_recorder.py`:
  - `test_prune_database_locked_logs_warning_and_skips_without_failing_publisher`: verified that locking the SQLite DB during `_prune` logs a warning and does not raise or kill the publisher process in `_publish_closed`.
  - `test_finalize_pin_does_not_hold_sqlite_lock_during_ffmpeg_and_hashing`: verified that an external write transaction can execute `BEGIN IMMEDIATE` while ffmpeg is running inside `finalize_pin`.
- `tests/test_quota.py`:
  - `test_cleanup_storage_reclaims_released_and_acked_manifests`: verified that released+ACKed manifests are reclaimed, while unreleased manifests, released-unACKed manifests, and unknown files are strictly preserved.
  - `test_quota_pinned_bytes_excludes_released_and_acked_manifests`: verified that released+ACKed manifests count toward `ring_bytes` (reclaimable) and not `pinned_bytes`.
  - `test_get_active_pins_error_marks_metric_degraded`: verified that SQLite query failure sets `degraded=True` and populates `degraded_reason`.
- `tests/test_evidence_lifecycle.py`:
  - `test_can_accept_new_evidence_receives_estimated_bytes_from_actual_range`: verified that `persist()` passes the exact segment bytes sum to `can_accept_new_evidence`.
  - `test_reconcile_calls_can_accept_new_evidence_with_estimated_bytes`: verified that `reconcile()` passes `estimated_bytes` when evaluating finalization.

---

## 4. Verification & Pytest Output
Executed command:
`PYTHONPATH=. .venv-oracle/bin/pytest tests/test_recorder.py tests/test_quota.py tests/test_evidence_lifecycle.py tests/test_crash_recovery.py -q`

Output:
```
........................................................... [ 75%]
...................                                         [100%]
78 passed, 9 warnings, 21 subtests passed in 35.26s
```
All 78 tests passed. No regressions. Working tree uncommitted changes preserved.
