# Ticket #41 — Malformed storm không ăn hết state reserve (server slice)

Ngày 2026-10-24. Blocker #18/#05 đã done. Slice này làm **phía server ingress**; counter phía edge để lại.

## Phạm vi

| Lát cắt | Nội dung |
|---|---|
| Contract thuần | `domain/storm_guard.py` — rolling window, budget malformed riêng, forensic ring bounded, truncation/degraded |
| Server | `app.state.ingest_guard`; `POST /v1/events` admit + ghi outcome từng nhánh; middleware body-limit ghi `too_large`; `GET /healthz` + `GET /v1/ingest/guard` |
| Store | `persist` trả `duplicate: true` trên nhánh idempotent (additive) để route phân biệt retry với việc mới |

## Quyết định thiết kế

1. **Budget chỉ áp cho nhóm malformed.** `accepted/duplicate/unavailable` không tiêu budget, không tạo sample —
   nhờ vậy edge retry (dedup) không thể tự bóp nghẹt traffic hợp lệ. Đây chính là bullet "duplicate compact nhưng
   valid incident/revision không compact".
2. **Không từ chối dữ liệu hợp lệ.** Guard không bao giờ chặn event unique hợp lệ; storm unique thể hiện bằng
   `truncated` + `dropped_samples` + `degraded`, không bằng mất dữ liệu im lặng.
3. **Forensic sample là dữ liệu bounded, không phải payload.** Chỉ giữ `outcome/device_id/size_bytes` + detail
   phẳng ≤ 240 byte, tối đa 4 key; nested/oversize bị bỏ, không truncate giữa key (test khoá hành vi này).
4. **429 thay vì ghi tiếp.** Khi budget hết, route trả 429 + `Retry-After` **trước khi** parse/persist, nên reserve
   không tăng; mỗi lần từ chối vẫn được đếm (`rate_limited`) để operator thấy flood kéo dài.
5. **Healthz tách readiness khỏi degradation.** `/healthz` vẫn 200 khi DB ok nhưng `status = degraded` +
   summary `ingest_guard`; snapshot đầy đủ ở `/v1/ingest/guard` (dashboard/reviewer).
6. **`duplicate` đến từ nguồn sự thật.** `EventStore.persist` biết chắc key+canonical hash đã tồn tại; route không
   đoán lại từ response. Key mới là additive nên không đổi identity/hash/receipt cũ.

## Bằng chứng chạy thật

- `.venv-oracle/bin/python -m pytest tests/test_storm_guard.py tests/test_storm_api.py -q` ⇒ **22 passed**
  (12 domain + 10 HTTP).
- Full suite ⇒ **643 passed, 126 subtests** trong 138.24s (baseline 622, +21).
- `mypy apps/server/main.py apps/server/store.py domain/storm_guard.py` ⇒ chỉ 2 lỗi pre-existing.
- HTTP-level đã kiểm: flood 3 malformed → 429 + Retry-After; duplicate không tiêu budget và không có forensic;
  6 event unique với budget 2 vẫn 200 hết; 415/422 đều vào `malformed`; payload > `MAX_EVENT_BYTES` → 413 +
  `too_large` với `size_bytes`; `/healthz` degraded; `/v1/ingest/guard` cần credential; rollover window trả lại
  budget.

## Còn mở

- **Edge counter** (`apps/edge/health.py`) cho payload/command bị từ chối tại edge — chưa làm, nên ticket giữ
  `partial`.
- Bullet acceptance thứ 2 giữ unchecked: chưa inject lỗi ghi media (disk full) nên chưa chứng minh "media không ghi
  được thì không hứa giữ forensic fact vô hạn".
- Rate limit phía proxy/WAF và soak 24h ngoài scope.
