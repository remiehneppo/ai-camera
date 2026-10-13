# 09: Khôi phục event/evidence sau process crash

Status: ready-for-review
Execution: completed
Owner: edge-backend-crash-recovery

**What to build:** Restart edge/server giữa các bước commit và upload; detail phản ánh đúng clip còn, thiếu, partial hoặc corrupt.

**Blocked by:** [#05: Retry và revision không làm mất hoặc lùi event](05-retry-va-revision-khong-lam-mat-hoac-lui-event.md); [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md).

## Acceptance criteria

- [x] Inject pending/temp/final/orphan/missing/corrupt và uploading unknown response; reconcile có expected state.
- [x] Không DB complete giả khi file thiếu; không orphan tăng vô hạn, dữ liệu protected giữ và faults rõ.
- [x] Crash event commit→pin, recorder ACK→edge receipt và recorder reboot đều reconcile được theo request ID; không unowned pin hoặc pending vô hạn khi ring đã hết.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: J04, R03, E02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-13: Hoàn thành Ticket #09 - Khôi phục event/evidence sau process crash:
  1. Edge Crash Reconciliation:
     - Thêm `reconcile_and_cleanup(outbox, recorder)` trong `apps/edge/uploader.py` và `apps/edge/outbox.py`.
     - Hỗ trợ gọi độc lập hoặc qua `EdgeUploader.upload_pending(reconcile=True)`.
     - Quét và dọn dẹp các tệp tạm mồ côi (`*.tmp*`, `*.concat`) trong thư mục clips / recorder.
     - Xử lý các request ở trạng thái `pending` / `in_progress` / `requested` / `collecting`:
       - Kiểm tra clip trên đĩa: nếu toàn vẹn (đúng SHA-256 và size), chuyển sang `'fulfilled'` sẵn sàng upload.
       - Nếu clip bị hỏng (sai SHA-256 hoặc size), chuyển sang `'failed'` với lỗi `clip corrupted`.
       - Nếu clip chưa tồn tại và ring buffer đã bị xoay/hết (pruned), chuyển sang `'failed'` với `last_error='ring segments expired'` tránh treo `pending` vĩnh viễn.
     - Upload resumption: Cho phép tiếp tục upload sau khi rớt mạng / lỗi 503, tự kiểm tra SHA-256 và cập nhật idempotent.
  2. Server Crash Reconciliation:
     - Thêm hàm dọn dẹp `cleanup_temp_evidence(evidence_dir)` chạy khi startup `create_app` hoặc gọi trực tiếp, xóa sạch các file tạm `.tmp`.
     - Trong endpoint manifest và media playback (`/media`): Kiểm tra tệp tin trên đĩa; nếu tệp bị thiếu hoặc hỏng checksum/size, trả về 404 và cập nhật trạng thái `missing`/`corrupt`, không trả về fake complete hay gây unhandled exception.
  3. Tests & Verification:
     - TDD: `tests/test_crash_recovery.py` bao gồm 8 test cases kiểm thử đầy đủ các kịch bản crash, orphan cleanup, expired ring segments, corrupt media, và network drop recovery.
     - Unit tests: `.venv-oracle/bin/python -m unittest tests/test_crash_recovery.py -v` -> 8/8 tests pass.
     - Regression tests: `.venv-oracle/bin/python -m unittest tests/test_edge_uploader.py tests/test_server_evidence.py` -> 22/22 tests pass.
     - Typecheck: `.venv-oracle/bin/mypy --follow-imports=silent apps/edge/outbox.py apps/edge/uploader.py apps/edge/recorder.py tests/test_crash_recovery.py` -> Success: no issues found.
