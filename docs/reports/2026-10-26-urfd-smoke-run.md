# URFD smoke run — chạy luồng thật trên dữ liệu fall (2026-10-26)

Chạy thử theo [khảo sát dataset](2026-10-26-video-dataset-candidates.md): tải một subset **UR Fall Detection**
(rgb cam0) và chạy qua pipeline edge thật. Mục tiêu của lượt này là **kiểm luồng + đo hiệu năng**, không phải
nghiệm thu chất lượng.

## 1. Dữ liệu đã tải (research-only, **không** commit — `data/` đã gitignore)

Nguồn: `http://fenix.ur.edu.pl/~mkepski/ds/uf.html` (HTTP 200 hôm nay). 6 clip RGB + 3 CSV đồng bộ hoá:

| File | Bytes | sha256 (rút gọn) |
|---|---|---|
| fall-01-cam0.mp4 | 1.299.104 | `5fcb77e5…76bc` |
| fall-02-cam0.mp4 | 878.005 | `4135a857…77b7` |
| fall-03-cam0.mp4 | 1.756.850 | `6496581c…2aff` |
| adl-01-cam0.mp4 | 1.194.846 | `b7b0220c…16f8` |
| adl-02-cam0.mp4 | 1.448.005 | `46d63331…994a` |
| adl-03-cam0.mp4 | 1.451.527 | `44ec54c8…a3fa` |
| fall-01-data.csv / fall-02-data.csv / adl-01-data.csv | 2.466 / 1.631 / 1.358 | xem lệnh `sha256sum` trong log |

Đặc điểm kỹ thuật (ffprobe): **640×240, 30 fps, 3,67–7,17 s**. Tức là **khác ODD lab** (camera cố định 1080p
ngoài trời) về độ phân giải và bối cảnh trong nhà — dùng để kiểm luồng, không đại diện ODD.

Không có file nhãn onset trên trang này: chỉ có `*-data.csv` (frame, ms, accelerometer) và `*-acc.csv`.
⇒ **không tính được recall**; muốn có nhãn phải lấy file annotation từ mirror khác, hoặc suy ra onset bằng một
luật được ghi rõ và dán nhãn là "derived" (không được coi là ground truth).

## 2. Chạy gì, kết quả gì

### a) Benchmark hiệu năng (decode → YOLOX-Tiny → ByteTrack → IncidentEngine → FileRecorder)

```sh
.venv-oracle/bin/python tools/run_benchmark.py --video data/benchmark/urfd/fall-01-cam0.mp4 \
  --max-frames 60 --sample-fps 10 --output-report /tmp/urfd-bench.md --output-json /tmp/urfd-bench.json
```

| Kịch bản | FPS | Median latency |
|---|---|---|
| Baseline | 43,46 | 20,53 ms |
| + RTMPose-Tiny | 25,75 | 28,32 ms (pose 4,6 ms/người) |

### b) Full edge flow qua runtime (recorder process + analytics process riêng)

```sh
.venv-oracle/bin/python -m apps.edge.doctor --config /tmp/urfd-fall-01.json --start
```

Kết quả cả 2 clip (fall-01, adl-01): `outcome: ok`, recorder `completed`, **50–54 observation** được consume,
segment `.mkv` + metadata được ghi trong `data/edge/urfd-*/lab-replay/`. Không có outbox event vì `EdgeRuntime`
chạy **detector-only** (đúng thiết kế hiện tại — incident engine không nằm trong runtime).

### c) Đánh giá mức event bằng tool mới `tools/eval_clip.py`

Tool mới (viết trong lượt này): chạy `PerceptionPipeline` đầy đủ (decode → detect → track → incident → outbox) và
in metric mức event. Chạy 6 clip, `--sample-fps 10 --pose`:

| Clip | frames | detections | person | pose outcomes | **events** | p50 |
|---|---|---|---|---|---|---|
| fall-01 | 54 | 235 | 62 | 20 | **0** | 24,84 ms |
| fall-02 | 37 | 192 | 48 | 24 | **0** | 26,03 ms |
| fall-03 | 72 | 344 | 113 | 60 | **0** | 27,85 ms |
| adl-01 | 50 | 138 | 44 | 26 | **0** | 28,39 ms |
| adl-02 | 60 | 177 | 51 | 35 | **0** | 27,48 ms |
| adl-03 | 60 | 185 | 58 | 29 | **0** | 24,70 ms |

## 3. Kết luận & phát hiện

1. **Luồng chạy đúng trên dữ liệu thật**: decode, detect (person được nhận), track, pose (20–60 outcome), recorder
   ghi segment, runtime tách process, không lỗi. Đây là bằng chứng luồng end-to-end ngoài 2 clip benchmark cũ.
2. **Không có event person-down trên cả fall lẫn ADL**: đường ống hoạt động nhưng **tầng quyết định chưa được
   calibrate cho ODD này** (trong nhà, 640×240, khung bị crop, vật thể "chair" chiếm đa số detection). Đây là
   phát hiện đúng loại cần thiết: không thể coi "chạy được" là "nhận đúng".
3. **Không thể chấm recall với URFD công bố hiện tại** (không có nhãn onset trên trang) ⇒ mọi con số "recall" nếu
   có sẽ là bịa. Cần annotation từ mirror hoặc luật suy ra được ghi rõ.
4. Khác ODD (640×240 vs 1080p, indoor vs street) nên **không dùng URFD để ký #21/#25/#26/#49**; chỉ dùng cho
   flow/latency + regression công cụ.

## 4. Việc tiếp

1. Lấy **annotation onset URFD** (mirror) hoặc định nghĩa luật suy ra từ `*-data.csv` + accel, ghi rõ "derived".
2. Thêm **ODD profile indoor/nhỏ** + chỉnh ngưỡng rồi chạy lại để thấy event xuất hiện (nếu không xuất hiện, đó là
   tín hiệu cần sửa logic chứ không phải dataset).
3. Chạy **CAUCAFall** để kiểm chéo người/bối cảnh.
4. Với nghiệm thu capability vẫn phải dùng field data có nhãn do người có trách nhiệm duyệt.
