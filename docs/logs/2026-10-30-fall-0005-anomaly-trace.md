# Truy vết bất thường trên clip fall_0005.mp4 — 2026-10-30

Tài liệu ghi lại toàn bộ chuỗi trace frame-by-frame (`yolox_tiny` -> `ByteTracker` -> `RTMPose` -> `IncidentEngine` / `CrowdIncidentEngine`) trên clip `data/benchmark/unidata/fall_0005.mp4` (1920x1080 @ 30 FPS, 691 frames, 23.03s, 231 sampled frames ở nominal 10 FPS).

---

## 1. Hiện tượng bất thường

1. **Phát cảnh báo sai (False Positive) tại t = 12.8s:** Pipeline phát `suspected_disorder` (bạo loạn / gây rối đám đông) trong khi thực tế chỉ có 1 người duy nhất đang tập thể dục trên máy tập ngoài trời.
2. **Bỏ lọt cảnh báo (False Negative) tại t = 16s – 23s:** Người ngã từ máy tập xuống nền đất và nằm bất động, nhưng pipeline phát **0 sự kiện** `person_down` (`person_fall` = 0, `person_lying_persistent` = 0).

---

## 2. Truy vết Anomaly 1: Cảnh báo `suspected_disorder` tại t = 12.8s

### 2.1. Dữ liệu trích xuất từ pipeline trace
- **Thời điểm:** Frame 384 (index 128), `ts = 12.800s`.
- **Sự kiện phát ra:** `taxonomy="suspected_disorder"`, `severity="high"`, `anchor_time=12.8s`.
- **Metrics ghi nhận trong payload:**
  - `crowd_count = 3`, `involved_track_ids = [2, 9, 26]`.
  - `mean_speed = 42.35 px/s`, `mean_acceleration = 81.61 px/s^2`.
  - `dispersal_rate = 28.82 px/s` (ngưỡng quy định trong rule: `>= 25.0 px/s`).
  - `reasons = ["rapid_dispersal_divergence"]`.

### 2.2. Cơ chế và nguyên nhân gốc (Root Cause)
1. **Dò quét đối tượng ở hậu cảnh xa:**
   - Trong khung hình, YOLOX phát hiện thêm người ở băng ghế hoặc tán cây xa phía sau:
     - `track_id=2`: bbox `[1360.7, 66.4, 1459.4, 211.2]` (ở góc trên bên phải, y từ 66 đến 211).
     - `track_id=26`: bbox `[1568.7, 0.0, 1670.4, 205.4]` (mới xuất hiện từ t=12.7s ở rìa trên).
   - Ở tiền cảnh:
     - `track_id=9`: bbox `[1078.5, 350.8, 1427.7, 869.7]`. Đây là người tập thể dục đang kéo/đẩy máy tập.
2. **Kích hoạt điều kiện đám đông ảo:**
   - Ngưỡng tối thiểu `min_disorder_count = 3`. Đúng tại `t = 12.8s`, có đúng 3 track cùng mang label `person` trong khung hình (`[2, 9, 26]`).
3. **Đột biến vận tốc do thao tác máy tập:**
   - Tại t = 12.8s, người tập kéo mạnh tay đòn máy tập xuống dưới, làm tâm bbox của `track_id=9` dịch chuyển nhanh: vận tốc tức thời vọt lên **106.3 px/s**, gia tốc **108.8 px/s^2**.
   - Trọng tâm cụm (center of mass) của 3 đối tượng được tính bằng trung bình tọa độ: `cm_x = 1427.6`, `cm_y = 283.9`.
   - Vector chuyển động của `track_id=9` hướng xa khỏi trọng tâm cụm (`dx = -174`, `dy = +326`).
   - Hàm `CrowdIncidentEngine._evaluate_disorder` tính `mean_dispersal = 28.82 px/s >= 25.0 px/s` (vượt ngưỡng phân tán nhanh), và vận tốc trung bình `42.35 px/s >= 25.0 px/s` với ít nhất 1 đối tượng `>= 30.0 px/s`.
4. **Kết luận Anomaly 1:**
   - Do thiếu ràng buộc về **khoảng cách địa lý / bán kính cụm (spatial clustering / proximity)** giữa các đối tượng trước khi gom thành "đám đông", 2 người ở hậu cảnh xa cách 800px đã bị gom chung với 1 người đang vận động mạnh trên máy tập. Vận tốc cơ học của một cá nhân đơn lẻ đã làm sai lệch toàn bộ chỉ số phân tán của cụm.

---

## 3. Truy vết Anomaly 2: Bỏ sót `person_down` tại t = 16s – 23s

### 3.1. Dữ liệu trích xuất từ pipeline trace
- **Giai đoạn trước ngã (t = 14.0s – 15.6s):**
  - Người tập được theo dõi ổn định dưới `track_id = 9` (`label="person"`, score 0.74 – 0.86, aspect ratio 0.54 – 0.70 < 0.85).
  - Trạng thái `IncidentEngine`: `had_standing = True`.
- **Giai đoạn ngã khỏi máy tập (t = 15.7s – 15.8s):**
  - `t = 15.7s`: bbox `[1088.0, 597.0, 1343.6, 852.1]`, aspect ratio tăng vọt lên **1.002**.
  - `t = 15.8s`: bbox `[1083.6, 597.7, 1287.5, 916.9]`, aspect ratio = 0.639.
- **Giai đoạn detector gán nhầm nhãn `bird` (t = 16.0s – 17.4s):**
  - Khi người rơi xuống nền đất tối dưới chân máy tập, detector YOLOX mất nhãn `person` và bắt đầu phát hiện đối tượng tại vị trí này với label **`bird`** (chim) ở các mốc:
    - `t = 16.0s`: `label="bird"`, score 0.53, bbox `[1261.9, 627.2, 1353.2, 783.3]`.
    - `t = 16.4s`: `label="bird"`, score 0.31, bbox `[1129.5, 633.0, 1350.6, 826.6]`.
    - `t = 17.0s`: `label="bird"`, score 0.32, bbox `[1110.6, 630.5, 1358.4, 796.9]`.
    - `t = 17.1s`: `ByteTracker` khởi tạo **`track_id = 34`** với label **`"bird"`**!
  - `track_id = 9` (người cũ) không có detection nào match trong 2 giây liên tiếp nên bị xóa (`state="lost"` từ t=15.9s, timeout ở t=17.9s).
- **Giai đoạn dính nhãn cũ trong ByteTracker (t = 18.1s – 20.3s):**
  - Từ `t = 18.1s`, YOLOX nhận diện lại được người nằm trên mặt đất:
    - Bbox: `[1101.9, 640.1, 1384.0, 812.9]`, score 0.36, aspect ratio **1.55** (nằm ngang, > 1.2).
  - Tuy nhiên, `ByteTracker.update` ghép bbox này vào `track_id = 34` có sẵn theo IoU match.
  - Trong logic hiện tại của `apps/edge/tracker.py:Track.update()`:
    ```python
    self.bbox = [float(x) for x in bbox]
    self.score = float(score)
    self.last_time = float(timestamp)
    # KHÔNG cập nhật lại self.label!
    ```
  - Do đó, `track_id = 34` vẫn tiếp tục mang nhãn **`label="bird"`** từ t=18.1s đến t=20.3s.
  - `IncidentEngine.process_tracks()` kiểm tra `if track.label != "person": continue`. Kết quả: `track_id = 34` bị bỏ qua 100%.
- **Giai đoạn mất hoàn toàn detection (t = 20.4s – 22.7s):**
  - Suốt 2.3 giây liên tục (t=20.4s đến 22.7s), YOLOX không phát hiện bất kỳ vật thể nào tại khu vực người nằm (do ánh sáng yếu ban đêm, người nằm bất động không có độ tương phản).
  - `track_id = 34` bị timeout và xóa sổ ở t = 22.4s (`max_lost_time = 2.0s`).
- **Giai đoạn cuối video (t = 22.8s – 23.0s):**
  - Tại `t = 22.8s` (frame 684), YOLOX phát hiện lại người nằm: `label="person"`, score 0.30, bbox `[1103.8, 637.8, 1381.0, 816.5]`, aspect ratio = **1.551**.
  - `ByteTracker` tạo mới **`track_id = 42`** (`label="person"`).
  - Vì đây là track hoàn toàn mới, `had_standing = False` (chưa từng thấy đứng). Do đó nhánh `person_fall` không thể kích hoạt.
  - Nhánh `person_lying_persistent` yêu cầu `persistent_lying_duration >= 3.0s`.
  - Nhưng video kết thúc ở `t = 23.03s` (frame 690). `track_id = 42` chỉ kịp tồn tại trong **0.23 giây** (< 3.0s) thì clip dừng.

---

## 4. Bảng tổng hợp nguyên nhân

| Hiện tượng | Cơ chế lỗi trong mã nguồn |
|---|---|
| **`suspected_disorder` sai (12.8s)** | `apps/edge/crowd_incident.py`: `min_disorder_count=3` gom tất cả đối tượng `person` trong toàn khung hình mà không xét khoảng cách cụm (`cluster distance`). Vận tốc tay kéo máy tập đơn lẻ (~106 px/s) đẩy chỉ số phân tán chung (`dispersal_rate`) vượt ngưỡng 25 px/s. |
| **Mất chuỗi ngã (16s - 18s)** | `apps/edge/oracle_detector.py`: YOLOX-tiny nhầm người ngã thành `bird` (score 0.31 - 0.53) trong điều kiện thiếu sáng. |
| **Dính nhãn sai trong Tracker (18s - 20s)** | `apps/edge/tracker.py`: `Track.update()` chỉ cập nhật bbox và score khi match IoU, không cho phép cập nhật hoặc voting lại `label`. Một track bị gán nhãn `bird` ở frame trước sẽ mãi mãi là `bird`, khiến `IncidentEngine` bỏ qua. |
| **Thiếu thời gian duy trì (22.8s - 23.0s)** | Clip bị cắt kết thúc quá sớm (23.0s), track mới chỉ tồn tại 0.23s, không đủ thời gian tích lũy ngưỡng `min_lying_duration = 3.0s`. |

---

## 5. Bản sửa nhỏ (T1) và kết quả kiểm chứng lại — 2026-10-30

### 5.1. Thay đổi đã triển khai
1. **`apps/edge/tracker.py` (`_coarse_label_group` trong `ByteTracker._match_iou`)**:
   - Chỉ ghép nối IoU khi track và detection thuộc cùng nhóm đối tượng thô (`person`: `{"person", "pedestrian"}`, `two_wheeler`: `{"bicycle", "motorcycle"}`, `motor_vehicle`: `{"car", "bus", "truck"}`; các lớp khác đối sánh chính xác theo `label`).
   - Ngăn track mang nhãn nhiễu (`"bird"`, `"cat"`, `"bench"`) nuốt các detection `"person"` trùng vị trí ở những frame tiếp theo, đồng thời vẫn giữ liên tục track xe khi detector dao động giữa `bus` và `truck`.
2. **`apps/edge/crowd_incident.py` (`_spatial_clusters`, `_evaluate_cluster_disorder`)**:
   - Gom cụm không gian theo thành phần liên thông với bán kính chuẩn hóa theo kích thước bbox nhỏ hơn (`max(120.0, 2.5 * min(scale_i, scale_j))`), ngăn đối tượng tiền cảnh có bbox lớn gom nhầm người ở hậu cảnh xa.
   - Bắt buộc nhánh `rapid_dispersal_divergence` phải có ít nhất **2 người** cùng có vận tốc hướng ra ngoài cụm (`v_radial >= 15.0`), đồng bộ với nguyên tắc đa tác nhân của `is_surge` và `is_chaotic`.
3. **Unit tests chặn hồi quy**:
   - `tests/test_tracker_lifecycle.py`: `test_incompatible_class_does_not_hijack_person_track`.
   - `tests/test_crowd_incident_flow.py`: `test_single_mover_among_stationary_bystanders_does_not_trigger_dispersal`, `test_distant_background_bystanders_do_not_form_disorder_cluster`.

### 5.2. Kết quả chạy lại trên `fall_0005.mp4` và bộ clip đối chứng
- **`suspected_disorder` tại `t = 12.8s` trên `fall_0005.mp4`**: **Đã triệt tiêu (`1 -> 0`)**. Tại `t = 12.8s`, hai người ở hậu cảnh (`track_id=2, 27`) tách rời khỏi người tập máy (`track_id=9`), `is_disorder = False`.
- **Nhận diện `person` sau khi ngã (`t = 18.1s – 20.3s`) trên `fall_0005.mp4`**: **Đã khôi phục đúng nhãn `person`**.
  - Ngay tại `t = 18.1s`, detection `person` không còn bị gộp vào track `"bird"` (`track_id=35`) mà tạo mới **`track_id = 40` (`label="person"`, `state="active"` từ `18.2s`, aspect ratio `1.55 – 1.58`)**, giúp số lượt `RTMPose` trên clip tăng từ `80 -> 88`.
  - Tuy nhiên, clip vẫn **không phát `person_lying_persistent`** vì hai giới hạn độc lập nằm ngoài lỗi gộp track:
    1. `yolox-tiny` ($416\times 416$) bị đứt quãng detection dưới bóng tối ở `t = 18.4s` (1 frame), `18.8s` (1 frame), `19.1s – 19.9s` (0.9s), và mất hoàn toàn từ `20.4s – 22.7s` (2.3s).
    2. Theo bất biến **Ticket #23** (`tests/test_track_gap.py:test_missing_track_frame_resets_dwell`), `IncidentEngine` bắt buộc xóa thời gian tích lũy (`dwell`) khi thiếu quan sát để không suy diễn trạng thái qua khoảng mù; do đó chuỗi nằm liên tục dài nhất của `yolox-tiny` chỉ đạt `0.3s` (`< 3.0s`). Không hạ ngưỡng `ByteTracker` hay phá bất biến Ticket #23 để ép nổ cảnh báo.
- **Đối chứng các clip khác (`tools/eval_all_scenarios.py`)**:
  - `fall_0001.mp4`: Vẫn phát `person_lying_persistent` tại `t = 14.6s` (và loại bỏ sự kiện trùng lặp do track cũ không còn bị kéo dài giả tạo bởi 117 bbox nhầm sang `"cat"`).
  - `fall_0002.mp4`, `fall_0003.mp4`, `fall_0004.mp4`: Giữ nguyên `0` sự kiện.
  - `intersection_traffic_1080p.mp4`: Chạy đủ 606 frames sạch lỗi (`0` detector failure).

### 5.3. Cổng kiểm chứng kỹ thuật
- `.venv-oracle/bin/python -m mypy domain/ apps/ tools/`: **Success: no issues found in 72 source files**.
- `.venv-oracle/bin/python -m pytest -q`: **893 passed, 360 warnings, 188 subtests passed in 149.50s** (0 failures, 0 skipped).
