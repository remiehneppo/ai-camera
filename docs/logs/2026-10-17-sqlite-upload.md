# 2026-10-17 — SQLite version check và upload 413 (luồng B)

## Thay đổi
- `apps/edge/doctor.py`: `sqlite_wal_reset_check()`; `preflight` thêm `capabilities.sqlite` và cảnh báo stderr, không đổi `status`.
- `apps/edge/uploader.py`: `UploadPayloadTooLarge`; HTTP 413 raise ngay, không retry.
- `apps/edge/evidence.py`: bắt lỗi đó trong `_upload` -> `state=failed`, receipt `operational_fault=upload_413_payload_too_large`, `last_error`. Không ack, không release pin. `_reconcile` bỏ qua request failed có `operational_fault`, nên không bị hồi sinh.
- Tests: `tests/test_edge_uploader.py` (2 test 413), `tests/test_edge_doctor.py` (2 test SQLite).

## Kiểm tra read-only phiên bản
- `/usr/bin/python3` 3.12.3: SQLite 3.45.1. `.venv-oracle/bin/python` 3.12.3: 3.45.1. Không có venv khác. libsqlite3-0 `3.45.1-1ubuntu2.8`.
- Nhánh 3.45 không có bản backport công bố; chưa xác nhận Ubuntu backport. Trạng thái: chưa xác minh vá, cảnh báo.

## Kết quả test (`.venv-oracle`)
- uploader+doctor: 22 passed, 3 skipped (python3 hệ thống).
- Nhóm liên quan (uploader, doctor, evidence_lifecycle, crash_recovery, quota, event_delivery, health, recorder): 138 passed, 2 failed.
- 2 fail: `test_crash_recovery::test_server_{corrupt,missing}_media_file_handling` (server/MongoDB), không thuộc phạm vi sửa; chưa điều tra nguyên nhân.
- Full suite: 309 passed, 1 failed, dừng sớm (-x) ở `test_review_fixes::...concurrent_different_uploads...`. `test_review_fixes.py` chạy riêng: 11 fail khi có thay đổi, 10 fail khi stash (baseline). Hai lần chạy có cây làm việc khác nhau (do luồng khác sửa server/pipeline), nên không kết luận được lỗi này có từ trước hay không.
- Python hệ thống thiếu deps nên không chạy được full suite.

## Giới hạn
- Chưa pin SQLite đã vá. Chưa có max-artifact sizing. Không sửa tracker/pipeline/tracker/incident/server.
