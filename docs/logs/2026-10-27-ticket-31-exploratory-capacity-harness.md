# Ticket #31 — Exploratory capacity harness — 2026-10-27

## Phạm vi (người dùng chốt)
- Làm **exploratory profiling** theo đúng delta của #31: "Exploratory profiling/measurement được chạy trước signed G2
  với workload và missing gates ghi rõ; số đo exploratory không được ghi thành accepted capacity".
- **Không** ký capacity, **không** soak 24–72h, **không** claim accepted.
- #31 là một trong hai ticket dependency-sạch (#28, #18 done; target ONNX nên không kích hoạt #30/#54/#55/#56).

## Nguyên tắc: chỉ báo cáo cái đo được
Sau review, harness được viết lại để **không con số nào là suy diễn**. Mỗi trục có nguồn thật hoặc bị đánh dấu `unmeasured`:

| Trục | Nguồn thật | Ghi chú |
|---|---|---|
| latency (P99) | đo quanh `process_frame` | mean/p50/p90/p95/p99/max |
| skipped_frames | `last_observation["detection_status"]` | đổi tên từ `dropped_frames` vì trước đó là proxy sai |
| fsync | wrapper đếm `os.fsync` thật trong lúc chạy | có test chứng minh bộ đếm hoạt động |
| WAL | `PRAGMA journal_mode` + kích thước `-wal` | |
| storage/headroom | `quota_manager.get_storage_breakdown()` | |
| coverage/gaps | `recorder.actual_range()` | không có span ⇒ `unmeasured`, không trả 0 |
| pose | `pipeline.get_pose_metrics()` | rỗng ⇒ `unmeasured` + reason |
| queue | `outbox.pending()` | `drops: None` + reason vì EventOutbox không có counter |
| upload | drainer đếm cả `drains` và `failed_drains` | lỗi không bị nuốt |

`ingest_fps` được ghi kèm `ingest_fps_scope = "synthetic ingest loop; excludes decode and inference"` để không bị đọc
thành throughput thật. CLI rỗng (nhận `--frames`/`--output` rồi bỏ qua) đã bị xoá.

## Thay đổi
- `apps/edge/capacity_lab.py` (mới): `percentiles`, `gap_totals`, `_FsyncCounter`, `_UploadDrainer`, `run_lab`.
- `tools/run_benchmark.py`: bỏ `calculate_percentiles` trùng lặp, dùng chung helper có p99; **thêm cột P99 cho mọi dòng**
  (trước đó chỉ dòng tổng có p99 nên Max/Mean của 5 dòng stage bị đẩy sang cột sai); bỏ `import numpy` không còn dùng.
- `tests/test_capacity_lab.py` (mới): 12 test.

## Kiểm chứng
- `.venv-oracle/bin/python -m pytest tests/test_capacity_lab.py -q` ⇒ **12 passed**.
- `.venv-oracle/bin/python -m pytest -q` ⇒ **843 passed, 360 warnings, 126 subtests**.
- `.venv-oracle/bin/python -m mypy apps/edge/capacity_lab.py tools/run_benchmark.py` ⇒ **Success: 2 source files**.
- `git diff --check` sạch.

## Review hai trục và cách xử lý
- Standards (`7bd627a6`): 1 lỗi cứng — bảng benchmark lệch cột sau khi thêm P99 (Max hiển thị dưới P99, Mean dưới Max);
  đã sửa cho cả 5 dòng stage. Sửa thêm: unused `numpy`, docstring thiếu p90, CLI bỏ qua tham số.
- Spec (`2355e5c0`): chỉ ra nhiều chỗ "báo cáo như đã đo nhưng không đo" — `dropped_frames` là proxy,
  `queue` vốn không thể khác 0, coverage trả 0 cạnh nhãn unmeasured, pose rỗng. Đã sửa toàn bộ theo bảng trên.

## Còn mở (không claim)
- **Chưa chạy profile thật**: chưa có workload manifest, chưa có số đo nào được tạo.
- Chưa soak 24–72h, thermal/power, fsync/WAL endurance dài hạn.
- Chưa có actual target SKU/RAM/OS/SDK; conformance decode/buffer trước soak chưa chạy.
- Multi-camera concurrency/fairness chưa đo (harness profile một camera).
- `drops` chưa đo được vì EventOutbox không có counter — cần instrumentation riêng nếu muốn ký.
- Pose axis chỉ đo khi pipeline có pose manager; run mặc định là `unmeasured`.
