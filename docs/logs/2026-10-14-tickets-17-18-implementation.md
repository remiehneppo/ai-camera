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
- Quét qua `ocr review` với model `Gemini 3.8 Flash (High)`:
  1. *Health status guard*: Không để gán `DEGRADED` vô tình ghi đè trạng thái `UNAVAILABLE` hoặc `STARTING`.
  2. *I/O Lock latency*: Tránh gọi `get_storage_breakdown()` nhiều lần khi đang giữ `_lock` trong `get_health_snapshot()`.
  3. *Critical usage projection*: Đưa `estimated_bytes` vào tính toán tỷ lệ phần trăm dung lượng đĩa trước khi chấp nhận clip mới.
  4. *Active segment protection*: Không unlink nhầm các file `.segment-*.part.mkv` đang được ghi active trong lúc cleanup.
  5. *Dead code removal*: Xóa hàm `_get_acknowledged_request_ids` không được sử dụng.
  6. *Health synchronization*: Đồng bộ tham chiếu `health` giữa `LivePerceptionRunner` và `PerceptionPipeline`.
  7. *Backend checker*: Truyền `backend_checker=uploader` vào `EdgeHealthMonitor` mặc định trong pipeline.

## Verification Evidence
- `tests.test_health`: 16/16 tests passed.
- `tests.test_quota`: 9/9 tests passed.
- Core regression suite (117 tests): 117/117 tests passed (17.481s).
- Mypy: 0 errors trên toàn bộ source files liên quan.
