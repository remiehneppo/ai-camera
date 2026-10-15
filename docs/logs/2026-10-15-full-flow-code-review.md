# BÁO CÁO REVIEW KIẾN TRÚC & TOÀN BỘ LUỒNG MÃ NGUỒN DỰ ÁN AI CAMERA GIAO THÔNG

- **Ngày thực hiện:** 2026-10-15
- **Phạm vi:** Toàn bộ hệ thống End-to-End (Edge Ingestion, Perception, Incident Pipeline, Evidence Storage & Quota, Network Outbox Delivery, Central FastAPI Backend, Review Workflow & Dataset Lineage).
- **Tài liệu quy chuẩn đối chiếu:**
  - `CONTEXT.md`
  - `docs/architecture/contracts.md`
  - `docs/architecture/system-architecture.md`
  - `docs/adr/0001-feature-pipeline-boundaries.md`
  - `docs/adr/0002-server-downstream-event-publishing.md`
  - `docs/adr/0003-fastapi-mongodb-backend.md`
  - `docs/adr/0004-integration-contracts.md`
  - `docs/logs/2026-10-14-head-minus-5-code-review.md`

---

## I. TỔNG QUAN KIẾN TRÚC & LUỒNG DỮ LIỆU END-TO-END

```
[ Camera RTSP Stream ] (H.264/H.265)
        │
        ├───────────────────────────────────────────────────────┐
        ▼ (Live Sampling @ 3 FPS)                               ▼ (Full Stream Copy)
[ OpenCV VideoCapture ]                                   [ ffmpeg Concat Pipe ]
        │ (cv2.cvtColor BGR->RGB)                               │ (2s segments)
        ▼                                                       ▼
[ PerceptionPipeline ]                                    [ FileRecorder ]
        │                                                       │
        ├─► [ OnnxDetector (YOLOX-Tiny) ]                       ├─► [ Ring Buffer (600s rolling) ]
        │        │ (Detections)                                 │     - segment-XXXXX.mkv
        │        ▼                                              │     - segment-XXXXX.json
        ├─► [ ByteTracker ]                                     │
        │        │ (Active Tracks & Lineage)                    │ (Trigger Pin [-10s, +20s])
        │        ▼                                              ▼
        ├─► [ PoseManager / PoseScheduler ] ──────────────► [ Finalize Pin Clip ]
        │        │ (RTMPose-Tiny, Keypoints)                    │   - manifests/<sha256>.mkv
        │        ▼                                              │   - manifests/<sha256>.json
        ├─► [ IncidentEngine ]                                  │
        │        │ (person_fall / person_lying_persistent)      │
        │        ▼                                              │
        └─► [ EvidenceLifecycle & StorageQuotaManager ] ◄───────┘
                 │ (Reserve Check >= 50MB, Atomic Enqueue)
                 ▼
        [ EventOutbox (SQLite Journal) ] ◄── WAN Outage Resilient
                 │
                 ├──────────────────────────────┬──────────────────────────────┐
                 ▼ (HTTP POST /v1/events)       ▼ (HTTP PUT /v1/evidence)      ▼ (HTTP GET /v1/health)
      [ Central FastAPI Server ]      [ Evidence Storage ]           [ Prometheus / Doctor ]
                 │
                 ├─► [ MongoDB Replica Set (EventStore) ]
                 │        ├─► event_revisions (Immutable Snapshots)
                 │        ├─► current_events (Projected Latest State)
                 │        ├─► evidence_manifests (Two-phase Guard)
                 │        └─► downstream_outbox (Intent Ledger)
                 │
                 ├─► [ Review API (/v1/events/.../review) ]
                 │        └─► Optimistic Locking & Freshness Guard
                 │
                 └─► [ Dataset Lineage Export (/v1/datasets/export) ]
                          └─► Deterministic Hash Split & Training Lineage
```

### 1. Luồng Thu Nhận Video (Ingestion Flow)
- **RTSP Source (`apps/edge/rtsp.py`):** Phân giải thông tin cấu hình từ `.env.local` hoặc môi trường, ẩn mật khẩu/thông tin nhạy cảm trong log, dùng `ffprobe` qua giao thức TCP để kiểm tra tính khả dụng của luồng trước khi khởi tạo.
- **Continuous Rolling Ring Buffer (`apps/edge/rtsp_recorder.py`, `apps/edge/recorder.py`):** Tiến trình `ffmpeg` sao chép trực tiếp luồng video (stream copy không transcode) vào named pipe `.feed-{session_id}.mkv`. `FileRecorder` chia thành các phân đoạn 2 giây (`.segment-%05d.part.mkv`). Khi phân đoạn hoàn tất, kiểm tra header EBML, đổi tên thành `segment-%05d.mkv` và ghi metadata `.json` nguyên tử kèm `fsync` thư mục. Giới hạn lưu trữ cuốn chiếu 600 giây.
- **Sampling & Pipeline Runner (`apps/edge/live_pipeline.py`):** Chạy luồng đọc `cv2.VideoCapture` ở tốc độ lấy mẫu (mặc định 3 FPS) đưa vào `PerceptionPipeline`.

### 2. Luồng Trích Xuất Đặc Trưng & Theo Vết (Perception & Tracking Flow)
- **Chuẩn Hóa Frame (`apps/edge/perception.py`):** Đóng gói `FrameMetadata` gắn liền `PTS`, `time_base`, `event_time`, `core_epoch`, đảm bảo định danh bất biến suốt session.
- **Phát Hiện Đối Tượng (`apps/edge/oracle_detector.py`):** Mô hình YOLOX chạy trên ONNX Runtime, tiền xử lý affine transform với letterbox, suy luận song song các lớp đối tượng giao thông (`person`, `car`, `motorcycle`, `bus`, `truck`), giải mã lưới anchorless và lọc NMS đa lớp.
- **Theo Vết Đa Đối Tượng (`apps/edge/tracker.py`):** Thuật toán ByteTrack 2 giai đoạn: ghép cặp active tracks với high-score detections (>= 0.5), sau đó ghép cặp tracks chưa match với low-score detections (0.1 - 0.5), và ghép cặp high-score detections còn lại với lost tracks.

### 3. Luồng Đánh Giá Tư Thế & Sự Cố (Pose & Incident Pipeline)
- **Lập Lịch Ước Lượng Tư Thế (`apps/edge/pose.py`):**
  - `RtmposeEstimator`: Mô hình RTMPose-Tiny chạy ONNX, giải mã SimCC heatmaps thành 17 điểm khớp chuẩn COCO và ánh xạ ngược lại tọa độ pixel frame gốc.
  - `PoseScheduler`: Phân bổ ngân sách suy luận công bằng giữa các track, chia 3 mức ưu tiên (`fast_fall`: p=1, deadline 0.5s; `slow_collapse`: p=2, deadline 1.5s; `persistent_lying`: p=3, deadline 3.0s). Có cơ chế xả tải (overload shedding) và hysteresis phục hồi sau 3 chu kỳ ổn định.
- **Nhận Diện Sự Cố (`apps/edge/incident.py`):**
  - Đánh giá tỷ lệ khung bao (aspect ratio): đứng < 0.85, nằm >= 1.2.
  - Sự cố ngã (`person_fall`): Yêu cầu có giai đoạn đứng trước đó (`had_standing`), vận tốc rơi theo phương thẳng đứng >= 15 px/s hoặc tốc độ đổi aspect ratio >= 0.35/s, kết thúc bằng trạng thái nằm yên kéo dài > 3.0s (tốc độ chuyển động < 5 px/s).
  - Sự cố nằm bất động kéo dài (`person_lying_persistent`): Người nằm tại chỗ quá thời gian ngưỡng (mặc định 3.0s) khi không quan sát được giai đoạn bắt đầu ngã.

### 4. Luồng Quản Lý Bằng Chứng, Quota & Giám Sát Sức Khỏe (Storage & Health)
- **Trích Xuất Clip Bằng Chứng (`apps/edge/evidence.py`, `recorder.py`):** Khi sự cố được kích hoạt, tạo yêu cầu pin đoạn video `[anchor - 10s, anchor + 20s]`. `FileRecorder` khóa các segment tương ứng trong SQLite `pins` table dưới giao dịch `BEGIN IMMEDIATE`. `finalize_pin` dùng ffmpeg concat demuxer ghép các segment thành file `.mkv` duy nhất, băm SHA-256 toàn bộ clip và từng segment thành phần, ghi receipt và manifest nguyên tử.
- **Bảo Vệ Dung Lượng Ổ Đĩa (`apps/edge/quota.py`):** Giám sát dung lượng disk với Soft limit (90%), Critical (95%) và State Reserve cứng (50 MB). `EvidenceLifecycle.persist` kiểm tra dung lượng trống trước khi ghi nhận sự kiện, bảo đảm không làm hỏng SQLite journal khi ổ đĩa cạn kiệt. Cơ chế thu hồi dung lượng `cleanup_eligible` ủy quyền hoàn toàn cho `FileRecorder.cleanup_storage` dưới SQLite write lock.
- **Giám Sát Sức Khỏe Trung Thực (`apps/edge/health.py`):** Theo dõi trạng thái camera từ `starting` -> `healthy` / `degraded` / `unavailable`. Phát hiện camera stall, mất khung hình, lỗi analytics, gián đoạn recorder, đĩa đầy, hoặc mất kết nối backend.

### 5. Luồng Chuyển Giao Dữ Liệu Qua Mạng & Central Backend (Outbox & Server)
- **Local Outbox Journal (`apps/edge/outbox.py`, `send_synthetic.py`, `uploader.py`):** Lưu trữ bền vững các event revision và evidence upload request vào SQLite cục bộ. Khi có mạng, worker gửi metadata lên Server `/v1/events` kèm header `[SECRET]` để định danh thiết bị. `EdgeUploader` thực hiện tải lên file video bằng chứng với retry backoff số mũ.
- **Central Event Store (`apps/server/store.py`, `main.py`):** Sử dụng MongoDB Replica Set ACID transactions. Lưu trữ lịch sử snapshot bất biến trong `event_revisions`, cập nhật hình chiếu trạng thái mới nhất vào `current_events`, lưu trữ `evidence_manifests` với guard concurrency, và ghi nhận ý định downstream vào `downstream_outbox`.
- **Review Workflow & Dataset Lineage (`apps/server/main.py`, `dataset.py`):** Người trực kiểm tra và xác nhận sự kiện qua giao diện. Server kiểm tra Optimistic Locking: nếu AI phát sinh revision mới hoặc evidence thay đổi so với bản người trực xem -> trả về HTTP 409 Conflict (bảo đảm tính Freshness). Khi xuất dataset huấn luyện, truy xuất chính xác snapshot revision và manifest đã review, phân chia train/val/test ngẫu nhiên theo camera/thời gian mà không làm rò rỉ dữ liệu (data leakage).

---

## II. ĐỐI CHIẾU KẾT QUẢ SỬA LỖI TỪ ĐỢT REVIEW TRƯỚC (2026-10-14)

Rà soát lại 6 phát hiện trọng yếu từ file `docs/logs/2026-10-14-head-minus-5-code-review.md`:

| Vấn đề trước đây | Phân loại | Tình trạng trong code hiện tại | Đánh giá kỹ thuật |
|---|---|---|---|
| **P1 Standards**: Đọc pin tách rời xóa file trong `quota.py`; xóa file không giữ SQLite write lock của recorder. | P1 | **ĐÃ KHẮC PHỤC TRIỆT ĐỂ** | `StorageQuotaManager.cleanup_eligible()` (quota.py:294-318) đã loại bỏ hoàn toàn việc tự xóa file; ủy quyền cho `FileRecorder.cleanup_storage()` (recorder.py:277-329) chạy dưới `BEGIN IMMEDIATE` trên `pins.sqlite3`. |
| **P1 Standards**: Dọn dẹp wildcard temp file không kiểm tra ownership, vi phạm bảo tồn file lạ. | P1 | **ĐÃ KHẮC PHỤC TRIỆT ĐỂ** | Xóa wildcard đã bị loại bỏ. `cleanup_storage()` chỉ dọn dẹp scratch files có tên khớp với SHA-256 của các `request_id` đã ghi nhận trong bảng `pins`. Các file lạ được bảo toàn nguyên vẹn. |
| **High Spec (#17)**: Monitor giữ trạng thái `starting`; `mark_started()` không có caller trong runtime. | High | **ĐÃ KHẮC PHỤC TRIỆT ĐỂ** | `LivePerceptionRunner._run_loop()` (live_pipeline.py:406) và `PerceptionPipeline.process_frame()` (pipeline.py:164) đã gọi `mark_started()`. Đã bổ sung cả `mark_starting()` và `mark_stopped()`. |
| **High Spec (#18)**: Pipeline khởi tạo `EvidenceLifecycle` không truyền `quota_manager`. | High | **ĐÃ KHẮC PHỤC TRIỆT ĐỂ** | `PerceptionPipeline.__init__` (pipeline.py:56-68) đã nhận `quota_manager` (hoặc khởi tạo mặc định) và truyền vào `EvidenceLifecycle` cùng `health.quota_manager`. |
| **High Spec (#18)**: Từ chối state reserve xảy ra sau khi event đã enqueue vào outbox. | High | **ĐÃ KHẮC PHỤC TRIỆT ĐỂ** | `EvidenceLifecycle.persist(event)` (evidence.py:36-46) kiểm tra `free_bytes <= min_state_reserve_bytes` và ném `OSError(ENOSPC)` trước khi gọi `self.outbox.enqueue(event)`. |
| **High Spec (#18)**: Lỗi truy vấn SQLite pins trong quota trở thành empty ownership, khiến unACK segment bị xóa. | High | **ĐÃ KHẮC PHỤC TRIỆT ĐỂ** | Logic xóa đã chuyển sang `cleanup_storage()` trong `recorder.py`. Nếu SQLite truy vấn lỗi, toàn bộ transaction rollback, bảo đảm fail-closed tuyệt đối. |

---

## III. MA TRẬN PHÁT HIỆN RỦI RO & BỌ TRÊN TOÀN BỘ HỆ THỐNG

### 1. Nhóm Mức Độ P0 (Nghiêm Trọng Nhất: Lỗi Logic Cốt Lõi, Gây Bão False Alert, Treo Khóa Hoặc Sập Luồng)

#### [P0-01] `IncidentEngine` thiếu hoàn toàn bộ lọc nhãn `person` -> Toàn bộ ô tô, xe tải, xe máy đều bị kích hoạt alert `person_lying_persistent`
- **Vị trí:** `apps/edge/incident.py:108-120`, `apps/edge/incident.py:154-213`.
- **Bằng chứng mã nguồn:**
  ```python
  for track in tracks:
      tid = track.track_id
      if tid not in self._states:
          self._states[tid] = _TrackIncidentState()
      state = self._states[tid]

      # Pose assessment
      is_standing = (
          track.aspect_ratio < self.standing_aspect_ratio
          or any(obs.aspect_ratio < self.standing_aspect_ratio for obs in track.history)
      )
      is_lying = track.aspect_ratio >= self.lying_aspect_ratio
  ```
- **Phân tích hệ quả:** YOLOX detector phát hiện nhiều lớp đối tượng (`person`, `car`, `motorcycle`, `bus`, `truck`). ByteTracker lưu nhãn vào `track.label`. Tuy nhiên, `IncidentEngine.process_tracks` KHÔNG kiểm tra `track.label == "person"`. Ô tô và xe tải có chiều rộng lớn hơn chiều cao, nên `aspect_ratio` (width/height) thường từ 1.5 đến 2.5 (đều thỏa mãn `>= 1.2 = lying_aspect_ratio`). Sau 3 giây di chuyển hoặc dừng trên camera, mọi phương tiện giao thông đều kích hoạt sự kiện `person_lying_persistent` với `severity="high"`! Điều này gây bão cảnh báo giả liên tục, làm tê liệt hệ thống giám sát.
- **Giải pháp khắc phục:**
  Đặt guard check ngay đầu vòng lặp xử lý track:
  ```python
  if getattr(track, "label", None) != "person":
      continue
  ```
  Đồng thời xây dựng nhánh phát hiện riêng cho phương tiện dừng đỗ (`person_on_stationary_vehicle`) theo đúng ADR-0001 và `contracts.md`.

---

#### [P0-02] Nhánh `person_lying_persistent` không kiểm tra vận tốc di chuyển -> Phương tiện hoặc người đang di chuyển bình thường bị kích hoạt alert người nằm bất động
- **Vị trí:** `apps/edge/incident.py:192-212`.
- **Bằng chứng mã nguồn:**
  ```python
  else:
      # Missing onset / person already lying / slow lying -> persistent lying detection
      if state.first_qualifying_time is None:
          state.first_qualifying_time = ts

      persistent_duration = ts - state.first_qualifying_time
      if (persistent_duration > self.persistent_lying_duration
              and (state.last_alert_time is None
                   or ts - state.last_alert_time >= self.cooldown_seconds)):
          anchor_time = state.first_qualifying_time
          incident = self._create_incident(
              taxonomy="person_lying_persistent",
              ...
          )
  ```
- **Phân tích hệ quả:** Trong nhánh `person_fall`, engine có kiểm tra `speed > max_motion_speed` để bảo đảm đối tượng đã dừng chuyển động trước khi phát cảnh báo. Nhưng trong nhánh `else:` (`person_lying_persistent`), code hoàn toàn không kiểm tra `speed` hay điều kiện đứng yên! Bất kỳ đối tượng nào có aspect ratio >= 1.2 di chuyển ngang màn hình trong 3 giây đều bị alert là người nằm bất động.
- **Giải pháp khắc phục:** Bổ sung điều kiện kiểm tra vận tốc trọng tâm (`speed < stationary_speed_threshold`) liên tục trong suốt khoảng `persistent_lying_duration`. Nếu đối tượng di chuyển đáng kể, phải reset `first_qualifying_time = ts`.

---

#### [P0-03] Cơ chế Reconnect & Fallback hỏng: Đứt kết nối RTSP một lần khiến hệ thống vĩnh viễn chuyển sang ghi/phân tích video giả lập (synthetic), không bao giờ tự động kết nối lại RTSP
- **Vị trí:** `apps/edge/rtsp_recorder.py:100-116`, `apps/edge/live_pipeline.py:234-240`.
- **Bằng chứng mã nguồn:**
  Trong `rtsp_recorder.py`:
  ```python
  if self.rtsp_url:
      try:
          probe_rtsp_stream(self.rtsp_url, timeout_seconds=self.probe_timeout_seconds)
          self._current_source = "rtsp"
          self._record_rtsp_stream()
          return
      except Exception as exc:
          self._last_error = sanitize_probe_output(str(exc), self.rtsp_url)
          self._current_source = "fallback"

  # 2. Fallback to fixture or synthetic
  self._record_fallback()
  ```
  Trong `live_pipeline.py`:
  ```python
  if self.rtsp_url and self._current_source == "rtsp":
      self._cap = self._open_capture(self.rtsp_url)
      if self._cap is not None:
          self.is_connected = True
          return self._cap
      self._current_source = "fallback"
  ```
- **Phân tích hệ quả:** Khi kết nối mạng RTSP chập chờn hoặc rớt gói tin:
  1. `RtspRingRecorder` bắt ngoại lệ và chuyển sang `self._record_fallback()`, vĩnh viễn ghi video giả lập vào ring buffer.
  2. `LivePerceptionRunner` gán `self._current_source = "fallback"`, khiến các lần gọi tiếp theo chỉ mở video synthetic.
  3. Phương thức `handle_reconnect()` (tăng `core_epoch`, đổi session ID) không bao giờ được gọi tự động. Toàn bộ hệ thống camera giám sát trực tiếp biến thành bộ mô phỏng offline mà không tự phục hồi.
- **Giải pháp khắc phục:** Bổ sung worker giám sát kết nối RTSP với chu kỳ probe và exponential backoff. Khi mất kết nối, chuyển camera sang trạng thái degraded/disconnected; khi RTSP khả dụng trở lại, tự động gọi `handle_reconnect()` để cập nhật epoch và session lineage.

---

#### [P0-04] Mất Terminal Outcomes im lặng trong `PoseManager` vi phạm `contracts.md §1`: Outcomes bị kẹt trong `_terminal_outcomes` vĩnh viễn không bao giờ được trả về
- **Vị trí:** `apps/edge/pose.py:755-766`, `apps/edge/pipeline.py:202-213`.
- **Bằng chứng mã nguồn:**
  ```python
  def submit_request(self, request: PoseRequest | dict[str, Any]) -> bool:
      ...
      accepted = self.scheduler.submit_request(req)
      if not accepted:
          shed = self.scheduler.poll_shed_outcomes()
          self._terminal_outcomes.extend(shed)
      return accepted

  def process_pending(self, current_time: float) -> list[PoseOutcome]:
      with self._lock:
          requests_to_process, shed_outcomes = self.scheduler.schedule_batch(current_time)

      outcomes: list[PoseOutcome] = list(shed_outcomes)
      for req in requests_to_process:
          ...
      return outcomes
  ```
- **Phân tích hệ quả:** `PoseManager` lưu các request bị shed (do hàng đợi đầy hoặc epoch cũ) vào `self._terminal_outcomes`. Khi `set_epoch()` hủy các request cũ, nó cũng lưu vào `_terminal_outcomes`. Tuy nhiên, phương thức `process_pending()` HOÀN TOÀN KHÔNG lấy `self._terminal_outcomes` ra! Kết quả là các terminal outcome này bị bỏ rơi vĩnh viễn trong memory, vi phạm hợp đồng `contracts.md:11`: *"Consumer chậm không làm mất terminal outcome im lặng: giữ slot tới khi consumer nhận... Request được nhận có đúng một terminal outcome trong epoch đang sống"*.
- **Giải pháp khắc phục:** Trong `process_pending()`, gộp và làm rỗng `self._terminal_outcomes`:
  ```python
  with self._lock:
      requests_to_process, shed_outcomes = self.scheduler.schedule_batch(current_time)
      outcomes = list(shed_outcomes) + list(self._terminal_outcomes)
      self._terminal_outcomes.clear()
  ```

---

### 2. Nhóm Mức Độ P1 (Nghiêm Trọng: Vi Phạm Hợp Đồng, Rò Rỉ Tài Nguyên, Suy Giảm Hiệu Năng)

#### [P1-01] apps/server/main.py:358 & 490 — Đọc toàn bộ file Evidence vào RAM khi Upload/Download (Nguy cơ OOM Crash)
- **Vị trí:** `apps/server/main.py:358`, `apps/server/main.py:490`.
- **Bằng chứng:**
  - `body = await request.body()` (dòng 358): Đọc toàn bộ file video tải lên vào memory của tiến trình Python trước khi tính SHA-256 và ghi disk.
  - `content = f.read()` (dòng 490): Đọc toàn bộ file video vào memory khi client không truyền Range header.
- **Hệ quả:** Một clip bằng chứng 30s bitrate cao hoặc nhiều edge upload đồng thời sẽ ngốn hàng trăm MB RAM/request, gây Out-Of-Memory (OOM) làm sập API container.
- **Giải pháp:** Chuyển sang đọc stream theo chunk (64KB - 1MB chunk) tính rolling hashlib sha256 và ghi thẳng vào temporary file; khi download dùng FastAPI `FileResponse` hoặc streaming generator.

---

#### [P1-02] Finalized Evidence Clips trong `manifests/` không bao giờ được thu hồi (Storage Leak Vĩnh Viễn Trên Edge)
- **Vị trí:** `apps/edge/recorder.py:184-261, 99-107, 277-329`, `apps/edge/quota.py:141-156`.
- **Bằng chứng:** Trong `release_pin()`, khi pin được đánh dấu `released = 1` và upload ACK thành công, không có dòng code nào xóa bỏ các file clip `.mkv` và metadata `.json` trong thư mục `manifests/`. Hàm `cleanup_storage()` bỏ qua hoàn toàn thư mục `manifests` (`if directory.name == "manifests": continue`). Trong khi đó `quota.py` tiếp tục tính dung lượng này vào `pinned_bytes`.
- **Hệ quả:** Sau vài ngày hoạt động, thư mục `manifests/` sẽ chiếm trọn 100% dung lượng đĩa, và cơ chế dọn dẹp khẩn cấp không thể thu hồi được byte nào từ đây.
- **Giải pháp:** Bổ sung chính sách thu hồi cho `manifests/` trong `cleanup_storage()`: Khi dung lượng đĩa bị áp lực, truy vấn các pin đã `released = 1` và đã có transfer receipt được ghi nhận trong bảng `transfers`, cho phép unlink file `.mkv` và `.json` tương ứng.

---

#### [P1-03] Giữ SQLite Write Lock `BEGIN IMMEDIATE` trong suốt quá trình chạy ffmpeg và băm SHA-256 gây timeout lock và làm chết tiến trình ghi hình camera
- **Vị trí:** `apps/edge/recorder.py:170-261` (trong `finalize_pin`) so với `apps/edge/recorder.py:461-482, 784-791` (trong `_publish_closed` & `_prune`).
- **Bằng chứng:** `finalize_pin()` gọi `db.execute("BEGIN IMMEDIATE")` rồi thực thi lệnh `ffmpeg concat` (timeout 20s) và băm SHA-256 hàng chục file segment. Luồng `publisher` của `ingest` chạy mỗi 2 giây, gọi `_prune()` cũng với `BEGIN IMMEDIATE`. Khi chờ quá 30 giây, `_prune` ném lỗi `sqlite3.OperationalError: database is locked`. Vì không bắt lỗi này, luồng publisher rơi vào `except BaseException as exc:` và gọi `self._stop(process)` — GIẾT CHẾT TIẾN TRÌNH FFMPEG GHI HÌNH CAMERA.
- **Giải pháp:**
  1. Trong `_prune(session_id)`: Bọc khối SQLite trong `try...except sqlite3.OperationalError:` và log cảnh báo bỏ qua chu kỳ prune đó, không làm chết luồng recording publisher.
  2. Trong `finalize_pin()`: Tách phần tính toán nặng I/O (ffmpeg và hash SHA-256) ra ngoài SQLite write transaction.

---

#### [P1-04] `RtspRingRecorder` chết vĩnh viễn khi rớt mạng RTSP do tái sử dụng `session_id` trong Fallback
- **Vị trí:** `apps/edge/rtsp_recorder.py:100-117, 180-196` so với `apps/edge/recorder.py:382-383`.
- **Bằng chứng:** Khi RTSP đứt kết nối, `_record_fallback()` gọi `record_file(fallback_file, self.session_id, ...)`. Trong `FileRecorder.ingest()`, nếu session directory đã chứa file `segment-*.mkv`, hàm lập tức ném lỗi `FileExistsError`. Hàm `_record_fallback()` bắt lỗi và rơi vào vòng lặp chờ vô tận, dừng toàn bộ việc ghi hình.
- **Giải pháp:** Khi fallback, phải sinh session ID mới (rollover session) và có logic retry kết nối lại RTSP.

---

#### [P1-05] apps/edge/send_synthetic.py:70-85 & pipeline.py:382 — `deliver_pending` thiếu Exponential Backoff và Bounded Retry
- **Vị trí:** `apps/edge/send_synthetic.py:70-85`.
- **Bằng chứng:** Trong `deliver_pending`, vòng lặp `for item in outbox.pending():` gọi trực tiếp `urlopen(request, timeout=5)`. Khi gặp lỗi mạng, hàm ném ngoại lệ ngay lập tức, ngắt toàn bộ batch mà không có backoff/sleep giữa các lần retry.
- **Hệ quả:** Khi WAN chập chờn, pipeline kích hoạt upload liên tục sẽ dồn dập gửi request (thundering herd) hoặc ngắt ngang, không có chiến lược giãn cách thời gian retry có kiểm soát như `EdgeUploader`.
- **Giải pháp:** Bổ sung cơ chế retry loop với exponential backoff kèm jitter cho `deliver_pending`.

---

#### [P1-06] apps/server/store.py:183-233 — Thiếu Pagination và Cursor-based Pagination ở `list_current`
- **Vị trí:** `apps/server/store.py:183-233`.
- **Bằng chứng:** `list_current(self, limit: int)` chỉ nhận tham số `limit`, truy vấn `self.current.find().sort("updated_at", -1).limit(limit)`. Không hỗ trợ `skip` hoặc cursor (`after_id`, `before_id`).
- **Hệ quả:** Dashboard hoặc API client chỉ xem được tối đa N bản ghi mới nhất, không có cách nào xem các sự kiện cũ hơn khi số lượng sự kiện tích lũy trong ngày tăng lên hàng ngàn.
- **Giải pháp:** Bổ sung cursor-based pagination (theo `updated_at` + `_id`) cho `/v1/events` và `list_current`.

---

#### [P1-07] Lệch không gian màu BGR vs RGB giữa OpenCV và các mô hình AI YOLOX / RTMPose
- **Vị trí:** `apps/edge/live_pipeline.py:333-345`, `apps/edge/oracle_detector.py:82-88`, `apps/edge/pose.py:122-124, 203`.
- **Bằng chứng:** `cv2.VideoCapture.read()` trả về mảng BGR. `LivePerceptionRunner` truyền trực tiếp mảng này vào `pipeline.process_frame(rgb, ...)`. Trong `RtmposeEstimator`, ảnh được chuẩn hóa theo ImageNet RGB (`IMAGENET_MEAN = np.array([123.675, 116.28, 103.53])`). Kênh Blue bị trừ mean của Red và ngược lại.
- **Hệ quả:** Làm méo mó đặc trưng hình ảnh và suy giảm độ chính xác nhận diện bbox và keypoints.
- **Giải pháp:** Chuyển đổi tường minh `cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)` tại `LivePerceptionRunner._read_next_frame()`.

---

#### [P1-08] Frame Pacing & OpenCV Buffer Delay: Tích lũy độ trễ khổng lồ (Latency Buildup) do đọc 3 FPS tuần tự từ RTSP 25/30 FPS
- **Vị trí:** `apps/edge/live_pipeline.py:405-430, 214-225`.
- **Bằng chứng:** `LivePerceptionRunner` chạy sleep 0.333s giữa các frame và gọi `cap.read()`. Trong OpenCV, FFmpeg ngầm đệm frame từ luồng RTSP 25-30 FPS. Do không cấu hình `nobuffer` và không có cơ chế drain frame cũ, `cap.read()` sẽ lần lượt lấy các frame cũ tồn đọng trong queue thay vì frame trực tiếp tại thời điểm hiện tại.
- **Hệ quả:** Độ trễ phân tích AI trôi dần từ vài giây lên vài phút sau một thời gian chạy.
- **Giải pháp:** Bổ sung cấu hình `"rtsp_transport;tcp|fflags;nobuffer|max_delay;500000"` cho VideoCapture, hoặc sử dụng thread nền chuyên đọc liên tục (`cap.grab()`) và chỉ lưu lại frame mới nhất khi pipeline yêu cầu.

---

#### [P1-09] Hàm làm tròn `round(..., 3)` gây lỗi false observation gap và xóa sạch lịch sử tracking
- **Vị trí:** `apps/edge/live_pipeline.py:324`, `apps/edge/pipeline.py:158-161, 231-236`.
- **Bằng chứng:** Khi hai frame liên tiếp được xử lý trong cùng 1 millisecond, `round(now_mono - start, 3)` cho kết quả bằng nhau. Khi `ts <= self._last_timestamp`, `PerceptionPipeline` coi frame là "stale", gọi `_observation_gap()`, xóa sạch toàn bộ `track.history` và reset incident engine.
- **Giải pháp:** Không dùng `round(..., 3)`; đảm bảo `ts` tăng đơn điệu nghiêm ngặt (`ts = max(ts, self._last_timestamp + 1e-6)`).

---

#### [P1-10] `onset_time` bị ghi đè khi đối tượng tiếp tục chuyển động nhanh sau khi ngã (vi phạm `contracts.md §3`)
- **Vị trí:** `apps/edge/incident.py:167-171`.
- **Bằng chứng:**
  ```python
  if state.in_fall_candidate:
      if speed > self.max_motion_speed:
          state.lying_start_time = ts
          state.onset_time = ts
  ```
- **Hệ quả:** Khi người đã bắt đầu ngã, nếu họ lăn hoặc chuyển động nhanh trên sàn, `onset_time` bị ghi đè thành timestamp frame chuyển động cuối cùng. Mốc neo bằng chứng pre10/post20s bị tính sai thời điểm bắt đầu ngã, làm cắt mất đoạn video ngã ban đầu trong evidence clip.
- **Giải pháp:** Chỉ cập nhật `lying_start_time = ts` khi đối tượng chuyển động nhanh; giữ nguyên `onset_time` nếu đã được xác lập ban đầu.

---

#### [P1-11] Xóa `track.history` khi track rơi vào trạng thái 'lost' phá hủy khả năng phát hiện ngã khi có track gap ngắn
- **Vị trí:** `apps/edge/pipeline.py:186-189`.
- **Bằng chứng:**
  ```python
  for track in self.tracker.get_all_tracks():
      if track.state != "active":
          track.history.clear()
  ```
- **Hệ quả:** Khi đối tượng bị che khuất hoặc detector bỏ lỡ 1 frame, track chuyển sang `lost`. Code lập tức xóa sạch lịch sử `track.history`. Khi track được liên kết lại ở frame kế tiếp, lịch sử chỉ có 1 observation, khiến vận tốc rơi và thay đổi aspect ratio bị reset về 0, làm mất cơ hội phát hiện sự kiện ngã.
- **Giải pháp:** Chỉ xóa `track.history` khi track chuyển sang trạng thái `removed`.

---

#### [P1-12] ByteTracker thiếu Kalman Filter & trạng thái Tentative theo `contracts.md:139`
- **Vị trí:** `apps/edge/tracker.py:169-267`.
- **Bằng chứng:** Thuật toán chỉ tính IoU tĩnh giữa box cũ và box mới mà không có Kalman Filter dự đoán vị trí (motion prediction). Ở tốc độ 3 FPS, vật thể di chuyển nhanh có IoU < 0.2 dẫn đến mất track liên tục và sinh ID mới. Đồng thời mọi detection chưa ghép cặp đều lập tức tạo thành track `active`, thiếu giai đoạn `tentative`.
- **Giải pháp:** Tích hợp mô hình chuyển động tuyến tính (Constant Velocity Kalman Filter) và yêu cầu >= 2 frame liên tiếp xuất hiện trước khi chuyển track sang `active`.

---

#### [P1-13] Thiếu kiểm tra ROI (Region of Interest) và ODD (Operational Design Domain) trên toàn bộ pipeline
- **Vị trí:** `apps/edge/pipeline.py`, `apps/edge/incident.py`, `apps/edge/perception.py`.
- **Bằng chứng:** Vi phạm ADR-0001 và `contracts.md §1`. Pipeline hiện tại không lọc polygon ROI lòng đường; mọi đối tượng nằm trên vỉa hè, biển quảng cáo đều bị cảnh báo. Trạng thái chất lượng hình ảnh chỉ gán tĩnh "unknown" mà không có module kiểm tra camera mờ, lóa hoặc freeze.
- **Giải pháp:** Bổ sung cấu hình đa giác ROI lòng đường (`roi_polygon`) và kiểm tra tọa độ chân đối tượng nằm trong polygon; tích hợp bộ đánh giá ODD cơ bản (độ tương phản, độ sáng, độ nét Laplacian).

---

### 3. Nhóm Mức Độ P2 (Trung Bình / Cải Tiến Thiết Kế Kiến Trúc & Code Smells)

| Mã | Vị trí | Mô tả vấn đề | Giải pháp đề xuất |
|---|---|---|---|
| **P2-01** | `apps/edge/evidence.py:50, 113` | `can_accept_new_evidence()` luôn được gọi với `estimated_bytes=0`, tiềm ẩn nguy cơ xâm phạm State Reserve khi ghi clip lớn (10MB-40MB). | Tính tổng dung lượng các segment cần ghép nối trước khi gọi `can_accept_new_evidence(estimated_bytes)`. |
| **P2-02** | `apps/edge/quota.py:83-93` | Lỗi kết nối SQLite trong `_get_active_pins` làm sai lệch telemetry metric phân loại `pinned_bytes` vs `ring_bytes`. | Nâng timeout hoặc đánh dấu metric degraded khi truy vấn thất bại. |
| **P2-03** | `apps/edge/recorder.py:73-143, 784` | Rò rỉ connection SQLite do thiếu `contextlib.closing`, chỉ phụ thuộc vào garbage collector của CPython. | Đồng bộ sử dụng `contextlib.closing(sqlite3.connect(...))` cho toàn bộ các điểm kết nối SQLite trong `recorder.py`. |
| **P2-04** | `apps/server/store.py:53-56` | `EventStore` phụ thuộc cứng vào MongoDB Replica Set (`replicaSet=...`), không có `InMemoryStore` fallback cho testing. | Tách interface `BaseEventStore` và cung cấp `InMemoryEventStore` cho CI/test nhẹ. |
| **P2-05** | `apps/edge/outbox.py:71-114` | `EventOutbox.enqueue` chưa kiểm tra tính đơn điệu tăng dần nghiêm ngặt của `event["revision"]`. | Thêm kiểm tra `revision > max(revision)` trong SQLite outbox. |
| **P2-06** | `apps/server/store.py:195-207` | Dùng toán tử `$setWindowFields` trong `list_current` đòi hỏi MongoDB >= 5.0. | Ghi rõ ràng yêu cầu phiên bản MongoDB >= 5.0 trong tài liệu và `compose.yaml`. |
| **P2-07** | `apps/server/main.py:377` | Tên file evidence lưu trữ cố định dạng `.mkv` và header MIME `video/x-matroska`, không linh hoạt với ảnh JPEG. | Suy luận extension từ `Content-Type` hoặc metadata `codec`. |
| **P2-08** | `apps/edge/pose.py:514, 781` | Mâu thuẫn Clock Domain trong `PoseOutcome.executed_at`: chỗ dùng `current_time` (event-time), chỗ dùng `time.time()` (wall-clock). | Chuẩn hóa theo `clock_domain` của `PoseRequest`. |
| **P2-09** | `apps/edge/oracle_detector.py:131` | NMS sử dụng quy ước tọa độ rời rạc `+ 1` cho hộp số thực làm sai lệch IoU của các box nhỏ. | Bỏ `+ 1` trong phép tính diện tích tọa độ số thực. |
| **P2-10** | `apps/edge/oracle_detector.py:87-88` | Ép kiểu `int()` khi resize ảnh gây sai lệch tỉ lệ co giãn thực tế theo trục X và Y (Sub-pixel Drift). | Tính tỉ lệ rescale độc lập cho chiều rộng và chiều cao khi map lại tọa độ ảnh gốc. |

---

## IV. LỘ TRÌNH HÀNH ĐỘNG KHUYẾN NGHỊ (ACTION PLAN)

### Giai đoạn 1: Khắc phục khẩn cấp các lỗi P0 (Ngăn chặn False Alert & Crash luồng)
1. **Sửa P0-01 & P0-02 (`apps/edge/incident.py`):**
   - Lọc chỉ xử lý track có nhãn `person`: `if getattr(track, "label", None) != "person": continue`.
   - Bổ sung điều kiện vận tốc di chuyển `speed < stationary_speed_threshold` trong nhánh `person_lying_persistent`.
2. **Sửa P0-03 (`apps/edge/rtsp_recorder.py`, `live_pipeline.py`):**
   - Xây dựng vòng lặp reconnect RTSP định kỳ với exponential backoff.
   - Khi kết nối lại thành công, tự động gọi `handle_reconnect()` để đổi `session_id` và tăng `core_epoch`.
3. **Sửa P0-04 (`apps/edge/pose.py`):**
   - Trong `PoseManager.process_pending()`, thu hồi toàn bộ `self._terminal_outcomes` cùng với `shed_outcomes` từ scheduler.

### Giai đoạn 2: Khắc phục các lỗi P1 (Bảo vệ Lưu trữ & Tối ưu Hiệu năng)
1. **Sửa P1-01 (`apps/server/main.py`):** Chuyển endpoint `/v1/evidence` upload và download sang dạng streaming chunk.
2. **Sửa P1-02 (`apps/edge/recorder.py`, `quota.py`):** Bổ sung logic thu hồi file `.mkv` và `.json` trong `manifests/` cho các pin đã được ACK và release.
3. **Sửa P1-03 (`apps/edge/recorder.py`):** Bọc `try...except sqlite3.OperationalError` trong `_prune()` để không làm chết tiến trình ghi hình camera; tách ffmpeg và SHA-256 ra ngoài SQLite transaction.
4. **Sửa P1-07 & P1-08 (`apps/edge/live_pipeline.py`):** Chuyển đổi màu `BGR -> RGB` trước khi đưa vào pipeline; thêm thread drain frame RTSP để loại bỏ tích lũy độ trễ.
5. **Sửa P1-09, P1-10, P1-11 (`apps/edge/pipeline.py`, `incident.py`):** Không dùng `round(..., 3)` cho timestamp; không ghi đè `onset_time` sai lệch; không xóa `track.history` khi track mới chỉ rơi vào trạng thái `lost`.

### Giai đoạn 3: Nâng cấp chuẩn hóa & Nghiệm thu Field Pilot
1. Tích hợp đa giác ROI lòng đường (`roi_polygon`) và module đánh giá ODD.
2. Bổ sung Cursor-based Pagination cho API Server `/v1/events`.
3. Tích hợp bộ lọc Kalman Filter cho ByteTracker nhằm ổn định track ID trên luồng 3 FPS.
4. Đồng bộ quản lý connection SQLite với `contextlib.closing`.

---
*Tài liệu này được biên soạn và kiểm chứng độc lập bởi Agent Dispatcher dựa trên bằng chứng mã nguồn thực tế của dự án AI Camera Giao Thông.*
