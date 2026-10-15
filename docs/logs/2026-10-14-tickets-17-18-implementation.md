# Implementation & Review Log — Tickets #17 & #18 (2026-10-14)

## Context & Objectives
Triển khai Khối Giám sát Sức khỏe & Quản lý Bộ nhớ bao gồm:
1. **Ticket #17: Health phản ánh khả năng quan sát thực** (`.scratch/system-build-slices/issues/17-health-phan-anh-kha-nang-quan-sat-thuc.md` / Task H01):
   - Trạng thái sức khỏe trung thực: `starting`, `healthy`, `degraded`, `unavailable` với `reason` và `capabilities`.
   - Độ tươi frame trung thực: khi không có ánh xạ đồng hồ camera hợp lệ, báo cáo `receive_age` với `clock_mapping_valid=False`, không bịa đặt capture age.
   - Bắt lỗi treo/deadlock/chết tiến trình analytics, đứt đoạn recorder gap, đĩa đầy, mất kết nối backend.
   - Ẩn thông tin nhạy cảm (`redact_rtsp_url`), giới hạn metric labels cố định (`component`, `status`, `reason` - không dùng `event_id`/`frame_id`), bộ đệm telemetry có dung lượng hữu hạn không chiếm vùng lưu trữ trạng thái.
2. **Ticket #18: Quota bảo vệ pinned evidence và journal** (`.scratch/system-build-slices/issues/18-quota-bao-ve-pinned-evidence-va-journal.md` / Tasks R04, R05, J01):
   - Kế toán bộ nhớ đa lớp: `ring_bytes`, `pinned_bytes`, `temp_bytes`, `wal_bytes`, `free_bytes`, `total_bytes`, `used_percent`.
   - Dọn dẹp khẩn cấp khi đĩa đạt ngưỡng cảnh báo ($\ge 90\%$): xóa temp mồ côi và segment ring unpinned cũ nhất.
   - **Bảo vệ tuyệt đối bằng chứng chưa ACK (unACK)**: không bao giờ xóa clip/segment chưa được server xác nhận, kể cả khi mất mạng WAN kéo dài $> 24\text{h}$.
   - Vùng bảo vệ trạng thái (`min_state_reserve_bytes = 50MB`): khi đĩa $\ge 95\%$ hoặc hết reserve, từ chối tạo clip mới với lỗi `storage_exhausted` / `reserve_exhausted`, không cấp commit hoặc ACK giả.

## Delegation & Model Routing
- Điều phối viên phân rã task book chi tiết và giao Subagents với route:
  - `onechain/Gemini 3.8 Flash (High)` (Ticket #17)
  - `onechain/Gemini 3.8 Flash (High)` (Ticket #18)
- Cả hai subagent tuân thủ TDD và Karpathy Guidelines.

## Implementation Details
1. **`apps/edge/health.py`**:
   - `EdgeHealthMonitor`: đo lường frame age, frame drops, recorder gaps, disk metrics từ quota manager, outbox pending count, backend connectivity.
   - Phân tích trạng thái sức khỏe đa chiều, phát hiện queue stall, analytics failure, recorder gap, disk near capacity, disk exhausted.
2. **`apps/edge/quota.py`**:
   - `StorageQuotaManager`: kiểm kê chi tiết dung lượng lưu trữ, dọn dẹp file eligible khi có áp lực bộ nhớ, bảo toàn unACK evidence, kiểm tra hạn mức cho evidence mới (`can_accept_new_evidence`).
3. **`apps/edge/evidence.py`**:
   - Tích hợp kiểm tra quota trước khi pin/finalizing clip. Khi đĩa cạn kiệt, đánh dấu request `failed` với lý do `storage_exhausted`, xử lý lỗi `ENOSPC` mà không sinh ACK giả.
4. **`apps/edge/pipeline.py` & `apps/edge/live_pipeline.py`**:
   - Tích hợp `health` monitor và đồng bộ giữa Live Runner và Perception Pipeline.

## OpenCodeReview (OCR) Findings & Remediation
- Quét commit `882d843` bằng `open-code-review` CLI (`ocr review -c 882d843`, Session: `57b92352-5c30-42de-bcee-b540d62ee4ab`, Model: `Gemini 3.8 Flash (High)`):
  - **Kết quả tổng quan**: 5 files reviewed (`apps/edge/quota.py`, `apps/edge/health.py`, `apps/edge/evidence.py`, `apps/edge/pipeline.py`, `apps/edge/live_pipeline.py`), 17 findings.
  - **Các phát hiện quan trọng (High / Medium)**:
    1. *High*: `apps/edge/quota.py:365-380` — `cleanup_eligible()` purge unpinned segments không kiểm tra ngưỡng phục hồi áp lực và sort theo từng session thay vì global FIFO.
    2. *High*: `apps/edge/health.py:236-252` — `get_health_snapshot()` giữ `self._lock` khi thực thi các tác vụ I/O đĩa/mạng, có thể gây frame drop / lock contention trong realtime pipeline.
    3. *High*: `apps/edge/evidence.py:97-104` — `can_accept_new_evidence()` đánh fail request đang ở trạng thái `collecting` trước khi hoàn tất window.
    4. *High*: `apps/edge/health.py:287-295` — `capabilities["recorder"] = "gap_detected"` ghi đè trước khi kiểm tra `recorder_cap`, che lấp lỗi thành phần recorder.
    5. *Medium*: `apps/edge/quota.py:83-88` — `sqlite3.connect` dùng context manager không đóng connection, gây leak file descriptors trong `_get_active_pins()`.
    6. *Medium*: `apps/edge/quota.py:130-134` — `recorder_root` fallback phụ thuộc `manifests.is_dir()` khởi tạo trễ, khiến `ring_bytes` bị tính là 0 khi chưa có manifest.
    7. *Medium*: `apps/edge/health.py:198-207` — `_measure_recorder_gap()` tính gap pairwise mà chưa sort segments theo `start_seconds`.
    8. *Medium*: `apps/edge/health.py:156-163` — `_mask_secrets_in_obj()` lọc substring `"key"` gây false-positive cho `"keyframe_pts"`.
    9. *Medium*: `apps/edge/health.py:328-328` — `primary_reason` chọn `reasons[0]` theo thứ tự duyệt thay vì mức độ ưu tiên theo severity (UNAVAILABLE > DEGRADED > STARTING).
    10. *Medium*: `apps/edge/quota.py:121-127` — `seen_wal_files` không chuẩn hóa `.resolve()`, có thể trùng lặp file giữa relative và absolute paths.
    11. *Medium*: `apps/edge/quota.py:277-279` — Công thức `projected_used_bytes` tính cả root-reserved blocks, lệch so với `breakdown.used_percent`.
    12. *Maintainability*: Redundant cleanup call trong `evidence.py:72`, unused import `os` trong `health.py` và `quota.py`, unused import `EvidenceLifecycle` trong `live_pipeline.py`, unused `_total_frames_received` và `_manual_status` trong `health.py`.
  - **Khắc phục toàn diện (Remediation Applied)**:
    - `apps/edge/quota.py`: Quản lý connection SQLite bằng `contextlib.closing`, chuẩn hóa `.resolve()` cho file WAL, tính `projected_used_bytes` nhất quán từ `breakdown.used_percent`, gom tập `all_eligible_segments` toàn cục sắp xếp FIFO theo `s_start`, tính toán ngân sách dung lượng cần giải phóng `target_bytes_to_reclaim` để xả tải lũy tiến, loại bỏ import `os` thừa.
    - `apps/edge/health.py`: Tách đo lường đĩa/mạng/recorder ngoài lock, sắp xếp segment theo `start_seconds` khi đo gap, tinh chỉnh pattern nhận diện secret tránh false-positive trên `keyframe_pts`, kiểm tra `recorder_cap` trước khi gán `gap_detected`, phân định `primary_reason` theo độ nghiêm trọng trạng thái (UNAVAILABLE > DEGRADED > STARTING), đưa `total_frames_received` vào snapshot metrics, loại bỏ biến thừa `_manual_status`/`_manual_reason` và import `os`.
    - `apps/edge/evidence.py`: Chuyển vị trí guard `can_accept_new_evidence()` trong `_reconcile` về ngay trước `finalize_pin`, không đánh fail oan các request đang thu thập (`collecting`); đồng bộ danh sách file dọn dẹp từ `cleanup_eligible()`.
    - `apps/edge/live_pipeline.py`: Loại bỏ import không sử dụng `EvidenceLifecycle`.

## Verification Evidence
- `tests.test_health`: 16/16 tests passed.
- `tests.test_quota`: 9/9 tests passed.
- `tests.test_architecture_deepening`: 14/14 tests passed.
- `tests.test_pose`: 24/24 tests passed.
- `tests.test_live_pipeline`: 10/10 tests passed.
- Mypy: 0 errors trên toàn bộ 4 files mã nguồn (`apps/edge/quota.py`, `apps/edge/health.py`, `apps/edge/evidence.py`, `apps/edge/live_pipeline.py`).
