# Ticket #32 — Retained evidence truy hồi có authorization (software lab)

Ngày 2026-10-24. Blocker #08/#18 đã done nên ticket mở; đây là wave 1 của
[phân rã 2026-10-24](2026-10-24-work-breakdown-next-wave.md).

## Phạm vi đã làm

| Lát cắt | Nội dung |
|---|---|
| Contract | `domain/retrieval_contract.py` — command immutable, allowlist target/action, closed wire field set, state machine pending→claimed→completed/failed/expired, `metadata` ack không release clip |
| Server | `EventStore` issue/claim/acknowledge/settle/view với CAS theo `status`+`lease_id`; 4 route (issue, view, device poll, device ack) |
| Edge | `apps/edge/retrieval.py` — transport HTTP, worker (metadata ack → execute → artifact/failure ack), `RecorderClipRetainer` |

## Quyết định thiết kế

1. **Một contract thuần, ba consumer.** State machine không biết Mongo/HTTP; store chỉ map doc↔state và CAS; route chỉ
   auth + map lỗi; worker chỉ validate + execute + ack. Nhờ vậy race/idempotency test được ở cả ba tầng.
2. **Không remote shell bằng cấu trúc, không bằng kiểm tra.** Wire payload là closed field set; mọi field khớp
   `shell|exec|argv|script|url|endpoint|callback|spawn|pipe|stdin|binary` bị từ chối trước khi tới executor. Ack
   cũng có closed field set theo từng kind.
3. **Metadata ACK ≠ release.** `metadata` chỉ đặt `metadata_acknowledged`; command vẫn `claimed`, clip vẫn còn trên
   đĩa (test API assert file tồn tại + manifest còn). Chỉ `artifact` mới đóng command.
4. **Expiry là cửa sổ side-effect.** Claim sau `expires_at` ⇒ `expired` và **không deliver**; ack muộn sau expiry
   **không** được complete (trả `expired`, không nhận artifact). Nhờ vậy một command không thể "sống lại".
5. **`target=server` do server tự settle**, không đẩy cho device: `GET /v1/retrieval/{id}` probe availability thật
   (`get_evidence(verify_file=True)`) rồi `settle_target` ⇒ `completed` hoặc `failed: evidence_unavailable`. Đây là
   chỗ race cleanup/retrieval được kiểm; manifest receipt vẫn còn sau khi clip bị dọn.
6. **Chỉ `target=edge` được deliver cho device** (filter trong `claim_retrieval`), nếu không command server-target sẽ
   chặn queue của device.
7. **`offline` là trạng thái delivery, không phải quyết định retention**: device chưa poll lần nào ⇒ `offline`; đã poll
   ⇒ `pending`. Với `target=server` bỏ qua device liveness vì server là bên fulfil.

## Bằng chứng chạy thật

- `.venv-oracle/bin/python -m pytest tests/test_retrieval_contract.py tests/test_retrieval_worker.py tests/test_retrieval_api.py -q`
  ⇒ **54 passed** (24 contract + 15 worker/transport + 14 API).
- Full suite: `.venv-oracle/bin/python -m pytest -q` ⇒ **622 passed, 126 subtests** trong 133.18s (baseline 568, +54).
- `mypy domain/retrieval_contract.py apps/edge/retrieval.py apps/server/store.py apps/server/main.py` ⇒ chỉ còn 2 lỗi
  pre-existing (`store.decode_cursor` typing, `FileResponse.content_disposition_type`), không có lỗi mới.
- Coverage theo acceptance: long-poll (wait 0–5s, bounded), auth (reviewer-only issue, device-only poll/ack, dashboard
  token bị từ chối), target allowlist, expiry, replay guard (poll lại sau completed ⇒ không cấp lại; ack lặp cùng
  bytes ⇒ idempotent; khác bytes ⇒ 409 conflict), cleanup→retrieval race (server target + file bị xoá ⇒ failed
  `evidence_unavailable`, manifest receipt còn), metadata ACK không release clip. **Chưa** kiểm: download media
  đồng thời với retrieval (không có test concurrency cho `GET /media`), và long-poll 5s chỉ test ở mức 0.15s.

## Còn mở (không claim)

- SLA/latency trên LAN và long-poll 5s chỉ là **lab bound**, chưa sign-off.
- Worker chưa chạy như daemon trong `EdgeRuntime`; hiện là API + unit cho caller (việc nối vào process thuộc vòng
  hardening runtime).
- UI hiển thị `pending/offline/expired/completed` thuộc #44/#45.
- Chưa kiểm: device thật, mất mạng WAN (#36 sẽ dùng ticket này), nhiều device đồng thời ở tải thật.
