# Hồ sơ readiness cho hệ thống CiviWatch (`civi-watch`)

**Cập nhật:** 2026-11-11 (commit `17d9a32`, theo [Review remediation](../logs/2026-11-11-review-remediation.md)). **Trạng thái:** Bộ test kiểm thử phần mềm quan sát remediation đạt **979 passed, 207 subtests passed** và `mypy` sạch trên **83 source files** (xem [docs/README.md](../README.md); không suy luận là sign-off thực địa). Danh mục hệ thống định nghĩa 14 kịch bản an toàn đô thị (US01–US14); công cụ đánh giá `tools/eval_all_scenarios.py` hiện hỗ trợ 4 baseline và 11 extended scenarios (US04, US10, US14 chưa được cấu hình do công cụ không cung cấp ROI controls). Các bảng mẫu hardware/site dưới đây phục vụ thu thập dữ liệu nghiệm thu thực địa (G3–G5). Toàn bộ các cổng G3–G5, phần cứng target/SKU, hiệu chuẩn thực địa và quyền pháp lý mô hình/dữ liệu vẫn đang mở. Tài liệu này hỗ trợ [kiến trúc](system-architecture.md), không thay đặc tả module.

## Hồ sơ cần khóa

Inventory workstation và ODD/protocol snapshot hiện tại: [hồ sơ lab](lab-profile.md). Facts host này không phải edge capacity evidence.

Owner dưới đây là vai trò đề xuất; chủ dự án phải gán người cụ thể, ngày và link bằng chứng trước khi đánh dấu đạt. `TBD`, `null`, `REQUIRED` là thiếu dữ liệu, không phải giá trị nghiệm thu.

Quyết định vòng 1 ngày 2026-10-11: chưa chọn board; ONNX/software decode làm baseline lab, event ring + clip sự kiện, một server lab nội bộ. G1 lab không đòi hardware đích; inventory lab ghi thực tế, mục target chưa chọn ghi rõ pending. Trước nghiệm thu target capacity/pilot vẫn cần facts, decoder/buffer và benchmark trên thiết bị thật; kết quả x86 không chứng minh Raspberry Pi hoặc RKNN đã đạt. Tracker C++ ở P1, pose native ở P2; backend mới phải giữ contract semantic và vượt conformance/event regression.

| Artifact | Nội dung bắt buộc | Owner đề xuất | Gate |
|---|---|---|---|
| Physical/facts sheet | Camera SKU/firmware; main/sub codec/profile/bitrate/FPS; concurrent sessions đã test; board/RAM/OS/kernel/SDK; storage SKU/TBW/filesystem; switch/VLAN/WAN; UPS/power/thermal enclosure | Edge/platform | Trước BOM và Slice 1 |
| Stream ADR | Upstream/reconnect/capture owner; dual/relay; timestamp mapping; bounded queue; main/sub; kill/hang test | Edge/platform | Trước nghiệm thu Slice 1 |
| Workload/retention | Camera/site, analysis FPS, pose mean/burst, event/day, ring/pre/post, pinned retention, export/delete policy | Product + edge | Trước BOM |
| Preliminary SLO | ODD, latency, evidence completeness, offline autonomy, RPO/RTO scope, AI quality và review capacity | Product + operations | Trước hardware/PoC |
| Storage plan | Mount/quota/reserve, shared physical failure domains, WAL/checkpoint/fsync budget, time-to-full, endurance/backup | Platform | Tối thiểu Slice 1; đủ trước pilot |
| Threat/privacy record | Attacker/trust boundaries, physical access, credentials; căn cứ xử lý, retention/access/transfer, legal approval tên/ngày/site | Security + pháp chế | Trước pilot có dữ liệu thật |
| Model manifest | Exact weights/hash, code/checkpoint/dataset terms, training/source lineage, conversion/runtime/pre/post versions, golden/field report, clearance | ML + pháp chế | Trước release lên site |
| Benchmark/capacity | Workload và provenance, bottlenecks, thermal 24–72h, recording/upload đồng thời, P95/P99 và headroom đã đo | Edge + ML | Trước field pilot |
| Failure/recovery matrix | Fault, expected degraded state, dữ liệu được bảo vệ, detection time/RTO, test evidence và runbook | QA + operations | Trước field pilot |
| Field acceptance | Ngày/đêm/mưa/che khuất, positives/hard negatives, negative-audit sampling/uncertainty, recall/FP và operator load | ML + product | Trước fleet |
| Central SLA/restore | Ingestion/DB/object-store failure domain, durable receipts, backup/restore/HA theo SLA | Backend + operations | Trước fleet theo SLA |

## Ứng viên công nghệ và gate mở rộng — 2026-10-20

Theo [quyết định Q35](../logs/2026-10-20-requirements-expansion.md), RF-DETR + ViTPose là ứng viên đánh giá bổ sung; YOLOX/RTMPose/ONNX và software decode vẫn là baseline lab. NVIDIA Jetson Orin NX là dòng ứng viên, không phải Xavier NX; board deployment chưa chọn và chưa có accepted SKU. Exact RAM/SKU, OS/SDK/runtime, checkpoints/weights/hash, license/data clearance, model quality và camera/FPS/capacity đều `pending`. Xem [hồ sơ ứng viên](../requirements/technology-candidates.md).

[Danh mục tình huống](../requirements/urban-safety-scenarios.md) không phải cam kết detector + pose đáp ứng toàn bộ 13 nhóm hoặc nhánh phá hoại. Mỗi capability cần dữ liệu/quan sát domain, temporal/state/rule/config phù hợp và gate quality riêng: positives/hard negatives, bỏ sót, báo nhầm theo camera/giờ, latency từ diễn biến đủ điều kiện đến cảnh báo, tải review và ODD ngày/đêm/mưa đã kiểm thử; ngưỡng số theo site/workload còn pending. Thiếu hình ảnh hoặc ngoài điều kiện đã kiểm thử là unknown/degraded, không phải negative. Person-down đạt gate trước, tai nạn xe sau; giữ ADR-0001.

Trước chấp nhận engine cần conformance semantic/native-oracle và event regression. Trước ký capacity cần benchmark **actual target SKU toàn hệ thống**: decode, perception, tracking, các module bật/temporal state, ghi ring/clip và upload đồng thời; đo P95/P99, memory/I/O/storage, headroom và thermal soak 24–72h. Không suy từ inference-only FPS, TOPS, workstation x86 hoặc việc register thêm module. Privacy/site approval, exact artifact rights và provenance vẫn là gate, không được bỏ qua vì là ứng viên.

Theo hiệu chỉnh Q36, raw clip giữ **10 giây trước/20 giây sau anchor**: person-down giữ baseline [contracts §3](contracts.md), person fall có onset quan sát dùng onset estimate có provenance, persistent lying/on-vehicle thiếu onset dùng first qualifying observation của chuỗi persistence đang dùng (không gọi là onset); các nhóm mới dùng mốc đủ điều kiện cảnh báo. Không đổi anchor/runtime person-down sang alert-condition. Clip không bảo đảm bao phủ toàn bộ sự kiện kéo dài hay onset. Giữ mốc bắt đầu quan sát/thời gian duy trì, vùng/config và nguồn gốc; onset ngoài clip phải thể hiện rõ, lịch sử quan sát không thay video. Complete/partial/missing theo hợp đồng hiện hành; không tự thêm nhiều clip hoặc NVR dài ngày.

## Site profile tối thiểu

Target lab đã xác nhận ở Q6: pre-roll 10 giây, post-roll 20 giây, event ring 10 phút, server giữ clip 7 ngày và edge outage budget 24 giờ cho clip chưa ACK. Đây là đầu vào sizing; chưa xác nhận quota, bitrate/event rate, time-to-full hoặc bảo đảm autonomy. Q12 bảo vệ pinned/unACK evidence, dọn dữ liệu được phép trước; vẫn thiếu thì degraded và evidence mới partial/failed. Không tự xóa evidence chưa ACK khi vượt 24 giờ. State/outbox có reserve hữu hạn; khi journal không commit được phải báo fault và không ACK giả.

Minh họa dữ liệu cần thu thập, chưa phải schema runtime. Không đưa credential hoặc URI có password vào hồ sơ.

```yaml
site:
  id: REQUIRED
  facts_sheet_ref: REQUIRED
  physical_diagram_ref: REQUIRED
  privacy_approval_ref: REQUIRED
camera:
  id: REQUIRED
  sku_firmware: REQUIRED
  main_stream_profile_ref: REQUIRED # codec/profile/resolution/FPS/bitrate đo
  sub_stream_profile_ref: REQUIRED # hoặc explicit unsupported
  verified_concurrent_sessions: null
  stream_ownership_adr: REQUIRED
odd:
  profile_ref: REQUIRED # min person pixels, light/weather, occlusion/ROI
workload:
  camera_count_per_edge: null
  analysis_fps_per_camera: null
  pose_mean_roi_per_second: null
  pose_burst_roi_per_second: null
evidence:
  mode: event_ring
  pre_roll_seconds: 10
  post_roll_seconds: 20
  ring_minutes: 10
  pinned_retention_policy_ref: REQUIRED
  quota_and_reserve_ref: REQUIRED
network:
  measured_uplink_mbps: null
  expected_maximum_outage_hours: null
acceptance:
  preliminary_slo_ref: REQUIRED
  capacity_report_ref: REQUIRED
  field_acceptance_ref: REQUIRED
  approved_by: null
  approved_at: null
```

## Sizing evidence và phục hồi WAN

Anchor/ranges và pin recovery theo [contracts §3](contracts.md). Với ring10 phút, phải đo maximum anchor-to-pin delay gồm verification/scheduling/handoff/recovery cộng pre10 giây và clock/keyframe margin; vượt budget báo partial/missing, không coi clip đủ chiều dài là đủ onset.

F03/J05 ghi backlog B, tốc độ upload hữu dụng U và tốc độ sinh evidence G cùng đơn vị. Nếu U ≤ G thì backlog không thoát; nếu U > G, thời gian drain xấp xỉ B/(U−G). Đo cả burst, pin/temp/proxy/WAL/reserve và lúc upload cạnh tranh recording. Outage24h không phải TTL xóa protected data.

G3 áp dụng target thực: ONNX vẫn phải native/oracle/event conformance và soak; chỉ thêm conversion/RKNN parity khi chọn RKNN. Chưa chọn target thì chưa ký capacity, nhưng không chặn lab ONNX.

*Lưu ý benchmark lab lịch sử (quan sát ngày 2026-10-27):* Đã thực hiện đo đạc benchmark perception pipeline đa kịch bản trên workstation x86 (Intel Core i5-12400F, ONNX Runtime CPU) chạy đồng thời cả 4 Engine nhận diện (Person-down, Vehicle incident, Illegal parking, Crowd incident) kèm ByteTracker và RTMPose-Tiny trên video test tổng hợp/dataset đóng:
- **Video 1080p Full HD (`fall_0001`, `shibuya_crossing`):** Độ trễ trung vị P50 đạt 30.3–36.8 ms/frame (tương đương **28–33 FPS** thông lượng suy luận thuần túy).
- **Video 720p HD (`AccidentBench Fixed CCTV`):** Độ trễ trung vị P50 đạt 22.0–24.3 ms/frame (tương đương **40–45 FPS**).
- **Ràng buộc ODD phần cứng:** Đã xác định tiêu chuẩn mục tiêu: **100% camera CCTV giao thông cố định, độ phân giải HD (720p) đến 2MP (1080p)**. Tuyệt đối loại bỏ camera hành trình (dashcam) và camera độ nét thấp (< 720p) khỏi benchmark và hồ sơ triển khai.
- **Ranh giới và giới hạn đo đạc:** Các con số trên là kết quả đo thăm dò quá khứ (exploratory measurement) trên CPU máy trạm x86 cho tầng perception thuần túy, **chưa đo đồng thời với ghi hình ring recording, trích xuất clip evidence và áp lực tải upload WAN**. Đây không phải là bằng chứng năng lực thực tế (capacity) trên thiết bị biên nhúng và không chứng minh tính sẵn sàng thời gian thực trong môi trường vận hành thực địa. `tools/run_benchmark.py` và các công cụ phát lại hiện đã được hợp nhất qua module `tools/replay_runner.py` với timestamp hữu tỉ suy từ frame gốc và kiểm tra trạng thái fail-fast (chi tiết tại [log đồng bộ](../logs/2026-11-11-docs-architecture-sync.md) và [README.md](../../README.md)). Dòng NVIDIA Jetson Orin NX là ứng viên đánh giá, chưa được phê duyệt hay lựa chọn làm deployment SKU chính thức. Thử nghiệm trên phần cứng thật (actual target SKU) kèm tải toàn hệ thống và thermal soak 24–72h là điều kiện bắt buộc trước khi ký nghiệm thu capacity.

## Manifest benchmark tối thiểu

Số chưa đo là `null`; điền lý do trong `missing_measurements`. Clock basis phải cho biết capture age hay receive age. Không ký capacity từ manifest mẫu này.

```json
{
  "device_profile_hash": null,
  "camera_profiles_hash": null,
  "model_artifact_hash": null,
  "config_snapshot_hash": null,
  "dataset_manifest_hash": null,
  "duration_hours": null,
  "workload": {
    "camera_count": null,
    "analysis_fps_per_camera": null,
    "pose_mean_roi_per_second": null,
    "pose_burst_roi_per_second": null,
    "recording_and_upload_profile_ref": null
  },
  "clock_basis": null,
  "results": {
    "frame_age_p95_ms": null,
    "frame_age_p99_ms": null,
    "event_latency_p95_ms": null,
    "event_latency_p99_ms": null,
    "recorder_gap_seconds": null,
    "evidence_completeness_ratio": null,
    "fsync_p99_ms": null,
    "max_wal_bytes": null,
    "peak_outbox_bytes": null,
    "max_temperature_c": null,
    "sustained_power_watts": null,
    "resource_timeseries_ref": null,
    "event_quality_report_ref": null
  },
  "missing_measurements": ["Template only; no hardware run"],
  "accepted_capacity": null,
  "approval_ref": null
}
```

## Rủi ro và quyết định còn mở

Priority là thứ tự xử lý thiết kế, chưa phải xác suất định lượng từ vận hành. Ghi likelihood/confidence sau khi có field data; không coi mọi rủi ro dưới đây là lỗi đã xảy ra.

| Risk | Priority | Trigger / bằng chứng cần | Mitigation / quyết định |
|---|---|---|---|
| Recorder phụ thuộc analytics upstream | P0 | Kill/hang analytics tạo segment gap | Stream ADR + fault domain đúng §6.3a |
| Disk full/wear/failure | P0 | Time-to-full, write/fsync error, health/endurance | Quota/reserve/I/O budget; ghi residual physical SPOF; backup theo RPO |
| Capacity hoặc nhiệt không đạt | P0 | Frame age/pose burst/throttle trong soak | Giảm scope/camera, đổi BOM; không chỉ giảm threshold AI |
| Domain shift/ID switch/missing onset | P0 | Field regression/negative audit theo ODD | Persistent-lying path, uncertainty, dataset/acceptance theo site |
| Privacy hoặc artifact license chưa clearance | P0 | Thiếu hồ sơ owner/ngày/phạm vi/hash | Chặn production; không suy license repo thành weights license |
| Native crash làm mất analytics state | P1 trước pilot | Crash/restart hoặc RTO không đạt | Pinned SDK/soak; process isolation có điều kiện, reset epoch |
| Update compromise/rollback/clock uncertain | P0 trước pilot | Bad signature/expired/old sequence/wrong target | Trust bootstrap/rotation/revocation + signed activation tests |
| Malformed storm | P1 trước pilot | Forensic quota/counter tăng | Bounded samples/duplicate compaction; truncation fault |
| WAN hoặc central outage | P1 | Outbox age/bytes, ACK outage | Offline autonomy, reconcile; central HA theo SLA |
| Python/C++ divergence | P1 | Golden/event tolerance fail | Shared conformance kit, chặn release |
| Review overload | P1 | Alerts cần review × phút/alert | TCO gồm true/false/uncertain alerts; ký review capacity |

Không chọn sẵn ba process, shared-memory IPC, WORM compliance mode, Kubernetes hoặc HA đa site. Những lựa chọn đó cần fault test, threat model, retention và SLA; rollback phải giữ trust high-water mark và data compatibility.

## Độ bền SQLite và upload evidence (cập nhật 2026-10-17)

- SQLite WAL-reset race sửa ở 3.51.3 (backport 3.44.6/3.50.7). Python hệ thống và `.venv-oracle` đều dùng 3.45.1 (libsqlite3-0 3.45.1-1ubuntu2.8; chưa xác minh backport của distro). `apps/edge/doctor.py` cảnh báo không chặn; pin bản đã sửa trước pilot.
- HTTP 413 khi upload là operational fault: không retry, giữ nguyên pin cục bộ, request ở trạng thái `failed` với `operational_fault`; ACK metadata không giải phóng clip. Cần sizing artifact tối đa theo bitrate/GOP thực. Chi tiết: [log](../logs/2026-10-17-sqlite-upload.md).

## Hiện trạng kỹ thuật và bằng chứng commit 17d9a32 (cập nhật 2026-11-11)

Tổng hợp các ranh giới đã quan sát tại commit `17d9a32` theo [log khắc phục](../logs/2026-11-11-review-remediation.md) và [mục lục tài liệu](../README.md) (thuật ngữ chuẩn tại [CONTEXT.md](../../CONTEXT.md)):

1. **Kiểm thử phần mềm và Typecheck**:
   - Bằng chứng remediation quan sát được: **979 passed, 207 subtests passed** (bộ pytest đầy đủ) và `mypy` sạch trên **83 source files**. Kết quả này thay cho số liệu cũ 918/190/79 trước remediation, không được suy diễn thành chứng nhận chất lượng hiện trường hay tuân thủ pháp lý/an ninh.
2. **Media Auth, Fixture Smoke và Đường dẫn Streaming**:
   - Ranh giới xác thực media T2 (`fix-civiwatch-media-control-auth`) dùng image `alexxit/go2rtc:1.9.15` ghim digest, bắt buộc credentials ngoài (`GO2RTC_API_USER`, `GO2RTC_API_PASSWORD`), kiểm tra cô lập: `/api/streams` trả 401 khi thiếu auth và 200 khi đủ auth, chặn foreign WebSocket origin (403), loại bỏ route quản trị exit/restart/config (404). Fixture smoke với file mount read-only (`/api/stream.mp4`) trả HTTP 200 kèm header MP4 `ftyp` cho `civi-cam-01` và `civi-cam-02`.
   - Tuy nhiên, `LivePerceptionRunner` và `RtspRingRecorder` vẫn mở kết nối trực tiếp tới nguồn camera upstream ([ADR-0007](../adr/0007-rtsp-stream-ownership.md) giữ nguyên trạng thái `proposed`). Media adapter/helper không chứng minh khả năng single-session fanout của go2rtc trên camera thật, độ trễ WebRTC hay độ bền giữ bằng chứng. Dashboard web vẫn giữ nguyên luồng hiển thị MJPEG sẵn có, không đồng nghĩa đã chuyển sang WebRTC/go2rtc.
3. **Huấn luyện Mô hình: Tách biệt Blueprint và Active**:
   - Quy trình dry-run tạo riêng tệp artifact kiểu blueprint, bảo toàn nguyên vẹn manifest và model đang hoạt động (active deployments); huấn luyện thường không có CUDA thất bại đúng kỳ vọng và dữ liệu COCO tái tạo khi nhãn thay đổi.
   - Ba mô hình huấn luyện trên dataset trộn (`yolox_tiny_civiwatch_416`, `yolox_s_civiwatch_640`, `yolo26s_civiwatch_640`; xem [log huấn luyện](../logs/2026-11-11-three-models-training-and-edge-benchmark.md)) bị ràng buộc chuyên biệt miền góc cao (99.1% dữ liệu giao thông trên cao) và chưa có quyền pháp lý/dữ liệu hay gate nghiệm thu để thay thế triển khai thực địa.
4. **Ranh giới Verification, Storyboard và Snapshot**:
   - Ý định thiết kế tại [ADR-0005](../adr/0005-incident-snapshot-ownership.md), [ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md) và [ADR-0008](../adr/0008-civiwatch-v2-hybrid-vlm-architecture.md) không thay đổi: pipeline sở hữu việc hậu kiểm (verification) và `snapshot.py` dựng đầy đủ snapshot sự kiện.
   - Mặc định verifier đô thị và phương tiện có `endpoint_url=""` ở trạng thái **offline**; biến môi trường đơn lẻ bị bỏ qua cho tới khi chọn verifier tường minh. Khi bật verifier từ xa, cuộc gọi thực thi **đồng bộ dưới pipeline processing lock**.
   - Ở thời điểm neo (`anchor`), các frame storyboard tương lai không khả dụng nếu chưa được nạp vào buffer (kể cả khi chạy replay, hệ thống không tự nhìn trước tương lai); `build_grid` lấy mẫu lại từ buffer quá khứ và có thể lặp lại frame, không bảo đảm có 6 quan sát độc lập theo thời gian.
5. **Tính Nguyên tử Lưu trữ, Hình học và Pose**:
   - Thao tác SQLite enqueue sự kiện, outbox và retrieval request được thực thi atomic trong cùng một transaction; tuy nhiên, việc ghi file video và tạo/giải phóng pin clip trên filesystem nằm **ngoài transaction SQLite**.
   - Mẫu ma trận Homography mặt đất ($3\times 3$) trong cấu hình live vẫn là mẫu **chưa hiệu chuẩn** (uncalibrated template). Khả năng batching của pose phụ thuộc vào đồ thị xử lý và các yêu cầu đồng bộ hiện tại có thể chạy tuần tự.
6. **Phạm vi Công cụ Đánh giá (Evaluation Tooling) và Benchmark**:
   - Hệ thống đăng ký 14 kịch bản trong Registry (US01–US14). Công cụ `tools/eval_all_scenarios.py` chỉ đánh giá 4 baseline và 11 extended scenarios; **US04, US10 và US14 bị loại trừ theo cấu trúc hiện tại (`unconfigured`)** do công cụ CLI không cung cấp điều khiển ROI và không tự động kích hoạt chỉ bằng việc thay đổi cấu hình.
   - Các benchmark lịch sử trước đây chỉ đo suy luận perception, **chưa đo đồng thời recording, đóng gói bằng chứng và tranh chấp băng thông WAN**; do đó chưa chứng minh năng lực xử lý thực tế (capacity), chất lượng hiện trường hay tính thời gian thực.
7. **Cổng Mở (Open Gates)**:
   - Lựa chọn target hardware/SKU thực tế, hiệu chuẩn hiện trường, giải tỏa bản quyền trọng số/dataset, quyền riêng tư/pháp lý và toàn bộ các cổng nghiệm thu **G3–G5** tiếp tục giữ ở trạng thái mở (`pending/open`).
