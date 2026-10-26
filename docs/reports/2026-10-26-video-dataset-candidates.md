# Dataset video cho bài toán hiện tại — khảo sát & cách chạy (2026-10-26)

Mục đích: chọn dataset **camera cố định** để (a) chạy thử luồng event→clip→server→review và (b) chấm
điểm capability đang mở, thay vì chỉ benchmark độ trễ trên 2 clip Wikimedia sẵn có.

## 1. Tiêu chí chọn

| Tiêu chí | Vì sao |
|---|---|
| Camera cố định, góc nhìn kiểu giám sát | ODD hiện tại là camera cố định; dashcam/drone là ODD khác (#46, #56) |
| Có **nhãn theo thời gian** (frame/segment) | Muốn tính recall/FP/độ trễ phải có onset/end, không chỉ đếm detection |
| License cho phép dùng nội bộ (research/CC) | Repo chỉ lưu **tham chiếu + sha256**, media không commit (`data/` đã gitignore) |
| Tải được, kích thước vừa lab | Lab chạy CPU x86; clip 1080p ngắn là đủ cho smoke + đo |
| Map được vào capability đang mở | #25/#26/#27/#53 person-down, #47 vehicle, #28 hard negatives |

## 2. Tier A — dùng được ngay (nhỏ, có nhãn, đúng ODD)

| Dataset | Nội dung | Dùng để chấm | Truy cập (kiểm 2026-10-26) |
|---|---|---|---|
| **UR Fall Detection (URFD)** | ~70 chuỗi falls + ADL, 2 camera (RGB + depth), trong nhà | #25 fall có onset, #26 lying bền vững, **FP/giờ trên ADL** (hard negatives cho G2) | `http://fenix.ur.edu.pl/~mkepski/ds/uf.html` → **HTTP 200** |
| **CAUCAFall** | ~250 video RGB, 10 người × 5 tình huống × 5 lần, phòng lab | #25 recall theo người/bối cảnh, kiểm ảnh hưởng ánh sáng/che khuất | `https://data.mendeley.com/datasets/7w7fccy7ky/5` → **HTTP 200** |
| **Le2i Fall Detection** | ~191 clip, 4 phòng khác nhau | độ bền theo phòng/góc máy (proxy cho ODD mở rộng #21) | trang ĐH Bourgogne (research license) |

## 3. Tier B — mạnh hơn nhưng cần đăng ký/tải lớn

| Dataset | Nội dung | Dùng để chấm | Truy cập |
|---|---|---|---|
| **UCF-Crime** | ~1.900 video CCTV, 13 lớp (Fighting, Assault, Abuse, Vandalism, Arson, Explosion, Accident…) | #64 ẩu đả, #68 phá hoại, #62 tai nạn; normal clips làm negative | trang CRCV **000 từ host này** → cần mirror/đăng ký |
| **CUHK Avenue / ShanghaiTech Campus** | camera cố định, nhãn frame-level anomaly | hiệu chuẩn recall/FP cho "bất thường" khi chưa có nhãn nghiệp vụ riêng | trang CUHK **000** → cần đăng ký/mirror |
| **VIRAT Video Dataset** | giám sát ngoài trời, person/vehicle events, độ phân giải cao | #14/#47, kiểm tracker + vehicle motion | `https://viratdata.org/` → **200** (cần thoả agreement) |
| **UA-DETRAC** | nhiều camera giao thông cố định, bounding box xe | #47 vehicle pipeline, đếm/luồng xe | research license |
| **PKLot / CNRPark+EXT** | bãi đỗ xe camera cố định, nhãn occupancy | #62 đỗ sai vùng/giờ (cần thêm zone + schedule của site) | research license |
| **XD-Violence / UBI-Fights** | video bạo lực (audio-visual / web) | #64 ẩu đả — chỉ sau khi có policy | phụ thuộc YouTube |

## 4. Tier C — chỉ train/demo, **không** dùng để nghiệm thu

- 2 clip Wikimedia hiện có (`data/benchmark/`): CC BY-SA 4.0, **không nhãn** → chỉ đo latency/FPS (đúng như
  báo cáo 2026-10-21 đang làm).
- BDD100K / DoTA: dashcam, khác ODD camera cố định.
- FloodNet / Sen1Floods11: UAV/satellite → không đại diện góc nhìn cột đèn.
- TACO / UAVVaste: ảnh rác, không phải video sự kiện.

## 5. Nhóm **không** có dataset công khai phù hợp (cần field data)

#57 vùng nguy hiểm (ROI theo site) · #61 chiếm vỉa hè · #62 đỗ sai **theo giờ** · #63 đám đông theo
ngưỡng site · #66 cây đổ · #67 đèn không sáng theo lịch · #27 person on stationary vehicle.
Dùng clip công khai để chứng minh **luồng chạy** không thay được nghiệm thu capability (đúng luật repo:
synthetic/mock không thay real held-out evidence).

## 6. Chấm điểm thế nào với nhãn có sẵn

1. Chuyển nhãn frame-level → **event window** theo policy pre10/post20 (`domain/evidence_contract.py`):
   `onset` = frame đầu tiên thuộc chuỗi sự kiện; `end` = frame cuối.
2. Đo trên mỗi video: **recall** (event có alert trong ±tolerance của onset), **độ trễ** (onset → durable
   commit trong outbox), **FP/giờ** (alert trên chuỗi ADL/normal), **completeness** của clip (complete/partial).
3. G2: negatives = các chuỗi ADL/normal → `tools/negative_audit_report.py --alerts <alerts.jsonl>
   --negatives <negatives.jsonl> --capability person_down --min-recall 0.90` (Horvitz-Thompson có sẵn).
4. Không ký chất lượng khi chỉ có clip public không nhãn.

## 7. Quy trình chạy (lệnh cụ thể)

```sh
# 1) Tải (data/ đã gitignore — không commit media; ghi sha256 + license vào docs)
curl -L '<dataset-url>' -o data/benchmark/urfd.zip && sha256sum data/benchmark/urfd.zip

# 2) Chuẩn hoá về 1080p H.264 để giống ODD lab
ffmpeg -i data/benchmark/urfd/fall-01.mp4 -vf scale=-2:1080 -c:v libx264 -pix_fmt yuv420p \
       -r 25 data/benchmark/urfd_fall01_1080p.mp4

# 3) Chạy luồng edge (decode → detect → track → incident → recorder) trên file
cat > /tmp/edge.json <<'JSON'
{"source": "data/benchmark/urfd_fall01_1080p.mp4", "output_dir": "data/edge/urfd",
 "analytics_enabled": true, "manifest_path": "models/yolox-tiny/manifest.json",
 "model_path": "data/oracle/yolox_tiny.onnx", "mode": "fast", "sample_fps": 5}
JSON
.venv-oracle/bin/python -m apps.edge.doctor --config /tmp/edge.json --start

# 4) Benchmark độ trễ + đếm detection trên đúng clip đó (--video mới thêm 2026-10-26)
.venv-oracle/bin/python tools/run_benchmark.py \
  --video data/benchmark/urfd_fall01_1080p.mp4 --max-frames 300 --sample-fps 10 \
  --output-report docs/reports/2026-10-26-urfd-benchmark.md --output-json data/benchmark/urfd_results.json

# 5) Provenance detector (oracle replay, không qua runtime)
.venv-oracle/bin/python -m apps.edge.oracle_replay \
  --video data/benchmark/urfd_fall01_1080p.mp4 --manifest models/yolox-tiny/manifest.json \
  --model data/oracle/yolox_tiny.onnx --sample-fps 2

# 6) Chấm recall/FP khi có labels.jsonl (onset/end/capability/negative)
.venv-oracle/bin/python tools/negative_audit_report.py --alerts data/urfd/alerts.jsonl \
  --negatives data/urfd/adl.jsonl --capability person_down --min-recall 0.90 -o data/urfd/report.json
```

## 8. Đã kiểm trong hôm nay (bằng chứng)

- `tools/run_benchmark.py` trước đây hard-code 2 clip ⇒ thêm `--video` (repeatable) để benchmark clip dataset
  mới mà không sửa code.
- Smoke thật trên clip có sẵn qua `--video`: `shibuya` 13.1 FPS (median 57.69 ms, pose 3.97 ms/người);
  `intersection_traffic` 14.73 FPS (54.56 ms) baseline và 16.31 FPS khi bật pose. Đã sửa lỗi
  `relative_to(ROOT)` làm tool crash khi ghi output ra ngoài repo (ví dụ `/tmp`).
- Reachability hôm nay: URFD **200**, CAUCAFall/Mendeley **200**, VIRAT **200**; CUHK Avenue **000**,
  UCF-Crime **000** (cần mirror/đăng ký trước khi lên kế hoạch).

Đã chạy bước 1: xem [URFD smoke run](2026-10-26-urfd-smoke-run.md) — luồng chạy đúng, 0 event person-down, chưa có nhãn onset để chấm recall.

## 9. Thứ tự đề xuất

1. **URFD** (nhỏ, có ADL): chạy smoke end-to-end + đo FP/giờ — mở khoá #25/#26 và cho #28 negatives thật.
2. **CAUCAFall**: kiểm recall theo người/bối cảnh.
3. **Avenue/ShanghaiTech** nếu lấy được: hiệu chuẩn FP trên cảnh "bình thường" đông người.
4. **VIRAT/UA-DETRAC**: khi bắt đầu #47 vehicle.
5. Field clips cho #57/#61/#62/#66/#67 — cần người có quyền cung cấp, không thay bằng dataset public.

## 10. Kiểm tra bộ dữ liệu local: `/media/tieubaoca/HDD1/F/dataset/video/fall-accident/`

Kiểm 2026-10-26 bằng `find`/`unzip -l`/`ffprobe`, chạy thật qua `tools/eval_clip.py`. Tổng 4,6 GB.

### 10.1 Đã xác minh

| Bộ | Có gì trên đĩa | Kết luận |
|---|---|---|
| **DAD_A3D — video** | `videos.zip` 2,7 GB, đã giải nén ra `DAD_A3D/videos/` = **1.750 clip** `*.mp4`, 1280×720@25 fps, 4,0 s, chia `training/testing` × `positive/negative` (456/830/166/302) | **DÙNG ĐƯỢC** cho flow/latency + video-level positive/negative |
| **DAD_A3D — annotation** | `annotation/*.txt` 620 file, chỉ phủ **100 video id**; dòng: `video_id, cột2, class(car/bike/motorbike), x1,y1,x2,y2, accident_flag(0/1)`. **Cột 2 không khớp nghĩa "frame id của clip 100 frame"** (max 25) **cũng không khớp "object index"** (3217 dòng/video, 582 dòng cùng một giá trị cột 2, box đều khác nhau) và không có README trong bản copy | **CHƯA dùng được làm ground truth** — thiếu schema; không dùng để chấm precision/recall/onset |
| **DAD_A3D — frame labels** | `A3D_frame_labels.zip` = 1.087 file, mỗi file 100 dòng `<id> <0|1>` ⇒ **đúng dạng nhãn frame** nhưng khoá theo `<youtube_id>_<index>`, **không map** được sang `videos/000001.mp4` nếu không có manifest gốc A3D | Tiềm năng, chưa nối được |
| **CADP** | `keyframes.tar.gz` = 28.281 JPEG theo video; `annotations_CADP.json` 226 video (keyframe track, có `type: "Traffic camera views"`); 1 clip mẫu 2400×1200@25 fps | **CHỈ ẢNH** — eval detector trên ảnh; muốn chạy video phải tải clip gốc CADP |
| **DoTA** | chỉ `repo/` + `DoTA_annotations.zip` + split + `download_DoTA.py`; **không có video** | **KHÔNG DÙNG ĐƯỢC** cho tới khi tải video |

### 10.2 Chạy thật trên 12 clip DAD (6 positive / 6 negative), 720p25, `--sample-fps 10`

```sh
.venv-oracle/bin/python tools/eval_clip.py --video .../testing/positive/000456.mp4 ... \
  --sample-fps 10 --output-json /tmp/dad_eval12.json
```

| Kết quả | Giá trị |
|---|---|
| Clip / frame | 12 / 600 |
| Detections | 4.257 (car 2.553, person ~700) |
| **Events** | **0** trên cả 12 (không có capability vehicle-accident trong pipeline) |
| p50 latency | median **37,04 ms**, min 28,5, max 37,9 |

⇒ Pipeline đọc ổn định dữ liệu dashcam 720p ở quy mô dataset; **chưa có gì để "đỏ/đạt" về sự kiện** vì #47 chưa được implement.

### 10.3 Kết luận

1. **DAD_A3D là bộ video dùng được ngay** (1.750 clip đã giải nén), nhưng **nhãn frame-level chưa dùng được** do
   schema annotation không được tài liệu hoá trong bản copy này và không khớp cả hai cách đọc phổ biến.
2. **Không bộ nào là person-fall** (dù thư mục tên `fall-accident`): DAD/DoTA là dashcam, CADP là ảnh
   traffic-camera ⇒ không thay được URFD/CAUCAFall/field data cho person-down.
3. **ODD khác** (dashcam ≠ camera cố định 1080p) ⇒ dùng phát triển/kiểm model, **không** dùng ký #21/#49.
4. **Sửa lại nhận định trước trong tài liệu này**: đoạn cũ nói "onset = frame đầu tiên `accident_flag=1`" và
   "22/25 file có chuyển 0→1" là **sai** — cột 2 không phải frame id của clip, nên không thể suy onset từ các file
   `annotation/*.txt`. Đã bỏ `tools/eval_detector_agreement.py` (viết theo giả định có GT per-frame, không có
   input hợp lệ trong repo).
5. Muốn chấm được nhánh vehicle (#47) cần **một trong hai**: (a) manifest A3D gốc để map
   `A3D_frame_labels.zip` → `videos/*.mp4`, hoặc (b) tải video DoTA (`repo/dataset/download_DoTA.py`) vì DoTA có
   annotation theo frame. Khi đó mới dựng `labels.jsonl` + chấm recall/latency.
6. License: DAD/DoTA/CADP research-only — dùng nội bộ, không commit media, chỉ lưu đường dẫn + hash.

### 10.4 Hai tài nguyên còn thiếu — đã thử lấy và bị chặn (bằng chứng)

**a) Video DoTA: nguồn YouTube đã chết.** `DoTA_urls.txt` có 184 URL; thử `yt-dlp --simulate` 18 URL
(12 đầu + 6 giữa) → **18/18 "This video is unavailable"**. README của DoTA cũng cảnh báo "high ratio of lost video
URL". Đường còn lại là bundle Google Drive chính thức (**55 GB** = 5×10 GB + 5 GB, hoặc folder 6 video riêng cho
các URL hỏng); `drive.google.com` trả 200 và `gdown` đã cài, nên về kỹ thuật là tải được nhưng cần quyết định
riêng vì 55 GB/hàng giờ. DoTA `annotations/` (4.677 JSON, có `anomaly_start`/`anomaly_end`/`video_start/end`)
đã có sẵn ⇒ chỉ thiếu video.

**b) Mapping A3D (số hiệu clip ↔ youtube_id) không có trong bản copy này.** Đã kiểm:
`videos.zip` chỉ chứa `*.mp4`; `A3D_detections.zip` = 1.204 `.pkl` (1.089 positive/115 negative) khoá theo
`<youtube_id>_<index>_<n>`; `A3D_frame_labels.zip` = **1.087** `.txt` khoá theo `<youtube_id>_<index>`;
`annotation/*.txt` dùng id số nhưng là object-level; không file `datalist/manifest` nào. GitHub repo search
`"A3D" accident dashcam` → **0 kết quả**. ⇒ Phải lấy danh sách gốc từ tác giả DAD/A3D (hoặc bản release có kèm
`datalist`).

**c) Phần đã sẵn sàng để chạy ngay khi có mapping:** `tools/a3d_labels.py` (có test) đọc trực tiếp
`A3D_frame_labels.zip` — đã chạy thử trên archive thật: **1.087 label file** được parse — rồi ghép với mapping
JSON bạn cung cấp để sinh `labels.jsonl` (clip, positive, onset 0-based + giây, duration). Tool **không đoán**
mapping: thiếu/sai thì báo `problem_count` và exit 1.

```sh
# khi có mapping.json {"<youtube_id>_<index>": "videos/training/positive/000123.mp4", ...}
.venv-oracle/bin/python tools/a3d_labels.py \
  --frame-labels .../DAD_A3D/A3D_frame_labels.zip --mapping mapping.json \
  --videos-root .../DAD_A3D --output-jsonl data/benchmark/a3d_labels.jsonl
```
