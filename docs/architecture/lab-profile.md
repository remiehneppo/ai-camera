# Hồ sơ lab và protocol nghiệm thu

**Cập nhật:** 2026-11-11 (commit `17d9a32`; inventory host probe gốc 2026-10-12). **Trạng thái:** Inventory workstation đã probe ở thời điểm lịch sử; bằng chứng remediation phần mềm tại `17d9a32` đạt **979 passed, 207 subtests passed** và `mypy` sạch trên **83 source files** (xem [docs/README.md](../README.md) và [log khắc phục](../logs/2026-11-11-review-remediation.md)); chưa nghiệm thu ODD, capacity thiết bị biên, chất lượng thực tế hoặc recovery (G3–G5 mở).

Đây là snapshot của workstation dùng trong lab, không phải hồ sơ site hay edge target. Số probe chỉ mô tả máy tại thời điểm ghi; giá trị `pending` cần người chịu trách nhiệm và evidence/sign-off, không được thay bằng ước lượng.

## Facts đã probe

| Hạng mục | Quan sát | Giới hạn |
|---|---|---|
| OS/kernel | Linux, Ubuntu-packaged kernel `7.0.0-31-generic`, x86_64 | Chưa pin image/OS deployment cho edge |
| CPU | Intel Core i5-12400F, 6 cores / 12 threads | Workstation host; không suy ra camera capacity |
| RAM | 31 GiB total, 13 GiB available lúc probe | Snapshot động, không phải budget của service |
| Accelerator | NVIDIA GeForce RTX 5060 Ti, 16311 MiB; driver 595.84 | Không phải target RKNN; GPU utilization/thermal/throughput chưa đo |
| Filesystem `/` | ext4, 915 GiB total, 103 GiB available (89% used) | Chỉ ảnh chụp dung lượng; không chứng minh endurance/quota/reserve |
| `/media/tieubaoca/HDD1` | ext4, 1.8 TiB total, 926 GiB available (47% used) | Không xác nhận là storage edge hoặc failure domain độc lập |
| Camera device | Không có `/dev/video*` tại thời điểm probe | RTSP camera/SKU/firmware/codec/session chưa được cung cấp hoặc kiểm tra |
| Network | Ethernet và Wi-Fi interfaces up; có default route | WAN/uplink throughput, latency, outage và clock correlation chưa đo |
| Lab stack | Docker CLI có; `docker compose ps` không phân giải được cấu hình vì `DASHBOARD_TOKEN` và `DEVICE_TOKENS` thiếu | Probe không khởi động hay thay đổi service; credentials không ghi vào hồ sơ |
| Repo fixtures tại probe #02 | Chưa có model/sample trong inventory ban đầu | Snapshot lịch sử; cập nhật #11 bên dưới, không suy production clearance |

Nguồn: read-only probes `uname -a`, `lscpu`, `free -h`, `lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS`, `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader`, `df -hT / /media/tieubaoca/HDD1`, `find /dev -maxdepth 1 -name 'video*' -print`, `ip -brief link`, `ip route`, `docker compose ps`, và inventory repo bằng `rg --files`. Full command/result record: [ticket #02 log](../logs/2026-10-12-ticket-02.md).

## Cập nhật software lab #11 — 2026-10-12

- Commit `e47d6cf`: manifests/attribution tại `models/yolox-tiny/`, independent goldens tại `fixtures/oracle/`; binary/photo ở ignored `data/oracle/`. Hash đầy đủ và rights scope nằm trong manifests, không dùng mutable release URL thay pin bytes.
- Python3.12.3, ORT1.20.1 CPU, NumPy1.26.4, OpenCV-headless4.10.0.84. Raw-BGR preprocessor source pin riêng với released binary và per-class postprocessor; mismatch old-tag preprocessing đã được user duyệt hiệu chỉnh.
- Pinned runtime full suite85/85 pass, no-record golden original13detections/10person, crop9/7, negative0. Đây là conformance fixtures, không đo recall/FP/capacity/field quality. [Evidence #11](../logs/2026-10-12-ticket-11.md).

## Ứng viên bổ sung — cập nhật tài liệu 2026-10-20

[Quyết định Q35](../logs/2026-10-20-requirements-expansion.md) bổ sung RF-DETR + ViTPose để đánh giá, không thay baseline YOLOX/RTMPose/ONNX/software decode hay các pins lab đã ghi. Jetson Orin NX là dòng hardware ứng viên (không phải Xavier NX), chưa chọn board deployment/accepted SKU. RAM/SKU, OS/SDK/runtime, exact model variants/checkpoints/hash, license/data/privacy clearance, model quality và camera/FPS/capacity đều `pending`; inventory workstation ở trên không phải kết quả Orin NX.

[Hồ sơ ứng viên](../requirements/technology-candidates.md) ghi capability và gates; [danh mục tình huống](../requirements/urban-safety-scenarios.md) không phải chứng nhận độ phủ. Detector + pose không tự đáp ứng các hành vi theo thời gian hay toàn bộ 13 nhóm/nhánh phá hoại; từng capability cần temporal/domain logic và quality/ODD acceptance riêng. Person-down một camera/ROI lòng đường vẫn đi trước tai nạn xe và các nhóm mở rộng.

## Thử nghiệm và Benchmark Dataset — Quan sát Lịch sử 2026-10-21

- Tải và ghim SHA-256 bộ video giám sát đô thị 1080p chuẩn mở (CC BY-SA 4.0) vào `data/benchmark/` bằng công cụ `tools/fetch_benchmark_dataset.py`, metadata tại `data/benchmark/manifest.json`:
  - `shibuya_crossing_1080p.mp4` (87.9 MB, SHA-256 `6689609b91920ae7276a74332763084e80a13754c87ce43332982bf95099fa2e`): Kịch bản luồng người đi bộ, phục vụ đo tracking người và trích xuất pose keypoints.
  - `intersection_traffic_1080p.mp4` (42.2 MB, SHA-256 `e2ac922ab543c444852e0116967cc28274692f07da87cca266edaf82ac3ff806`): Kịch bản phương tiện giao thông qua nút giao, phục vụ đo nhận diện và bám vết đa lớp đối tượng.
- Kết quả đo đạc tự động qua `tools/run_benchmark.py` trên workstation lab x86 (Intel Core i5-12400F, ONNX Runtime CPUExecutionProvider):
  - **Baseline Pipeline (YOLOX-Tiny + ByteTrack + IncidentEngine + FileRecorder):** Thông lượng đạt **16.35 – 20.10 FPS**, độ trễ trung vị P50 từ **44.79 – 56.25 ms**, bộ nhớ RAM đỉnh **266.7 – 334.9 MB**.
  - **Full Pipeline + RTMPose-Tiny (17 keypoints SimCC):** Thông lượng đạt **8.84 – 10.56 FPS**, trích xuất pose trung vị P50 từ **3.73 – 3.84 ms / người**, bộ nhớ RAM đỉnh **519.8 – 530.4 MB**.
  - Báo cáo chi tiết và bảng latency breakdown: [Báo cáo Benchmark Pipeline](../reports/2026-10-21-pipeline-benchmark-report.md).
- Ghi nhận kiểm thử phần mềm lịch sử (trước remediation 2026-11-09) từng báo cáo 918 passed (190 subtests) và 79 source files `mypy` clean. Tại commit `17d9a32` (2026-11-11), bằng chứng remediation quan sát được đạt **979 passed (207 subtests)** và `mypy` sạch trên **83 source files**; danh mục registry khai báo 14 kịch bản đô thị (US01–US14), trong đó công cụ đánh giá `tools/eval_all_scenarios.py` chỉ hỗ trợ 4 baseline và 11 extended scenarios (`US04`, `US10`, `US14` giữ trạng thái `unconfigured` theo cấu trúc công cụ vì không cung cấp điều khiển ROI).
- **Giới hạn và ranh giới lịch sử:** Các số đo 2026-10-21 trên đây là kết quả thăm dò trên CPU workstation x86 cho pipeline suy luận/nhận diện, **chưa đo đồng thời hoạt động ghi ring/clip liên tục, đóng gói bằng chứng và tranh chấp băng thông WAN**. `tools/run_benchmark.py` và các công cụ phát lại hiện đã được hợp nhất qua module `tools/replay_runner.py` với timestamp hữu tỉ suy từ frame gốc và kiểm tra trạng thái fail-fast (chi tiết tại [log đồng bộ](../logs/2026-11-11-docs-architecture-sync.md) và [README.md](../../README.md)). Dòng NVIDIA Jetson Orin NX chỉ là ứng viên tham khảo (chưa chọn target board/SKU); chưa nghiệm thu target capacity, thermal soak 24–72h hay thử nghiệm thực địa (G3–G5).

## Scope, workload và ODD

| Loại | Giá trị hiện tại | Trạng thái |
|---|---|---|
| Use case | Person-down, một camera cố định và ROI lòng đường trước | Scope lab đã duyệt; chưa có site/camera để xác nhận |
| Camera/edge count | Một camera / một edge là đơn vị triển khai ban đầu | Target workload, chưa đo |
| 1080p, 10–15 analysis FPS; 1–4 camera | Khoảng workload nghiên cứu để thử | Không phải capacity hoặc acceptance đã đạt |
| Person pixel minimum, camera pose/ROI cụ thể, ánh sáng/thời tiết/occlusion bounds | `pending` | Product/operations + ML cần định nghĩa từ site và data được phép dùng |
| Quality thresholds, recall/FP denominator, sample sufficiency và review minutes/alert | `pending` | Product/ML/QA cần duyệt protocol trước khi ký G2 |
| Vehicle, PTZ/multi-plane và calibrated motion | Ngoài scope baseline | Vehicle cần calibration và G4b riêng khi được bật |
| Samples/model lab #11 | YOLOX-Tiny ONNX và Shibuya public-domain fixture đã pin SHA/size/source/runtime; user duyệt lab ngày 2026-10-12 | Exact released-weight/training-data rights, privacy/personality và site/production clearance vẫn pending; không suy từ source Apache-2.0 |
| Site owner, named acceptance signer | `pending` | Product/operations gán tên và ngày trước site acceptance |

### Đã chọn làm target, chưa phải phép đo

| ID | Preliminary target | Acceptance boundary |
|---|---|---|
| Q6 | Event ring 10 phút; pre-roll 10 giây; post-roll 20 giây; server clips 7 ngày; outage budget 24 giờ cho clip chưa ACK | Sizing inputs; bitrate, event rate, quota, time-to-full, endurance và autonomy chưa đo. Không xóa protected/unACK evidence theo outage budget |
| Q16 | P95 từ durable edge event commit tới dashboard hiển thị ≤5 giây trên LAN | Chỉ ký với clock basis/correlation, uncertainty, sample count và browser timing; không gồm temporal verification hoặc post-roll upload và không chứng minh AI quality/capacity |
| Hardware | ONNX/software decode là baseline lab; board deployment chưa chọn; Orin NX là dòng ứng viên | Exact RAM/SKU/SDK và workload camera/FPS pending; không tuyên bố hardware decode, RKNN, target capacity hay thermal envelope đạt |
| Recovery | RPO/RTO, recorder gap budget và detection time | `pending`, phải gắn service/data scope, fault case, measurement và owner; không lấy outage budget làm RTO |

Theo hiệu chỉnh Q36, raw clip giữ 10 giây trước/20 giây sau anchor: person-down giữ baseline contracts §3 (person fall có onset quan sát dùng onset estimate có provenance; persistent lying/on-vehicle thiếu onset dùng first qualifying observation của chuỗi persistence đang dùng, không gọi là onset); các nhóm mới dùng mốc đủ điều kiện cảnh báo. Không đổi runtime hoặc anchor baseline person-down. Clip có thể chỉ bao phủ một phần sự kiện kéo dài. Ghi mốc bắt đầu quan sát/thời gian duy trì, vùng/config và provenance; onset ngoài clip phải thể hiện rõ. Lịch sử quan sát không thay video; không tự thêm nhiều clip/NVR dài ngày. Complete/partial/missing theo [contracts §3](contracts.md).

Sizing chỉ được tính sau khi thu bitrate/profile thực, event/day, pin overlap, queue/outbox, recording+upload contention và retention. Ghi missing input là `null`/`pending`; không suy capacity từ CPU/GPU model hoặc dung lượng đĩa tổng.

## Protocol tối thiểu

Trước mỗi run, pin commit/build, OS/SDK/runtime, model/config/dataset hashes, schema/rule/calibration versions; xác nhận fixture có quyền dùng, preliminary target, clock/uncertainty, workload, quota/reserve, owner và recovery method. Không chạy destructive power-cut nếu chưa xác định thiết bị lab, backup và người phục hồi.

| Case | Thao tác | Expected / evidence | Gate |
|---|---|---|---|
| Replay determinism | Cùng fixture với fixed inputs và clock | Outcomes/provenance ổn định; manifest fixture/hash và command | G1 |
| Camera/session loss | Disconnect/reconnect hoặc feed gap khi có nguồn thật | Operational fault/degraded rõ, epoch không nối sai, recorder gap/evidence partial đo được; synthetic không thay RTSP proof | G1 |
| Slow/failed storage | Inject lỗi/quota trên fixture hoặc disk lab riêng | Không ACK giả; protected evidence giữ nguyên; reserve/fault bounded và recovery trace | G1/G4a |
| WAN unavailable/resume | Cô lập endpoint trong thời gian được duyệt, sau đó phục hồi | Event/evidence/outbox còn durable, age/bytes đo được, reconcile idempotent; không xóa theo 24h target | G4a |
| Clock/latency | Ghi capture/receive/commit/render clock basis cùng sai số và sample count | Q16 chỉ pass khi tương quan đủ; nếu thiếu clock evidence thì `blocked`, không kết luận từ timestamp đơn lẻ | G1 |
| Quality/ODD từng capability | Held-out positives/hard negatives và unsupported conditions theo approved manifest, gồm ngày/đêm/mưa trong bounds đã kiểm thử | Report denominator, bỏ sót, báo nhầm theo camera/giờ, latency từ diễn biến đủ điều kiện đến cảnh báo, unknown/degraded và review load; ngưỡng/sufficiency theo site/workload pending thì không pass G2 | G2 |
| Thay detector/pose/runtime | Pin exact artifacts, mapping tensor/keypoints và pre/postprocess; chạy golden/native-oracle conformance và event regression | Giữ contract semantic và temporal outcomes trong tolerance được duyệt; không coi export/inference chạy được là đạt | G1/G2 trước chấp nhận engine |
| Actual target full-system capacity | Trên actual SKU/RAM/SDK và camera profiles đã khóa, chạy decode + perception + tracking + các module bật/temporal state + recording/ring/clip + upload đồng thời | P95/P99, queue/drop/gap, memory/I/O/storage/power/headroom và thermal soak 24–72h; không suy từ x86 hoặc inference-only FPS; chưa có device/workload/sign-off thì blocked/not-run | G3 |
| Power-cut/restore | Chỉ trên device cụ thể đã chọn, có snapshot/backup và recovery owner | Loss/gap theo approved RPO/RTO và recovery trace; chưa có device/signer thì `not-run/blocked` | G4a |

Mỗi case lưu `pass/fail/blocked/not-run`, expected/actual, command thật, timestamp/correlation, IDs/hashes của dữ liệu được bảo vệ, report, residual risk và reviewer. Failure matrix đầy đủ nằm tại [integration-release](../implementation-checklists/integration-release.md); case không chạy không được đánh dấu pass.

## Quyết định và việc còn thiếu

- Product/operations: gán site/use-case signer, ODD bounds và quality/review targets.
- Edge/platform: xác nhận camera/board, stream ownership, timestamp, storage mount/quota, uplink và workload thật.
- ML + Product/legal: giữ model/fixture pins lab #11; hoàn thiện released-weight/training-data/privacy/site clearance và held-out dataset trước production/quality acceptance.
- QA/operations: xác định RPO/RTO, recorder gap budget, fault scope, recovery device/owner và cách đo.

Các mục trên là gate mở, không cản synthetic/demo hoặc replay software hiện có; chúng chặn kết luận live-site, target capacity, quality sign-off và field readiness tương ứng.

## Bằng chứng kỹ thuật và ranh giới kiểm chứng 17d9a32 (cập nhật 2026-11-11)

Tổng hợp ranh giới hệ thống quan sát được tại commit `17d9a32` theo [log khắc phục](../logs/2026-11-11-review-remediation.md) và [mục lục tài liệu](../README.md) (thuật ngữ chuẩn tại [CONTEXT.md](../../CONTEXT.md)):

- **Kiểm thử phần mềm:** **979 passed, 207 subtests passed**, `mypy` sạch trên **83 source files** (bằng chứng remediation quan sát được; không tự suy diễn thành nghiệm thu hiện trường hay tuân thủ pháp lý/an ninh).
- **Media auth, fixture smoke và đường dẫn stream:** Ranh giới media control T2 (`fix-civiwatch-media-control-auth`) sử dụng `alexxit/go2rtc:1.9.15` ghim digest với credential ngoài (`GO2RTC_API_USER`, `GO2RTC_API_PASSWORD`), chặn foreign WebSocket origin (403), trả 401 khi thiếu auth và 404 với các route quản trị exit/restart/config; fixture smoke `/api/stream.mp4` trả HTTP 200 kèm header MP4 `ftyp`. Tuy nhiên, `LivePerceptionRunner` và `RtspRingRecorder` vẫn mở luồng kết nối trực tiếp tới nguồn upstream ([ADR-0007](../adr/0007-rtsp-stream-ownership.md) ở trạng thái `proposed`). Media helper/adapter không chứng minh go2rtc single-session fanout trên camera thật, độ trễ WebRTC hay lưu trữ bằng chứng; giao diện dashboard vẫn dùng đường dẫn MJPEG sẵn có.
- **Huấn luyện (Blueprint vs Active):** Quy trình dry-run tạo artifact blueprint riêng biệt, bảo toàn các tệp model đang hoạt động (active deployments); huấn luyện thường không có CUDA thất bại đúng kỳ vọng và tập COCO được tái tạo khi nhãn đổi. Ba mô hình huấn luyện trên dữ liệu trộn (`yolox_tiny_civiwatch_416`, `yolox_s_civiwatch_640`, `yolo26s_civiwatch_640`, xem [log huấn luyện](../logs/2026-11-11-three-models-training-and-edge-benchmark.md)) mang tính chuyên biệt miền góc camera trên cao (99.1% dữ liệu giao thông), chưa giải tỏa bản quyền trọng số/dữ liệu và chưa qua gate triển khai thực địa.
- **Verification, Storyboard và Snapshot:** Tuân giữ ý định thiết kế của [ADR-0005](../adr/0005-incident-snapshot-ownership.md), [ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md) và [ADR-0008](../adr/0008-civiwatch-v2-hybrid-vlm-architecture.md): pipeline sở hữu hậu kiểm và `snapshot.py` dựng đầy đủ snapshot. Mặc định VLM verifier cho tình huống đô thị và phương tiện đặt `endpoint_url=""` ở trạng thái **offline** (biến môi trường đơn lẻ không tự kích hoạt egress nếu chưa chọn verifier tường minh). Khi bật verifier từ xa, cuộc gọi chạy **đồng bộ dưới processing lock** của pipeline; tại thời điểm neo (`anchor`), các frame storyboard tương lai không khả dụng nếu chưa được nạp sẵn vào buffer (kể cả khi replay); `build_grid` lấy mẫu lại từ buffer quá khứ và có thể lặp lại frame, không bảo đảm 6 quan sát độc lập.
- **Lưu trữ, Hình học và Pose:** Thao tác SQLite enqueue event, outbox và retrieval request là atomic trong một transaction, nhưng việc tạo pin và ghi tệp clip video nằm trên filesystem **ngoài transaction SQLite**. Ma trận Homography mặt đất ($3\times 3$) trong live config là mẫu **chưa hiệu chuẩn** (uncalibrated template); khả năng batching của pose phụ thuộc đồ thị và các yêu cầu đồng bộ có thể chạy tuần tự.
- **Phạm vi công cụ đánh giá:** Registry có 14 kịch bản, nhưng `tools/eval_all_scenarios.py` chỉ chạy 4 baseline và 11 extended scenarios; **US04, US10, US14 giữ trạng thái `unconfigured`** theo thiết kế công cụ hiện tại (không có điều khiển ROI trên CLI, không tự kích hoạt khi chỉ đổi config).
- **Trạng thái cổng nghiệm thu:** Target hardware/SKU, hiệu chuẩn hiện trường, quyền dữ liệu/mô hình và toàn bộ các cổng **G3–G5** giữ ở trạng thái mở (`pending/open`).
