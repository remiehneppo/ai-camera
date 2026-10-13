# Implementation Dispatch: Tickets #09 & #20 — 2026-10-13

## 1. Complexity Triage & Collaboration Mode

- **Complexity Level**: L2 (Multi-module, Edge crash-recovery and Backend dataset lineage, parallel subagents, multi-tier acceptance).
- **Collaboration Mode**: `subagent` (explicit route `n9router/ag/gemini-3.8-flash-medium` as requested by user).
- **Interview Clarification & Decisions**:
  - **Q1 (Scope)**: Parallel execution of Ticket #09 (Crash Recovery) and Ticket #20 (Dataset Lineage). Both have all dependencies satisfied (#01, #02, #04, #05, #08 done).
  - **Q2 (Ticket #09 Strategy)**: Active startup sweep on edge/server + lazy check before upload/playback. Clean orphan temp files, handle unfulfillable pins cleanly, resume pending outbox uploads idempotently.
  - **Q3 (Ticket #20 Interface)**: Dual export interfaces: authenticated REST API endpoint (`GET /v1/dataset/export`) + CLI export tool (`python -m apps.server.export_dataset`) outputting JSONL manifests with site/camera/time split and complete version lineage.

## 2. Subagent Task Allocation

### Subagent 1: Ticket #09 — Crash Recovery & Evidence Reconciliation
- **Route**: `n9router/ag/gemini-3.8-flash-medium`
- **Ownership**: Edge & Server crash recovery and reconciliation.
- **Write Scope**:
  - `apps/edge/outbox.py`
  - `apps/edge/uploader.py`
  - `apps/edge/recorder.py`
  - `apps/server/store.py` (server-side evidence reconcile / status)
  - `apps/server/main.py`
  - `tests/test_crash_recovery.py`
  - `.scratch/system-build-slices/issues/09-khoi-phuc-event-evidence-sau-process-crash.md`
- **Requirements**:
  - Implement active startup sweep to scan and reconcile pending/partial evidence requests and orphan temp files (`.tmp`).
  - If ring segments are pruned and cannot fulfill pin, mark request explicitly as `expired` or `partial`/`missing` (no infinite pending, no fake complete).
  - Resume interrupted uploads idempotently with SHA-256 and size verification.
  - On the server side: clean up interrupted temporary files and prevent phantom records.
  - Ensure TDD (red-green) workflow and no regressions to existing tests.

### Subagent 2: Ticket #20 — Feedback Review to Dataset Lineage
- **Route**: `n9router/ag/gemini-3.8-flash-medium`
- **Ownership**: Backend Dataset Export & Audit Lineage.
- **Write Scope**:
  - `apps/server/dataset.py`
  - `apps/server/export_dataset.py`
  - `apps/server/main.py` (add `GET /v1/dataset/export`)
  - `apps/server/store.py` (dataset export queries)
  - `tests/test_dataset_lineage.py`
  - `.scratch/system-build-slices/issues/20-feedback-review-thanh-nhan-dataset-co-lineage.md`
- **Requirements**:
  - Do not overwrite original AI output or confidence; export reviewed corrections as versioned dataset labels.
  - Capture exact `reviewed_event_revision`, `reviewed_event_hash`, `viewed_evidence_versions`, evidence manifest sha256/path, model version, and config hash.
  - Support site/camera/time splitting (e.g. train/val/test splits without cross-camera or cross-time window data leakage).
  - Strip credentials and internal secret tokens from export outputs.
  - Provide both REST endpoint (`GET /v1/dataset/export`) and CLI (`python -m apps.server.export_dataset`).
  - Ensure TDD (red-green) workflow and clean typechecks.

## 3. Verification & Review Protocol
- Subagents execute TDD independently, verify with `.venv-oracle/bin/python -m unittest`, run mypy.
- Dispatcher reviews diffs, checks test logs and runs repository-wide test suite before concluding.
