# Kiến trúc hệ thống AI Camera giao thông tại edge

**Trạng thái:** Thiết kế tham chiếu để triển khai; chưa phải đặc tả API đã implement hoặc cam kết hiệu năng.  
**Ngày lập:** 2026-10-09 theo đồng hồ môi trường. **Cập nhật:** 2026-10-11 theo [đối chiếu review](../logs/2026-10-11-architecture-review-response.md).  
**Phạm vi:** Edge analytics, evidence, server cảnh báo/truy hồi và quản trị thiết bị.  
**Cơ sở:** Các quyết định kỹ thuật trong hội thoại và [báo cáo nghiên cứu](../../traffic-ai-camera-research/report.md).

## 1. Mục tiêu và giới hạn

### 1.1 Mục tiêu

- Phân tích video tại edge, phát hiện tai nạn nghi ngờ, ngã/quỵ xuống/người nằm bất động và các sự kiện đường bộ theo cấu hình.
- Không gửi video liên tục lên server theo mặc định; gửi metadata, ảnh/clip theo chính sách, truy hồi có phân quyền.
- Tái sử dụng domain logic khi đổi camera và compute platform: RTSP test → IP production, Raspberry Pi 5/ONNX Runtime → Orange Pi 5/RKNN → Jetson/TensorRT.
- Đảm bảo kết quả có provenance, timestamp, chất lượng quan sát và trạng thái xác minh; không báo im lặng khi hệ thống mất năng lực.
- Cho phép kiểm thử offline/replay cùng pipeline realtime, benchmark toàn hệ thống trước mở rộng.

### 1.2 Không thuộc mục tiêu

- Không chẩn đoán đột quỵ, ngất, mất ý thức hoặc tình trạng y tế từ video.
- Không tự quyết định xử phạt hay bảo đảm video-speed đáp ứng kiểm định pháp lý.
- Không yêu cầu zero-copy, microservices, Kubernetes, ReID hoặc nhiều detector framework ngay từ MVP.
- Không đảm bảo một model/artifact có thể chạy mọi backend chỉ bằng đổi tên runtime.

### 1.3 Miền hoạt động — ODD

Mỗi camera phải có cấu hình Operational Design Domain: địa điểm, vùng hỗ trợ, góc/tiêu cự, kích thước đối tượng tối thiểu đã kiểm thử, ánh sáng, mưa, mức che khuất, camera cố định/PTZ, mật độ đối tượng và hình học đường. Ngoài ODD hoặc không đủ bằng chứng phải là `unknown/unsupported/degraded`, không phải kết quả âm tính chắc chắn.

## 2. Quyết định và nguyên tắc kiến trúc

| Quyết định đã thống nhất | Hệ quả |
|---|---|
| Ports & adapters, dependency inversion | Domain không import OpenCV, RKNN, ONNX Runtime, SDK camera, network client hoặc DB |
| Ranh giới ứng dụng là detection/pose/track/event | Tensor-level inference engine nằm bên trong adapter model |
| Orchestrator là Application Service | Điều phối lifecycle, scheduling, queue và timeout; không chứa định nghĩa tai nạn |
| Camera và inference backend độc lập | Cấu hình nguồn video không gắn cứng với loại board |
| Logic temporal thay quyết định một frame | Tốc độ/gia tốc/y bất thường chỉ tạo candidate |
| Giữ video nén gốc cho evidence | Recorder không phụ thuộc frame AI đã resize/warp/enhance |
| Motion estimation tùy chọn, có confidence | Tracking compensation không tự chứng minh calibration mặt đường còn đúng |
| CPU frame path trước, hardware buffers sau profiling | Zero-copy phải chứng minh bằng measurement và hợp đồng ownership |
| Một ứng dụng edge trước, recorder là fault domain riêng | Module không mặc định là process/service. Recorder (FFmpeg/GStreamer segmenter hoặc MediaMTX) là process riêng do systemd giám sát; upstream của recorder không nằm trong analytics (§6.3a). Đây là ranh giới cách ly lỗi, không phải ranh giới nghiệp vụ; analytics pin/đọc segments theo contract §6.16. Process riêng không tự cách ly host OOM, disk hoặc nguồn điện |
| Runtime fallback phải rõ | Không âm thầm NPU→CPU hoặc mất inference mà tiếp tục báo bình thường |
| Provenance là contract bắt buộc | Mọi event/alert phải truy được camera/session/frame, config, model artifact hash, calibration version, capability/quality state và evidence còn tồn tại. Trường bắt buộc *hiện diện*, nhưng giá trị tường minh như `uncalibrated`/`unknown_artifact` hợp lệ. Event vi phạm schema vào forensic journal bounded ở trạng thái `malformed`, compact bản lặp và fault alert theo §6.17; không drop im lặng, không hứa lưu vô hạn khi disk lỗi/đầy |
| Recorder ưu tiên hơn analytics | Khi tài nguyên thiếu, giảm analysis FPS/pose trước; không để inference backpressure làm mất video đã mã hóa |
| Hai tầng ngôn ngữ: C++ perception core + Python control | Đường per-frame (decode→preprocess→inference→postprocess→track) là C++ (§6.7a); Python giữ phần tần suất thấp (orchestration, IncidentEngine, evidence, delivery, control). Pixel không đi qua Python trên hot path; chỉ metadata (detections/tracks/pose) vượt ranh giới |

**Công nghệ:** Python orchestration/reference pipeline, FastAPI/Python + MongoDB cho server; ONNX Runtime baseline inference; RKNN/MPP/RGA khi chọn target, alternative backends chỉ khi có yêu cầu. C++17 cho perception core (§6.7a), bindings pybind11/nanobind dự kiến; Python reference giữ làm oracle. Q19 chỉ yêu cầu dev demo UI đơn giản; chọn HTML/JS do FastAPI phục vụ để test qua API, không bắt buộc React app. Đội giao diện riêng ghép UI sản phẩm qua API/schema sau.

## 3. Bối cảnh và topology triển khai

```text
Camera RTSP / USB / CSI / video file
                  │
           Edge Application
   ┌──────────────┼─────────────────────┐
   │ AI pipeline  │ Evidence             │ Control/Health
   │             │ segments + manifest │ config/model/watchdog
   └──────────────┼─────────────────────┘
             Durable outbox
                  │ TLS / mTLS
                  ▼
          Server/API ingestion
       ┌──────────┼───────────────┐
       DB     Object storage   Alert/review workflow
                                  │
                          Dashboard / tích hợp nghiệp vụ
```

Edge tiếp tục phân tích và giữ sự kiện khi WAN lỗi, trong giới hạn retention/quota. Server không nằm trong critical path của detection. Camera RTSP dùng mạng local; camera CSI/USB nối trực tiếp compute device. Không cần NVR nếu edge recorder đáp ứng, nhưng có thể thêm NVR adapter cho production. Camera AI native events là nguồn bổ sung, không điều kiện bắt buộc duy nhất để phát hiện ngã/tai nạn.

### 3.1 Data plane và control plane

- **Data plane:** packets/frames → observations → event → evidence → upload. Ưu tiên độ trễ và tính toàn vẹn.
- **Control plane:** provision, config, calibration, model rollout, health, truy hồi. Không sửa live state tùy ý; thay đổi phải validation, version và activation boundary.
- **Trust boundary:** camera LAN, edge filesystem, transport edge–server, operator và export evidence. Credential không nằm trong event payload, config commit hoặc log.

## 4. Các lớp và quy tắc dependency

```text
entrypoints / composition root
             │
             ▼
        application ───────► domain
             │                ▲
             ▼                │
           ports ◄──────── adapters
```

- **Domain:** entities/value objects, event taxonomy, state machines, temporal rules, uncertainty; không I/O hoặc vendor dependency.
- **Ports:** hợp đồng use-case-facing (`IVideoSource`, `IObjectDetector`, ...), tham chiếu domain contracts.
- **Application:** orchestrator, schedulers, use cases evidence/delivery/control. Chỉ phụ thuộc domain/ports và utilities ổn định.
- **Adapters:** implementations source/decode/model/runtime/storage/network/platform. Có thể dùng thư viện vendor.
- **Composition root:** đọc cấu hình, chọn factory, inject dependencies, validate capability, khởi động/shutdown.

Ports không phải tất cả đều cần abstract base class. Python `Protocol` thích hợp cho structural interfaces; ABC khi có lifecycle/hành vi chung hữu ích. Composition ưu tiên hơn inheritance. Không tạo interface cho từng helper toán học chỉ để có chữ `I`.

## 5. Hợp đồng dữ liệu

Đây là đặc tả semantic; tên trường/cú pháp cuối cùng có thể điều chỉnh khi implement. In-process contracts không được tuần tự hóa toàn bộ buffer qua network.

### 5.1 Clock và định danh

- `device_id`, `camera_id` ổn định; `stream_session_id` đổi khi nguồn reconnect/reset continuity.
- `frame_id` duy nhất trong stream session; `track_id` scoped theo camera/session/tracker epoch, không phải danh tính người.
- `capture_time_utc` optional, có `time_source` và `uncertainty`; RTP/PTS không mặc nhiên là UTC capture time.
- `receive_time_utc` dùng audit; `receive_monotonic_ns` dùng đo latency local. Monotonic chỉ có ý nghĩa trong cùng boot/process clock domain, không so trực tiếp giữa máy.
- `presentation_time` + timebase cho video; source adapter giữ ánh xạ/độ tin cậy. Clock adjustment/reconnect tạo discontinuity, không sinh gia tốc giả.

### 5.2 CompressedPacket / EncodedSegment

Thông tin stream/session, codec/profile, PTS/DTS/timebase, keyframe, discontinuity, payload/buffer ref. Recorder có thể nhận segments thay packets. Copy/refcount phải bảo đảm recorder giữ dữ liệu sau khi decoder release. Không bắt buộc mọi source có đường encoded: USB/CSI raw phải có recorder encoder riêng nếu cần evidence.

### 5.3 FrameMetadata và FrameBuffer

Tách hai phần vì có lifecycle khác nhau:

- **`FrameMetadata` (domain, immutable, không I/O):** `camera_id`, session/frame ID, timestamps, width/height, pixel format, color space/range, plane layout/stride, geometry reference và quality flags. Chưa mặc định BGR cho mọi adapter.
- **`FrameBuffer` (port/adapter, có lifecycle):** tham chiếu dữ liệu điểm ảnh, gắn với một `FrameMetadata`. Domain chỉ thấy metadata.

Theo quyết định Q1 ngày 2026-10-11, Slice 1 dùng ONNX và software decode khi chưa chọn board; contract phải có fixtures stride ≠ width, format/color và buffer lifetime ngay từ đầu. Đường hardware decode/native buffer thật (NV12/MPP khi phù hợp) được kiểm khi chọn target, trước nghiệm thu capacity/pilot; CPU-copy tests không thay thế bằng chứng hardware.

**Buffer contract:** loại CPU/native handle; read/write permission; ownership; acquire/release hoặc context lifecycle; synchronization; validity. Native handles opaque với application/domain. Không giữ frame vô hạn trong track/event history. Scheduler phải release frame khi drop/cancel/fail.

### 5.4 TransformContext

Lưu crop region, resize scale, padding, rotation, distortion correction và mapping input→original image. Bbox/keypoint trả ra original image coordinates; version ảnh gốc/calibration rõ. Phi tuyến lens correction không được giả làm affine matrix. Nếu mapping không có, không xuất tọa độ calibrated.

### 5.5 ObservationBatch

Common envelope: camera/session/frame, timestamps, source/model version, processing status, coverage region, transform/calibration references.

- `Detection`: canonical class, bbox `xyxy` theo pixel ảnh gốc, score, observation source; bbox hợp lệ nằm trong ảnh, score có semantic theo model.
- `Pose`: association track/detection, keypoint schema/version, mỗi keypoint vị trí/score/visibility; điểm thiếu rõ ràng.
- `NativeObservation`: metadata/event camera, timestamp/coordinate quality, loại event và coverage. Không giả snapshot event là dense detection stream.

Status phân biệt `ok_empty`, `ok`, `skipped_by_policy`, `overloaded`, `unsupported`, `failed`, `stale`. Score khác model/backend không được coi đã calibration tương đương.

### 5.6 TrackSnapshot / MotionFeatures

Track lifecycle tentative/confirmed/lost/ended; measured vs predicted point; observation age; association confidence; pose history reference. Lưu history bounded bằng timestamps và semantic features, không mặc định giữ ảnh đầy đủ.

Ground observation chứa vị trí mét, uncertainty/validity, mặt phẳng/vùng calibration. Velocity/acceleration/TTC là estimates với quality; không hợp lệ khi timestamp/track continuity/calibration kém. Ảnh warp hoặc compensation phải rõ hệ tọa độ.

### 5.7 IncidentEvent và EvidenceManifest

Event: UUID, revision/schema version, source device/camera/session, taxonomy, candidate/onset/detection timestamps và uncertainty, lifecycle, severity, score + rule/model provenance, ROI/related tracks, quality/ODD flags, dedup reference, calibration/config version.

Evidence manifest: evidence ID, raw/derived designation, segment range thực tế, requested range, codec, URI/storage state, byte size/checksum, timestamps, redaction/enhancement provenance, retention/pin reason và upload ACK. Không đưa path local như URL tải công khai.

Event revision có thể tới trước clip; server biểu diễn `evidence_pending/unavailable`, không chờ clip mới nhận alert. Event UUID + revision giúp xử lý duplicate/out-of-order. Mọi schema network có version và compatibility policy.

**Network envelope tối thiểu:** `schema_version, message_id, event_id, revision, device_id, camera_id, stream_session_id, event_time, produced_at, config_version, model_lineage, model_artifact_hash, calibration_version, quality_state, payload`. Schema là JSON Schema/OpenAPI trong `schemas/`; CI chạy backward/forward compatibility tests cho các revision còn hỗ trợ.

## 6. Catalog module

### 6.1 Configuration & Composition Root

**Nhiệm vụ:** schema validate YAML/config; resolve secret references; chọn adapter; kiểm tra artifact/capabilities; tạo per-camera pipelines và shared inference resources.  
**Công nghệ dự kiến:** Python, Pydantic hoặc schema validation tương đương, typed factories, YAML.  
**Giao tiếp:** tạo các port implementations, cung cấp immutable config snapshot/version.  
**Chú ý:** fail fast khi model/runtime/device không tương thích; không dynamic import tùy ý từ config không tin cậy; config update phải stage/validate/activate/rollback. Không tạo universal plugin system trước có nhu cầu.

Q13 ngày 2026-10-11: pipeline enabled mà thiếu/sai config phải panic/fail-fast toàn bộ analytics startup (exit nonzero, nêu pipeline/field và mask secrets), không tự bỏ pipeline hoặc báo unavailable rồi tiếp tục. Validate mọi enabled pipeline trước start analytics. Pipeline disabled được phép thiếu config nghiệp vụ và hiển thị unavailable với reason=disabled. Config activation lỗi bị reject và giữ last-known-good; recorder độc lập vẫn tiếp tục. Lỗi runtime sau startup được quy định riêng.

### 6.2 VideoSource

**Port:** `open/start`, nhận frame stream; optional encoded stream capability; health; stop/close.  
**Nhiệm vụ:** nguồn file/RTSP/USB/CSI, auth, reconnect, timestamps, discontinuity, source health.  
**Dự kiến:** file/OpenCV baseline; FFmpeg/GStreamer RTSP; libcamera/V4L2 hoặc vendor CSI stack theo board.  
**Đầu ra:** FrameMetadata + FrameBuffer; encoded packets/segments nếu có.  
**Chú ý:** Wi-Fi/Ethernet không phải hai interface nghiệp vụ khác nhau. URL/password secrets; backoff+jitter, liveness/freeze detection, RTSP TCP/UDP cấu hình và đo thực tế. Replay giữ thời gian nội dung, không dùng tốc độ chạy file để suy tốc độ xe.

### 6.3 Transport/Demux & Decoder — adapter nội bộ

**Nhiệm vụ:** tách transport khỏi decode, duy trì codec/PTS, decode thành frame.  
**Dự kiến:** FFmpeg/GStreamer; Rockchip MPP decode; NVIDIA hardware decoder theo platform.  
**Giao tiếp:** compressed packets→frame buffers.  
**Chú ý:** MPP không thay RTSP client/demux. H.264/H.265/profile/resolution phải kiểm tra; codec change/reconnect invalidates pipeline state. CPU fallback là trạng thái explicit. Decoder port riêng chỉ cần khi thật sự thay hoặc test độc lập.

### 6.3a Stream ownership và fault boundary

Recorder process riêng chưa đủ nếu socket/demux cấp dữ liệu cho nó vẫn nằm trong analytics. Trước truth-path hardware của Slice 1 phải chốt ADR cho đúng camera/firmware; chưa mặc định một topology production.

| Topology | Ownership / điều kiện chọn | Failure contract |
|---|---|---|
| Dual sessions | Recorder tự mở RTSP/demux; analytics tự mở session khác. Đơn giản nếu camera đã qua test concurrent sessions/bitrate/reconnect | Analytics chết không ảnh hưởng session recorder. Hai nhánh có session ID riêng; không giả PTS/frame ID trùng, phải lưu mapping thời gian và uncertainty khi pin |
| Upstream + local relay | Process stream-owner/recorder (hoặc relay độc lập với analytics) sở hữu RTSP/reconnect; analytics subscribe encoded stream qua loopback/UDS | Consumer chậm/chết bị disconnect/drop theo policy, không chặn ghi segment. Stream-owner chết vẫn làm cả hai nhánh mất nguồn; watchdog/reconnect phải đo gap |

Một upstream nghĩa là một session **cho mỗi stream profile được chọn**, không nhất thiết một session/camera: record main + analyze sub vẫn cần hai upstream profiles. Không thêm broker/relay nếu dual sessions đã đạt acceptance. USB/CSI raw cần ownership capture/encode riêng, không áp máy móc topology RTSP.

Contract phải khóa reconnect owner, session/discontinuity IDs, PTS/time mapping, codec change, queue/lag limit, quyền pin/query/release và ACK pin trước cleanup. Recorder là chủ segment lifecycle; coordination dùng metadata/IPC tối thiểu, không để analytics giữ DB lock hoặc transaction dài chặn recorder. Gate: kill/hang/OOM analytics trong fault domain đã cấu hình, recorder vẫn đạt gap budget đã ký; recorder/relay chết phải phát fault và reconcile rõ. Cùng cgroup hoặc host OOM vẫn có thể giết cả hai: giới hạn tài nguyên/service priority phải được test.

### 6.4 Quality & ODD Monitor

**Nhiệm vụ:** blur/overexposure/low-light/freeze/occlusion, độ lệch camera, timestamp quality và ODD flags.  
**Dự kiến:** OpenCV/simple statistics và baseline scene references.  
**Giao tiếp:** frame/features→QualityReport; scheduler/incident engine dùng quality.  
**Chú ý:** gate không âm thầm suppress mọi sự kiện; báo lỗi quan sát. Threshold dựa dữ liệu site. Không đồng nhất khung ít chuyển động với camera bị freeze.

### 6.5 ImagePreprocessor — model adapter nội bộ

**Nhiệm vụ:** color convert, crop, resize/letterbox, normalize, tensor layout; trả TransformContext.  
**Dự kiến:** CPU OpenCV/NumPy, RGA cho Rockchip, CUDA/vendor preprocess khi cần.  
**Giao tiếp:** frame + ModelSpec→prepared input + mapping.  
**Chú ý:** preprocess model-specific; không normalize hai lần nếu RKNN compiler đã cấu hình. Enhancement chỉ bật A/B có provenance; không sửa evidence raw. Một generic preprocess port có thể dùng nhưng không ép mọi backend cùng byte-level pipeline.

### 6.6 Model Registry & Artifact Manager

**Nhiệm vụ:** quản lý model identity, artifact target/backend, checksum, input/output schema, labels, preprocess/postprocess versions, precision/quantization data provenance, SDK requirements, license status và validation report.  
**Dự kiến:** manifest JSON/YAML, local filesystem, signed deployment bundles.  
**Giao tiếp:** lookup compatible ModelSpec→detector/pose factory; rollout service.  
**Chú ý:** `.onnx` và `.rknn` là artifacts khác của model lineage, không coi output giống tuyệt đối. Không tải executable/model tùy ý từ event/network. Production deployment phải qua license gate và regression gate.

### 6.7 InferenceEngine — tensor-level port nội bộ

**Nhiệm vụ:** load/validate model, allocate resources, run inference, trả output/timing/errors; expose supported capabilities.  
**Dự kiến:** ONNX Runtime CPU cho RPi reference; RKNN Runtime/RKNN Lite tùy device/toolchain; TensorRT Jetson; OpenVINO tùy host.  
**Giao tiếp:** prepared tensors/native buffers→output tensors/backend handles.  
**Chú ý:** static/dynamic shapes, layout, dtype, batch, operator support, threads và concurrency phải explicit. Device/runtime objects có thể không thread-safe; không share tùy ý. NEON tối ưu không phải tính năng đảm bảo của mọi build; đo binary/version thật.

### 6.7a Native Perception Core (C/C++)

**Lý do:** runtime ONNX/RKNN/TensorRT vốn là C/C++; chi phí Python nằm ở phần *quanh* inference: copy frame sang NumPy, color convert/letterbox, dequantize output INT8 của RKNN, decode anchor + NMS, crop/affine cho từng ROI pose, glue per-call và tranh chấp GIL khi nhiều camera. Trên board ARM, các phần này có thể chiếm phần lớn ngân sách CPU còn lại sau NPU, nên con số cụ thể phải đo trên phần cứng đích.

**Phạm vi (theo camera, chạy trong thread native, không giữ GIL):**

| Bước | Native implementation |
|---|---|
| Decode | FFmpeg/libav, Rockchip MPP, NVDEC/GStreamer; buffer native (DMA-BUF/MPP buffer) không ra Python |
| Preprocess | RGA (RK3588), CUDA/NPP (Jetson), OpenCV/NEON (CPU); trả `TransformContext` |
| Inference | ONNX Runtime C++ API, RKNN C API (`rknn_api.h`), TensorRT C++ |
| Postprocess | dequant, decode YOLOX, NMS, map bbox về ảnh gốc |
| Tracker | ByteTrack C++ (ở trong core để tránh mỗi frame một round-trip Python) |
| Pose | crop/affine ROI + RTMPose + SimCC decode, theo `PoseRequest` từ Python scheduler |

**Không thuộc core:** IncidentEngine, PoseScheduler policy, evidence, journal/outbox, control, quality policy. Các phần này tần suất thấp, nhiều logic nghiệp vụ, cần thay đổi nhanh, nên giữ Python.

**API ranh giới (hẹp, ổn định, versioned):**

- `PerceptionCore.open(camera_config, model_specs) → handle`; `start/stop/close`; `capabilities()`; `health()`.
- Đầu ra: hàng đợi bounded `ObservationBatch` (detections + tracks + pose + `FrameMetadata` + timing per stage + status `ok/ok_empty/overloaded/failed/stale`). Python `poll(timeout)` hoặc callback; không có frame pixel.
- Đầu vào điều khiển: `request_pose(frame_id, track_ids, deadline)`, `set_analysis_fps`, `set_roi`. Frame cũ hết hạn → `skipped`, không chặn.
- Crop thumbnail cho review (khi cần) đi theo đường riêng, có giới hạn tần suất, không theo mỗi frame.

**Contract và quy tắc:**

- Struct dữ liệu (detection, track, pose, status) sinh từ một định nghĩa chung (ví dụ header + Python dataclass generated, hoặc FlatBuffers) để hai phía không lệch schema.
- Ownership buffer native nằm hoàn toàn trong core; Python chỉ thấy `FrameMetadata` (§5.3). Lỗi C++ đổi thành mã lỗi/typed status ở biên, không để exception C++ vượt qua binding.
- Release GIL trong mọi lời gọi chặn; mỗi camera một thread native, inference context chia sẻ theo policy fairness (§7.2). Context NPU/GPU không thread-safe thì core tự tuần tự hóa.
- **Fault isolation:** core chạy in-process với Python orchestrator; recorder độc lập theo §6.3a. Nếu SDK crash hoặc analytics RTO không đạt khi soak/fault test, đánh giá process isolation trước pilot. Giữ semantic API nhưng cần timeout, restart/epoch reset, reject result cũ và IPC conformance; không chỉ đổi factory là xong. Bounded UDS/loopback cho ObservationBatch đủ ở biên Python; shared memory chỉ cần khi pixel/native buffers thật sự vượt process boundary và profiling chứng minh cần.
- **Parity:** Python reference pipeline (ONNX CPU) là oracle. Golden clips chạy cả hai đường; so detections/tracks theo ngưỡng IoU/score đã thống nhất, và so event output của IncidentEngine. Sai khác vượt ngưỡng chặn release. Conformance kit versioned dùng chung cho Python/C++/backend gồm frames đã clearance, preprocess/transform parameters, detection/pose tolerances, tracker sequences (gaps/ID switches), expected event outputs và dataset hash; unit tests riêng không thay parity.
- Build: CMake, cross-compile toolchain theo board (aarch64), wheel theo profile (`traffic-camera-native-rk3588`, `-jetson`, `-cpu`); sanitizers (ASan/UBSan) và fuzz parser input trong CI trên x86.

**Chú ý:** không viết lại IncidentEngine bằng C++ trước khi profiling chứng minh cần. Không đưa toàn bộ edge app sang C++: lợi ích nằm ở hot path, phần còn lại sẽ chỉ tăng chi phí phát triển.

### 6.8 ObjectDetector

**Port:** detect(frame/request)→DetectionBatch, health/capability.  
**Nhiệm vụ:** đóng gói preprocess/inference/postprocess, label mapping, decode/NMS, bbox về ảnh gốc.  
**Dự kiến:** YOLOX tiny/small baseline; RTMDet đối chứng nếu cần; ONNX/RKNN/TRT adapters.  
**Giao tiếp:** FrameMetadata + FrameBuffer→canonical detections.  
**Chú ý:** model COCO không tự có helmet/plate/accident labels; clipping/ROI/tiles phải dedup và giữ coverage. Không uniform threshold cho mọi backend. Camera-native dense metadata chỉ thay detector khi contract và coverage đã kiểm chứng.

### 6.9 CameraNativeAnalytics Adapter — tùy chọn

**Nhiệm vụ:** nhận ISAPI/ONVIF/vendor event hoặc object metadata, normalize thành NativeObservation.  
**Giao tiếp:** bổ sung trigger/verifier hoặc provider detection nếu dense metadata đáp ứng contract.  
**Chú ý:** có alarm line-crossing không đồng nghĩa có bbox/track mọi frame; không suy ONVIF S/G thành M. Firmware/capability cụ thể phải kiểm chứng. Giữ low-rate analysis fallback để không bỏ ngã chậm/đối tượng đã nằm. Không liên kết identity từ camera bằng giả định bbox proximity không được đánh giá.

### 6.10 MotionEstimator / MotionCompensator — tùy chọn

**Port:** estimate frame-to-frame/global background transform→transform/confidence/validity.  
**Dự kiến:** Identity/no-op default; sparse Lucas–Kanade + robust geometric fit và background mask nếu cần.  
**Giao tiếp:** tracker/geometry monitor nhận transform; coordinate compensation thay full-frame warp khi phù hợp.  
**Chú ý:** xe đông, ít texture, mưa/đêm, parallax làm ước lượng sai. Không coi optical flow xe là camera motion. Sai/large transform invalidate calibration hoặc require recalibration. Không bù hai lần trong tracker và feature computation.

### 6.11 Tracker

**Port:** update per-camera detections + timestamp + optional motion→TrackSnapshotBatch; reset reason.  
**Dự kiến:** ByteTrack Python cho reference/oracle; ByteTrack C++ trong perception core (§6.7a) trên thiết bị đích; ReID/tracker khác chỉ khi giảm lỗi được đo.  
**Giao tiếp:** DetectionBatch→tracks/history; motion/pose scheduler/incident engine consume.  
**Chú ý:** serial updates theo capture/presentation order mỗi camera; multi-camera không share track state. Adapter cần điều chỉnh aging/prediction theo sampling thực tế, không giả ByteTrack stock hỗ trợ arbitrary Δt hoàn hảo. Reset epoch khi mất continuity; out-of-order drop/reorder có giới hạn, không hồi tố state vô hạn.

### 6.12 GroundProjector & Calibration Repository

**Nhiệm vụ:** intrinsic/distortion, camera extrinsic/road plane homography, ROI/lane/stop-line mapping, calibration validity và uncertainty.  
**Dự kiến:** OpenCV geometry, versioned calibration files; wizard/tool offline.  
**Giao tiếp:** point original image→ground position/validity; motion monitor→invalidate; event lưu calibration version.  
**Chú ý:** bbox bottom không luôn contact point; người chân bị che, đường dốc/multi-plane phải unknown hoặc region models. PTZ preset riêng; lưu mốc đo và sai số theo vùng. Không trả m/s đáng tin nếu geometry chưa hiệu chuẩn.

### 6.13 MotionAnalyzer

**Nhiệm vụ:** trajectory smoothing/outlier rejection, velocity/acceleration, direction, stationary state, interaction graph/TTC khi hợp lệ.  
**Dự kiến:** NumPy, Kalman/robust windowed estimates; pure geometry functions.  
**Giao tiếp:** tracks + ground observations + timestamps→MotionFeatures.  
**Chú ý:** measured/predicted phân biệt; derivative khuếch đại jitter; stopped vì đèn đỏ/kẹt xe không phải crash. TTC và overlap chỉ evidence/risk features, không collision proof.

### 6.14 PoseScheduler & PoseEstimator

**Scheduler:** chọn person ROI theo fast-fall trigger, slow-posture sampling, persistent-lying check; fair budget và burst priority.  
**Estimator port:** frame/ROIs→PoseBatch.  
**Dự kiến:** RTMPose model adapter ONNX trước, RKNN/TRT sau conversion test.  
**Giao tiếp:** tracks/features/quality→PoseRequest; pose→temporal history/incident engine.  
**Chú ý:** track/frame association đúng; ROI quá nhỏ hoặc keypoint thiếu là unknown. Sampling policy có coverage metrics; không trigger chỉ từ y spike. Raw frame retention phải bounded để async crop còn buffer hợp lệ. Taxonomy schema pinned; không ghép COCO17/whole-body tùy ý.

### 6.15 IncidentEngine

Quyết định Q5/Q9 ngày 2026-10-11: IncidentEngine nằm trong từng pipeline tính năng cảnh báo đăng ký riêng; lifecycle/config/state tách theo pipeline và camera/session. Pipeline dùng chung semantic event contract có producer pipeline provenance, chia sẻ source/detector/tracker/pose khi tương thích. Chỉ tách process khi cần fault/resource isolation; tách logic không ngăn native crash hoặc quá tải shared resource. Xem [ADR-0001](../adr/0001-feature-pipeline-boundaries.md) và [plan triển khai](implementation-plan.md).

**Port:** evaluate observations/features/time→event transitions; reset/restore policy explicit.  
**Nhiệm vụ:** tai nạn/ngã/bất động, temporal verification, hysteresis, cooldown, dedup nội bộ; attach supporting evidence/uncertainty.  
**Dự kiến:** deterministic FSM + heuristic baseline; TCN/feature classifier hoặc video classifier khi data chứng minh cần.  
**Giao tiếp:** tracks/motion/pose/quality/native events/optional traffic-signal→IncidentEvent.  
**Chú ý:** không chứa vendor tensors, DB calls hoặc code gọi cấp cứu. Missing observation không phải negative. Phân biệt falling/fallen, crash/near-miss/stop; đèn đỏ cần signal timestamp và luật site. Cross-camera dedup chỉ khi có bằng chứng/geometry; giữ original alerts để audit.

**Người nằm trên yên xe đỗ (hard negative phổ biến tại VN):** camera đơn không đo được độ cao, nên tư thế nằm trên yên có thể chiếu như nằm lòng đường. Quy tắc:

- `person_fall` yêu cầu có pha `falling` (hạ thấp nhanh/va chạm) trong track history.
- Track hay bị che hoặc đổi ID đúng lúc ngã (xe máy đông), nên thiếu pha `falling` **không được rơi vào khoảng trống**: người nằm bền vững trong vùng lòng đường mà không quan sát được onset → `person_lying_persistent`, có ngưỡng thời gian và severity riêng.
- Association `on_vehicle`: người chồng lên `motorcycle` **đứng yên, đứng thẳng từ trước** khi người ngả xuống, ổn định N giây → ground point lấy theo bánh xe, không theo thân người; pose (hông trong vùng yên) là bằng chứng phụ.
- `on_vehicle` **chỉ hạ ưu tiên, không suppress**: event vẫn tạo với nhãn `person_on_stationary_vehicle`, vào hàng review mức thấp, không gửi notification khẩn. Lý do: các điều kiện dựa trên bbox 2D rất nhiễu, mà bỏ sót tai nạn đắt hơn nhiều so với một lượt review. Dấu hiệu xe đang chạy rồi dừng đột ngột, bbox xe chuyển thấp/rộng (đổ nghiêng), hoặc chuyển động đột ngột → ưu tiên bình thường.
- Xe đỗ trong làn chạy → `stationary_vehicle_in_lane` (traffic hazard), không phải `person_down`. Chưa đủ bằng chứng → giữ `verifying/unknown`.
- Không phân biệt được ngủ vs bất tỉnh qua video. Mặc định kỹ thuật là hàng review mức thấp như trên. Có báo/không báo/ngưỡng thời gian là **quyết định sản phẩm/đạo đức, cần stakeholder ký** trước pilot, không phải mặc định kiến trúc.
- Góc camera thấp/gần ngang → ODD `degraded` cho loại sự kiện này.

### 6.16 EvidenceRecorder & RetentionManager

**Port:** continuously append encoded data; pin(requested interval,event); finalize manifest; query/export authorized; release pin.  
**Nhiệm vụ:** ring buffer segments, pre/post clip, keyframe-aware boundaries, manifests, quota, retention, crash recovery.  
**Dự kiến:** FFmpeg/GStreamer segment/remux hoặc MediaMTX, chạy **process riêng** (xem §2); filesystem + SQLite metadata.  
**Phạm vi lưu cần chốt trước khi chọn SKU:** ghi liên tục kiểu NVR N ngày, hay chỉ ring buffer ngắn quanh event? Ví dụ 4 Mbps liên tục ≈ 43,2 GB/ngày/camera (GB thập phân, chưa overhead; `GB/day ≈ 10.8 × Mbps`). Ring ngắn giảm dung lượng chiếm dụng nhưng không giảm lượng ghi liên tục. Không chọn microSD thường làm evidence media production; endurance SKU/TBW, write amplification, nhiệt và tuổi thọ phải theo BOM/workload đã đo.  
**Phát lại:** H.265 không phát ổn định trên mọi trình duyệt. H.264 thuận lợi cho browser nhưng Pi 5 phải software decode; chọn codec theo decode budget và playback đã đo. Nếu dùng H.265, có thể tạo proxy H.264 như derived artifact có chủ đích (transcode ở server, hoặc ở edge nếu còn encode budget).  
**Giao tiếp:** encoded stream→segments; event→pin/finalize; uploader→ACK; control→query.  
**Chú ý:** pre-event segments phải tồn tại trước trigger; pin atomically để cleanup không xóa. Reconnect/PTS discontinuity có thể tạo clip gaps, ghi rõ. Nếu source raw phải encode budget; Orin Nano không NVENC. Overlay/redacted video là derived artifact, raw không overwrite. Retention ưu tiên/capacity failures có cảnh báo; không pin vô hạn khi WAN mất lâu.

### 6.17 EventJournal, Outbox & Uploader

**Nhiệm vụ:** persist event revisions/outbox trước gửi; retry/backoff, idempotency, resume evidence upload, ACK riêng metadata/clip.  
**Dự kiến:** SQLite transactions edge, HTTPS JSON + chunk/multipart upload cho MVP; MQTT optional theo integration.  
**Giao tiếp:** event + manifest→durable journal/outbox→server; server receipts→ACK state.  
**Chú ý:** transaction journal/outbox cùng DB để tránh crash giữa hai write. Clip file và DB không có atomic transaction chung: temp file/fsync/rename theo platform, manifest states và startup reconciliation. At-least-once + server dedup, không hứa exactly-once network. Hash/size verify, limits/timeouts, bounded retries và dead-letter/operator state.

**Local evidence commit protocol** (delivery state tách riêng, xem 7.5):

1. DB transaction ghi manifest `pending` (intent) **trước** khi tạo temp file — để mọi temp file đều có chủ.
2. Ghi temp → `fsync(file)` → atomic `rename` → `fsync(dir)`.
3. DB transaction: checksum/size/range thực tế, manifest `finalized_local` (hoặc `partial` kèm lý do gap).

| Startup: DB | File | Hành động |
|---|---|---|
| Không manifest | temp/final mồ côi | quarantine rồi xóa theo retention; log |
| `pending` | temp tồn tại | validate → hoàn tất bước 2–3 hoặc `failed` |
| `pending` | final tồn tại | verify checksum → bước 3 |
| `finalized_local` | file mất | `evidence_missing` + fault alert |
| bất kỳ | checksum sai | quarantine, `corrupt`, alert |
| `uploading` | — | re-query server theo evidence ID, idempotent re-upload |

**SQLite production profile phải pin:** `journal_mode=WAL`, `synchronous=FULL` (mục tiêu RPO metadata = 0 buộc FULL: với WAL + `NORMAL`, commit gần nhất có thể mất khi cắt điện dù DB không hỏng; đo chi phí fsync trên storage thật), checkpoint policy/max WAL size, filesystem giả định (ext4 data=ordered, không network FS), hành vi disk-full (từ chối event mới hay xóa evidence ưu tiên thấp) và power-loss test thật (cắt điện, không chỉ `kill -9`).

**Durability boundary:** RPO=0 là mục tiêu cho transaction đã commit / evidence đã finalized khi filesystem, OS và storage thực hiện đúng flush và media còn lành. WAL/FULL không chống hỏng ổ, controller nói sai flush hoặc mất cả thiết bị. ACK không được thành công nếu write/fsync lỗi. Cần power-cut trên BOM thật và bản sao ở failure domain khác nếu yêu cầu chịu disk/site loss. Tham chiếu [SQLite WAL](https://www.sqlite.org/wal.html) và [giới hạn sync của storage](https://www.sqlite.org/howtocorrupt.html).

**Malformed-event storm:** giới hạn bytes/event, tốc độ ingest và tổng quota forensic journal. Lưu bounded sample đầu tiên theo hash payload + schema/error context; compact bản lặp thành `count, first_seen, last_seen, sample_ids` với counter bền vững, alert rate-limit. Không compact incident hợp lệ hoặc revision khác nhau. Unique malformed storm vẫn có thể đầy quota: reserve metadata/fault capacity, báo `forensic_truncated`/counts khi còn ghi được và degraded qua health channel; không hứa giữ forensic fact nếu thiết bị hết khả năng ghi. Retention forensic phải theo privacy policy.

**Integrity vs authenticity:** checksum chỉ phát hiện corruption. Chống sửa đổi sau khi đến server: server lưu hash + ingestion receipt bất biến (append-only/object lock). Ký manifest bằng device key chỉ chứng minh "device này tạo ra", không chống device đã bị chiếm; bật khi threat model/pháp lý yêu cầu chain-of-custody, khóa trong TPM/secure element nếu phần cứng có.

### 6.18 DeviceHealth & FleetControl

**Nhiệm vụ:** camera liveness, thermal/RAM/disk/runtime health, queue age, uptime/model/config, watchdog, authenticated rollout/rollback và authorized evidence query.  
**Dự kiến:** structured logs, Prometheus-style metrics/OpenTelemetry nếu cần, systemd watchdog, signed manifests.  
**Giao tiếp:** component health→health snapshot/alert; server control→validated command→local use case.  
**Chú ý:** control không phải remote shell tùy ý. Rate limit/replay protection/expiry; rollout per-device/site và canary. Khi update model giữ/cập nhật tracker/event state có policy rõ, không trộn model versions trong event mà không ghi provenance.

### 6.19 Server và Dashboard

| Module | Nhiệm vụ / giao tiếp | Công nghệ dự kiến / chú ý |
|---|---|---|
| Ingestion API | Authenticate device, validate schema/limits, idempotent event revision persist, ACK | FastAPI/Python theo Q14; ACK sau durable commit, không sau chỉ enqueue RAM |
| Evidence service | Authorized upload/download, checksum, object key ownership, manifest states | S3-compatible storage; scoped short-lived upload URL nếu dùng; không cho client tùy ý overwrite key khác |
| Event repository/search | Metadata, filtering time/site/type/review | MongoDB theo Q14; compound indexes theo query thực, unique revision và event lineage/version preserved |
| Alert workflow | Operator assignment, ACK/escalate/resolve, notification retry | DB + worker; cứu hộ theo human review/protocol, không từ một threshold chưa nghiệm thu |
| Retrieval service | Check local/server retention, gửi request edge, phản hồi pending/expired/offline | REST/control transport; không bảo đảm có clip ngoài thời hạn lưu |
| Fleet/config service | Inventory, desired/observed versions, rollout status | Versioned DB/bundle store, RBAC, audit |
| Dev demo / UI bàn giao | Lab list/detail/play/review; UI sản phẩm và annotation/fleet UX do đội giao diện làm sau | Lab HTML/JS gọi API, raw access phân quyền; đội UI nhận OpenAPI/schema/fixtures |

Q19 thay phạm vi UI lab trong bảng trên bằng dev demo list/detail/play/review đơn giản, HTML/JS gọi public API và do FastAPI phục vụ. Annotation/fleet UX và UI production giao đội giao diện riêng qua OpenAPI/fixtures, không bắt buộc framework cho đội đó. Demo không bypass auth/download permissions hoặc ghi thẳng DB. Q18 chốt MongoDB replica set một member cho lab với persistent volume/transaction tests; production HA/restore chốt riêng.

Không coi evidence storage và MongoDB là một transaction: server cần pending/finalize/reconciliation tương tự edge. Enforce unique `(device_id, event_id, revision)` trong scope device đã authenticate/authorize; cùng key khác payload hash là conflict/quarantine, không overwrite im lặng. Giữ revision history; chỉ cập nhật current view bằng revision hợp lệ mới hơn. Persist revision/current projection và server outbox intent trong cùng MongoDB transaction; cần transaction-capable replica set, topology lab chốt riêng. Commit dùng `w: majority, j: true`; timeout/unknown commit reconcile/retry bằng idempotency, không ACK giả. Worker dùng idempotency key cho mỗi side effect; không bảo đảm exactly-once ở downstream/provider thiếu dedup/receipt. Synthetic/replay bị chặn trước notification outbox. Journal/revisions phục vụ audit/recovery cục bộ, không cam kết event sourcing toàn hệ thống. [MongoDB transactions](https://www.mongodb.com/docs/manual/core/transactions-production-consideration/), [write concern](https://www.mongodb.com/docs/manual/reference/write-concern/).

## 7. Pipelines và scheduling

### 7.1 Khởi động

1. Validate config, secrets, artifact hash/license gate, backend capability và disk quota.
2. Reconcile journal/outbox/segments sau crash; đánh dấu events từ boot trước, không phục hồi tracks từ RAM như chưa gián đoạn.
3. Load inference resources và warm-up input hợp lệ; health là starting đến khi nguồn và backend sẵn.
4. Start recorder/source rồi analytics; chỉ có pre-roll đủ sau thời gian buffer, event trước đó phải ghi pre-roll incomplete.
5. Start delivery/health independently; capture session mới và calibration state rõ.

### 7.2 Luồng realtime

```text
Camera stream(s)
  ├── recorder-owned RTSP/demux → ring segments (process riêng)
  └── analytics RTSP session HOẶC local relay subscription (§6.3a)
                            → decoder → bounded frame queue
                                      │
                                quality/sampling
                                      │
                                 object detector
                                      │
                          ordered per-camera tracker
                                      │
                    calibration + motion + pose scheduling
                                      │
                             temporal incident engine
                                      │
                       event journal/outbox + evidence pin
                                      │
                                upload/ACK/review
```

Motion estimator chạy tại nhánh/frame pair cần thiết, không bắt buộc mọi model frame. Inference worker pool shared theo device/model với per-camera fairness; tracker và temporal engine giữ state riêng theo camera. Detection/pose async kết quả phải correlate frameID/session/modelVersion, reject stale hoặc cập nhật history theo policy; không gán pose cũ vào frame hiện tại.

### 7.3 Các lớp tần suất

- Source/recorder giữ FPS gốc nếu khả thi, không phụ thuộc analysis rate.
- Detector sampling theo camera budget; tracker cập nhật theo observations và time-aware aging policy.
- Pose baseline sampling cho slow collapse, tăng tốc candidate; hard limit ROI/concurrency.
- Incident evaluation theo timestamps; không đếm số frame như duration nếu FPS biến động.
- Telemetry/upload có rate riêng, không chặn detector.

### 7.4 Backpressure

| Queue | Policy |
|---|---|
| Frame realtime | Bounded, drop stale/latest-oriented theo config; release buffers và ghi drop/gap |
| Results | Bounded reorder theo camera/session; tracker update ordered |
| Pose requests | Priority + fairness + deadline; expired→skipped/degraded |
| Recorder input | Cố gắng giữ continuity; disk/overflow→explicit evidence gap, không drop im lặng |
| Events/outbox | Durable, quota/priority/retention; không drop giống video frame |
| Upload | Bounded concurrent, metadata ưu tiên trước clip; WAN bandwidth budget |

**Degradation policy:** khi áp lực tăng, drop pose hết deadline/ưu tiên thấp → giảm analysis FPS trong envelope đã nghiệm thu → tắt enhancement/motion compensation tùy chọn. Mỗi bước có metric kích hoạt, hysteresis/cooldown và điều kiện phục hồi ổn định rồi ramp-up; threshold khóa theo benchmark. Nếu tắt capability ảnh hưởng use case thì đánh dấu `degraded/unsupported`, không tiếp tục xuất calibrated motion hoặc âm tính như bình thường. Recorder lỗi: bảo vệ evidence đã pin, phát critical fault và ghi gap. CPU fallback chỉ theo profile đã validate.

MVP có thể serial inference cho đơn giản. Không dùng async/thread pool không giới hạn. Deadline và measured queue age quan trọng hơn throughput đơn lẻ.

### 7.5 Event và evidence lifecycle

Ba state machine trực giao, mỗi cái có revision/audit riêng:

- **AI incident (edge, IncidentEngine):** `normal → candidate → verifying → suspected → closed`; `candidate → expired`, `verifying → rejected`. Severity có thể phát sớm rồi revision.
- **Review (server, Alert workflow):** `unreviewed → confirmed | false_positive`; `confirmed → resolved`. Operator confirmation không làm tăng AI confidence và không phải kết luận y khoa/pháp lý.
- **Evidence/delivery:** như dưới.

AI revision mới không reset review state; review không ghi ngược vào AI FSM. False positive là label phản hồi cho dataset.

Evidence: `buffering → pinned → collecting_postroll → finalized_local → uploading → uploaded`, cùng `partial/failed/expired` states. Delivery state và incident state độc lập. Event update không tạo eventID mới tùy ý; lifecycle có revision và transition audit.

### 7.6 Replay/offline

FileSource dùng PTS để giữ event-time semantics; deterministic clock cho domain tests. Có fast mode (không chờ wall-clock) và real-time mode (thử scheduler/backpressure). Tắt external publisher hoặc dùng local sink. Không gửi incident diễn xuất vào workflow cứu hộ thật.

### 7.7 Shutdown và reconnect

Stop accept new work→cancel/drain bounded tasks→finalize partial evidence→flush transactions→release native buffers/runtime→close sources. Graceful shutdown có timeout; watchdog vẫn có thể kill, nên recovery không phụ thuộc shutdown luôn thành công. Reconnect tạo discontinuity/session policy; không tính velocity qua gaps lớn/ID reset.

## 8. Profile triển khai phần cứng

| Profile | Source/decode | Preprocess/inference | Phần tái sử dụng | Ràng buộc |
|---|---|---|---|---|
| Reference CPU | File/OpenCV hoặc RTSP FFmpeg/GStreamer | OpenCV + ONNX Runtime CPU | Contracts/domain/scheduler/tracker/events/delivery | Đo FPS thật; CPU copies chấp nhận MVP |
| Raspberry Pi 5 | RTSP/USB/CSI adapter phù hợp OS | ONNX Runtime build tương thích; CPU SIMD tùy binary | Như trên | Không cam kết 10–15FPS nếu chưa benchmark. Pi 5 chỉ có hardware decode HEVC, **không có H.264**: stream H.264 decode bằng CPU, ăn vào ngân sách inference |
| Orange Pi 5 RK3588 | RTSP demux + MPP nếu codec/driver phù hợp | RGA + RKNN compatible artifact | Domain và pipeline policies | Toolchain/driver/stride/color/quantization; zero-copy chưa mặc định |
| Jetson | RTSP HW decode/GStreamer/DeepStream adapter | TensorRT + vendor buffers | Domain contracts/state machines | JetPack/SDK matrix; **Orin Nano** không NVENC, raw encode/transcode phải tính CPU; remux encoded input không cần encoder. Không suy từ tên Nano sang mọi Jetson |
| Camera native AI | RTSP evidence + metadata adapter | Native detections/events, optional edge verifier | Event/evidence/server | Capability/firmware/coverage; không chỉ alarm làm detector |

ONNX→RKNN/TRT là build/conversion workflow offline, không convert model trên startup edge. Artifact phải có golden sample validation, quantization representative data và validation report. Backend identity là property triển khai; domain không chứa `if board == ...`.

## 9. Storage, giao tiếp và security

### 9.1 Giao tiếp module nội bộ

Typed calls/iterators hoặc bounded queues; events nội bộ chỉ dùng khi giúp decouple workflow cụ thể. Không cần event bus toàn cục che mọi control flow. Heavy frames truyền references, metadata immutable khi qua worker boundaries. Runtime exceptions chuyển thành typed failure ở adapter boundary, logs có correlation IDs.

Q17: sau startup hợp lệ, pipeline runtime fault phải báo degraded/fault, retry/restart có giới hạn và reset state/session khi mất continuity. Giữ pipeline không phụ thuộc thành phần lỗi và recorder hoạt động; shared native core crash có thể restart toàn analytics, không silent fallback. Q13 config enabled thiếu/sai vẫn fail-fast startup, không chuyển thành runtime degraded để bỏ qua.

### 9.1a Storage classes và resource ownership

| Class | Nội dung | Budget / bảo vệ |
|---|---|---|
| OS/app | Image, binaries, runtime | Read-mostly/recoverable image; update reserve; A/B khi SKU hỗ trợ |
| State | SQLite DB/WAL, config snapshots, outbox, audit | Reserved free bytes, WAL/checkpoint budget, fsync P95/P99; ACK sau commit |
| Evidence | Ring, pinned/final clips, temp/proxy files | Endurance SSD/NVMe theo workload; quota tính cả temp/pins/postroll, retention ưu tiên |
| Telemetry | Logs, metrics spool, dumps, forensic samples | Quota/rotation riêng; không ăn reserve state/evidence; logs không chặn recorder |

Tách directory/partition/quota chỉ hạn chế disk-full, **không loại bỏ SPOF vật lý hoặc I/O contention trên cùng ổ**. Nếu BOM dùng chung media, ghi residual risk mất cả metadata/evidence; nếu tách ổ vẫn có thể chung nguồn/controller/host. Trước procurement khóa mount/filesystem, bytes reserve, sustained write/IOPS, fsync/checkpoint latency, upload-read budget và health (SMART/NVMe nếu có). Disk-full, write error và WAL tăng phải thử cùng recording + inference + upload. Disk-failure RPO cần bản sao ở failure domain khác; UPS và SSD bền hơn không thay backup.

### 9.2 Edge–server

MVP HTTPS: event POST với schema/revision/idempotency, evidence upload riêng, health heartbeat. **Command transport tách khỏi event transport:** edge sau NAT không nhận kết nối vào, nên poll định kỳ làm truy hồi evidence và rollback khẩn cấp trễ bằng một chu kỳ poll. MVP dùng HTTPS long-poll cho kênh lệnh, WebSocket/MQTT khi cần. Event vẫn chỉ có một nguồn sự thật. Có thể thêm MQTT adapter khi cần push/integration; QoS1 vẫn duplicate, retain không dùng tùy tiện cho incident commands. Không chọn đồng thời hai event transports làm hai nguồn sự thật.

Theo Q6/Q10 ngày 2026-10-11, EventPublisher nằm ở server downstream để sau này thêm Kafka, RabbitMQ hoặc WebSocket; chưa triển khai adapters/dependencies. Edge giữ HTTPS; server commit event cùng downstream outbox intent rồi worker publish, không để downstream outage đảo ngược ingestion đã commit. Transport mới giữ identity/revision/idempotency và delivery result; broker ACK/WebSocket send không thay ingestion/evidence receipt hoặc chứng minh consumer đã xử lý. Q7 giữ lab review trên dashboard; placeholder không bật notification ngoài dashboard. Xem [ADR-0002](../adr/0002-server-downstream-event-publishing.md).

### 9.3 An toàn thông tin và dữ liệu

TLS/mTLS, device identity riêng, secret rotation, camera VLAN, local RTSP không port-forward public. Mask credentials trong URI/errors; authorization theo site/camera/evidence. Encryption at rest theo threat model, audit raw access/export, retention per-policy. Quyền dữ liệu/video/model và pháp lý cần duyệt trước production; camera public không tự miễn nghĩa vụ bảo vệ dữ liệu cá nhân.

**Device trust lifecycle:** enroll → provision identity → activate → rotate → quarantine → revoke → decommission; mỗi bước có runbook và audit. Camera VLAN là defense-in-depth, không thay authentication/authorization theo identity. Key protection (TPM/secure element/secure boot) phụ thuộc board — ghi rõ mức đạt được theo hardware profile, không giả định đồng nhất.

**Privacy policy-as-data per site:** `purpose → retention class → access class → export policy → deletion workflow → audit evidence`, cấu hình versioned theo site, không hard-code toàn fleet. Mốc kiểm chứng 2026-10-11: [Luật 91/2025/QH15](https://vanban.chinhphu.vn/?classid=1&docid=214590&pageid=27160&typegroup=) có hiệu lực 01/01/2026; [Nghị định 356/2025/NĐ-CP](https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-356-2025-nd-cp-468371.htm) có hiệu lực 01/01/2026; [Luật An ninh mạng 116/2025/QH15](https://congbao.chinhphu.vn/van-ban/luat-so-116-2025-qh15-468678/61574.htm) có hiệu lực 01/07/2026. [Điều 32 và giải thích của Cổng TTĐT Chính phủ](https://xaydungchinhsach.chinhphu.vn/quy-dinh-bao-ve-du-lieu-ca-nhan-thu-duoc-tu-hoat-dong-ghi-am-ghi-hinh-tai-noi-cong-cong-119250730154729554.htm) cho phép một số trường hợp không cần đồng ý; vẫn có trách nhiệm thông báo (trừ ngoại lệ luật định), xử lý đúng mục đích, giới hạn lưu trữ và bảo vệ dữ liệu. Không suy thành clearance chung cho dự án.

**Legal/privacy production gate:** chủ dự án chỉ định người chịu trách nhiệm pháp chế/privacy; hồ sơ phải có mục đích/căn cứ áp dụng, vai trò xử lý, dữ liệu/luồng chuyển giao, retention/delete, thông báo, quyền truy cập/export và phê duyệt ghi tên/ngày/phạm vi site. Thiếu hồ sơ được duyệt thì chưa đạt gate; owner cụ thể hiện chưa được chỉ định, không coi tài liệu này là ý kiến pháp lý.

**Release provenance:** `source commit → build job → ONNX → target conversion → golden validation → SBOM/provenance → signature → artifact registry → canary → production`. Edge không convert artifact lúc startup. Bundle có version đơn điệu/expiry chống rollback attack.

Semantics tham chiếu [TUF specification](https://theupdateframework.github.io/specification/): target hardware/runtime/schema, artifact hash/length, sequence, issued/expiry, key ID/trusted role và chữ ký trên serialization canonical. Lưu highest accepted sequence bền vững; khóa bootstrap/rotation/revocation ngoài payload không tin cậy. Expiry cần nguồn giờ tin cậy và policy khi clock uncertain/WAN offline: không kích hoạt bundle mới chưa xác minh, tiếp tục last-known-good theo policy đã ký và báo degraded. Rollback vận hành dùng authorization mới có sequence cao hơn trỏ artifact cũ được phép; không hạ high-water mark bằng `rollback_allowed_to`. Manifest tự ký không đồng nghĩa triển khai đầy đủ TUF.

Model manifest ghi riêng code license, exact checkpoint/hash, dataset terms, training/source/converter/runtime versions và clearance record. [MMPose issue #3273](https://github.com/open-mmlab/mmpose/issues/3273) chỉ là câu hỏi license cho hai weights cụ thể, không chứng minh mọi RTMPose weights bị cấm hoặc đã clearance. SBOM/build provenance tham chiếu [SLSA 1.2](https://slsa.dev/spec/v1.2/), không tự nhận compliance khi chưa có bằng chứng.

Service users/ACL phân quyền recorder/app/uploader; edge control outbound-only, không remote shell Internet. systemd hardening phải test device nodes, vendor runtime, shared memory và quyền ghi thực; không áp mù MemoryMax/watchdog. WatchdogSec chỉ hữu ích nếu app phát heartbeat watchdog đúng cách.

Signed config/model bundles, allowlisted factories, hash verification, downgrade/rollback policy, dependency/license manifests. Không dùng pickle hoặc arbitrary executable payload từ server không tin cậy. Live preview không phải đường stream WAN mặc định; on-demand được giới hạn và audit.

## 10. Quan sát, lỗi và phục hồi

- Metrics: sourceFPS/analysisFPS, queue age/drop, inference/P95/P99, pose ROI budget, tracking gaps, frame quality, thermal, CPU/GPU/NPU/RAM, disk bytes/IO, outbox age, delivery latency và evidence completeness.
- Logs: structured với device/camera/session/frame/event/model/config IDs; không log ảnh hoặc credentials mặc định.
- Health: starting/healthy/degraded/unavailable; lý do và observed capability. Có người xem dashboard mới phát hiện camera mất luồng là không đủ: fault alerts riêng.
- Failure matrix: reconnect source; invalidate geometry khi lệch; backend fail→configured explicit fallback/stop analytics; disk full→retention policy/fault; WAN loss→outbox; corrupt artifact→rollback; crash→reconcile. Không nhầm silence với negative event.
- Domain event và operational fault là hai loại riêng, severity routing khác.
- **Synthetic health probe:** định kỳ đi qua source→decode→inference→journal→server; taxonomy `synthetic` giữ qua mọi revision, server guard chặn notification/rescue outbox kể cả retry/replay. Probe failure báo fault riêng. Process "running" nhưng loop deadlock không phải healthy.
- **Clock:** NTP + metric clock offset/uncertainty mặc định; PTP chỉ khi use case (cross-camera fusion, đo tốc độ nghiêm ngặt) chứng minh cần.
- **Telemetry → SLI → alert:** page khi cần người xử lý ngay (mất capability, disk sắp đầy, evidence missing), ticket khi xử lý sau, còn lại chỉ log. Correlation context xuyên camera/session/frame/event/upload (OpenTelemetry nếu dùng). Label metric theo allowlist có cardinality budget (device/camera khi fleet hữu hạn; model lineage/version chỉ khi bounded) — không dùng event/frame ID làm label.

### 10.1 SLI và NFR

Định nghĩa đo lường cố định ngay. **Preliminary targets** do owner sản phẩm/vận hành duyệt trước chọn hardware/PoC: latency, quality, evidence, offline autonomy, recovery và review load; đó là yêu cầu để thử, không phải kết quả đã đạt. Sau benchmark/lab soak khóa capacity envelope và acceptance cho field pilot; sau field pilot ký final targets trước procurement fleet. Không lấy con số nghiên cứu hoặc TBD làm bằng chứng đạt gate. Hồ sơ đầu vào/owner xem [deployment readiness](deployment-readiness.md).

| SLI | Định nghĩa |
|---|---|
| Detection availability | % thời gian camera trong ODD mà analytics thực sự capable (không failed/overloaded/stale). Luôn báo cáo cùng SLI dưới, vì đánh dấu out-of-ODD nhiều sẽ làm chỉ số này đẹp giả |
| Out-of-ODD time | % thời gian out-of-ODD theo camera, kèm phân loại lý do (đêm, mưa, che khuất, lệch camera...) |
| Local event latency | `event_persisted_at − onset_estimate`, P95/P99 |
| Event delivery latency | `server_ack_at − event_persisted_at` (tách lỗi AI khỏi WAN/server) |
| Frame freshness | P95/P99 frame age tại nhận kết quả; map capture/PTS sang clock đo cùng domain và ghi uncertainty. Nếu thiếu mapping đáng tin, báo receive-to-result age riêng, không gọi là capture age |
| Evidence completeness | % incident yêu cầu evidence có đủ pre/post interval, không có gap ngoài tolerance; `partial` có lý do báo riêng, không tính là complete |
| Delivery completeness | % event revisions có ACK durable từ server |
| Degraded visibility | % thời gian degraded/unavailable đã báo lên monitoring |
| Disk autonomy | `disk_time_to_full_estimate`; số giờ chịu WAN loss mà không mất evidence ưu tiên |
| Inference failure ratio | Báo riêng `failed/overloaded/stale/skipped` trên attempted/scheduled work phù hợp; không gộp với `ok_empty` |
| Recovery | RTO sau reboot/camera reconnect/backend crash; RPO metadata (mục tiêu 0 event đã persist) và evidence |
| Capacity/thermal | camera × resolution × FPS ổn định sau soak test, gồm recording/upload, không phải 2 phút đầu |
| AI quality | recall/precision/false alerts per camera-day theo site/ODD; false alert là chi phí review trực tiếp. Recall ngoài đời đo bằng **negative audit**: định kỳ lấy mẫu clip *không có event* (phân tầng theo site/ca đêm/mưa) cho người review, vì hệ thống chỉ sinh event khi đã phát hiện |

### 10.2 Alert contracts

Recorder segment gap/pin failure, source mất tiến triển, outbox age/bytes vượt autonomy, time-to-full, write/fsync errors, frame age, clock uncertainty và native restart/crash loop là tín hiệu P0 trước pilot. Thermal, track fragmentation, evidence completeness và desired/observed version drift bổ sung P1. Mỗi alert ghi metric/window/threshold theo site profile, severity, owner nhận, runbook và recovery condition; `>0` dùng cho lỗi như pin failure, không áp chung mọi metric. Freeze detector phải phân biệt cảnh đứng yên với luồng treo.

## 11. Kiến trúc source code dự kiến

**Đây là cây đề xuất cho implementation tương lai, không mô tả code đã tồn tại.** Chọn monorepo gọn, không tạo tất cả folder rỗng ngay. Python là baseline dự kiến; tree giữ semantic boundaries để đổi ngôn ngữ khi có lý do.

```text
AI-Camera-OC/
├── pyproject.toml                  # deps core/server, optional extras theo backend
├── src/traffic_camera/
│   ├── domain/
│   │   ├── contracts/              # frame metadata, detection, pose, track, event
│   │   ├── incidents/              # FSM, temporal rules, taxonomy
│   │   ├── motion/                 # feature logic, uncertainty, pure geometry
│   │   └── policies/               # event quality/severity/ODD policies
│   ├── ports/
│   │   ├── video.py
│   │   ├── perception.py           # detector/pose; inference internal port đặt ở adapters/ai nếu phù hợp
│   │   ├── tracking.py
│   │   ├── geometry.py
│   │   ├── evidence.py
│   │   ├── delivery.py
│   │   └── control.py
│   ├── application/
│   │   ├── pipeline/               # orchestrator, camera sessions, routing
│   │   ├── scheduling/             # budgets, deadlines, fairness, result ordering
│   │   ├── evidence/               # pin/finalize/retrieve use cases
│   │   ├── delivery/               # journal/outbox/upload coordination
│   │   └── fleet/                  # rollout/config activation use cases
│   ├── adapters/
│   │   ├── video/                  # file, RTSP, USB/CSI; demux/decode implementations
│   │   ├── buffers/                # CPU and optional native buffer ownership
│   │   ├── ai/
│   │   │   ├── models/             # YOLOX/RTMPose preprocessing+decode+model specs
│   │   │   ├── engines/            # ONNX; optional RKNN/TRT/OpenVINO
│   │   │   └── preprocessing/      # CPU; optional RGA/CUDA
│   │   ├── camera_analytics/       # optional ISAPI/ONVIF integrations
│   │   ├── tracking/              # ByteTrack adapter
│   │   ├── geometry/              # calibration repository + LK estimator
│   │   ├── evidence/              # segmenter/remux/filesystem
│   │   ├── persistence/           # SQLite implementations/migrations
│   │   ├── transport/             # HTTPS; optional MQTT
│   │   └── platform/              # OS health/watchdog/device capabilities
│   ├── bootstrap/                 # config, factories, capability validation, wiring
│   └── utilities/                 # small clock/IDs/errors only; no catch-all business logic
├── apps/
│   ├── edge/                      # entrypoint/CLI; thin composition root
│   ├── server/                    # API, use cases, repositories, workers, migrations
│   └── dashboard/                 # UI sản phẩm tương lai do đội giao diện sở hữu; lab demo nằm trong server
├── schemas/                       # network JSON schemas/OpenAPI, canonical versions
├── configs/
│   ├── examples/                  # no credentials; minimal reference config
│   ├── profiles/                  # CPU/RPi/RK3588/Jetson capability defaults
│   └── sites/                     # templates; deployed secrets/site data not committed
├── model_manifests/               # artifacts references/hashes/licenses; not huge weights
├── tools/
│   ├── calibration/
│   ├── model_conversion/
│   ├── benchmark/
│   ├── replay/
│   └── diagnostics/               # RTSP probe, doctor, evidence export checks
├── native/                        # C++ perception core (§6.7a), CMake
│   ├── include/traffic_camera/    # public C++ API + generated observation structs
│   ├── src/
│   │   ├── decode/                # libav, MPP, NVDEC backends
│   │   ├── preprocess/            # RGA, CUDA/NPP, OpenCV/NEON
│   │   ├── engines/               # ORT C++, RKNN C API, TensorRT
│   │   ├── models/                # YOLOX/RTMPose postprocess, NMS, SimCC
│   │   ├── tracking/              # ByteTrack C++
│   │   └── core/                  # per-camera pipeline, queues, scheduling, timing
│   ├── bindings/python/           # pybind11/nanobind, GIL release, typed errors
│   ├── tests/                     # GoogleTest/Catch2, sanitizers, fuzz
│   └── toolchains/                # aarch64 cross-compile per board
├── tests/
│   ├── unit/                      # pure domain and application tests with fakes
│   ├── contract/                  # each adapter obeys semantic ports
│   ├── integration/               # RTSP/DB/recorder/server boundaries
│   ├── regression/                # golden clips/model/event metrics
│   ├── hardware/                  # explicit device markers, no default hardware dependency
│   └── fixtures/                  # synthetic/small cleared data + external dataset refs
├── deploy/                        # systemd, optional containers, server deployment
├── docs/
│   ├── architecture/system-architecture.md
│   ├── adr/                       # decisions split into ADRs when implemented
│   ├── runbooks/                  # provisioning/fault/recovery/privacy/upgrade
│   └── logs/                      # action/decision tracking
└── traffic-ai-camera-research/     # research evidence and sources
```

### 11.1 Quy tắc quản lý module

- Vendor imports confined adapters; domain tests chạy không cần board/NPU/network.
- Optional extras và lazy imports cho RKNN/TRT/OpenVINO để reference machine không cần mọi SDK.
- Không để `utilities/` thành nơi chứa inference/event logic hoặc service locator.
- Không tạo port mới nếu không có lý do cụ thể về substitution, test isolation hoặc lifecycle; `ImagePreprocessor`/`InferenceEngine`/`Decoder` giữ là boundary nội bộ adapter đến khi có implementation thứ hai thật.
- Config schema có owner; labels/keypoints/network contracts versioned, tránh sao chép mỗi adapter một định nghĩa.
- Python adapter `adapters/ai/native_core` là implementation của `ObjectDetector`/`Tracker`/`PoseEstimator` ports bọc perception core; application không biết đường nào là Python hay C++. Contract tests chạy chung cho hai implementation.
- C++ bindings expose hẹp; không duplicate IncidentEngine Python/C++ trước có nhu cầu và test parity.
- Models/artifacts/video thật lưu ngoài Git hoặc artifact storage; repo chỉ manifest, hash, quyền và tiny fixtures đủ kiểm thử.
- Pin dependency/backend versions theo deployment profile; lockfiles/build metadata và third-party notices.
- Schema sharing với dashboard dùng generated types nếu cần; không share Python DB entity trực tiếp như wire contract.

### 11.2 Cấu hình minh họa

```yaml
schema_version: 1
profile: reference_cpu
cameras:
  - id: test-01
    source:
      type: rtsp
      uri_secret: CAMERA_TEST_RTSP_URI
    analysis:
      target_fps: 10
      max_frame_age_ms: 500
    calibration_ref: calibrations/test-01/v1
perception:
  detector:
    adapter: yolox_onnx
    model_manifest: model_manifests/yolox-small-onnx.yaml
  pose:
    adapter: rtmpose_onnx
    model_manifest: model_manifests/rtmpose-onnx.yaml
motion_estimation:
  adapter: identity
tracking:
  adapter: bytetrack
evidence:
  mode: encoded_segments
  pre_roll_seconds: 10
  post_roll_seconds: 20
delivery:
  adapter: https
  endpoint: https://example.invalid/api
  credential_secret: EDGE_SERVER_CREDENTIAL
```

Số FPS/age/pre/post ở đây là giá trị minh họa để test, không default production đã nghiệm thu. Orange Pi đổi profile/adapters/manifests sau compatibility validation, không chỉ đổi extension `.onnx` thành `.rknn`. Secret reference không được tự resolve thành plaintext trong logs/config export.

## 12. Utilities và công cụ phụ trợ

| Công cụ | Mục đích |
|---|---|
| `camera-probe` | Kiểm tra RTSP local, codec/FPS/PTS/reconnect; redact credentials |
| `device-doctor` | Versions/driver/runtime, khả năng decode/inference, RAM/disk/thermal, artifacts |
| Calibration tool | Mốc ảnh/mét, distortion, ROI/vạch/hướng, sai số và version |
| Replay runner | Reproduce event-time, fast/realtime, export metrics không phát cảnh báo thật |
| Model conversion pipeline | ONNX export→RKNN/TRT build, representative INT8 data, golden comparisons |
| Benchmark runner | detector-only + E2E, burst/thermal/queue/drops, manifest hardware/software |
| Evidence verifier | Check manifest/hash/gaps/retention/export provenance |
| Dataset/annotation utilities (data engine) | License provenance, split site/time/person; hard-negative mining từ false positive đã review và negative audit; dataset versioning gắn với model artifact; vòng fine-tune cho điều kiện VN. Model pretrained trên COCO nhiều khả năng là điểm nghẽn chất lượng trước phần cứng |
| Config validator | Dry-run dependency/capability/secret validation trước activation |
| Privacy utilities | Redact credentials/logs và derived evidence theo policy |

Clock abstraction cho domain tests, ID generator, typed errors và bounded queue helpers đủ nhỏ có thể đặt utilities. Các helpers có platform dependencies đặt adapter tương ứng.

## 13. Kiểm thử và acceptance

### 13.1 Layers

1. Unit domain: FSM, durations, unknown observations, cooldown/dedup, velocity outliers và gaps bằng fake clock.
2. Contract adapters: tọa độ gốc, colors/layout, label/keypoint schema, empty vs fail, buffer lifetime/release, backend capability errors.
3. Golden perception: cùng frames trên ONNX/RKNN/TRT; IoU/class/pose tolerance và event regression, không yêu cầu tensors giống tuyệt đối.
4. Integration: RTSP disconnect, codec switch, SQLite outbox, segment pin/cleanup race, server duplicates/reordered revisions và upload retry.
5. Hardware/performance: 1/2/4 streams, person/pose bursts, wall-power/thermal, queue age/P95/P99, 72h soak theo workload.
6. Field pilot: ngày/đêm/mưa, xe máy đông, người xa/che khuất, operator feedback, nhiều camera-ngày và sufficient events.

### 13.2 Mỗi báo cáo benchmark phải ghi

Hardware/OS/drivers/SDK; model/artifact hash; input/precision/batch; source codec/resolution/FPS/bitrate; sampling/crops/pose concurrency; recorder/render/upload settings; nhiệt môi trường; event metrics, latency/drop/quality và provenance dataset. TOPS hay FPS model đơn lẻ không thành camera capacity. Xuất machine-readable manifest với duration/workload, frame age/event latency P95/P99, recorder gaps, fsync/WAL, CPU/RAM/accelerator/thermal/power, outbox bytes/age và pose burst. Đo từng bottleneck decode/preprocess/inference/memory/disk/uplink rồi khóa số camera ở workload bền vững; thiếu kết quả dùng `null` + lý do, không dùng `0` giả số đo. Mẫu trong [deployment readiness](deployment-readiness.md).

### 13.3 Gates

- Đổi backend: contract tests + golden event quality + E2E performance đạt tiêu chí thống nhất.
- Đổi camera: stream test, lens/ROI/geometry calibration lại, field regression và quality/ODD update.
- Production: commercial license clearance, security/retention review, sustained thermal/disk/network recovery, operator workflow, evidence integrity và rollback.
- Mục tiêu recall/báo giả/latency chọn theo pilot và nhân lực; không lấy con số nghiên cứu làm cam kết tự động.
- Trước field pilot: preliminary targets + lab capacity envelope (10.1) đã ký; fault-injection drills đạt — camera freeze/reconnect/codec change, analytics kill/hang/native crash, recorder kill, WAN outage nhiều giờ, disk 95%/100%/write errors/WAL growth, power cut lúc commit và rename, clock jump, model load/config activation failure, duplicate/reordered/conflicting revisions; 24–72h soak recording + analytics + upload. Signed rollout test chặn bad hash/signature, expired/old sequence, wrong target và clock uncertain; synthetic không tạo notification. Final field quality/SLO ký sau pilot trước fleet; central backup/restore drill theo SLA.

## 14. Kế hoạch triển khai theo vertical slices

**Use case làm trước đã xác nhận ở Q11: person-down**, một camera cố định/ROI lòng đường (ngã/người nằm: pose, persistence, hard negatives, ít cần calibration). Theo Q5/Q9, mỗi tính năng cảnh báo là pipeline register riêng với lifecycle/config/state độc lập theo camera/session và event contract chung có pipeline provenance. Registry dùng allowlisted factories, chia sẻ perception khi tương thích; chỉ tách process khi cần fault/resource isolation. Nhánh tai nạn xe (calibration, ground projection, TTC, motion compensation) triển khai sau gate person-down, không triển khai đồng thời chỉ vì có registry.

**Module theo slice** (module không có trong slice hiện tại thì không tạo code/port, kể cả file rỗng):

| Slice | Module/yêu cầu |
|---|---|
| 1 (MVP) | Config/composition root, VideoSource (file+RTSP), Python reference pipeline (oracle), native core: software decode + ORT C++ detector + NMS + ByteTrack C++ + binding, IncidentEngine tối thiểu, recorder process riêng, EventJournal/Outbox/Uploader, Ingestion API + review tối thiểu |
| 2 | Quality & ODD Monitor, PoseScheduler/Estimator với pose native ONNX, negative audit + data engine tối thiểu |
| 3 | RKNN/RGA backends trong native core khi chọn target, hardware buffer verification, Model Registry, model conversion pipeline |
| 4 (Pilot prep) | Retention đầy đủ, DeviceHealth/FleetControl, device trust lifecycle, SBOM/release provenance, RBAC/audit, signed rollout, retrieval, GroundProjector/Calibration + MotionAnalyzer cho use case tai nạn xe |
| 5 (Target) | TPM/secure element theo SKU, MotionCompensator, CameraNativeAnalytics, PTP nếu chứng minh cần |

### Slice 1 — Một camera đến một sự kiện có clip

File + RTSP source, CPU/ONNX detector, ByteTrack C++ trong native core (Python làm oracle), một FSM cơ bản, compressed recorder (process riêng), local journal/outbox, HTTP ingress server, event review tối thiểu. Khi chưa chọn board, chạy software decode + ONNX trên nền tảng lab có runtime hỗ trợ; x86/Raspberry Pi/board khác cần build và E2E test riêng để xác nhận hỗ trợ. Gate Slice 1 không bắt buộc board đích hoặc hardware decode. Khi chọn target phải đo nhiệt/decode/I/O và kiểm `FrameBuffer` trên hardware thật trước nghiệm thu capacity/pilot. Kèm các quyết định/spike trước nghiệm thu:

- **Facts sheet + preliminary SLO:** hardware/camera/storage/network/power inventory và workload/retention trước BOM; storage reserve/quota tối thiểu và disk-full fault từ Slice 1, không đợi Slice 4.
- **ADR stream ownership:** chọn dual sessions hoặc upstream + relay theo §6.3a; chưa tạo ADR accepted khi camera benchmark chưa có.

- **ADR main/sub stream:** record main stream + phân tích sub stream (rẻ, nhưng người ở xa và pose mất chất lượng) hay decode main stream rồi crop/tile (tốn compute). Kiểm tra giới hạn số RTSP session đồng thời của camera. Ảnh hưởng trực tiếp độ chính xác pose và capacity.
- **Spike pháp lý và license:** license checkpoint YOLOX/RTMPose và dữ liệu huấn luyện, quy định dữ liệu cá nhân. Làm ngay vì có thể buộc đổi model; Slice 5 chỉ là clearance cuối.

Gate: replay và live tạo event/clip đúng timestamps, retry idempotent; kill analytics process không làm mất segment.

### Slice 2 — Temporal quality và pose

Quality flags, fast/slow/persistent-fall coverage (gồm `person_lying_persistent` khi không thấy onset), RTMPose scheduler, hard negatives (bắt buộc gồm người ngủ trên yên xe đỗ ngày/đêm/nhiều góc, cùng ca đối chứng tai nạn có người nằm vắt trên xe đổ và người ngã cạnh xe đỗ; đo cả false alert/camera-day lẫn recall tai nạn thật) và event regression. **Đo sớm tỉ lệ track bị đứt/ID switch trên dữ liệu thật**, vì đây là giả định nền của IncidentEngine. Negative audit chạy từ slice này. Gate: không chỉ bbox demo; missing observations/ID switches được xử lý.

### Slice 3 — RK3588 portability

Compatible RKNN artifacts, conversion/golden tests, MPP/RGA adapters nếu cần. Đầu tiên đúng semantic output, sau tối ưu native buffer copies. Gate: cùng IncidentEngine và application contracts, capability/fallback rõ.

### Slice 4 — Reliability và server workflow

Crash recovery, disk quotas/retention, evidence retrieval, health/faults, RBAC/audit, signed config/model rollout. Multi-camera scheduling/fairness có benchmark. Device identity/provision/rotate/revoke và SBOM/build provenance cơ bản hoàn tất trước field pilot; TPM/secure element theo SKU. Nếu native crash/RTO không đạt, thử process isolation và rerun contract/recovery trước pilot.

### Slice 5 — Production pilot

Camera production/compute đã đo, calibration/site ODD, thermal/PoE/UPS/tủ, legal/license clearance cuối (spike đã làm ở Slice 1), operator SLA và field tests. Jetson/OpenVINO/native analytics adapters chỉ thêm khi mục tiêu triển khai yêu cầu.

## 15. Các câu hỏi còn mở khi implement

- Ranh giới C++/Python đã chốt ở §6.7a; còn mở: core in-process hay process riêng (quyết định sau soak test), và định dạng struct chung (generated dataclass hay FlatBuffers).
- Camera/SKU/firmware, FPS/codec và capture timestamp quality thực tế.
- Artifact YOLOX/RTMPose thương mại nào được clearance; khả năng export RKNN từng checkpoint.
- Native buffer import/concurrency trên board/OS/SDK được chọn; zero-copy phải đo.
- ROI/ODD/retention, số camera/site, pose budget, alert SLA và final acceptance thresholds.
- Kênh lệnh: HTTPS long-poll (MVP) hay WebSocket/MQTT, tùy infrastructure; event transport vẫn một nguồn sự thật (9.2).
- Main/sub stream và phạm vi lưu liên tục vs ring buffer: chốt ở Slice 1, trước khi chọn SKU (6.16, 14).
- Cloud/on-prem, object store license và yêu cầu pháp lý cụ thể của đơn vị triển khai. **Phải thành ADR trước pilot** vì quyết định HA/DR server, PKI, data residency, backup và chi phí.
- Cost model `TCO/camera/tháng = edge HW khấu hao + storage wear + điện + mạng + server storage/compute + observability + support + human review`; cần số event/ngày và false alert rate từ pilot. `ReviewHours/month = Cameras × AlertsRequiringReview/camera-day × MeanReviewMinutes × 30 / 60`; false alerts chỉ tính phần chi phí false-positive, tổng review gồm cả true/uncertain/escalation. Không gán effort/person-week hoặc tiền tuyệt đối khi chưa có inventory/workload/team data.
- Provisioning reproducible (image build + provisioning as code + site desired state versioned) — làm ở Slice 4, khi có thiết bị thật.

**Kết luận:** kiến trúc ổn định ở semantic contracts và domain logic, không ở vendor tensor format. Thay phần cứng là thay adapter + artifact + config + kiểm chứng; không viết lại toàn bộ nghiệp vụ, nhưng cũng không bỏ qua hiệu chuẩn, quantization, memory path và chất lượng hiện trường.
