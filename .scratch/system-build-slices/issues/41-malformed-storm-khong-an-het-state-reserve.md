# 41: Malformed storm không ăn hết state reserve

Status: ready-for-agent
Execution: done (software lab; edge storm guard + health integration + media write failure handling pass)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Flood payload sai schema và theo dõi bounded forensic samples/counters/truncation ở edge/health.

**Blocked by:** [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md); [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md).

## Acceptance criteria

- [x] Duplicate compact nhưng valid incident/revision không compact; unique storm có truncation/degraded rõ.
- [x] Quota/limits/rate/counters/retention được kiểm; media không ghi được thì không hứa giữ forensic fact vô hạn.

## Traceability

Task nguồn: J04, H01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-24: Implement phần server ingress (phần edge counter chưa làm, xem dưới).
  `domain/storm_guard.py` — rolling window counter theo outcome (`accepted/duplicate/conflict/malformed/too_large/
  unavailable/rate_limited`), budget riêng cho nhóm malformed, forensic **ring bounded** + `truncated`/
  `dropped_samples`, sample chỉ giữ detail phẳng ≤ `sample_text_bytes` (không payload dump, không secret);
  `admit()` false khi budget hết ⇒ caller trả 429 + `Retry-After` thay vì persist. `duplicate`/`accepted`/
  `unavailable` **không** tiêu budget và **không** tạo sample ⇒ retry của edge không bóp nghẹt traffic hợp lệ;
  valid unique event không bao giờ bị guard từ chối, chỉ hiện truncation/degraded.
  Server: guard ở `app.state.ingest_guard`; middleware body-limit ghi `too_large` (kể cả `Content-Length` sai);
  `POST /v1/events` gọi `admit()` trước khi parse và ghi đúng outcome cho từng nhánh (415/400/422/403/409/503 →
  malformed/conflict/unavailable; 200 → `accepted`, `duplicate` khi revision đã có cùng canonical hash).
  `EventStore.persist` trả `duplicate: true` trên nhánh idempotent (additive, không đổi identity/hash).
  `GET /healthz` thêm `status: degraded|ok` + summary `ingest_guard`; `GET /v1/ingest/guard` (dashboard/reviewer)
  trả snapshot đầy đủ cho operator.
  Evidence: `.venv-oracle/bin/python -m pytest tests/test_storm_guard.py tests/test_storm_api.py -q` ⇒ **17 passed**
  (12 domain + 10 HTTP); full suite ⇒ **643 passed, 126 subtests** (baseline 622). `mypy` các file liên quan chỉ còn
  2 lỗi pre-existing.
  Còn mở: **counter/log phía edge** (`apps/edge/health.py`) cho payload bị từ chối tại edge; chưa inject lỗi
  ghi media (disk full) nên bullet acceptance thứ 2 giữ unchecked; 24h/soak và rate-limit phía proxy chưa đo.
- 2026-10-27: Hoàn tất phần phía edge và media failure handling trong software lab.
  `domain/storm_guard.py`: Hỗ trợ `forensic_sink`, `storage_available` predicate, `record_media_failure` /
  `record_sink_failure`. Khi ghi forensic/media gặp lỗi (`OSError`) hoặc storage hết reserve: guard an toàn
  bỏ qua sample, tăng `dropped_samples` và `sink_failures` (`media_write_failures`), set
  `forensic_storage_degraded: True`, không bao giờ ăn vào state reserve hay crash caller.
  `apps/edge/health.py`: Tích hợp edge `StormGuard`, kiểm tra `_is_storage_available` theo `quota_manager`
  reserve / critical percent. Expose `record_malformed_payload`, `record_ingest_outcome`, `record_media_failure`.
  Khi storm guard bị degraded/truncated/storage degraded: health chuyển `HealthStatus.DEGRADED` với primary
  reason `malformed_storm_detected` (nằm trong `DEGRADED_REASONS`).
  Evidence: `pytest tests/test_storm_guard.py tests/test_storm_api.py tests/test_health.py -q` ⇒ **48 passed**;
  `mypy domain/storm_guard.py apps/edge/health.py` sạch.