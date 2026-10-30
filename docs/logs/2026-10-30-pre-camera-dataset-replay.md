# Kiểm thử dataset trước khi có camera thật — 2026-10-30

## Phạm vi và quyết định

- Yêu cầu: chạy lại với dataset sát bài toán hiện tại trước khi có camera thật. Đây là investigation/evaluation; không sửa runtime, ngưỡng, model, schema, nhãn hoặc báo cáo lịch sử.
- ODD chính: CCTV giao thông cố định, 1280×720 đến 1920×1080. Đọc CONTEXT.md, sổ dataset và log đính chính 2026-10-29 trước khi chọn mẫu; metadata nguồn/ODD không phải annotation đã duyệt.
- Ưu tiên dữ liệu đã có trên máy, không tải thêm hoặc gửi footage sang cloud. DAD_A3D/dashcam, URFD/UCF-Crime/UCSD độ phân giải thấp không nằm trong metric chính. UniDataPro 1080p chỉ là cohort bổ trợ Person-down; camera/bối cảnh phải được kiểm trực quan, không mặc định đạt ODD giao thông.
- Chạy trọn clip theo sampling hiện hữu của evaluator, nominal sample_fps=10, max_frames=0, pose bật. Không cắt 100/200 frame đầu rồi gọi là kiểm cả clip. Lưu cấu hình hiệu lực, trạng thái, snapshot persist, hash input/model/source và phiên bản môi trường trong thư mục kết quả mới; không ghi đè JSON cũ.
- Illegal parking cần ROI/lịch cấm được duyệt, danger-zone cần ROI/lịch; crowd cần ngữ cảnh cho tập trung/gây rối. Nếu dataset không có những policy/nhãn này, chỉ báo phản ứng rule/exploratory flow, không kết luận vi phạm thực hoặc tự bịa site policy.
- Chưa có nhãn độc lập cho alert và no-alert intervals thì không tính precision/recall/FP mỗi giờ hoặc nhận quality/held-out gate. Kiểm trực quan của agent chỉ dùng phát hiện khoảng cần review, không tự tạo nhãn nghiệm thu.

## Inventory đã kiểm

- Kết quả cục bộ: `data/benchmark/pre-camera-replay-20261030T000210Z/` (gitignored).
- `input-inventory.json`: 17 video, tổng 286.353866 giây, dự kiến 3,012 frame phân tích theo stride hiện hữu.
- Phân loại ban đầu (đã rút lại ở phần kết quả): 10 clip `traffic_cctv_hd/000001..000010.mp4`, mỗi clip 5 giây, 720p/10 FPS; hai clip đô thị Shibuya (1080p/25 FPS, 58.56 giây) và intersection (1080p/30000/1001 FPS, 60.593867 giây). Không dùng tên cohort ban đầu làm chứng nhận ODD.
- Cohort bổ trợ: 5 clip `unidata/fall_0001..0005.mp4`, 1080p/30 FPS, 21.8–27.933333 giây; không có manifest hash/nhãn reviewed trong thư mục này, nên lượt này tự tính hash làm provenance của lượt chạy, không gọi đó là hash đã được nguồn xác nhận.
- Đã chạy ffprobe với `-count_frames`, đọc toàn bộ video stream, không có lỗi decode/stderr; kích thước/hash của 12 clip chính khớp manifest hiện hữu. Tất cả 17 file có raster trong khoảng HD–1080p; raster không tự chứng minh camera cố định hay bối cảnh phù hợp.
- Sampling hiện hữu dùng `round(native_fps / sample_fps)` làm stride: Shibuya 25 FPS/stride 2 thực tế khoảng 12.5 FPS; intersection stride 3 khoảng 9.99 FPS. Giữ nguyên behavior, ghi rõ khác biệt nominal/effective; không sửa thuật toán lấy mẫu trong lượt test.

## Kế hoạch bằng chứng

1. Kiểm nguồn/nhãn/policy và contact sheet để phân cohort, không dùng tên dataset làm ground truth.
2. Chạy evaluator đa tình huống qua pipeline thật, full clip/sampling hiện hữu; quan sát snapshot SQLite trước cleanup để lưu bản ghi đầy đủ trong output riêng mà không đổi đường xử lý.
3. Đối chiếu số frame dự kiến, trạng thái detection/pose, số event emitted/persisted, source anchor/request/session, config và lineage; giữ event là proposal chưa duyệt.
4. Kiểm lại các khoảng có event và một số khoảng không event, ghi rõ false-alert/miss chỉ là nghi vấn nếu thiếu review độc lập.
5. Với danger-zone/parking/đám đông thiếu site policy/nhãn, bổ sung kiểm flow có cấu hình thử nghiệm tường minh nếu làm được và tách khỏi đánh giá ngữ nghĩa thực; không nhận đã bao phủ đầy đủ chỉ vì bốn engine mặc định chạy.

## Kết quả

### Kết luận về ODD sau kiểm tra

- **Không có clip giao thông nào trong inventory này đủ căn cứ đưa vào cohort nghiệm thu CCTV cố định.** Giữ toàn bộ kết quả ở vai trò chẩn đoán luồng xử lý.
- `traffic_cctv_hd/000001..000010.mp4`: contact sheet cho thấy nắp xe/dashboard và chuyển động góc nhìn. Rút nhận định CCTV cố định trong manifest lịch sử; đây là dashcam.
- Shibuya: contact sheet tại 5%, 50%, 90% cho thấy zoom/đổi khung hình. Không dùng làm CCTV cố định. FPS thực là 25, không phải 29.97.
- Intersection: kiểm ba ảnh ban đầu chưa phát hiện chuyển hướng, nên lượt chạy dùng tên cohort `fixed_intersection`. Kiểm các thời điểm proposal phát hiện nền đổi khung hình. ORB + RANSAC trên dải nền phía trên, raster phân tích 960×540, so với mốc 0.4 giây: tại 3.8 giây có 503 inlier, trung vị dịch chuyển quy về raster gốc **290.386 px**; tại 30 giây là 42.228 px/549 inlier, tại 55 giây là 32.787 px/559 inlier. Rút nhận định cố định; kết quả chỉ là chẩn đoán video đô thị. Phép đo này không chứng nhận kiểu gá camera và không đo độ chính xác thuật toán cảnh báo.
- UniDataPro: 5 clip dàn dựng trong nhà/sân/khu tập thể dục, chỉ bổ trợ Person-down; không thuộc ODD giao thông.
- Phân loại cuối nằm trong `final-odd-classification.json`; `verified-cohorts/input-inventory.json` và `results.json` giữ tên cohort lúc chạy để truy vết. Tên `verified-cohorts` cũng không có nghĩa nhãn/ODD đã qua nghiệm thu.
- [Trang nguồn intersection](https://commons.wikimedia.org/wiki/File:Intersection_Pie-IX-Sherbrooke.webm) ghi tác giả **Thomas1313**, CC BY-SA 4.0, mô tả giao lộ; không xác nhận camera CCTV gá cố định. Nguồn này không thay thế kiểm tra footage.
- Agent inventory không tìm thấy video CADP trên ổ dữ liệu: chỉ keyframe/annotation; DoTA thiếu media. DAD_A3D là dashcam, URFD/UCF-Crime/UCSD thấp hơn 720p. Không tải thêm video trong lượt này.

### Replay đã hoàn tất và đối chiếu

Hai lượt lưu đủ **17 clip khác nhau**, tổng **286.353866 giây**, **7,296 frame nguồn / 3,012 frame phân tích**, **13,623 detection**, **1,923 pose outcome**, **131 proposal/snapshot SQLite**. Đây không phải một tiến trình hoàn tất duy nhất: dừng lượt đầu sau 11 clip đã lưu, rồi chạy đủ 6 clip còn lại trong thư mục con. Không tính phần xử lý chưa lưu của lượt bị dừng.

| Input | Frame phân tích | Detection | Pose outcome | Proposal chưa duyệt | p95 xử lý/frame (ms) |
| --- | ---: | ---: | ---: | --- | ---: |
| `traffic_cctv_hd/000001..000010` (10 clip, dashcam) | 500 | 1,233 | 1 | 24 `vehicle_incident` | Không gộp percentile các clip |
| Shibuya (đổi khung hình) | 732 | 5,195 | 1,462 | 22 `vehicle_incident`, 5 `suspected_disorder` | 118.03 |
| Intersection (đổi khung hình) | 606 | 5,707 | 174 | 76 `vehicle_incident`, 1 `suspected_disorder` | 89.80 |
| `fall_0001` | 224 | 251 | 68 | 1 `person_lying_persistent`, 1 `person_fall` | 79.06 |
| `fall_0002` | 221 | 173 | 26 | 0 | 75.90 |
| `fall_0003` | 218 | 161 | 43 | 0 | 118.65 |
| `fall_0004` | 280 | 193 | 66 | 0 | 79.83 |
| `fall_0005` | 231 | 710 | 83 | 1 `suspected_disorder` | 78.12 |

Lưu ý: p95 chỉ đo `pipeline.process_frame`, gồm persistence cục bộ; loại decode, sampling và nạp model. Không dùng bảng này làm số đo throughput camera thật hoặc SLA. Giá trị Shibuya lấy từ artifact của lượt đầu; không suy ra percentile chung.

- Tổng trạng thái detector: **2,635 `ok`, 377 `ok_empty`, 0 lỗi**. Tất cả frame gọi detector có đồng hồ hữu tỉ nhất quán; không biến lỗi detector thành kết quả không phát hiện.
- Proposal tổng: 122 `vehicle_incident`, 7 `suspected_disorder`, 1 `person_lying_persistent`, 1 `person_fall`. Intersection riêng có 62 `vehicle_vehicle`, 12 `vehicle_rollover_or_barrier`, 2 `vehicle_pedestrian`. Không gọi những con số này là số tai nạn thực, precision hay FP/giờ.
- Script kiểm đủ số frame theo stride, một session riêng mỗi clip, `origin=replay`, hash model thật trong snapshot, chất lượng payload khớp envelope, snapshot trả về khớp bản đọc từ SQLite, canonical event hash và event contract hợp lệ.
- Với 131 proposal, script đối chiếu ID emitted/persisted và evidence request dùng đúng session/anchor, khoảng yêu cầu trước 10 giây/sau 20 giây. Không có proposal bị mất trong phạm vi các lượt đã lưu.
- Các snapshot của 6 clip lượt sau ghi `calibration_version=uncalibrated`; Person-down dùng `pipeline-v1`, vehicle dùng `vehicle-incident-v1`, crowd dùng `crowd-incident-v1`. Các tên/hash cấu hình hiệu lực có trong JSON; không gọi đây là cấu hình camera/site đã duyệt.
- Không đưa ring video vào recorder trong evaluator hiện hữu; chỉ kiểm snapshot và yêu cầu evidence. Ví dụ 45/77 request intersection, 2/2 request `fall_0001`, 1/1 request `fall_0005` vượt đầu/cuối media nguồn. Không có bằng chứng clip evidence 30 giây đã được dựng, pin đầy đủ, gửi server hoặc phát lại trên UI.

### Kiểm trực quan và khoảng cần người duyệt

- Script tạo sheet theo thời điểm proposal chính xác cho ba nhánh vehicle và crowd trên intersection, thêm mốc 30/55 giây; 5 clip bổ trợ có các mốc 5, 10.8, 12.8, 15, 20 giây. Đây là spot-check, không phải nhãn độc lập cho toàn bộ timeline.
- Intersection: proposal đầu `vehicle_vehicle` tại 0.4004 giây gắn hai bbox tách rời; cảnh nền đổi hướng có thể làm nhiễu chuyển động pixel. **[INFERENCE]** Camera motion/bbox jitter cần điều tra trước khi hiệu chỉnh rule. Chưa gán false positive cho toàn bộ 76 proposal và không lấy mục tiêu 76→0.
- `fall_0001`: ảnh từ 10.8 đến 20 giây có người nằm trên sàn. Proposal persistent-lying phát tại 14.6 giây, anchor 11.5; proposal fall phát tại 14.7, anchor 10.8. Hai loại khác nhau không tự động có nghĩa là duplicate. Không tính latency onset hay true-positive rate khi thiếu onset do người duyệt.
- `fall_0002/0003`: một số mốc thấy người cúi/ngồi/đứng; tên file `fall` không đủ để gọi không phát proposal là miss. `fall_0004` tại 20 giây thấy người hạ thấp sát tường; cần review toàn timeline và pose/detection trước khi xác nhận miss.
- `fall_0005`: mốc 12.8 giây của `suspected_disorder` trùng bối cảnh người dùng thiết bị tập; mốc 20 giây thấy người trên mặt sân nhưng không có Person-down proposal. Đưa cả hai khoảng vào danh sách cần review trong lượt chạy tại `HEAD=758bc95` này (cập nhật chuyển tiếp: truy vết frame-by-frame và bản sửa T1 cho `ByteTracker` / `CrowdIncidentEngine` đã được ghi nhận tại [2026-10-30-fall-0005-anomaly-trace.md](2026-10-30-fall-0005-anomaly-trace.md)).
- Các clip này đã được agent xem; không dùng lại như unseen hold-out.

### Lệnh, phiên bản và artifact

```sh
.venv-oracle/bin/python /tmp/camera-dataset-eval-s9r6_ofe/replay_datasets.py data/benchmark/pre-camera-replay-20261030T000210Z
.venv-oracle/bin/python /tmp/camera-dataset-eval-s9r6_ofe/replay_datasets.py data/benchmark/pre-camera-replay-20261030T000210Z/verified-cohorts
.venv-oracle/bin/python /tmp/camera-dataset-eval-s9r6_ofe/review_results.py data/benchmark/pre-camera-replay-20261030T000210Z/verified-cohorts /tmp/camera-dataset-eval-s9r6_ofe
.venv-oracle/bin/python /tmp/camera-dataset-eval-s9r6_ofe/check_background.py
```

- Lệnh replay đầu: chủ động dừng sau khi 11 clip đã lưu. Lệnh replay thứ hai: exit 0, `COMPLETED 6 clips 1780 sampled frames`, wall 118.67 giây. Lệnh tạo sheet và đo nền: exit 0; không sửa runtime/ngưỡng/model.
- Checkout HEAD khi chạy: `758bc952bce6a1490f0293023860944ad14e7ee1`; lượt chạy dùng mã trên working tree, không khẳng định đó là cây sạch tại commit này. `run-context.json` ghi SHA-256 từng source/model; lượt 6 clip kiểm hash source trước/sau không đổi. Hai lượt có cùng hash source/model tại lúc bắt đầu.
- Môi trường: Python 3.12.3, NumPy 1.26.4, ONNX Runtime 1.20.1, OpenCV headless 4.10.0.84.
- Thư mục kết quả gitignored: `data/benchmark/pre-camera-replay-20261030T000210Z/`. `reconciliation.json` gộp 17 clip đã lưu; `final-odd-classification.json` là phân loại ODD cuối. Thư mục con lưu kết quả 6 clip, snapshot, cấu hình hiệu lực, `run-context.json`, `visual-review-index.json`, `background-stability.json`.
- Helper và sheet ở `/tmp/camera-dataset-eval-s9r6_ofe/`, có thể mất khi dọn temp. Không đưa video/ảnh dẫn xuất vào Git; registry ghi UniDataPro CC BY-NC-ND 4.0 nên không coi việc có file trên máy là quyền phân phối/thương mại. Không upload footage; script replay cấm socket connect.

### Kiểm thêm policy cho danger-zone và parking

- Evaluator đa tình huống dùng bốn engine, không có `danger_zone`; parking ở lượt chính dùng dwell 20 giây, crowd dùng count 5/duration 3 giây theo cấu hình evaluator hiện hữu. Không gọi lượt chính là nghiệm thu đủ năm nhóm cảnh báo.
- Đã chạy `.venv-oracle/bin/python /tmp/policy_smoke.py`: **6/6 kịch bản đạt assertion** qua `PerceptionPipeline`, SQLite outbox và request evidence thật, với detection tổng hợp. Mỗi module có ba trường hợp: ROI/lịch đang hoạt động phát một proposal, lịch không hoạt động không phát, ngoài ROI không phát. Parking giữ dwell mặc định constructor 30 giây; trace dài 31.5 giây, bước 0.5 giây để không vượt observation-gap 1 giây. Danger-zone giữ hai hit liên tiếp/dwell 0 giây. Script kiểm event contract, canonical hash, lineage, session/anchor và bản ghi SQLite; không chứng minh detector/nhãn thực.
- `.venv-oracle/bin/python /tmp/video_replay.py`: chạy đủ intersection lần riêng, chỉ bật `danger_zone` và `illegal_parking`, detector thật, ROI toàn khung chuẩn hóa, lịch all-day bảy ngày dùng cho lab. Giữ mặc định constructor: parking dwell 30 giây, tracker high/low 0.5/0.1, pose tắt. Cấu hình này khác lượt evaluator chính; không so proposal/latency như cùng cấu hình.
- Lượt video đầu của subagent ghi `policy-video-replay.json`: 606 frame, 5,707 detection, 11 proposal `danger_zone_intrusion` đã persist, không có `illegal_parking`. Không suy ra nguyên nhân không phát parking từ số đếm; không có trace stationarity/nhãn để kết luận xe đỗ đúng hay sai.
- Parent thêm assertion status từng frame, đủ frame, emitted/persisted ID, event contract/hash và session/anchor/request window, lưu cả snapshot và mô tả policy trong artifact mới rồi chạy lại **exit 0**: `policy-video-replay-audited.json`, 606 frame, 11 proposal/persisted, wall vòng xử lý 32.16 giây. Không ghi đè artifact lượt đầu. Đây là video chạy policy thử nghiệm, không phải 11 xâm nhập được người sở hữu site xác nhận. Không cộng các lượt lặp này thành clip độc lập hoặc cộng 11 vào bảng 131 proposal của lượt chính.
- Bằng chứng policy riêng: `policy-smoke.json`, `policy-video-replay.json`, `policy-video-replay-audited.json` trong cùng thư mục kết quả. Helper `/tmp/policy_smoke.py` và `/tmp/video_replay.py` là script điều tra tạm; không sửa mã runtime/config trong repo.
- Subagent đã chạy `.venv-oracle/bin/python -m unittest tests/test_danger_zone_flow.py tests/test_parking_incident_flow.py`: **44 test, 0.672 giây, OK**. Parent nhận stdout của lệnh đã chạy, không chạy lại để xác nhận báo cáo.


### Điều kiện còn thiếu trước camera thật

1. Video CCTV giao thông cố định 720p–1080p, quyền sử dụng phù hợp, có metadata camera/source và kiểm ổn định nền. Dữ liệu hiện có không đáp ứng mục này.
2. Nhãn người duyệt độc lập cho cả event lẫn no-alert intervals, đủ collision types, có hash media và chia theo camera/source; cần dữ liệu chưa dùng để xem/chỉnh rule.
3. ROI/lịch cấm/ngoại lệ được người sở hữu site duyệt cho danger-zone và parking; ngữ cảnh/ngưỡng được duyệt cho crowd. Full-frame/all-day mặc định không chứng minh vi phạm.
4. Camera thật: calibration, ánh sáng/che khuất, rung/mất frame, RTSP/reconnect và recorder/evidence/upload/UI. Lượt replay cục bộ chưa kiểm các đường này.

Không chạy lại full suite/mypy/build trong lượt investigation không sửa mã runtime này. Ngoài 44 unit test nêu trên, bằng chứng gồm assertion trong replay/chẩn đoán/smoke; không dùng kết quả kiểm thử lịch sử để tuyên bố gate hiện tại đã xanh.

### Tự rà soát kết quả

| Trục | Điểm / 5 | Bằng chứng hoặc giới hạn |
| --- | ---: | --- |
| Chính xác | 4 | Đã đối chiếu JSON/snapshot/source hash và sửa phân loại ODD; spot-check hình ảnh không thay nhãn toàn timeline. |
| Đầy đủ | 4 | Đã chạy 17 clip, thêm policy cho module còn thiếu; chưa có dữ liệu đạt ODD/nhãn độc lập để kiểm chất lượng. |
| Rõ ràng | 4 | Tách lượt chính, lượt lặp policy và nhãn chưa duyệt; tên thư mục lịch sử vẫn dễ gây nhầm nên có file phân loại cuối. |
| Khả năng hành động | 4 | Có artifact, lệnh, khoảng cần review và điều kiện dữ liệu; cần người sở hữu site cung cấp policy/nhãn. |
| Súc tích | 4 | Chi tiết truy vết nằm trong log; phản hồi người dùng chỉ nêu kết quả và giới hạn quyết định. |

Trung bình 4.0/5. Ưu tiên tiếp theo: thu footage CCTV cố định có quyền dùng; duyệt event/no-alert intervals trước khi chỉnh rule. Tự kiểm: người đọc có thể phân biệt bằng chứng luồng xử lý với bằng chứng chất lượng; chưa có căn cứ nghiệm thu chất lượng.
