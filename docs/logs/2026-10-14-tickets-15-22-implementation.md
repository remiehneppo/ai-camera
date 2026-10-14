# Implementation & Review Log — Tickets #15 & #22 (2026-10-14)

## Context & Objectives
Triển khai hai khối công việc tiếp theo theo yêu cầu của người dùng:
1. **Khối 1: Ticket #15 — Camera RTSP live giữ correlation với recorder**:
   - Kết nối trực tiếp camera RTSP từ `.env.local` (`rtsp://192.168.1.93:554/h264/ch1/main/av_stream`).
   - Vừa ghi rolling ring buffer 10 phút vừa cấp frame thời gian thực cho `PerceptionPipeline`.
   - Xử lý disconnect/reconnect: đánh dấu `observation_gap()`, tăng `core_epoch` khi kết nối lại, đảm bảo correlation chính xác giữa timestamps quan sát và segments ghi hình.
   - Tự động ghim (pin) bằng chứng `[anchor - 10s, anchor + 20s]` và đưa vào Outbox khi phát hiện ngã hoặc nằm bất động.
2. **Khối 2: Ticket #22 — Pose request trả keypoints đúng frame và track**:
   - Tải mô hình RTMPose-tiny ONNX chuẩn COCO 17-keypoints từ OpenMMLab.
   - Xây dựng `RtmposeEstimator` hỗ trợ crop affine 192x256, SimCC decoding (split ratio 2.0) và ánh xạ ngược về tọa độ gốc của frame.
   - Xây dựng `PoseManager` quản lý vòng đời PoseRequest theo hợp đồng tích hợp: kiểm tra deadline (nếu quá hạn chuyển `skipped`), kiểm tra epoch (nếu lệch chuyển `cancelled`), giới hạn hàng đợi và bộ nhớ đệm frame.
   - Tích hợp vào `PerceptionPipeline`.

## Delegation & Model Routing
- Đã phân rã công việc theo Task Book chuẩn và giao cho Subagents thực hiện tuần tự với route:
  - `onechain/Gemini 3.8 Flash (High)` (Khối 1: Ticket #15)
  - `onechain/Gemini 3.8 Flash (High)` (Khối 2: Ticket #22)
- Cả hai subagent tuân thủ phương pháp TDD và Karpathy Guidelines.

## Implementation Details
1. **Khối 1 (`apps/edge/live_pipeline.py`, `tests/test_live_pipeline.py`)**:
   - Thêm `LivePerceptionRunner`: kết nối RTSP stream có che giấu thông tin xác thực (`redact_rtsp_url`), đồng bộ hóa cùng `session_id` giữa `RtspRingRecorder` và `PerceptionPipeline`.
   - Cơ chế xử lý mất tín hiệu và kết nối lại bảo toàn tính toàn vẹn của track/incident lineage.
2. **Khối 2 (`apps/edge/pose.py`, `models/rtmpose-tiny/`, `tests/test_pose.py`)**:
   - Thêm `RtmposeEstimator`: tải `rtmpose_tiny.onnx` và `manifest.json`, thực hiện chuẩn hóa ImageNet, SimCC postprocessing.
   - Thêm `PoseManager`: đảm bảo mỗi pose request có duy nhất một kết quả cuối cùng (`ok`, `skipped`, `failed`, `cancelled`) kèm lý do rõ ràng.
   - Mở rộng `PerceptionPipeline` hỗ trợ `pose_manager`, `request_pose()`, và đồng bộ `set_core_epoch()`.

## Verification & Real Hardware Evidence
- **Kiểm thử trên Camera RTSP LAN thật**:
  - Đã kết nối thử nghiệm camera `192.168.1.93:554` trong 3 giây.
  - Kết quả: `Runner Status: running, Source: rtsp, Frames processed: 3, Epoch: 1`.
- **Unit & Integration Tests**:
  - `tests.test_live_pipeline`: 10/10 tests passed (6.486s).
  - `tests.test_pose`: 12/12 tests passed (0.420s).
  - Core integration suite (80 tests): 80/80 tests passed (16.874s).
- **Type Checking**:
  - `mypy --follow-imports=silent`: 0 lỗi trên toàn bộ 6 file liên quan.
