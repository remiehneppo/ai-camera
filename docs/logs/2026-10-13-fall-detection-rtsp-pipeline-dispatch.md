# Fall Detection & RTSP Evidence Pipeline Dispatch — 2026-10-13

## 1. Context & User Decisions
- User requested end-to-end implementation for Direction 1 (AI Tracking + Person Fall Detection) and Direction 2 (RTSP Ring Buffer Ingest + Automatic Evidence Clip Pinning and Upload).
- Complexity Level: **L2**
- Collaboration Mode: `subagent` with route `n9router/ag/gemini-3.8-flash-high`.
- Clarification Interview & Agreed Decisions:
  1. **Fall Detection Criteria (Q1)**: Rơi đột ngột (drop in centroid Y / sudden aspect ratio change) kết hợp Nằm bất động (tỷ lệ $w/h \ge 1.2$ duy trì $> 3.0$ giây).
  2. **RTSP Recording Mode (Q2)**: Ghi hình vòng tròn liên tục 10 phút ở chế độ nền bằng `FileRecorder` ring buffer cuốn chiếu (luôn sẵn sàng 10 giây trước sự cố).
  3. **Event Cooldown (Q3)**: Cooldown 30 giây cho cùng một Track ID để chống spam bão sự kiện.
  4. **End-to-End Delivery**: Khi phát hiện ngã $\rightarrow$ IncidentEngine tạo Event Outbox $\rightarrow$ Pin clip $[-10s, +20s]$ $\rightarrow$ EdgeUploader upload lên Server $\rightarrow$ Dashboard tự động hiển thị sự kiện và video clip bằng chứng.

## 2. Boundaries & Task Breakdown

### Task 1: AI Tracker & Fall Detection Incident Engine
- **Files**:
  - `apps/edge/tracker.py`
  - `apps/edge/incident.py`
  - `tests/test_tracking_incident.py`
- **Ownership**: Object tracking and behavior analysis.

### Task 2: RTSP Ring Buffer Recorder, Pipeline Orchestration & End-to-End Delivery
- **Files**:
  - `apps/edge/rtsp_recorder.py`
  - `apps/edge/pipeline.py`
  - `tests/test_rtsp_pipeline.py`
  - `.scratch/system-build-slices/issues/13-native-tracks-co-time-va-session-semantics.md`
  - `.scratch/system-build-slices/issues/14-pipeline-baseline-bien-observations-thanh-event.md`
  - `.scratch/system-build-slices/issues/25-person-fall-co-onset-quan-sat.md`
- **Ownership**: Continuous RTSP ring capture, end-to-end pipeline coordination, clip pinning, outbox enqueue, and upload integration.

## 3. Verification Protocol
- TDD Red-Green cycle for each task.
- Clean Mypy typechecking.
- Full regression test execution across the entire repository.
