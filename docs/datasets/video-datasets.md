# Sổ đăng ký dataset video (đã kiểm) — dùng lại về sau

Cập nhật: 2026-10-26. Mọi dòng dưới đây đều dựa trên **lần kiểm thật** (tải/ffprobe/chạy pipeline), không dựa trên
mô tả của dataset. Media **không** vào repo (`data/` đã gitignore): chỉ lưu đường dẫn, kích thước, hash và kết quả.

## 0. Quy tắc dùng chung

1. Chỉ lưu **tham chiếu** trong repo; không commit media, không redistribute.
2. Luôn kiểm `ffprobe` + kích thước/hash trước khi đưa vào metric; file tải lỗi (0 hoặc vài chục byte) phải bị loại
   và **không** được tính là "0 detection".
3. Dataset công khai **không** dùng để ký nghiệm thu capability (G2/G4/G5); chỉ dùng để phát triển, regression và
   phát hiện lỗi đường ống.
4. Ghi rõ ODD: camera cố định (fixed) hay dashcam/UAV; ảnh hay video; có nhãn frame-level hay chỉ nhãn mức clip.

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

## 6. Việc nên làm khi cần "dataset tốt hơn" lần tới

1. **Fall/person-down, 1080p, có nhãn frame**: ưu tiên mua/lấy **full UniDataPro 1.047 video kèm annotation**
   (nguồn ngoài HF) — đây là bộ duy nhất đã chứng minh chạy đúng ODD.
2. **Negatives/FP cho #28**: cần clip **1080p camera tĩnh, cảnh bình thường** (dùng phần không-fall của UniDataPro
   hoặc field data); UCSD không đủ độ phân giải.
3. **#47 vehicle**: DAD_A3D (nhãn mức clip) hoặc DoTA (nếu chấp nhận tải 55 GB).
4. **#64/#68/#58**: UCF-Crime mirror (13 lớp) khi capability tương ứng được implement.
