# 32: Retained evidence truy hồi có authorization

Status: ready-for-agent
Execution: done (software lab; device channel + server settle tested; real camera/SLA/window khác chưa nghiệm thu)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Người có quyền yêu cầu clip edge/server qua outbound command và thấy pending/offline/expired/completed.

**Blocked by:** [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md); [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md).

## Acceptance criteria

- [x] Long-poll ID/auth/target/expiry/replay guard, retry idempotent; không remote shell/arbitrary executable.
- [x] Cleanup/download/retrieval race được kiểm; metadata ACK không release clip, retention/delete scope rõ.

## Traceability

Task nguồn: R05, T03, UI04.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-24: Implement software lab. Ba lát cắt, cùng một contract thuần:
  `domain/retrieval_contract.py` — command immutable (`command_id/device/issued_by/issued_at/expires_at`), allowlist
  `target ∈ {edge, server}`, `action = retain_clip`, TTL ≤ 3600s, `retention_scope ∈ {clip, metadata}`; wire payload
  là **closed field set** và từ chối mọi field dạng `argv/shell/script/url/exec/stdin/binary` ⇒ không thể thành remote
  shell. State machine: `claim` idempotent trong lease (cùng lease_id, không tăng attempts) và replay-safe (command đã
  completed trả nguyên trạng, không cấp lại); claim sau `expires_at` ⇒ `expired`; ack muộn sau expiry **không** được
  complete. `acknowledge` đóng field set theo từng kind; `metadata` chỉ ghi receipt, **status vẫn mở, clip vẫn giữ**;
  `artifact` complete + idempotent cùng sha256/size, khác bytes ⇒ `artifact_conflict`; `failure` chỉ nhận reason
  allowlist. `server` target do server tự settle từ availability thật.
  Server: `EventStore.issue_retrieval/claim_retrieval/acknowledge_retrieval/settle_server_retrieval/retrieval_view`
  (CAS theo `status`+`lease_id`, index poll; device chưa poll ⇒ `offline`, đã poll ⇒ `pending`). Routes:
  `POST /v1/evidence/{d}/{e}/{r}/retrieval` (reviewer-only + site scope #33), `GET /v1/retrieval/{command_id}`
  (viewer + site scope, settle server-target), `GET /v1/devices/{d}/commands?wait=` (device token, lifecycle check,
  long-poll bounded 5s, chỉ deliver `target=edge`), `POST /v1/devices/{d}/commands/{c}/ack` (409 cho stale
  lease/terminal/conflict, 422 cho input sai).
  Edge: `apps/edge/retrieval.py` — `RetrievalTransport` (HTTPS/loopback, device bearer), `RetrievalWorker`
  (validate payload → ack `metadata` → execute → ack `artifact`/`failure`; command completed không chạy lại),
  `RecorderClipRetainer` (idempotent `finalize_pin`, thiếu/released pin ⇒ `evidence_unavailable`).
  Evidence: `.venv-oracle/bin/python -m pytest tests/test_retrieval_contract.py tests/test_retrieval_worker.py
  tests/test_retrieval_api.py -q` ⇒ **53 passed**; full suite ⇒ **622 passed, 126 subtests** (baseline 568).
  `mypy domain/retrieval_contract.py apps/edge/retrieval.py apps/server/store.py apps/server/main.py` ⇒ chỉ còn 2 lỗi
  pre-existing (`store.decode_cursor` line 114, `FileResponse.content_disposition_type` line 691), ngoài scope.
  Còn mở (không claim): SLA/latency trên LAN, long-poll 5s là lab bound chưa sign-off, worker loop/daemon chưa nối
  vào runtime process, và chưa có UI hiển thị pending/offline/expired/completed (thuộc #44/#45).

- 2026-10-24 (review round): rà lại slice này (chưa từng được review) bằng probe + đọc code; sửa 2 defect:
  1. `RetrievalWorker` **không kiểm `target`**: một server lỗi/độc hại gửi `target=server` sẽ bị chạy bằng executor
     của edge. Nay worker có `SUPPORTED_TARGETS = {edge}` và ack `unsupported_target` (reason đã có trong enum nhưng
     trước đó không reachable) mà không chạy executor.
  2. `retention_scope="metadata"` **không bao giờ complete được** (metadata ack không terminalise, mà edge executor
     chỉ tạo được artifact clip) ⇒ field chết, và nếu ép complete thì phải bịa artifact. Nay `issue_command` từ chối
     scope chưa implement (`retention_scope_not_supported`, HTTP 422), worker ack
     `retention_scope_unsupported` nếu nhận command cũ từ server khác; `validate_command_payload` vẫn parse được
     payload đó để device từ chối có kiểu.
  Đã kiểm không phải lỗi: 6 thread `issue_retrieval` đồng thời cho cùng evidence/target ⇒ **1** command (khoá dedupe
  theo identity đang mở giữ đúng); claim lần hai trong lease trả cùng `lease_id`; re-issue giữ TTL của command đang mở
  (idempotent theo identity, TTL mới bị bỏ — đã ghi rõ trong docstring).
  Evidence: `pytest tests/test_retrieval_contract.py tests/test_retrieval_worker.py tests/test_retrieval_api.py -q` ⇒
  **56 passed**; full suite ⇒ **667 passed, 126 subtests**. `mypy` các file liên quan chỉ còn 2 lỗi pre-existing.
  Ghi nhận chưa sửa: flood 422 vào route retrieval không đi qua storm guard (#41 chỉ áp `/v1/events`);
  `GET /v1/retrieval/{id}` với target=server có side-effect ghi manifest (qua `get_evidence(verify_file=True)`).
