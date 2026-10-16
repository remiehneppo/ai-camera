# Edge Ingestion, Perception & Incident Pipeline Architecture & Code Review

- **Date:** 2026-10-15
- **Task:** task-1 ("Review Edge Ingestion, Perception & Incident Pipeline")
- **Reviewer:** perception-reviewer (Teammate)
- **Scope:**
  - `apps/edge/rtsp.py`
  - `apps/edge/rtsp_recorder.py`
  - `apps/edge/live_pipeline.py`
  - `apps/edge/pipeline.py`
  - `apps/edge/runtime.py`
  - `apps/edge/oracle_detector.py`
  - `apps/edge/tracker.py`
  - `apps/edge/pose.py`
  - `apps/edge/incident.py`
  - `apps/edge/perception.py`
- **Standards & Specifications:**
  - `docs/adr/0001-feature-pipeline-boundaries.md`
  - `docs/architecture/contracts.md`
  - `docs/architecture/system-architecture.md`
  - `CONTEXT.md`

---

## 1. Overview: Ingestion -> Perception -> Incident Flow

1. **Video Ingestion:**
   - Cấu hình nguồn RTSP được tải và thẩm định qua `apps/edge/rtsp.py`, ẩn thông tin nhạy cảm (credentials) bằng `redact_rtsp_url` và `sanitize_probe_output`.
   - `apps/edge/rtsp_recorder.py` (`RtspRingRecorder`) khởi tạo tiến trình ghi vòng cuốn 600s (`FileRecorder`) thông qua named pipe (FIFO) sử dụng `ffmpeg` stream-copy sang các segment `.part.mkv` 2 giây.
   - `apps/edge/live_pipeline.py` (`LivePerceptionRunner`) điều phối song song luồng ghi ring và luồng suy luận thời gian thực qua OpenCV `cv2.VideoCapture` ở tần số lấy mẫu `sample_fps` (mặc định 3 FPS).
2. **Detector -> Tracker:**
   - `apps/edge/perception.py` (`PerceptionExecution`) quản lý chuỗi lineage (`camera_id`, `stream_session_id`, `core_epoch`, `origin`, `frame_id`, `pts`, `event_time`) và validate đầu ra detector.
   - `apps/edge/oracle_detector.py` (`OnnxDetector`, `LiveDetector`, `OracleDetector`) thực thi suy luận YOLOX đa lớp (COCO labels) trên ONNX Runtime, resize TopDownLetterbox, giải mã anchorless grid và NMS.
   - `apps/edge/tracker.py` (`ByteTracker`) thực hiện liên kết 2 giai đoạn theo IoU bounding box: high-score detections (>= 0.5) với active tracks, low-score detections (0.1 - 0.5) với remaining active tracks, và high-score detections còn lại với lost tracks.
3. **Pose Estimation:**
   - `apps/edge/pose.py`:
     - `RtmposeEstimator`: Tiền xử lý affine warp về 192x256, chuẩn hóa ImageNet RGB, chạy mô hình ONNX RTMPose-Tiny, giải mã SimCC heatmaps (split_ratio=2.0) và nghịch đảo ma trận affine về toạ độ pixel gốc của frame (17 keypoints COCO).
     - `PoseScheduler`: Phân loại 3 nhánh ưu tiên (`fast_fall`: p=1, deadline 0.5s; `slow_collapse`: p=2, deadline 1.5s; `persistent_lying`: p=3, deadline 3.0s). Lập lịch công bằng (fair scheduling) với min shares cho từng nhánh và chia sẻ budget còn lại theo độ ưu tiên. Overload shedding loại bỏ yêu cầu ưu tiên thấp khi hàng đợi đầy. Cơ chế Hysteresis phục hồi sau 3 chu kỳ êm ả.
     - `PoseManager`: Hàng đợi bounded, bộ đệm khung hình giải mã LRU (`max_cached_frames=30`), kiểm soát epoch và deadline, trả về kết quả terminal outcome (ok, skipped, failed, cancelled).
4. **Incident Detection:**
   - `apps/edge/incident.py` (`IncidentEngine`):
     - Đánh giá tư thế dựa trên tỷ lệ khung hình (aspect ratio = width / height): đứng (< 0.85) vs nằm (>= 1.2).
     - Phát hiện ngã (`person_fall`): kiểm tra vận tốc rơi thẳng đứng (`vertical_velocity >= 15.0 px/s`) hoặc thay đổi tỷ lệ khung hình (`ar_change >= 0.35`). Duy trì trạng thái nằm yên > 3.0s với tốc độ di chuyển `<= 50.0 px/s` để xác nhận ngã.
     - Phát hiện nằm bất động kéo dài (`person_lying_persistent`): khi không quan sát được giai đoạn bắt đầu (onset), duy trì tư thế nằm > 3.0s.
     - Cooldown 30s giữa các lần cảnh báo trên cùng track.
5. **Evidence & Integration:**
   - `apps/edge/pipeline.py` (`PerceptionPipeline`): Tạo `EventSnapshot` chuẩn schema v1 (`domain/event_contract.py`), phát sinh yêu cầu lưu trữ bằng chứng pre10/post20s (`domain/evidence_contract.py`), pin ring buffer vào SQLite qua `EvidenceLifecycle` và chuyển giao cho `EventOutbox` / `EdgeUploader`.

---

## 2. Findings, Defects & Architectural Risks

### P0 (Critical)
1. **`IncidentEngine` thiếu kiểm tra nhãn đối tượng `person` (`apps/edge/incident.py:108-120`)**:
   - Mọi track (kể cả ô tô, xe tải có aspect ratio > 1.2) đều bị đánh giá và kích hoạt cảnh báo `person_lying_persistent` sau 3 giây. Gây bão false alert nghiêm trọng tại hiện trường.
2. **`person_lying_persistent` không kiểm tra vận tốc di chuyển (`apps/edge/incident.py:192-212`)**:
   - Đối tượng (xe cộ hoặc người di chuyển ngang màn hình) đang chạy bình thường vẫn bị kích hoạt `person_lying_persistent` nếu duy trì aspect ratio >= 1.2 trong 3 giây mà không có kiểm tra đứng yên (stationary/motion speed).
3. **Mất kết nối RTSP dẫn đến fallback vĩnh viễn không bao giờ reconnect (`apps/edge/rtsp_recorder.py:100-116`, `apps/edge/live_pipeline.py:234-240`)**:
   - Khi RTSP ngắt tạm thời, hệ thống vĩnh viễn chuyển sang ghi/phân tích video giả lập (synthetic fallback), không có vòng lặp reconnect hay backoff. `handle_reconnect()` không được tự động kích hoạt trong luồng chạy.
4. **Outcomes bị kẹt trong `_terminal_outcomes` của `PoseManager` làm mất kết quả im lặng vi phạm `contracts.md §1` (`apps/edge/pose.py:755-766`)**:
   - `submit_request` khi bị queue full hoặc epoch cũ lưu outcome vào `_terminal_outcomes`, nhưng `process_pending()` không bao giờ drain deque này, làm mất terminal outcome im lặng.

### P1 (High)
5. **Lệch không gian màu BGR vs RGB (`apps/edge/live_pipeline.py:333-345`, `apps/edge/pose.py:203`)**:
   - OpenCV đọc BGR nhưng `OnnxDetector` và `RtmposeEstimator` xử lý chuẩn RGB. Kênh Red/Blue bị đảo lộn làm suy giảm độ chính xác inference và điểm tin cậy keypoints.
6. **Frame pacing & đệm OpenCV gây trôi độ trễ (Latency Buildup) (`apps/edge/live_pipeline.py:405-430`)**:
   - Đọc 3 FPS từ RTSP 25/30 FPS qua `cap.read()` tuần tự mà không có cờ `nobuffer` hay luồng đọc nền liên tục (frame drainer) khiến buffer phình to và độ trễ tăng dần.
7. **Làm tròn `round(..., 3)` gây false observation gap và xóa lịch sử track (`apps/edge/live_pipeline.py:324`, `apps/edge/pipeline.py:158-161`)**:
   - Hai frame liên tiếp rơi vào cùng millisecond bị coi là stale, kích hoạt `_observation_gap()`, xóa sạch `track.history` và ngắt chuỗi phát hiện sự kiện.
8. **Ghi đè `onset_time` khi nạn nhân cử động sau khi ngã (`apps/edge/incident.py:167-171`)**:
   - Cử động nhanh sau ngã ghi đè `onset_time = ts`, khiến mốc neo bằng chứng pre10/post20s bị tính sai thời điểm ngã ban đầu.
9. **Xóa `track.history` khi track rơi vào trạng thái `lost` (`apps/edge/pipeline.py:186-189`)**:
   - Che khuất 1 frame khiến track chuyển `lost` và bị xóa sạch lịch sử, làm mất khả năng khôi phục vận tốc rơi khi track được re-associate.
10. **Thiếu Kalman Filter và trạng thái Tentative trong ByteTracker (`apps/edge/tracker.py:169-267`)**:
    - Không có dự đoán chuyển động (motion prediction); khởi tạo track `active` ngay lập tức từ một detection đơn lẻ, dễ gây nhảy track ID và nhạy cảm với nhiễu.
11. **Thiếu kiểm tra ROI và ODD trên toàn bộ pipeline (`apps/edge/pipeline.py`, `apps/edge/incident.py`)**:
    - Không hỗ trợ polygon ROI lòng đường (vi phạm ADR-0001); không có ODD monitor kiểm tra độ mờ, lóa sáng, đóng băng khung hình (freeze).

### P2 (Medium/Low)
12. **Mâu thuẫn clock domain trong `PoseOutcome.executed_at` (`apps/edge/pose.py:514, 799`)**: Trộn lẫn event-time float và wall-clock epoch time.
13. **Quy ước toạ độ rời rạc `+ 1` trong NMS hộp số thực (`apps/edge/oracle_detector.py:131-135`)**: Thổi phồng diện tích và IoU của các box nhỏ.
14. **Sub-pixel drift do ép kiểu `int()` khi tính tỉ lệ scale resize (`apps/edge/oracle_detector.py:87-88`)**: Sai lệch toạ độ hệ thống giữa chiều ngang và dọc.
15. **Trả về synthetic frame xám khi mất kết nối RTSP (`apps/edge/live_pipeline.py:368-370`)**: Tạo observation giả thay vì ngắt và báo trạng thái missing/failed rõ ràng.
16. **Sanitize credential RTSP có thể chưa bao phủ đầy đủ query params phức tạp (`apps/edge/rtsp.py:116-133`)**.
