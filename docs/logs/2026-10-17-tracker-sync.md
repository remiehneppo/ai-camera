# 2026-10-17 — Luồng A: đồng bộ tracker slices

Phạm vi ghi: `.scratch/system-build-slices/PRD.md`, `issues/{08,09,13,15,16,17,18,22,24,26}-*.md`, log này. Không sửa source/tests; không đụng #04/#21/#23, uploader, SQLite.

## Kiểm chứng
- Code tồn tại (grep `apps/`; codegraph index không phủ các symbol Python này, trả "No results"): `reconcile_and_cleanup` (outbox.py, uploader.py), `cleanup_temp_evidence` (server/store.py), `LivePerceptionRunner` (live_pipeline.py), `EdgeHealthMonitor` (health.py), `StorageQuotaManager` (quota.py), `RtmposeEstimator`/`PoseScheduler`/`PoseManager` (pose.py), `person_lying_persistent` (incident.py).
- Lệnh: `.venv-oracle/bin/python -m pytest -q -x tests/test_crash_recovery.py tests/test_edge_uploader.py tests/test_server_evidence.py tests/test_live_pipeline.py tests/test_rtsp_pipeline.py tests/test_rtsp.py tests/test_edge_runtime.py tests/test_health.py tests/test_quota.py tests/test_pose.py tests/test_tracking_incident.py` → **188 passed**, 45 warnings (FastAPI `on_event` deprecated), 65s. Không chạy mypy, camera, power-cut.

## Quyết định
| # | Trước (PRD) | Sau | Lý do |
|---|---|---|---|
| 09 | done | done (software lab) | test crash/uploader/server pass |
| 13 | done | done (Python, chưa native C++) | implementation `tracker.py` Python; native còn #10/#12 |
| 15 | not-started | **partial** | code + test live pass; acceptance chưa tích (stream ADR, actual ranges, reconnect/codec change thật không có artifact). Ticket header trước ghi "done (live camera verified)" — hạ xuống vì thiếu bằng chứng |
| 16 | not-started | done (software) | test_edge_runtime pass; chưa SIGKILL thực |
| 17 | not-started | done (software) | test_health pass; ODD đầy đủ ở #21 |
| 18 | not-started | done (software) | test_quota pass; chưa disk-pressure/24h thật |
| 22 | not-started | done (software) | test_pose pass |
| 24 | not-started | done (software) | test_pose pass; pose chưa vào IncidentEngine |
| 26 | not-started | done (software) | test_tracking_incident pass; anchor đã sửa 15-10 |

- #08: bảng done là đúng (uploader/server tests pass); sửa đoạn "Cách chọn việc" và đánh dấu đoạn đó là snapshot 12-10. #07 vẫn partial.
- Status triage giữ nguyên (ready-for-review, needs-info...). Không đóng gate G1–G5; "done" nghĩa là software lab, không phải nghiệm thu.
- Còn lệch: #15 `needs-info` ở bảng/PRD vs ticket `ready-for-review`; #19 vẫn bị chặn bởi #04 (luồng khác) và #15 partial.
