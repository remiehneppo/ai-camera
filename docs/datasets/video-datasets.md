# Sổ đăng ký dataset video (đã kiểm) — dùng lại về sau

Cập nhật: 2026-10-26. Mọi dòng dưới đây đều dựa trên **lần kiểm thật** (tải/ffprobe/chạy pipeline), không dựa trên
mô tả của dataset. Media **không** vào repo (`data/` đã gitignore): chỉ lưu đường dẫn, kích thước, hash và kết quả.

## 0. Quy tắc dùng chung & Ràng buộc ODD (Cập nhật 2026-10-27)

1. **Ràng buộc ODD phần cứng (Bắt buộc)**:
   - **TUYỆT ĐỐI KHÔNG DÙNG**:
     * **Camera hành trình (dashcam)**: Camera gắn trên phương tiện di chuyển tạo luồng quang học biểu kiến (ego-motion), làm sai lệch toàn bộ vận tốc tương đối và gia tốc của vật thể tĩnh ven đường, vi phạm giả định camera tĩnh của Edge Pipeline hiện tại. (Loại bỏ các bộ dashcam như DAD_A3D khỏi benchmark đánh giá chính thức).
     * **Camera độ phân giải thấp (< 720p)**: Như 240p/320×240 (UCF-Crime), 238×158 (UCSD). Độ phân giải thấp làm mờ nát bounding box, detector YOLOX bỏ lọt đối tượng hoặc nhảy kích thước frame-by-frame gây nhiễu gia tốc giả.
   - **BẮT BUỘC DÙNG**: Camera giám sát giao thông **CỐ ĐỊNH (Fixed CCTV / Traffic Surveillance Cameras)** lắp trên cột/cầu vượt/ngã tư, độ nét từ **HD (720p / 1280×720)** đến **2MP (Full HD 1080p / 1920×1080)**.
2. Chỉ lưu **tham chiếu** trong repo; không commit media, không redistribute.
3. Luôn kiểm `ffprobe` + kích thước/hash trước khi đưa vào metric; file tải lỗi phải bị loại và **không** được tính là "0 detection".
4. Dataset công khai **không** dùng để ký nghiệm thu capability (G2/G4/G5); chỉ dùng để phát triển, regression và phát hiện lỗi đường ống.

## 1. Bộ NÊN dùng (đã tải, đã chạy)

| Bộ | Loại / ODD | Nội dung đã kiểm | License | Dùng cho | Không dùng cho |
|---|---|---|---|---|---|
| ⭐ **UniDataPro fall-detection** (HF `UniDataPro/fall-detection`) | Video, **1920×1080@30**, camera tĩnh + động, cảnh dựng | 5 clip, 21,8–27,9 s, 272 MB. **`fall_0001` → 1 event `person_fall` (candidate, critical, pose ok)**, p50 51 ms; 2 clip còn lại 0 event | **CC BY-NC-ND 4.0** (nội bộ, không thương mại, không phái sinh phân phối) | **Chạy thử luồng trên đúng ODD 1080p**, kiểm person-down có bật được | Recall/precision (bản HF **không kèm nhãn**); thương mại |
| **URFD** (`fenix.ur.edu.pl/~mkepski/ds/uf.html`) | Video, 640×240@30, trong nhà | 6 clip (3 fall + 3 ADL) + CSV sync, 7,7 MB; chạy 0 event cả 6 (chưa calibrate ODD này) | research | Kiểm **flow/độ trễ**, đối chứng âm (ADL), test công cụ | Chấm recall (trang **không** có nhãn onset) |
| **UCSD Anomaly** (`svcl.ucsd.edu`) | **Chuỗi ảnh TIF** 238×158@10, camera cố định ngoài trời | 740.306.953 B, `gzip OK`; convert 4 clip mp4 20 s; **0 event** trên 60 s Train + 20 s Test, p50 19–27 ms | research | Smoke test đường ống image-sequence; **negative rất yếu** | Đo FP/giờ thật (độ phân giải quá thấp) |
| **UCF-Crime mirror** (HF `ertiaM/Anomaly_Detection_in_Surveillance_Videos`) | Video, **320×240**, CCTV/web | 950 mp4, **13 lớp** (Abuse, Arrest, Arson, Assault, Burglary, Explosion, Fighting, RoadAccidents, Robbery, Shooting, Shoplifting, Stealing, Vandalism); tải 6 clip, 42 MB. **Không có split Normal**; `Fighting001_x264.mp4` tải lỗi 15 byte | research-only (card HF không ghi license) | Dữ liệu cho #64 ẩu đả, #68 phá hoại, #58 cháy/nổ, #47 tai nạn khi các capability đó tồn tại | Chấm chất lượng hiện tại (chưa có capability); negatives (thiếu normal) |
| **DAD_A3D** (local: `/media/tieubaoca/HDD1/F/dataset/video/fall-accident/DAD_A3D`) | Video dashcam, **1280×720@25**, 4 s | **1.750 clip** đã giải nén (2,7 GB), chia training/testing × positive/negative (456/830/166/302). Chạy 12 clip: 4.257 detection, **0 event**, p50 37 ms | research | Flow/latency quy mô lớn; **nhãn mức clip** (positive/negative) cho #47 sau này | Ground truth per-frame (annotation không có schema; xem §3) |

## 2. Bộ ĐÃ kiểm nhưng CHƯA tải được (ghi để không thử lại mù)

| Bộ | Vấn đề đã xác minh | Đường còn lại |
|---|---|---|
| **DoTA** (local `.../DoTA/repo`) | Annotation **rất tốt**: 4.677 JSON có `anomaly_start/anomaly_end`, `video_start/end`, `accident_name`. Nhưng **18/18 URL YouTube** đã chết (`yt-dlp --simulate`) | Bundle Google Drive chính thức **55 GB** (5×10 GB + 5 GB) — cần quyết định tải |
| **A3D frame labels** (local, 1.087 file × 100 frame) | Đúng dạng nhãn frame nhưng khoá `<youtube_id>_<index>`; **không có mapping** sang `videos/000001.mp4` (đã kiểm `videos.zip`, `A3D_detections.zip`, `annotation/`; GitHub search "A3D accident dashcam" = 0) | Xin `datalist` từ tác giả DAD/A3D; mapping xong thì chạy ngay `tools/a3d_labels.py` |
| **CADP** (local) | Chỉ có **28.281 JPEG keyframe** + `annotations_CADP.json` (226 video, có `type: "Traffic camera views"`) + 1 clip mẫu 2400×1200 | Tải clip gốc CADP nếu cần video |
| **CAUCAFall** (Mendeley `7w7fccy7ky`) | API trả 200; **folder root chỉ có 9 file tài liệu (1,1 MB)**, video nằm trong folder con | Gọi `/public-api/datasets/7w7fccy7ky/tree?folder_id=root&version=5` rồi tải từng folder |
| **UCF-Crime / Avenue / ShanghaiTech** (site gốc) | Trang CRCV và CUHK trả **000** từ host này | Dùng mirror HF (ở trên) hoặc đăng ký qua tác giả |
| **Simuletic CCTV fall/lying** (HF) | **111 ảnh PNG 1024×1024** (CC BY 4.0), nhãn YOLO-pose; **không phải video** | Chỉ dùng cho detector/pose trên ảnh tĩnh |

## 3. Bài học về annotation (đừng lặp lại)

- `DAD_A3D/annotation/*.txt`: 620 file nhưng chỉ phủ **100 video id**; cột 2 (max 25) **không** khớp "frame id của
  clip 100 frame" **cũng không** khớp "object index" ⇒ **không phải ground truth per-frame**. Đã **xoá**
  `tools/eval_detector_agreement.py` vì viết trên giả định sai này.
- Trước khi hứa "chấm recall", phải chứng minh: (a) tồn tại file nhãn, (b) nghĩa từng cột, (c) mapping sang đúng
  file clip. Thiếu một trong ba ⇒ chỉ chạy flow/latency.

## 4. Lệnh chuẩn (đã dùng thật trong repo)

```sh
# 1) chuẩn hoá clip về H.264 (giữ nguyên độ phân giải gốc, ghi lại nếu khác ODD)
ffmpeg -i in.mp4 -c:v libx264 -pix_fmt yuv420p out.mp4
# image-sequence (UCSD) -> mp4
ffmpeg -y -framerate 10 -i Train001/%03d.tif -c:v libx264 -pix_fmt yuv420p Train001.mp4

# 2) đánh giá mức event (decode->detect->track->incident->outbox)
.venv-oracle/bin/python tools/eval_clip.py --video data/benchmark/unidata/fall_0001.mp4 \
  --sample-fps 5 --pose --output-json /tmp/eval.json

# 3) benchmark hiệu năng trên 1 clip bất kỳ
.venv-oracle/bin/python tools/run_benchmark.py --video <clip> --max-frames 300 --sample-fps 10 \
  --output-report /tmp/bench.md --output-json /tmp/bench.json

# 4) nhãn A3D -> labels.jsonl (khi có mapping)
.venv-oracle/bin/python tools/a3d_labels.py --frame-labels .../A3D_frame_labels.zip \
  --mapping mapping.json --videos-root .../DAD_A3D --output-jsonl data/benchmark/a3d_labels.jsonl

# 5) negative audit / G2 (cần alert + negative reviewed)
.venv-oracle/bin/python tools/negative_audit_report.py --alerts a.jsonl --negatives n.jsonl \
  --capability person_down --min-recall 0.90 -o report.json
```

## 5. Vị trí media trên máy này (`data/` gitignored, không có trong git)

| Path | Kích thước | Ghi chú |
|---|---|---|
| `data/benchmark/shibuya_crossing_1080p.mp4`, `intersection_traffic_1080p.mp4` | 88 MB, 43 MB | Clip Wikimedia CC BY-SA (không nhãn) — benchmark gốc |
| `data/benchmark/unidata/fall_000{1..5}.mp4` | 272 MB | ⭐ fall 1080p (CC BY-NC-ND) |
| `data/benchmark/urfd/` | 7,7 MB | 6 clip URFD + CSV sync |
| `data/benchmark/ucfcrime/` | 42 MB | 6 clip UCF-Crime (13 lớp, 320×240) |
| `data/benchmark/ucsd/` | 1,9 GB | tar gốc + `extracted/` + `clips/*.mp4` (238×158) |
| `/media/tieubaoca/HDD1/F/dataset/video/fall-accident/DAD_A3D/videos/` | 2,7 GB | 1.750 clip dashcam 720p (đã giải nén) |

## 6. Danh mục Dataset Thay thế Chuẩn ODD: Camera Giao thông Cố định (HD đến 2MP / 1080p)

Để phục vụ đúng ODD camera giám sát thông minh cố định, các bộ dataset dưới đây được tuyển chọn thay thế cho dashcam và video độ nét thấp:

| Dataset | ODD & Góc quay | Độ phân giải | License & Truy cập | Mục đích sử dụng |
|---|---|:---:|---|---|
| ⭐ **NVIDIA AI City Challenge (Track 3 / Track 4 — TAR)** | **CCTV giao thông cố định** tại ngã tư & cao tốc của Sở GTVT (DOTs) | **1080p & 720p** | **CC BY 4.0** (HuggingFace `nvidia/PhysicalAI-Traffic-Anomaly-Reasoning`) | **Chuẩn vàng cho #47 (Tai nạn xe) & #62 (Dừng đỗ trái phép)**: Video camera tĩnh ghi nhận va chạm, xe chết máy, quay đầu trái phép, xe đỗ sai làn, có chuỗi suy luận thời gian. |
| ⭐ **SO-TAD (Small-Object Traffic Anomaly)** | **CCTV camera tĩnh** góc cao giám sát nút giao thông đô thị | **1080p & 720p** | Research (`cccccxy/so-tad` trên HuggingFace, ~27 GB) | **#47 (Va chạm xe & xe lật) & #62 (Dừng đỗ)**: Phát hiện phương tiện nhỏ/từ xa va chạm, xe máy đổ ngã, chướng ngại vật lòng đường. |
| ⭐ **TAD (Traffic Anomaly Dataset / TAD-bench)** | **CCTV camera tĩnh** giám sát đường cao tốc & giao lộ | **720p & 1080p** | Research (Kaggle `nikanvasei/traffic-anomaly-dataset-tad` hoặc Google Drive) | **#47**: Va chạm xe–xe, xe lật, xe đâm dải phân cách từ camera quan sát đường bộ cố định. |
| ⭐ **CADP (Car Accident Detection and Prediction)** | **CCTV camera giao thông công cộng** (Police & DOT CCTV) | **720p, 1080p** (đến 2400×1200) | Research (Đã có sẵn trên máy: `CADP/annotations_CADP.json` 226 video, `keyframes.tar.gz` 1.5 GB) | **#47**: Đã có sẵn 226 video chú giải keyframe tai nạn xe từ camera giám sát giao thông thực tế. |
| ⭐ **ACCIDENT Benchmark Dataset** | **CCTV giao thông cố định** (CVPRW 2024–2026) | **1080p & 720p** | Research (`accidentbench/ACCIDENT` trên GitHub) | **#47**: Bộ dữ liệu benchmark chuyên biệt cho tai nạn từ camera giám sát công cộng (loại trừ dashcam). |
| ⭐ **UA-DETRAC (Univ. at Albany)** | **CCTV camera tĩnh** tại các cầu vượt, ngã tư (Bắc Kinh & Thiên Tân) | **960×540 & 720p** | Academic / Research (100 video sequences, 140.000 frame) | **Đối chứng âm (Negative Control) cực tốt cho #47 & #62**: Mật độ giao thông cao, dừng đèn đỏ, xếp hàng chờ luồng, kiểm tra thời gian dừng đỗ (dwell time). |
| ⭐ **ShanghaiTech Campus Surveillance** | **CCTV camera tĩnh 1080p** ngoài trời | **1920×1080 @ 30fps** | Research (CUHK / Kaggle mirrors) | **#63 (Tụ tập đông người & gây rối) & #57 (Vùng nguy hiểm)**: Giám sát người đi bộ, đám đông tụ tập, người đạp xe bất thường từ camera tĩnh Full HD. |
| ⭐ **UniDataPro Fall Detection** | **Camera tĩnh 1080p** trong nhà & ngoài trời | **1920×1080 @ 30fps** | CC BY-NC-ND 4.0 (Đang có sẵn tại `data/benchmark/unidata/`) | **#25 / #26 / #53 (Person-down)**: Bộ duy nhất đã chứng minh đạt chuẩn ODD 1080p cho người ngã/nằm đường. |
