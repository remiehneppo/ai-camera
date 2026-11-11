# Ứng viên công nghệ và điều kiện đánh giá

**Cập nhật:** 2026-11-11 (đồng bộ trạng thái thực tế sau [báo cáo khắc phục](../logs/2026-11-11-review-remediation.md); xem [trạng thái hiện hành](../README.md)). **Trạng thái:** ghi nhận ứng viên theo Q35; chưa lựa chọn engine sản xuất hay nghiệm thu board/SKU deployment.

Nguồn quyết định: [nhật ký requirement Q1–Q35](../logs/2026-10-20-requirements-expansion.md). Phạm vi nghiệp vụ và nhãn nằm trong [danh mục tình huống an toàn đô thị](urban-safety-scenarios.md); tài liệu này không xác nhận khả năng đã hỗ trợ. Thứ tự [ADR-0001](../adr/0001-feature-pipeline-boundaries.md) giữ nguyên: person-down một camera cố định/ROI lòng đường đạt gate trước, tai nạn xe sau, các nhóm khác mở theo giai đoạn.

## Baseline và trạng thái ứng viên

| Thành phần | Trạng thái quyết định | Chưa được suy ra |
|---|---|---|
| YOLOX-Tiny / RTMPose-Tiny, ByteTrack, Ground-Plane Homography, ONNX Runtime | **Baseline software lab hiện hành**: Triển khai trong lab phục vụ các kịch bản qua 5 engine chuyên biệt + `UrbanSafetyScenarioEngine`. Sổ đăng ký phần mềm định nghĩa đủ 14 nhóm (`US01`–`US14`), nhưng công cụ đánh giá (`tools/eval_all_scenarios.py`) chỉ bao phủ 4 nhóm baseline hoặc 11 nhóm mở rộng (`US04`, `US10`, `US14` giữ trạng thái `unconfigured` theo cấu trúc công cụ do chưa gắn ROI/cấu hình chuyên biệt). Batching RTMPose (`estimate_batch`) phụ thuộc hỗ trợ dynamic batch của đồ thị ONNX (yêu cầu tức thời qua `request_pose` chạy tuần tự). Homography (`default_urban_cctv`) là template chuẩn hóa phối cảnh mặt đường (`calibration_version="uncalibrated"`). Ghi nhận 979 tests (207 subtests) và 83 source files `mypy` sạch tại [nhật ký 2026-11-11](../logs/2026-11-11-review-remediation.md). | Không tự suy là baseline sản xuất đã nghiệm thu; không lấy benchmark CPU 28–45 FPS trong các báo cáo lab lịch sử ([2026-10-21](../reports/2026-10-21-pipeline-benchmark-report.md), [2026-10-27](../architecture/deployment-readiness.md), [2026-11-10](../reports/2026-11-10-civiwatch-benchmark-report.md)) làm cam kết thời gian thực hay năng lực hiện tại; không suy template homography thành calibration đo đạc thực địa; không suy giải quyết được ngoài ODD camera cố định |
| Tier-2 Hybrid VLM Storyboard Verifier (`LocalVisualVerifier` / tùy chọn remote `Qwen2.5-VL-3B-Instruct` / `InternVL3`) | **Đã tích hợp trên seam `PerceptionPipeline` ([ADR-0008](../adr/0008-civiwatch-v2-hybrid-vlm-architecture.md))**: Mặc định khởi tạo `endpoint_url=""`, chạy heuristic phân tích thị giác cục bộ (`_verify_local`) offline, không phải mô hình neural VLM nhúng trong tiến trình. Endpoint VLM từ xa không tự bật qua biến môi trường mà cần truyền tường minh `VLMVerifier`, và chạy HTTP POST đồng bộ dưới lock xử lý pipeline. `StoryboardBuilder.build_grid` thiết kế các mốc `[-5s, -2s, 0s, +1s, +2s, +3s]`, nhưng khi chạy trực tuyến tại $t_0$ chưa có frame tương lai nên lấy mẫu lại (resample, có thể lặp frame) từ đệm quá khứ `[min_ts .. max_ts]`; trong replay, frame sau anchor chỉ có nếu đã được đệm trước đó. | VLM đóng vai trò Tier-2 triage/lọc báo giả (hard negatives), không thay thế quyết định review của con người; không suy heuristic cục bộ là neural VLM; không suy lưới online luôn đủ 6 quan sát độc lập hoặc có sẵn frame tương lai |
| Go2RTC Media Engine Helper (`infra/go2rtc.yaml`, `apps/edge/media_engine.py`) | **Helper streaming bổ trợ cho dashboard**: Hỗ trợ chuyển tiếp WebRTC/MSE/MP4 stream-copy và snapshot JPEG qua `go2rtc` kèm fallback `FileRecorder`. Ở runtime hiện tại, `LivePerceptionRunner` và `RtspRingRecorder` vẫn mở luồng RTSP trực tiếp độc lập (mô hình 2 phiên upstream theo [ADR-0007](../adr/0007-rtsp-stream-ownership.md) proposed); dashboard duy trì đường dẫn MJPEG/HTTP hiện hữu. | Helper này không chứng minh việc cắt chuyển sang kéo RTSP một phiên (single-session fanout), không chứng minh độ trễ WebRTC hay năng lực lưu giữ evidence |
| RF-DETR + ViTPose | Ứng viên detector + pose bổ sung để đánh giá nâng cao cho cảnh đêm/thời tiết xấu; **không chặn triển khai baseline hiện hành** | Không mặc nhiên tương thích adapter, export/runtime, schema keypoints, tốc độ, bộ nhớ hoặc license |
| NVIDIA Jetson Orin NX | Dòng hardware ứng viên đã chọn để đánh giá mở rộng, không phải Xavier NX | Board deployment chưa chọn; chưa có accepted SKU/RAM, SDK, capacity hoặc thermal envelope |

Exact RF-DETR/ViTPose variants, checkpoints/weights/hash, code/runtime/pre-postprocess/export versions, keypoint mapping và SDK đều `pending`. RAM/SKU/module/carrier, storage, OS/JetPack/SDK/runtime stack của Orin NX cũng `pending`; không tự chọn cấu hình mặc định. Camera SKU/firmware/profile, số camera, analysis FPS và tải đồng thời cần chốt và đo, không suy từ tên dòng chip hay inference FPS công bố. Trường `production_use_approved` trong các manifest detector (`yolox-tiny`, `yolox-tiny-hcmc`, `yolox-s-hcmc`, `civiwatch-640`) chỉ là metadata ghi nhận nội bộ trong manifest, KHÔNG phải giấy phép pháp lý (legal clearance) hay bằng chứng nghiệm thu phát hành sản xuất (release evidence).

## Giới hạn capability và kiểm chứng riêng

Detector cung cấp quan sát đối tượng và pose cung cấp keypoints trong điều kiện được kiểm thử; ghép hai model không tự tạo bằng chứng về diễn biến, quan hệ tương tác hoặc quy định site. RF-DETR + ViTPose không được coi là tự đáp ứng toàn bộ 13 nhóm và nhánh phá hoại tài sản.

- Person-down cần tracking/temporal verification và phân biệt fall có onset, persistent lying thiếu onset, person on stationary vehicle; không tự suppress nhánh cuối hay suy chẩn đoán y tế.
- Tai nạn, ẩu đả, gây rối, phá hoại và bỏ/đổ rác có diễn biến cần quan sát chuỗi thời gian/quan hệ tương ứng; tư thế hoặc trạng thái tĩnh riêng lẻ không chứng minh hành vi hay nguyên nhân.
- Lửa/khói, nước ngập, rác/vật tồn lưu, cây/cành lớn đã đổ và đèn không sáng cần dữ liệu, nhãn và khả năng quan sát domain riêng; detector/pose người không phải bằng chứng đã đáp ứng.
- Chiếm dụng, đỗ sai, tụ tập, vùng nguy hiểm và vật bỏ quên cần logic vùng/lịch, thời gian duy trì, ngoại lệ và trạng thái unknown phù hợp từng module × camera. Không thêm nhận diện danh tính, ANPR hoặc kết luận ý định/quyền sở hữu.

Mỗi capability được đề xuất phải có ma trận requirement → quan sát/model bổ sung nếu cần → state/rule/config → bộ positives/hard negatives → kết quả nghiệm thu. Module register độc lập có thể chia sẻ perception tương thích theo ADR-0001; không mặc định process riêng, inference trùng hoặc đủ tài nguyên để bật mọi module đồng thời. Module bật nhưng thiếu/sai cấu hình bắt buộc phải báo lỗi rõ theo fail-fast baseline, không silent skip. Lưu ý: Sổ đăng ký định nghĩa 14 nhóm tình huống, nhưng công cụ đánh giá `eval_all_scenarios.py` hiện tại phân tách 4 kịch bản baseline và 11 kịch bản mở rộng; các nhóm US04, US10, US14 được loại trừ theo thiết kế công cụ (`unconfigured`) do thiếu cơ chế nạp ROI và cấu hình chuyên biệt, không thể tự động kích hoạt chỉ qua tham số dòng lệnh.

## Gate trước khi chấp nhận ứng viên

| Gate | Bằng chứng phải có | Trạng thái |
|---|---|---|
| Artifact và quyền sử dụng | Exact code/checkpoint/weights/hash, license từng artifact, điều khoản dataset/training data, source lineage, conversion/runtime/pre-post versions và người clearance | `pending`; license repository không tự cấp quyền weights/data; metadata `production_use_approved` trong manifest không thay thế legal clearance |
| Privacy và provenance | Căn cứ xử lý/site approval, quyền dùng fixture/field data, retention/access/transfer; source/time/config/model/calibration lineage | `pending`; không dùng dữ liệu thật ngoài phạm vi được duyệt |
| Adapter/conformance | Tensor/pre-post và keypoint semantics; golden/native-oracle conformance, tolerance có duyệt; kết quả event regression khi thay engine | `pending`; inference chạy được không đủ chấp nhận thay engine |
| Quality từng capability | Held-out positives/hard negatives, bỏ sót, báo nhầm theo camera/giờ, latency từ diễn biến đủ điều kiện đến cảnh báo, tải review; ngưỡng/sufficiency theo site và workload | `pending`; không dùng điểm benchmark model tổng quát hay số đo CPU 28–45 FPS trong lab thay nghiệm thu nghiệp vụ |
| ODD từng capability | Ngày/đêm/mưa, occlusion, camera/ROI và giới hạn quan sát được kiểm thử; unsupported/thiếu hình ảnh thành unknown/degraded, không thành negative | `pending`; chưa kiểm thử không có nghĩa đã hỗ trợ |
| Actual target full-system capacity | Actual SKU/RAM/SDK và camera profiles đã khóa; decode + perception + tracking + các module bật + temporal state + ghi ring/clip + upload đồng thời; P95/P99, queue/drop/gap, memory/I/O/storage/power, headroom và soak thermal 24–72h | `pending`; không ký capacity từ x86, inference-only, TOPS hay FPS quảng cáo |
| Vận hành và evidence | Fault/recovery, protected pin/unACK, offline/restore, dashboard/review và evidence completeness theo hợp đồng hiện hành | `pending`; áp dụng [readiness](../architecture/deployment-readiness.md) và [protocol lab](../architecture/lab-profile.md) |

Không có số đo/chỉ tiêu quality, RAM, SDK, checkpoint, license/data clearance hoặc camera/FPS/capacity nào được tự điền bằng ước lượng. Owner phải khóa đầu vào và ngưỡng trước run/sign-off; ghi `blocked/not-run` thay vì pass khi thiếu evidence. Chỉ chấp nhận ứng viên cho capability, cấu hình và ODD thực sự vượt gate; không nâng thành hỗ trợ toàn danh mục.

## Quy chuẩn ODD Phần cứng và Dữ liệu Kiểm định (Cập nhật 2026-10-27)

Nhằm đảm bảo tính chính xác và loại bỏ các nguồn báo động giả do chuyển động camera và chất lượng hình ảnh kém, hệ thống áp dụng tiêu chuẩn ODD nghiêm ngặt:
- **Tuyệt đối loại bỏ**:
  1. *Camera hành trình (dashcam)*: Do chuyển động của xe tạo ra luồng quang học biểu kiến (ego-motion) làm sai lệch vector vận tốc/gia tốc tương đối của các đối tượng ven đường.
  2. *Camera độ nét thấp (< 720p)*: Làm vỡ nét đối tượng, detector YOLOX bỏ lọt hoặc nhảy giật kích thước hộp bounding box sinh gai gia tốc ảo.
- **Tiêu chuẩn bắt buộc**: Camera giám sát giao thông **CỐ ĐỊNH (Fixed CCTV)**, độ phân giải từ **HD (720p / 1280×720)** đến **2MP (Full HD 1080p / 1920×1080)**.
- **Các bộ dữ liệu đạt chuẩn ODD được phê duyệt**:
  - `UniDataPro Fall Detection` (1080p Fixed Camera): Kiểm định người ngã và nằm đường (US09).
  - `AccidentBench Fixed CCTV` (1280×720 @ 10fps): Kiểm định tai nạn phương tiện (US08).
  - `Shibuya & Pie-IX 1080p CCTV`: Kiểm định giao thông ngã tư bình thường, đỗ xe sai vùng (US05) và đám đông (US06).
  - `NVIDIA AI City Challenge TAR` (Track 3 / Track 4): Dữ liệu camera giao thông đường bộ cố định từ các Sở GTVT (DOTs).

## Evidence không đổi

Theo hiệu chỉnh Q36, raw clip giữ cố định **10 giây trước / 20 giây sau anchor**. Person-down giữ baseline [contracts §3](../architecture/contracts.md): person fall có onset quan sát dùng onset estimate có provenance; persistent lying/on-vehicle thiếu onset dùng first qualifying observation của chuỗi persistence đang dùng, không gọi là onset. Các nhóm mới dùng mốc đủ điều kiện cảnh báo; không áp mốc này thay anchor person-down. Đây là phân biệt policy tài liệu, không đổi runtime. Giữ nguồn gốc, thời gian, mốc bắt đầu quan sát, khoảng duy trì, vùng và config; đánh dấu complete/partial/missing theo hợp đồng. Sự kiện kéo dài có thể chỉ được clip bao phủ một phần; nếu onset ngoài clip phải thể hiện rõ. Lịch sử quan sát không thay video và không tự thêm nhiều clip hay NVR dài ngày. AI chỉ tạo sự kiện nghi ngờ để người trực xác minh, không kết luận pháp lý/y tế/nguyên nhân/trách nhiệm.

## Ghi nhận thay đổi tài liệu

Ngày 2026-10-20: bổ sung hồ sơ RF-DETR + ViTPose và Jetson Orin NX từ quyết định Q35; đồng bộ liên kết/điều kiện trong readiness và lab, giữ baseline và các gate đang mở. Hiệu chỉnh Q36 phân biệt anchor person-down baseline với mốc đủ điều kiện cảnh báo của nhóm mới; cả hai giữ 10/20 và không đổi runtime. Đây là thay đổi tài liệu; không download model/data, không huấn luyện, benchmark hay kiểm thử runtime, không công nhận capability hoặc target capacity.

Ngày 2026-11-11: đồng bộ trạng thái tài liệu theo kết quả rà soát kiến trúc và bằng chứng kiểm thử khắc phục ([nhật ký 2026-11-11](../logs/2026-11-11-review-remediation.md)). Làm rõ phạm vi baseline phần mềm lab (registry 14 kịch bản vs bộ đánh giá 4/11 kịch bản và 3 kịch bản unconfigured), cơ chế Tier-2 VLM verifier (heuristic phân tích cục bộ offline vs VLM từ xa chạy HTTP đồng bộ khi kích hoạt tường minh), giới hạn đệm storyboard trực tuyến tại $t_0$ (chỉ resample đệm quá khứ), template homography uncalibrated, dynamic batching phụ thuộc runtime ONNX, vai trò helper bổ trợ của go2rtc (chưa thay thế luồng RTSP kép upstream), và bản chất metadata nội bộ của trường `production_use_approved` trong manifest.
