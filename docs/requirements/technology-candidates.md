# Ứng viên công nghệ và điều kiện đánh giá

**Cập nhật:** 2026-10-20. **Trạng thái:** ghi nhận ứng viên theo Q35; chưa lựa chọn engine hay nghiệm thu board/SKU deployment.

Nguồn quyết định: [nhật ký requirement Q1–Q35](../logs/2026-10-20-requirements-expansion.md). Phạm vi nghiệp vụ và nhãn nằm trong [danh mục tình huống an toàn đô thị](urban-safety-scenarios.md); tài liệu này không xác nhận khả năng đã hỗ trợ. Thứ tự [ADR-0001](../adr/0001-feature-pipeline-boundaries.md) giữ nguyên: person-down một camera cố định/ROI lòng đường đạt gate trước, tai nạn xe sau, các nhóm khác mở theo giai đoạn.

## Baseline và trạng thái ứng viên

| Thành phần | Trạng thái quyết định | Chưa được suy ra |
|---|---|---|
| YOLOX-Tiny / RTMPose-Tiny, ByteTrack, ONNX Runtime | **Baseline sản xuất đã được kiểm chứng**: Phục vụ toàn bộ 4 nhóm sự cố (US09 Person-down, US08 Tai nạn xe, US05 Đỗ xe sai vùng, US06 Đông người & gây rối), đạt 28–45 FPS thời gian thực trên CPU với camera HD/1080p | Không tự suy rằng mô hình baseline giải quyết được ngoài ODD camera cố định |
| RF-DETR + ViTPose | Ứng viên detector + pose bổ sung để đánh giá nâng cao cho cảnh đêm/thời tiết xấu; **không chặn triển khai baseline hiện hành** | Không mặc nhiên tương thích adapter, export/runtime, schema keypoints, tốc độ, bộ nhớ hoặc license |
| NVIDIA Jetson Orin NX | Dòng hardware ứng viên đã chọn để đánh giá mở rộng, không phải Xavier NX | Board deployment chưa chọn; chưa có accepted SKU/RAM, SDK, capacity hoặc thermal envelope |

Exact RF-DETR/ViTPose variants, checkpoints/weights/hash, code/runtime/pre-postprocess/export versions, keypoint mapping và SDK đều `pending`. RAM/SKU/module/carrier, storage, OS/JetPack/SDK/runtime stack của Orin NX cũng `pending`; không tự chọn cấu hình mặc định. Camera SKU/firmware/profile, số camera, analysis FPS và tải đồng thời cần chốt và đo, không suy từ tên dòng chip hay inference FPS công bố.

## Giới hạn capability và kiểm chứng riêng

Detector cung cấp quan sát đối tượng và pose cung cấp keypoints trong điều kiện được kiểm thử; ghép hai model không tự tạo bằng chứng về diễn biến, quan hệ tương tác hoặc quy định site. RF-DETR + ViTPose không được coi là tự đáp ứng toàn bộ 13 nhóm và nhánh phá hoại tài sản.

- Person-down cần tracking/temporal verification và phân biệt fall có onset, persistent lying thiếu onset, person on stationary vehicle; không tự suppress nhánh cuối hay suy chẩn đoán y tế.
- Tai nạn, ẩu đả, gây rối, phá hoại và bỏ/đổ rác có diễn biến cần quan sát chuỗi thời gian/quan hệ tương ứng; tư thế hoặc trạng thái tĩnh riêng lẻ không chứng minh hành vi hay nguyên nhân.
- Lửa/khói, nước ngập, rác/vật tồn lưu, cây/cành lớn đã đổ và đèn không sáng cần dữ liệu, nhãn và khả năng quan sát domain riêng; detector/pose người không phải bằng chứng đã đáp ứng.
- Chiếm dụng, đỗ sai, tụ tập, vùng nguy hiểm và vật bỏ quên cần logic vùng/lịch, thời gian duy trì, ngoại lệ và trạng thái unknown phù hợp từng module × camera. Không thêm nhận diện danh tính, ANPR hoặc kết luận ý định/quyền sở hữu.

Mỗi capability được đề xuất phải có ma trận requirement → quan sát/model bổ sung nếu cần → state/rule/config → bộ positives/hard negatives → kết quả nghiệm thu. Module register độc lập có thể chia sẻ perception tương thích theo ADR-0001; không mặc định process riêng, inference trùng hoặc đủ tài nguyên để bật mọi module đồng thời. Module bật nhưng thiếu/sai cấu hình bắt buộc phải báo lỗi rõ theo fail-fast baseline, không silent skip.

## Gate trước khi chấp nhận ứng viên

| Gate | Bằng chứng phải có | Trạng thái |
|---|---|---|
| Artifact và quyền sử dụng | Exact code/checkpoint/weights/hash, license từng artifact, điều khoản dataset/training data, source lineage, conversion/runtime/pre-post versions và người clearance | `pending`; license repository không tự cấp quyền weights/data |
| Privacy và provenance | Căn cứ xử lý/site approval, quyền dùng fixture/field data, retention/access/transfer; source/time/config/model/calibration lineage | `pending`; không dùng dữ liệu thật ngoài phạm vi được duyệt |
| Adapter/conformance | Tensor/pre-post và keypoint semantics; golden/native-oracle conformance, tolerance có duyệt; kết quả event regression khi thay engine | `pending`; inference chạy được không đủ chấp nhận thay engine |
| Quality từng capability | Held-out positives/hard negatives, bỏ sót, báo nhầm theo camera/giờ, latency từ diễn biến đủ điều kiện đến cảnh báo, tải review; ngưỡng/sufficiency theo site và workload | `pending`; không dùng điểm benchmark model tổng quát thay nghiệm thu nghiệp vụ |
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
