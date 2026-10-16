# Báo cáo nghiên cứu: AI Camera giao thông xử lý tại edge

**Cập nhật thực nghiệm/implementation: 15-10-2026**, đối chiếu commit `6fff369f4c30dd6faff0150b660cf5e065207daa` và working tree hiện có. Đọc [§14](#14-cập-nhật-theo-implementation-và-thử-nghiệm-15-10-2026) trước: đây là đánh giá hiện trạng và đề xuất tiếp theo. Các mục phần cứng/giá bên dưới giữ mốc lịch sử; lựa chọn native C++ là thiết kế đã duyệt, chưa phải runtime hiện có. Lượt này chỉ sửa tài liệu, không chạy lại benchmark hay ký gate.

**Mốc nghiên cứu theo đồng hồ hệ thống: 09-10-2026.** Phạm vi được người dùng đồng ý: tài liệu không giới hạn thời gian, ưu tiên giá bán hiện hành Việt Nam, bổ sung quốc tế; PoC 1–4 camera, luồng 1080p, phân tích mục tiêu 10–15 FPS/camera. Báo cáo là nghiên cứu và đề xuất thiết kế, không phải benchmark trên phần cứng hoặc báo giá mua hàng đã xác nhận. Website được truy xuất trong phiên, không phải bản lưu lịch sử; ngày cập nhật/tồn kho của website có thể lệch đồng hồ hệ thống.

**Đồng bộ thiết kế: 11-10-2026.** Nguồn chuẩn là [mục lục thiết kế](../docs/README.md), [kiến trúc](../docs/architecture/system-architecture.md) và [contracts](../docs/architecture/contracts.md). Bản đầu: person-down một camera cố định, ONNX/native C++ + Python, recorder độc lập, HTTPS→FastAPI/MongoDB và dev demo. RKNN chỉ khi chọn target; vehicle là nhánh sau. Nghiên cứu giữ lý do lựa chọn và bất định, không là backlog thứ hai.

**Dữ liệu thị trường lịch sử:** 16 quan sát giá giữ ngày09-10-2026; bốn giá Tapo giữ ngày10-10-2026. Lượt đồng bộ11-10 không truy xuất lại retailer, không cập nhật giá/stock/license/legal clearance và không tạo benchmark mới. Các lựa chọn phần cứng/model ngoài baseline dưới đây là đối chứng nghiên cứu, không tự trở thành scope triển khai.

## 1. Kết luận điều hành

1. **Tách PoC chức năng khỏi benchmark/production.** Có thể bắt đầu bằng máy sẵn có hoặc RPi5/ONNX Runtime và camera RTSP giá rẻ; chuyển Orange Pi5/RKNN bằng adapters/artifacts sau regression. Đây là lựa chọn triển khai, chưa chốt board hoặc cam kết FPS. Jetson/x86 vẫn là phương án benchmark nhiều camera; không đưa devkit trần ra cột đường cho production. Phần cứng cuối được quyết định bằng workload thực và điều kiện hiện trường.
2. **YOLOX + ByteTrack là baseline hợp lý**, nhưng detector và tracker không tự nhận diện tai nạn. Chỉ mở đối chứng RTMDet-tiny/small khi lỗi chất lượng hoặc benchmark cho thấy cần; bổ sung RTMPose theo track và logic chuỗi thời gian. Không triển khai nhiều framework cùng lúc nếu không tạo lợi ích đo được.
3. **Tốc độ/gia tốc và thay đổi tọa độ y là tín hiệu kích hoạt, không phải bằng chứng quyết định.** Cần hình học mặt đường, timestamps, độ tin cậy tracking và xác nhận diễn biến trước/sau. Bổ sung nhánh phát hiện ngã chậm và người nằm bất động.
4. **Không chẩn đoán đột quỵ từ camera.** Đầu ra phù hợp: nghi ngã/quỵ xuống, người nằm bất động hoặc người ở vị trí nguy hiểm; người trực xác minh và kích hoạt quy trình hỗ trợ.
5. **Đầu vào tốt nhất đến từ quang học/lắp đặt/exposure**, không phải chạy chuỗi deblur/deglare nặng trên mọi khung hình. Ảnh phục hồi có thể tạo giả ảnh và làm giảm độ tin cậy chứng cứ.
6. **Chỉ gửi sự kiện lên server là khả thi**, nhưng phải lưu clip nén trước/sau tại edge; server nhận metadata trước, ảnh/clip theo chính sách hoặc yêu cầu. Nếu không lưu video liên tục ở đâu, không thể truy hồi đoạn chưa được giữ lại.
7. **Quan sát giá ngày09-10-2026 khác MSRP tham chiếu.** Ví dụ Nano Super ở Hshop hiển thị 15.228.000₫, Waveshare $634,99; không dùng mốc $249 làm ngân sách mua mà chưa có quote mới. Chi tiết và điều kiện tại phần 8 và `prices.csv`.

## 2. Miền hoạt động và camera

### 2.1 Phải xác định trước khi mua

- Đường/giao lộ/vỉa hè nào, tốc độ và mật độ xe máy, vùng quan sát và thời tiết.
- Góc lắp, chiều cao, tiêu cự, người ở xa còn bao nhiêu pixel; người bị xe che và ngã ra ngoài khung có được xem là ngoài miền hỗ trợ không.
- Phân biệt camera toàn cảnh phục vụ sự kiện với camera chuyên biển số. Một camera góc rộng thường không đồng thời đáp ứng pose người xa và biển số xe nhanh ban đêm.
- Khuyến nghị camera cố định. PTZ làm thay đổi ROI/homography; phải biết preset và calibration tương ứng, hoặc dừng kết luận tốc độ/vi phạm trong lúc quay.

### 2.2 Thông số mua và nghiệm thu

Camera IP PoE, RTSP, ONVIF Profile T; 1080p hoặc 4MP tùy pixel-on-target; 25–30 FPS nguồn; chỉnh được shutter/gain/WDR; hoạt động đêm có chiếu sáng phù hợp; IP67 cho camera ngoài trời. Profile M hữu ích nếu tích hợp metadata AI vào VMS, không phải điều kiện để một camera thường cấp RTSP cho edge. Đối chiếu conformant product/firmware thực tế, không chỉ chữ “ONVIF” trên brochure.

Giữ main stream chất lượng đủ bằng chứng; chọn luồng phân tích/crop ROI theo nhu cầu. Resize toàn cảnh xuống 640×640 có thể làm người/biển số quá nhỏ; khi đó thay tiêu cự, thêm camera, crop hoặc input lớn hơn, thay vì chỉ mua GPU mạnh hơn. Crop/tile tăng số inference và cần chống trùng tracking.

Shutter tham khảo 1/250–1/1000 giây cho đối tượng nhanh chỉ là điểm bắt đầu thử nghiệm; ban đêm cần thêm ánh sáng, cân bằng gain/noise. Không bảo đảm mọi cảnh chạy được shutter nhanh. WDR đa exposure có thể gây artifact ở đối tượng chuyển động. [Axis](https://www.axis.com/en-nz/solutions/wide-dynamic-range-wdr) nhấn mạnh exposure ngắn và chất lượng xử lý quan trọng hơn chỉ số dB đơn lẻ.

### 2.3 Tiền xử lý có điều kiện

**Baseline lab:** software decode → sửa distortion nếu cần → crop/resize/letterbox → normalize theo đúng model. Khóa và version biến đổi tọa độ để tracking/calibration không bị lệch.

**Chỉ khi phát hiện vấn đề:** quality gate đo blur, vùng cháy sáng, thiếu sáng, freeze, che lens và rung. CLAHE/denoise nhẹ hoặc stabilization thử A/B theo đêm/mưa. Nếu stabilize, cập nhật phép ánh xạ về tọa độ gốc/mặt đường; rung lớn phải báo mất calibration.

**Không mặc định:** neural deblur, dehaze, super-resolution hay generative enhancement trên tất cả frame. Đánh giá bằng event recall/báo giả, không chỉ ảnh đẹp/PSNR. Giữ bản nén gốc làm bằng chứng; ảnh đã enhance phải có nhãn và không thay thế ảnh gốc. Vùng bão hòa trắng không thể phục hồi đáng tin chi tiết đã mất.

### 2.4 Camera RTSP giá rẻ cho PoC

| Model | Giá đọc lại10-10-2026 | Vai trò và giới hạn |
|---|---:|---|
| Tapo C100 | 339.000₫ | 1080p Wi-Fi, trong nhà, test pipeline cơ bản |
| Tapo C110 | 389.000₫ | 3MP Wi-Fi, góc cố định; lựa chọn tiết kiệm khuyến nghị |
| Tapo C200 | 399.000₫ | 1080p quay/quét; giữ góc cố định khi test tracking/ROI |
| Tapo C310 | 649.000₫ | 3MP, Wi-Fi + Ethernet, IP66; không mặc định có PoE |
| EZVIZ H1c | Chưa kiểm tra giá | 1080p H.264; iSpyConnect liệt kê RTSP `/11` và `/channel1`, cần thử firmware cụ thể |

Giá Tapo từ trang bán, không phải xác nhận tồn kho/VAT/checkout. `tapo.com.vn` là nguồn retail, không tự coi website chính thức của hãng. Nguồn hãng về RTSP: https://www.tp-link.com/vn/support/faq/2680/ . Cần tạo Camera Account riêng trong app; stream1/stream2, local LAN; không cần thẻ nhớ để ứng dụng edge nhận RTSP. Không áp dụng chung cho camera dùng pin. Bảng giá chi tiết trong prices.csv.

H1c: https://www.ispyconnect.com/camera/ezviz liệt kê model cụ thể với RTSP, là bằng chứng compatibility bên thứ ba. Trang hãng https://www.ezviz.com/product/h1c/47789 công bố H.264, max1Mbps và FPS tự thích ứng, nhưng không ghi RTSP. **Không loại H1c chỉ vì trang hãng không ghi RTSP**; cũng không suy các dòng RTSP thành xác nhận ONVIF hoặc mọi firmware. Phải thử VLC, local operation khi WAN ngắt, reconnect và FPS/latency. Credential thiết bị phải xác minh, không giả định là mật khẩu cloud.

Camera A9 chưa xác minh local stream/SDK: không khuyến nghị mua để viết AI chỉ dựa tên1080p; yêu cầu demo VLC trước. Wi-Fi/Ethernet là transport mạng, không ranh giới nghiệp vụ khác nhau. Camera giá rẻ chỉ đánh giá integration, không chứng minh event accuracy ngoài đường. Thay camera phải cập nhật lens/ROI/calibration, ODD, decode và regression.

### 2.5 Module IMX219 so với camera IP hoàn chỉnh

Waveshare IMX219-160 SKU16662: sensor1/4inch, ảnh tối đa8MP3280×2464, F2.35, FOV160° **đường chéo**, distortion hãng <14,3%, CSI-2, bản không IR. Nguồn: https://www.waveshare.com/product/ai/cameras/single-cameras/imx219-160-camera.htm . Camera Hikvision DS-2CD2T43G2-4I có sensor1/3inch, F1.6, WDR120dB, IR-cut/IR và vỏIP67 theo trang hãng. Không so góc đường chéo với ngang; 8MP ảnh tĩnh không mặc nhiên8MP30FPS.

Đối tượng xa trong góc160° có ít pixel; resize/correction giảm chi tiết hiệu dụng. Camera IP phù hợp thường có lợi thế ngày/đêm/lắp ngoài trời; không khẳng định mọi camera IP tốt hơn mọi module. Module CSI có thể tránh video compression và hỗ trợ control sâu, nhưng phải làm ISP/driver/lens/IR/cooling/enclosure. Chọn module hẹp/sensor phù hợp nếu sản xuất camera all-in-one; IMX219-160 không phải baseline lý tưởng cho pose người xa/ANPR. Pixel-on-target và video chuyển động quan trọng hơn megapixel.

### 2.6 Tận dụng AI native của camera

DS-2CD2T43G2-4I: hãng công bố motion human/vehicle classification, line crossing, intrusion, face detection; API ISAPI/SDK, ONVIF S/G. Nguồn: https://www.hikvision.com/ph/products/IP-Products/Network-Cameras/Pro-Series-EasyIP-/ds-2cd2t43g2-2i-4i/?subName=DS-2CD2T43G2-4I . Face detection không phải nhận dạng danh tính; không xác minh ANPR/fall/crash từ lời quảng cáo nhà bán.

Ba mức tích hợp:
1. Event-only: nhận alarm vùng/vạch, lấy clip và gửi server; có thể thay AI cho đúng sự kiện đã kiểm chứng.
2. Hybrid trigger: native event kích hoạt verifier, nhưng giữ phân tích nền để không bỏ ngã chậm/người đã nằm.
3. Dense metadata: chỉ thay detector/tracker nếu camera xuất bbox/class/timestamp/coverage liên tục và track ID đủ tốt. **Chưa xác minh mức3 cho model này.**

ISAPI/SDK hoặc ONVIF label không đảm bảo mọi metadata capability. RFQ/demo cần payload mẫu, rate, IDs, coordinate system, firmware, local auth và no-cloud operation. Không OCR bbox overlay hoặc screen-capture app làm pipeline production.

## 3. Model và giấy phép thương mại

| Thành phần | Vai trò | Giấy phép mã nguồn đã kiểm tra | Đề xuất |
|---|---|---|---|
| YOLOX nano/tiny/small | Person/vehicle detector | Apache-2.0 | Baseline đầu tiên, fine-tune điều kiện Việt Nam |
| ByteTrack | Liên kết detection theo thời gian | MIT | Baseline tracker; đánh giá ID switch và xe máy đông |
| RTMDet trong MMDetection | Detector thay thế | Apache-2.0 | So sánh với YOLOX bằng cùng dữ liệu và cùng pipeline |
| RTMPose trong MMPose | Keypoint trên crop người | Apache-2.0 | Chạy chọn lọc và theo chuỗi, không kết luận từ một pose |
| MMAction2 | Huấn luyện/triển khai action classifier | Apache-2.0 | Chỉ thêm nếu temporal rule không đạt mục tiêu |
| PP-YOLOE/RT-DETR trong PaddleDetection hoặc RT-DETR official | Detector thay thế | Apache-2.0 | Tùy kinh nghiệm team; kiểm chứng export/precision |
| Supervision | Annotation/utility | MIT | Tùy chọn, không phải model tai nạn |
| Ultralytics | Detector/pose/tooling | AGPL-3.0 hoặc Enterprise | Không ưu tiên cho sản phẩm đóng nguồn nếu chưa giải quyết hợp đồng |

Nguồn gốc: [YOLOX](https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE), [ByteTrack](https://github.com/FoundationVision/ByteTrack/blob/main/LICENSE), [MMDetection](https://github.com/open-mmlab/mmdetection/blob/main/LICENSE), [MMPose](https://github.com/open-mmlab/mmpose/blob/main/LICENSE), [PaddleDetection](https://github.com/PaddlePaddle/PaddleDetection/blob/develop/LICENSE), [Ultralytics](https://www.ultralytics.com/license).

**Quan trọng: bảng trên xác nhận code, không xác nhận mọi pretrained weight được phép thương mại.** Phải duyệt từng checkpoint: URL, hash, tag, model card, giấy phép weight, dữ liệu pretrain/train và dependency. RTMPose có nhiều checkpoint dùng mixed datasets; không gán cùng kết luận cho tất cả. Fine-tune không tự xóa hạn chế nguồn gốc. COCO annotation và ảnh Flickr nguồn không phải một giấy phép blanket duy nhất.

Apache/MIT cho phép sử dụng code thương mại với nghĩa vụ license/notice tương ứng; AGPL không cấm kiếm tiền, nhưng có nghĩa vụ copyleft/source tùy phân phối, sửa đổi và truy cập mạng. Với sản phẩm proprietary dùng Ultralytics, cần đánh giá pháp lý và Enterprise/OEM terms thay vì suy luận AGPL tự động được phép hay bị cấm. Không thấy mức phí Enterprise công khai đủ để lập dự toán.

**Stack thực tế tại 15-10:** YOLOX-Tiny ONNX → tracker Python hai giai đoạn → rule bbox/chuyển động/thời gian. RTMPose estimator/scheduler đã có implementation tùy chọn; pose outcomes chưa được IncidentEngine dùng để quyết định sự kiện. Temporal classifier tự huấn luyện chưa được xác nhận. RTMDet là đối chứng tùy kết quả, không bắt buộc PoC và không cài song song trong baseline. Detector COCO mặc định không có nhãn tai nạn, ngã, helmet hoặc biển số.

## 4. Thiết kế nhận diện sự kiện

### 4.1 Tracking và tốc độ

ByteTrack dùng cả detection độ tin cậy thấp để phục hồi track; vẫn có ID switch khi đông xe, che khuất và detector bỏ sót. Detection phải đủ tốt trước khi thêm ReID. Có thể so sánh tracker có camera-motion compensation/ReID nếu giảm lỗi thực sự; ReID gây thêm compute và nghĩa vụ dữ liệu.

Với camera cố định, chọn điểm gần tiếp xúc mặt đường, không dùng tâm bounding box như tọa độ vật lý. Hiệu chuẩn intrinsic/distortion và homography từ mốc tọa độ đo thực tế, biến điểm ảnh thành mét:

`v(t) ≈ [X(t) − X(t−Δt)] / Δt`, `a(t) ≈ [v(t) − v(t−Δt)] / Δt`.

Dùng timestamp thật, không giả định mọi frame đúng 1/30 giây. Lọc chuỗi vị trí bằng Kalman/robust regression và cửa sổ thời gian; loại outlier, che khuất, ID switch. Homography chỉ đúng gần mặt phẳng đường và điểm contact phù hợp; cầu dốc, nhiều mặt phẳng, bbox bottom không đúng contact và PTZ gây sai. Ước lượng sai số theo vùng camera; confidence thấp thì xuất unknown, không xuất km/h chính xác giả.

Gia tốc là đạo hàm tiếp theo nên rất nhạy với jitter. Không đặt một ngưỡng gia tốc pixel rồi gọi tai nạn. Tốc độ phục vụ cảnh báo kỹ thuật khác tốc độ đủ điều kiện làm bằng chứng; radar/thiết bị đo có hồ sơ phù hợp là lựa chọn nếu mục tiêu xử phạt.

### 4.2 Tai nạn: nhiều tín hiệu + diễn biến hậu sự kiện

Một candidate score gồm: quỹ đạo tiếp cận/cắt nhau, khoảng cách footprint trên mặt đường, chuyển hướng/dừng đột ngột, xe có tư thế bất thường, người/vật xuất hiện trên đường, các đối tượng liên quan không phục hồi chuyển động. Bbox overlap không chứng minh chạm; TTC chỉ báo rủi ro với giả định chuyển động tương đối, không chứng minh collision.

State machine đề xuất:

`normal → candidate → verifying → suspected → closed`. Review server độc lập: unreviewed→confirmed/false_positive, confirmed→resolved; correction/reopen có audit và needs_re_review theo [contracts §5](../docs/architecture/contracts.md).

Duration xác minh là threshold theo ODD cần nghiệm thu; evidence lab giữ pre10/post20 tính theo anchor, tách khỏi verification window. Classifier chỉ thêm khi chất lượng đã đo yêu cầu; cảnh báo khẩn có thể gửi sớm rồi cập nhật confidence/clip, không đợi hết clip. Phân biệt hard negatives: phanh gấp, kẹt xe, chuyển làn, đỗ xe, người băng qua, xe đi qua nhau khác chiều sâu, track mất rồi xuất hiện lại. Cooldown và dedup theo camera/thời gian/vùng/track graph, không suppress một tai nạn mới chỉ vì gần sự kiện cũ.

Nếu rule không đủ chất lượng, dùng temporal classifier nhẹ trên trajectory + pose + crop sequence; đầu tiên thử feature classifier/TCN, sau đó mới xét video network nặng. Đây là hướng thiết kế, không phải model tai nạn đã đạt accuracy xác nhận.

### 4.3 Té ngã/quỵ xuống và người bất động

Trigger y bất thường chỉ là một nhánh. Bổ sung thay đổi tỷ lệ bbox, độ cao đầu/hông chuẩn hóa theo kích thước người, góc thân, chuyển động xuống mặt đường, mất chuyển động và tư thế nằm duy trì. Bộ trigger cần ưu tiên recall; giảm báo giả ở bước temporal verification.

- **Ngã nhanh:** trigger mở ROI pose và chuỗi khung gần sự kiện; không chỉ pose một ảnh.
- **Ngã chậm:** low-rate pose sampling trên track người đủ lớn hoặc nhánh theo dõi thay đổi tư thế chậm. Tần suất 1–3 FPS/track là điểm bắt đầu PoC, không cam kết đủ cho mọi chuyển động.
- **Người đã nằm khi vào khung/camera restart:** persistent lying/abnormal posture detector; không bắt buộc thấy chuyển tiếp đứng→ngã.
- **Pose đang nghi vấn:** tăng tần suất ví dụ 8–15 FPS trên ROI có confidence; giới hạn tổng ROI và báo trạng thái giảm năng lực khi quá tải.
- **Keypoint thiếu/che khuất:** unknown; không diễn giải thành người an toàn hoặc bất động.

Phân biệt đứng→ngồi, ngồi xổm, cúi buộc giày, nhặt đồ, nằm nghỉ, người bị xe che, người xuống xe máy. Dùng chuỗi tư thế, gần mặt đất, thời gian duy trì và hồi phục. Ngưỡng duration cần cân bằng cảnh báo sớm và báo giả; nằm trên làn xe có thể ưu tiên cảnh báo ngay bất kể nguyên nhân.

**Không gán nhãn đột quỵ/ngất/mất ý thức.** Camera không có thông tin lâm sàng đủ; cảnh báo cần người xác minh và quy trình liên hệ cứu hộ/cấp cứu phù hợp. Không tự động gọi cấp cứu hàng loạt từ một confidence threshold chưa được nghiệm thu.

### 4.4 Phạm vi ngoài baseline

ANPR/helmet/vi phạm đèn đỏ, radar, ReID và nhận dạng danh tính không nằm trong backlog hiện hành. Chỉ mở nghiên cứu riêng khi có use case/ODD/rights được xác nhận. Vehicle suspected incident sau person-down có gate G4b, không tự mở toàn bộ các tính năng camera giao thông.

## 5. Video pipeline, runtime và edge–server

```text
Thiết kế đích (runtime hiện tại xem §14):
Camera RTSP đã nén
  ├── compressed segment/ring buffer → pin clip trước/sau → event upload / truy hồi
  └── native software decode (hardware khi được chọn/đo) → quality metrics → resize/crop → detector → tracker
                                                ├── trajectory + calibrated geometry
                                                └── pose chọn lọc + temporal verifier
                                          → event FSM → atomic event/outbox/pin intent
Server: HTTPS→FastAPI→MongoDB transaction/receipt → review + evidence filesystem lab → demo API
```

### 5.1 Lựa chọn phần mềm

- NVIDIA: JetPack/CUDA/TensorRT, GStreamer hoặc DeepStream nếu đa luồng và zero-copy mang lại lợi ích. Phải dùng ma trận version tương thích device/JetPack/CUDA/TensorRT/DeepStream; không mặc định tài liệu DeepStream mới nhất chạy được trên mọi Orin.
- Intel: OpenVINO + decode phù hợp iGPU; kiểm tra codec profile/driver và tác động CPU khi fallback.
- Portable: ONNX Runtime; thực nghiệm TensorRT/OpenVINO execution providers tùy thiết bị.
- Hailo/RK: compiler/runtime riêng; kiểm tra operator, NMS, pose decode, INT8 calibration, dynamic shapes, toolchain host, RAM và fallback CPU. TOPS cao không bảo đảm deploy được model mong muốn.
- MediaMTX có thể proxy/record/playback RTSP; không transcode video chỉ vì chuyển protocol. Không bắt buộc dùng nếu GStreamer segmentation đã đủ.
- Backend lab đã chốt: HTTPS event ingress, FastAPI/Python + MongoDB replica set một member/persistent volume; transaction readiness/retry phải chạy trên exact version. Evidence filesystem qua adapter, dev demo HTML/JS do FastAPI phục vụ. Server giữ downstream intent; chưa bật broker/notification. Production storage/HA là gate riêng, không coi lab là HA.

ORT MIT, OpenVINO Apache; GStreamer core LGPL, FFmpeg phụ thuộc cấu hình build; TensorRT/DeepStream full SDK chịu điều khoản NVIDIA. Xem `sources.md`. Audit `ffmpeg -buildconf`, `ffmpeg -L`, plugin và codec; `--enable-gpl` thay nghĩa vụ, `--enable-nonfree` có thể làm binary không được phân phối. Không gọi toàn bộ pipeline là open source miễn ràng buộc chỉ vì code ứng dụng MIT.

### 5.2 Clip và truy hồi

**Orin Nano không có NVENC**, theo [NVIDIA](https://docs.nvidia.com/jetson/archives/r35.6.1/DeveloperGuide/SD/Multimedia/SoftwareEncodeInOrinNano.html). RTSP camera đã H.264/H.265 có thể remux/lưu compressed packets không encode lại. Nếu ghi overlay hoặc privacy masking lên video ở edge, có thể cần decode + re-encode software, rất khác ngân sách compute. Giữ raw clip bảo vệ truy cập, gửi bản đã che theo yêu cầu; xác định rõ privacy masking ảnh hưởng quyền truy cập raw.

Lab dùng ring10 phút, pre10/post20 giây quanh onset hoặc first qualifying observation khi thiếu onset. Segment/GOP là thông số đo theo source, không thay requested interval. Event/outbox/evidence request cùng transaction; recorder persist pin receipt trước ACK, retry/query theo request ID. Ring budget phải tính verification/handoff/recovery; không đủ thì partial/missing. Clip keyframe-aligned có thể dài hơn cửa sổ yêu cầu; ghi timestamp chính xác và không cắt bừa giữa GOP. Nếu muốn truy hồi lịch sử bất kỳ, phải lưu liên tục nhiều giờ/ngày tại edge/NVR; ring buffer vài phút không đủ.

Metadata AI là full snapshot theo revision, identity/origin bất biến; clocks có domain/uncertainty. Review giữ viewed event/evidence versions và audit riêng. Evidence có build/completeness/transfer/availability/integrity riêng: clip partial vẫn được upload/ACK. Track ID không phải danh tính. Chi tiết và fixtures tại contracts, không định nghĩa wire schema thứ hai trong báo cáo này.

Store-and-forward: durable outbox, HTTPS retry theo device/event/revision và canonical content hash; ACK metadata và clip riêng. Outage24h là sizing budget, không tự xóa pinned/unACK khi hết 24h. Server clip retention7 ngày; edge release sau clip receipt và policy, metadata ACK không đủ. Khi protected data đầy quota, giữ dữ liệu đã bảo vệ, event mới evidence partial/failed và báo degraded. Báo lỗi hết bộ nhớ, không xóa bằng chứng im lặng. Clip có checksum/hash hỗ trợ integrity nhưng một hash đơn lẻ không chứng minh toàn bộ chuỗi chứng cứ chưa bị sửa.

### 5.3 Tính lưu trữ và băng thông

Ví dụ **4 camera × 4 Mbps**: 16 Mbps local video, không cần gửi WAN liên tục. Lưu liên tục: `4 Mbps × 86400 / 8 ≈ 43,2 GB/camera/ngày`, tổng **172,8 GB/ngày**, khoảng **1,21 TB/7 ngày**, chưa filesystem/bitrate overhead. SSD 1TB với 20% dung lượng dự phòng còn khoảng **4,6 ngày** theo giả định này, chưa OS/clip pinned. TB thập phân; không đồng nhất TiB.

Clip 30 giây ở 4 Mbps ≈ **15 MB/camera**. 100 clip/ngày từ một camera ≈ 1,5 GB; tổng 100 sự kiện/ngày từ cả fleet khác với mỗi camera 100. Thumbnail/metadata làm tăng thêm. Tính theo VBR thực tế và event burst; giảm băng thông không đồng nghĩa không còn dữ liệu cá nhân. Chọn SSD theo endurance/TBW, write workload, nhiệt độ và power-loss protection khi cần, không chỉ dung lượng/giá consumer NVMe.

## 6. Dữ liệu và đánh giá

| Nguồn | Giá trị | Hạn chế/quyền |
|---|---|---|
| DoTA | Annotation anomaly thời gian/không gian | Dashcam khác camera cố định; MIT repo cho software không clear video |
| DAD | Accident anticipation | Dashcam; chưa xác minh commercial grant |
| TAD/TADBench | Tai nạn camera giám sát/highway | Gần bài toán hơn; quyền thương mại chưa xác minh |
| UR Fall | Ngã + hoạt động thường ngày | Tác giả nêu rõ **CC BY-NC-SA 4.0**, cần xin quyền thương mại |
| UP-Fall/Le2i | Ngã diễn xuất/multimodal | Khác miền ngoài đường; commercial license chưa xác minh |
| OmniFall | Taxonomy falling/fallen, đa miền | Kiểm tra từng nguồn video/subset; license bài báo không clear dataset |

[UR Fall](http://fenix.ur.edu.pl/~mkepski/ds/uf.html) không dùng thương mại mặc nhiên. “Public download”, citation hay mirror gắn MIT không thay giấy phép của tác giả/video. Với nguồn unknown: chỉ dùng trong phạm vi được cho phép sau khi duyệt, không đưa vào training sản phẩm rồi giải quyết sau.

Thu dữ liệu địa phương có hợp đồng quyền sử dụng/training và quy trình riêng tư: ngày/đêm/mưa, góc camera, xe máy, người lớn/trẻ nhỏ, che khuất, người xa; hard negatives phanh/đỗ/ngồi/cúi/nằm nghỉ. Không diễn xuất ngã/tai nạn nguy hiểm ngoài đường; mô phỏng có kiểm soát/đóng đường có phép, dùng diễn viên và phương án an toàn; synthetic hỗ trợ chứ không thay validation thực.

Split theo site/camera/ngày/person/video, không chia frame liền nhau vào train/test. Tập real-world riêng; annotation event onset/end, visible/unknown, severity, liên quan tracks, reviewer agreement. Hiếm tai nạn thật làm số liệu dễ quá tự tin; ghi số sự kiện, tổng camera-hours, confidence intervals. Không lấy mAP detector hay accuracy frame làm độ chính xác tai nạn.

**Acceptance hiện hành:** lab một camera; P95 durable edge commit→dashboard ≤5 giây trên LAN, clock correlation/số mẫu rõ. Không bao gồm temporal verification hoặc post-roll/upload. Pre10/post20 phải đủ requested range khi nguồn có dữ liệu; missing/gap báo partial. Đây là target chưa nghiệm thu.

Recall, false alerts/camera-day, analysis FPS, pose burst, RPO/RTO và operator capacity phải thành preliminary targets có owner theo [readiness](../docs/architecture/deployment-readiness.md), sau đó ký từ số đo. Không giữ các ngưỡng nghiên cứu cũ 90%/1 báo giả/ngày/2 giây như requirements mặc định. Semantic replay dùng fixed inputs và virtual clock; realtime stress đo drop/coverage riêng. G3 target soak24–72h gồm recording/upload; field pilot cần đủ sample/event/camera-days, không cam kết hoàn tất theo số tuần cố định.

Đánh giá recall gồm negative audit phân tầng lấy clip trước ring expiry, inclusion probability/trọng số, missing coverage, matching windows và uncertainty; không suy recall từ alerts-only hoặc cộng raw sample counts giữa strata khác tỷ lệ.

Nếu không có báo giả trong T camera-ngày, upper bound Poisson một phía 95% xấp xỉ 3/T, chỉ là ước tính với giả định độc lập/rate ổn định. Ví dụ 0 trên 30 camera-ngày vẫn chỉ hỗ trợ upper bound khoảng 0,1/ngày, không chứng minh zero error. Mưa/đêm tương quan đòi hỏi đánh giá phân tầng.

## 7. Phần cứng và hiệu năng kỳ vọng

**Các mức dưới đây là phạm vi ưu tiên thử nghiệm, không benchmark bảo đảm.** Workload: 1080p 25–30 FPS nguồn, detector 640 hoặc tương đương 10–15 FPS/camera, tracking, pose chọn lọc, raw compressed recording, không neural deblur/video overlay liên tục. Người quá nhỏ cần input/crop tăng tải.

| Nền tảng | Mục tiêu bắt đầu thử | Ưu/nhược chính |
|---|---|---|
| Intel N150, 16GB | 1 camera; mở rộng 2 sau đo | Giá/điện tốt, OpenVINO; chưa mặc định đủ 15 FPS + pose nhiều người |
| Jetson Orin Nano Super 8GB | 1–2 camera; thử 4 sau tối ưu | CUDA/TRT, decode; RAM chung CPU/GPU 8GB, không NVENC, devkit chỉ PoC |
| Orin NX16 edge computer | 2–4 camera; thử 4–8 workload nhẹ | RAM dư hơn, encode tùy cấu hình; phải audit SKU/carrier/tản nhiệt, không mặc định industrial temperature |
| x86 RTX5060 8GB + RAM32GB | 4 camera; thử 8 sau benchmark | Dễ phát triển/nâng cấp, NVDEC/NVENC; VRAM8GB có giới hạn batch/multi-model, điện và bảo trì cao hơn |
| Pi5 + Hailo8L/8 | 1–2 detector stream làm thử | Accelerator tiết kiệm; pose/export/host decode/compiler là rủi ro tích hợp |
| RK3588(S) 8GB | 1–2 stream nhẹ làm thử | Giá thấp tiềm năng; 6TOPS marketing không chứng minh capacity, RKNN operator/INT8 cần test |

Không so INT8 sparse TOPS với FP16/FP4 TFLOPS hoặc dùng phép chia TOPS để ra số camera. FPS detector tổng không bao gồm mặc định pose, decode, tracking, recording, upload và nhiệt tủ kín. [DeepStream benchmark](https://docs.nvidia.com/metropolis/deepstream/8.0/text/DS_Performance.html) đo pipeline có cấu hình cụ thể, tắt rendering/OSD/tiler; không áp số trên thiết bị khác cho YOLOX của dự án.

Ước lượng tải: `detector_FPS_required = camera_count × analysis_FPS × crops_per_frame`. 4×15×1 =60 full-frame inference/s; tile 4 ROI tăng thành 240 nếu chạy cả 4 mỗi frame. Pose tải phụ thuộc số người được kích hoạt: 20 ROI×10FPS =200 crop inference/s trong burst. Ngân sách không chỉ detector. CPU NMS/pose decode/Python copies có thể là bottleneck trước GPU.

Khi benchmark: đo detector-only và end-to-end riêng, FP16 trước rồi INT8 với representative day/night calibration; so event quality sau quantization. Đo 1/2/4/8 RTSP stream, burst người, network loss; RAM/VRAM, CPU/GPU, nhiệt, disk I/O, frame drops và P95/P99. Dành headroom mục tiêu khoảng 25–30%, không dùng 100% GPU làm capacity nghiệm thu.

[NVIDIA lifecycle](https://developer.nvidia.com/embedded/lifecycle) nêu devkit để phát triển/prototype, không production. Module Orin NX/Nano có thời hạn cung ứng công bố đến Jan2032; không đồng nghĩa bảo hành hệ thống đến thời điểm đó. Jetson Thor là phương án compute cao tham khảo, chưa có lợi ích/giá được chứng minh cho PoC này.

Camera AI all-in-one [Viettel VCAM-YITS-01](https://viettelhightech.com/en/category-detail/viettel-flagship-camera) đáng mời demo/RFQ: Qualcomm edge, ANPR/vehicle/violation và tích hợp radar; chưa có xác nhận công khai về fall/accident, khả năng nạp model riêng hay giá. So total integration cost, không chỉ giá box; không suy capture rõ 250km/h là chứng nhận đo tốc độ.

## 8. Quan sát giá lịch sử và BOM tham khảo

### 8.1 Giá quan sát ngày09–10-10-2026

Giá ở đây là số đã hiển thị trên trang/HTML/schema tại ngày quan sát, **không phải MSRP hoặc giá của bài review cũ**. Tồn kho/schema có thể sai; cần báo giá có hiệu lực, checkout, VAT, ship, SKU và bảo hành trước khi đặt. Không có quy đổi USD/CZK sang VND như tỷ giá live.

| SKU/nhà bán | Giá hiển thị | Điều kiện/mức xác minh |
|---|---:|---|
| Orin Nano Super 8GB Hshop | **15.228.000₫** | HTML visible price và JSON price trùng; trang BH1 năm, kèm PSU; VAT/stock checkout chưa xác nhận |
| Orin Nano Super Waveshare | **$634,99** | Trang bán/raw/schema, InStock; chưa ship/thuế nhập khẩu |
| Orin NX16 reComputer J4012 Seeed | **$1.749** | Trang bán hiển thị in stock; exact bundle/accessories cần RFQ |
| GMKtec G3 Plus N150 16GB/1TB | **11.060.000₫** | Biến thể có hàng được kiểm tra; không lấy barebones rẻ hết hàng làm giá bộ hoàn chỉnh |
| INNO3D RTX5060 Twin X2 8GB An Phát | **9.399.000₫** | Có VAT; stock “Liên hệ”; **chỉ bán cùng build PC**, không giá mua GPU rời độc lập |
| Colorful RTX5060 Battle AX DUO Phong Vũ | **13.990.000₫** | Đọc trực tiếp trang; stock/VAT/checkout chưa xác nhận |
| SSD Kingston NV3 1TB MemoryZone | **3.790.000₫** | HTML giá sale + schema; schema InStock; giá gạch 4.190.000 không dùng làm giá hiện tại |
| Hikvision DS-2CD2T43G2-4I camera4MP | **5.210.000₫** | Trang camerahikvision.vn ghi còn hàng; VAT chưa xác nhận; mô tả có mâu thuẫn IR30/80m, đối chiếu datasheet hãng |
| AI HAT+ 13TOPS PiVietnam | **2.400.000₫** | Chưa VAT, BH6 tháng; không gồm Pi5/nguồn/SSD; 26TOPS không cùng giá mặc định |
| Hailo8 M.2 Waveshare | **$179,99** | Schema InStock; host/carrier/ship/thuế không gồm |
| Orange Pi5 RK3588S8GB Techfun | **3.746 CZK** | Visible price; hết hàng; schema3808 khác, không dùng schema để thay giá visible |

Bổ sung lựa chọn giá thấp hơn đã đọc: [Hikvision DS-2CD1043G2-LIU](https://lapdatcameragiare.vn/san-pham/camera-ip-4mp-hikvision-ds-2cd1043g2-liu/) **1.263.000₫**, stock metadata; [trang hãng](https://www.hikvision.com/en/products/IP-Products/Network-Cameras/value-series/ds-2cd1043g2-liu-f-/) đã xác nhận WDR120dB, PoEmax6,5W và ProfileT; **4MP chỉ20FPS, 1080p25FPS ở50Hz**, nên không gán30FPS cho mọiSKU. Không coi chỉ sốWDR là chất lượng ban đêm tương đương camera cao cấp hoặc đủANPR; kiểm tra lens/firmware đúng đơn hàng. [UPS APC BX650LI-MS](https://www.f5c.vn/bo-luu-dien-line-interactive-apc-bx650li-ms-p18470.html) **998.000₫ chưa VAT**, 650VA/325W; runtime phải đo theo tải, không mặc định phù hợp x86 GPU. [TP-Link TL-SG1005P-PD](https://tapo.com.vn/san-pham/tp-link-tl-sg1005p-pd-5-port-gigabit-desktop-switch-with-1-port-poe-in-and-4-port-poe-out/) **790.000₫** là switch nhận nguồn PoE upstream, **không** thay switch AC trực tiếp nếu thiếu injector. [Palit Pandora Nano Super8GB](https://hugotech.vn/palit-pandora-nvidia-jetson-orin-nano-super-a003fv1p1/) **20.900.000₫**, schema stock và VAT excluded; vỏ máy không mặc nhiên đạt chuẩn ngoài trời. SKU Seeed J4012 trong bảng là **reComputer Industrial J4012**, trang quảng cáo100TOPS; không tự gán157TOPS Super nếu chưa xác minh firmware/carrier/thermal.

Không cộng GPU có điều kiện build PC với giá máy có sẵn nếu nhà bán không chấp nhận. Không dùng dev/test retailer domain hay listing 0₫/Liên hệ để suy thiết bị miễn phí. Chênh lệch giá là lý do cần ít nhất hai nhà bán và RFQ trong 7 ngày trước mua; stock đã xác nhận sẽ tốt hơn “có nút thêm giỏ”.

URL và trạng thái chi tiết trong `prices.csv`. Thiết bị công nghiệp, SSD endurance cao, UPS/PoE/chống sét/tủ chưa có đủ báo giá đúng cấu hình lắp; ngân sách dưới ghi rõ **allowance**, không giả vờ là giá đã kiểm chứng.

### 8.2 BOM tham khảo tại ngày nghiên cứu, không phải cấu hình đã chọn

Các tổng dưới là **dự toán số học hỗn hợp giá đọc được + allowance**, chưa final VAT/ship/công trình; chưa gồm nghiên cứu phần mềm/dữ liệu/backend. Không double-count SSD nếu bộ máy đã gồm 1TB.

**A — PoC 2 camera dùng Nano Super, trong phòng kỹ thuật có mái che**
- Devkit: 15,228 triệu (giá Hshop).
- SSD1TB: 3,790 triệu (MemoryZone; ví dụ giá consumer, không đề nghị mặc định production endurance).
- 2 camera: 2×5,210 =10,420 triệu.
- PoE switch allowance1,500; case/tản nhiệt bổ sung0,800; UPS1,500; dây/phụ kiện1,000 triệu.
- **Tổng: 34,238 triệu** trước chốt thuế/phí. Nếu camera đã có và phù hợp: **23,818 triệu**. Muốn ngoài trời thêm tủ/chống sét/ground/lắp đặt theo khảo sát; không biến devkit thành thiết bị công nghiệp chỉ bằng hộp kín.
- Mục tiêu bắt đầu 2×10FPS detector + tracking + pose chọn lọc, giữ clip gốc; 2×15FPS hoặc 4 camera chỉ sau benchmark.

**B — PoC tiết kiệm 1 camera Intel N150**
- Máy N15016GB/1TB: 11,060 triệu (giá biến thể có hàng, cần đối chiếu URL trong ledger).
- 1 camera:5,210; PoE injector allowance0,400; UPS1,500; dây/phụ kiện0,700 triệu.
- **Tổng:18,870 triệu**, camera có sẵn:13,660 triệu. Không cộng SSD1TB thêm.
- Mục tiêu 1×10FPS với detector nhẹ + pose conditional; chưa hứa đạt1×15FPS. Dùng để kiểm tra OpenVINO, không chọn cho 4 camera chỉ vì CPU có iGPU.

**C — Trạm kỹ thuật 4 camera x86 RTX5060**
- GPU dùng giá Phong Vũ tham chiếu:13,990 triệu.
- CPU/main/RAM32GB/PSU/case allowance12,000 triệu, **không gồm SSD/GPU**.
- SSD1TB3,790; 4camera20,840; PoE allowance2,000; UPS2,500; dây/phụ kiện1,500 triệu.
- **Tổng:56,620 triệu**; camera có sẵn:35,780 triệu. Nếu builder chấp nhận GPU An Phát cùng cấu hình, giá GPU9,399 giảm tổng lý thuyết4,591 triệu; cần báo giá cả build và stock, không coi giảm này đã mua được.
- Mục tiêu bắt đầu4×15FPS, burst pose có giới hạn; 8camera phải đo và có thể cần GPU nhiều VRAM hơn.

**D — Edge production Orin NX16**
- Giá máy Seeed $1.749 là tham chiếu thiết bị, không phải tổng chi phí nhập về Việt Nam hay chứng nhận công nghiệp của mọi bundle.
- RFQ local: edge computer/cooling/SSD/endurance/nguồn DC/watchdog; camera; PoE; UPS; tủ phù hợp; chống sét/earth; công lắp; nghiệm thu 24/7 và bảo hành.
- Không chốt giá landed VND khi chưa có tỷ giá, thuế, vận chuyển và quote. Nếu nhà cung cấp không công bố giá, ghi cần RFQ thay vì đưa một số bịa.

Pi5+Hailo phải cộng host/PSU/cooling/storage/carrier; HAT13TOPS2,4 triệu không có nghĩa edge hoàn chỉnh2,4 triệu. RK giá hết hàng chỉ là market reference, không phương án procurement sẵn.

### 8.3 TCO và backend

TCO3 năm = CAPEX + điện + mạng + lưu trữ + phần mềm/license + nhân công review + bảo trì + linh kiện dự phòng + vệ sinh/hiệu chuẩn + phát triển/dữ liệu/labeling. Với giả định điện3.000₫/kWh **không phải biểu giá live**, 50W tổng site24/7 ≈438kWh/năm ≈1,314triệu/năm; 150W≈3,942triệu/năm. Phải đo tại ổ điện gồm camera/PoE/UPS, không dùng TDPCPU hay power modeJetson làm điện cả site.

Backend hiện hành là FastAPI/MongoDB và filesystem evidence cho lab. Chưa chốt vCPU/RAM từ benchmark; production DB/storage/HA theo ADR riêng trước pilot. Server capacity phụ thuộc số event/ảnh/clip/concurrent review, không tương ứng FPS edge. Nếu 100event/ngày tổng hệ thống×15MB×30ngày≈45GB clip/tháng trước replica/backup; 100event/ngày/camera với 100camera tăng100 lần. Lưu metadata dài hơn clip theo chính sách. Chưa đủ yêu cầu để báo một giá cloud monthly chắc chắn.

## 9. Bảo mật, pháp lý và vận hành

- Mạng camera VLAN riêng, chặn Internet không cần thiết, tắt P2P/cloud vendor nếu không có cơ sở; mTLS/TLS edge–server, unique credentials, rotation, RBAC và audit.
- Timestamp UTC/NTP; giữ monotonic khi clock điều chỉnh. Nếu cần đồng bộ đèn/radar chính xác cao, đo sai số và dùng cơ chế sync phù hợp; không mặc định NTP đủ mọi chứng cứ.
- Image/plate/person crops có thể là dữ liệu cá nhân; metadata location/time/track cũng có rủi ro. Không thu face recognition mặc định. Thiết kế retention, quyền xem raw, blur bản chia sẻ, log export, encryption at rest và minimization.
- [Luật Bảo vệ dữ liệu cá nhân91/2025/QH15](https://vanban.chinhphu.vn/?docid=214590&pageid=27160&typegroupid=3), hiệu lực01-01-2026, cần được đối chiếu cùng văn bản hướng dẫn hiện hành và bối cảnh chủ thể triển khai. Đây không phải tư vấn pháp lý hoàn chỉnh; không suy mọi camera công cộng dùng cùng consent/legal basis.
- Hồ sơ xử phạt phải đối chiếu luật/quy trình thẩm quyền, xác định phương tiện/người/đèn/địa điểm và chất lượng evidence; AI alert không tự trở thành hồ sơ hợp lệ.
- Theo dõi camera FPS/PTS, blur/occlusion/lệch góc, reconnect count, CPU/GPU/RAM, nhiệt, disk free/SMART, outbox age, delivery lag và checksum errors. Báo riêng “mất khả năng quan sát”, không im lặng coi không có sự kiện.
- OTA ký số, staged rollout, version pin, rollback model/calibration/config; watchdog và kiểm tra khởi động lại. Model update có thể thay calibration preprocessing; kiểm tra regression trước fleet rollout.
- Tủ kín ngoài trời có thể quá nhiệt dù môi trường chưa vượt spec module. Thiết kế thermal/moisture/condensation, chống sét đường nguồn/Ethernet, tiếp đất và dự phòng theo survey; PoE budget đủ camera IRban đêm và derating.
- Quy trình trực: receive→review→ACK→escalate→close; cấp bách khi người nằm trên làn xe, ưu tiên hỗ trợ hơn gán nguyên nhân. Đo thời gian ACK/dispatch, không chỉ inference.

## 10. Lộ trình theo gate đã chốt

| Gate | Kết quả cần | Giới hạn |
|---|---|---|
| G0 | Facts, ODD/samples, contract và preliminary targets | Board chưa chọn không chặn ONNX lab |
| G1 | File+RTSP→native detection/tracking→event/clip→server/review; durable retry/crash | Chưa chứng minh person-down quality hoặc target capacity |
| G2 | Native pose, fast/slow/persistent lying, hard negatives, negative audit | Thiếu onset/pose phải unknown, không negative |
| G3 | Conformance + actual-target capacity/thermal/record/upload | RKNN conversion chỉ nếu chọn RK3588; ONNX vẫn phải target tests |
| G4a | Reliability/trust/privacy/rollout/restore/operator readiness | Vehicle/notification chỉ theo scope bật; demo không thay UI vận hành |
| G4b | Calibration/motion/vehicle quality khi bật | Không chặn person-down nếu vehicle deferred |
| G5 | Field quality/SLO/review load và quyết định scale | Không ký từ TOPS hoặc số ngày chạy chưa đủ mẫu |

[Plan](../docs/architecture/implementation-plan.md) giữ phase/owner; [tracker](../.scratch/system-build-slices/PRD.md) giữ dependencies/Execution. Không duy trì timeline tuần riêng trong research. Procurement sau workload/BOM/thermal/rights và quote đúng SKU; không lấy các BOM lịch sử ở mục8 làm đơn hàng mặc định.

## 11. Điểm chưa được xác minh và yêu cầu RFQ

1. Commercial clearance của từng checkpoint và nguồn dữ liệu; registry phải đóng trước phát hành.
2. FPS toàn pipeline trên thiết bị thực tế, pose burst và quality sauINT8; mọi capacity ở đây là mục tiêu thử.
3. VAT/stock/checkout/ship của nhiều retailer; giá đã đọc không phải xác nhận đơn hàng.
4. Quote đúng spec của UPS/PoE/tủ/chống sét/SSDproduction và công lắp; allowance không thay khảo sát.
5. Khả năng nạp model custom/API/SDK của cameraAIall-in-one; cần demo và hợp đồng.
6. Khả năng phát hiện tai nạn hiếm/ngã thực ngoài trời; chưa có tập local đủ lớn được nghiệm thu.
7. Yêu cầu pháp lý cụ thể cho chứng cứ tốc độ/vi phạm và processing dữ liệu của đơn vị triển khai.

Tài liệu hỗ trợ: `outline.yaml`, `fields.yaml`, `prices.csv`, `sources.md`. Không coi tài liệu này là chứng nhận an toàn y tế, metrology hay hiệu năng thiết bị.


## 12. Đồng bộ thiết kế và câu hỏi nghiên cứu còn giá trị

| Đã chốt | Hệ quả / phần còn cần đo |
|---|---|
| Native C++ detector/tracker P1, pose P2; Python domain/control và oracle | Một PerceptionPipeline metadata-only; cùng consumer conformance, không gọi lại tracker từ late pose |
| ONNX baseline, RKNN khi chọn target | SDK/artifact/layout/precision/decode/lifetime thật phải kiểm; zero-copy chỉ sau profiling |
| Person-down trước, camera cố định/ROI | Pixel-on-target, pose coverage, ID switches và ODD ngày/đêm/mưa vẫn cần data thật |
| Raw recorder sở hữu upstream độc lập analytics | Camera sessions/main-sub/clock mapping cần probe; stream ADR sau bằng chứng |
| Ring/anchor/request/receipt và trạng thái evidence tách biệt | Đo ring margin, full-disk/ENOSPC/power-cut, B/U/G và backlog drain; WAL không thay backup |
| Full snapshot/origin, review freshness và downstream eligibility | Out-of-order/conflict, partial-uploaded, correction/re-review và no-auto-backfill có contract tests |
| FastAPI/MongoDB và demo nội bộ | Exact-version transaction tests; lab one-member không HA; production infra/restore/privacy gate riêng |

Câu hỏi mở: exact checkpoints/quyền dữ liệu, dataset theo site, conversion target khi được chọn, optical quality và timestamp mapping, capacity/thermal/storage endurance, human review load và TCO thực. Chỉ mở alternative model/backend khi kết quả cho thấy baseline không đạt; không xây nhiều framework đồng thời.

Các hợp đồng và trạng thái chuẩn nằm ở [contracts](../docs/architecture/contracts.md), không sao chép chi tiết ở research. Nghiên cứu không xác nhận legal/commercial clearance hoặc hiệu năng chỉ từ nguồn công khai.

## 13. Lịch sử cập nhật

- 09-10-2026: nghiên cứu phần cứng/model/data, 16 giá bán và BOM tham chiếu.
- 10-10-2026: đồng bộ camera budget/H1c/IMX219/native analytics; portable modules và tham chiếu kiến trúc; đọc lại4giá Tapo. Các16giá cũ/BOM không được refresh, H1c/RPi5/OrangePi5 Việt Nam chưa có quote mới.

- 11-10-2026: đồng bộ thiết kế/contracts/target gates và bỏ PostgreSQL, native-after-profiling, MQTT ingress, ngưỡng/timeline PoC cũ khỏi định hướng hiện hành. Giá/nguồn thị trường giữ ngày quan sát, không refresh.

- 15-10-2026: đối chiếu implementation, log thử nghiệm/review và số đo replay; bổ sung §14, cập nhật outline/fields/sources. Phản biện native-first, pose verification, FPS và sizing evidence. Không đổi ADR, ticket Execution, giá hoặc runtime.

## 14. Cập nhật theo implementation và thử nghiệm 15-10-2026

### 14.1 Phạm vi và độ tin cậy

Snapshot nền: `6fff369f4c30dd6faff0150b660cf5e065207daa`. Đã dùng CodeGraph để xác định đường chạy, đọc các hàm pipeline/incident liên quan, log triển khai và artifact replay. File chưa tracked trong working tree không tự trở thành bằng chứng release. Ngày báo cáo theo môi trường; ngày truy cập web không chứng minh nguồn được xuất bản đúng ngày đó.

Phân loại: **mã hiện có** xác nhận cấu trúc/hành vi dự kiến; **log test** là kết quả lịch sử với giới hạn ghi trong log; **số đo artifact** chỉ áp dụng workload/snapshot đã đo; **nghiệm thu** cần report và sign-off theo gate. Lượt cập nhật này không chạy lại suite, camera, browser hay board.

Tracker hiện có độ lệch nội bộ: phần “Cách chọn việc” nói #08 chưa bắt đầu nhưng bảng ghi done; #13 mang tên native nhưng implementation được đối chiếu là Python. Vì vậy không dùng số ticket done để suy native parity/G1 đã đạt. Cần chủ sở hữu đồng bộ acceptance/evidence trong tracker; research không tự đổi Execution.

### 14.2 Những gì đã có và phần chưa được chứng minh

| Thành phần | Hiện trạng được đối chiếu | Bằng chứng và giới hạn |
|---|---|---|
| Detector | YOLOX-Tiny ONNX, runtime/model pins, preprocess raw BGR, inclusive-pixel per-class NMS | [Oracle #11](../docs/logs/2026-10-12-ticket-11.md); independent goldens là parity fixtures, không phải event recall |
| Tracking | Python two-stage score association, tentative mặc định 2 hits, dự đoán vận tốc hằng từ observation history | [Triển khai tracker](../docs/logs/2026-10-15-impl-tracker-detector.md) và `apps/edge/tracker.py`; chưa phải full reference ByteTrack/Kalman, chưa có ID-switch report ngoài đường |
| Pose | RTMPose estimator, cache frame, scheduler nhiều nhánh, deadline/terminal outcomes; tùy chọn qua PoseManager | [Pose fixes](../docs/logs/2026-10-15-impl-pose.md); `pipeline.py` lưu outcomes vào observation nhưng `IncidentEngine.process_tracks(tracks, timestamp)` không nhận keypoints. Chưa có pose-based event verifier |
| Person-down | Rule person-only, ROI, bbox aspect ratio, vận tốc pixel, persistence/cooldown; giữ onset khi người còn chuyển động | [Incident fixes](../docs/logs/2026-10-15-impl-incident-pipeline.md), `apps/edge/incident.py`; chưa xác nhận chất lượng ngã nhanh/chậm/che khuất theo site |
| Live source | Runner OpenCV và recorder FFmpeg, reconnect/backoff, đồng bộ session, observation gap; có tùy chọn drain frames | [RTSP fixes](../docs/logs/2026-10-15-impl-rtsp-live.md); constructor `drain_frames=False`, không mặc định mọi entrypoint đã bật. Mock/fake capture không chứng minh latency camera thật |
| Ring/evidence/quota | Stream-copy segments, pin/finalize/receipt, reconcile, bảo vệ unACK và state reserve, cleanup ACK/released | [Storage fixes](../docs/logs/2026-10-15-impl-storage.md), [#51 hardening](../docs/logs/2026-10-13-ticket-51-hardening.md); race finalize/prune/release chưa có stress đa luồng thực tế |
| Delivery/backend | SQLite outbox; FastAPI/MongoDB revisions/review/dataset; evidence streaming, cursor pagination | [Server/outbox fixes](../docs/logs/2026-10-15-impl-server-outbox.md); một-member MongoDB không HA, chưa chứng minh WAN autonomy/restore/pilot |
| ODD | Mean brightness/contrast thành trạng thái chất lượng; ROI có qua constructor | `evaluate_odd` trong `apps/edge/pipeline.py`; heuristic này không chứng minh ODD supported, blur/freeze/occlusion monitoring hoặc signed site activation đầy đủ |
| Native/target | Native C++ vẫn là hướng thiết kế P1/P2; RKNN có điều kiện theo target | Chưa có bằng chứng C++ detector/tracker/pose hoặc target capacity trong phạm vi đối chiếu. Có Python gọi thư viện native không tương đương hoàn thành native boundary |

Các log triển khai là lịch sử: thay đổi NMS/scale trong log tracker đã được **hoàn tác** ở [dispatch summary](../docs/logs/2026-10-15-implement-dispatch-summary.md). Không lấy một log trung gian làm trạng thái cuối. Cùng summary ghi **409 passed**, gồm 11 regression mới sau sửa; đây là kết quả ghi lại, không phải suite vừa chạy trong lượt research. [Code-review sau sửa](../docs/logs/2026-10-15-code-review-of-implementation.md) còn giới hạn camera thật và concurrency.

### 14.3 Kết quả thử nghiệm có thể dùng

| Evidence | Kết quả ghi nhận | Kết luận được phép |
|---|---|---|
| Oracle #11, pinned CPU runtime | 85/85 tại mốc 12-10; ảnh original 13 detections/10 person, crop 9/7, negative 0 | Pre/postprocess và artifact parity trên fixture; không suy recall/FP/pose accuracy |
| Suite sau sửa 15-10 | Log ghi 409 passed | Regression phần mềm trong môi trường log; không tự đạt G1/G2/G3 hoặc mất điện an toàn |
| Replay synthetic 320×180 H.264, 30 FPS nguồn, fast mode, 10/100/1.000/10.000 giây | Đọc lại12 record trong `results-final.jsonl`:12/12 callback trước EOF; first callback0,079–0,105s; Python RSS21.320–22.316KiB; simultaneous Python+ffprobe RSS71.996–74.712KiB | Timestamp replay incremental trong envelope này; sampled RSS không bảo đảm peak; không phải decode+detector+pose benchmark |
| RTSP reconnect/pose scheduling/quota faults | Có tests dùng fake/mock và regression trong log | Chứng minh case phần mềm cụ thể; chưa đo reconnect camera/codec change, thermal, real power-cut hoặc WAN24h |

Artifact replay và [script tái lập](../.scratch/replay-measurements/reproduce.sh) đang ở thư mục chưa tracked. Snapshot recorder trong JSONL khác mã hiện tại; không gán số đo này cho HEAD. Script ghi đè snapshot/results khi chạy, nên phải lưu bản cũ trước tái lập. Không so throughput từ callback timestamp với inference FPS. Hash trong record nhận diện snapshot, không thay manifest hash fixture/model/config đầy đủ. Bước tiếp theo là đóng gói evidence cần giữ bằng version/manifest; không tự thêm video lớn vào Git.

### 14.4 Phản biện và quyết định kỹ thuật đề xuất

Các dòng **đề xuất** dưới đây chưa được accepted; chúng không sửa Q1–Q19/ADR. Nếu thay scope hoặc gate thì phải cập nhật plan/contracts/ticket tương ứng trong một quyết định riêng.

| Vấn đề | Nhận định và khuyến nghị | Điều kiện quyết định |
|---|---|---|
| Native C++ P1/P2 đã chốt | **Đề xuất mở lại thứ tự đầu tư**, không bỏ semantic boundary. ORT/FFmpeg đã làm phần nặng ở native; viết lại orchestration khi chưa profile có thể tăng chi phí mà không giảm frame age | Đo stage time/queue age dưới recording+upload+pose. Chỉ chuyển hotspot khi nó gây vi phạm SLO và thử nghiệm native cải thiện đủ để bù maintenance; owner duyệt mức cải thiện trước A/B. [ORT profiling](https://onnxruntime.ai/docs/performance/tune-performance/profiling-tools.html) |
| 3 FPS live so với mục tiêu nghiên cứu 10–15 FPS | Cả hai đều chưa có quality acceptance. 3 FPS có thể bỏ diễn biến onset; tăng toàn pipeline lên 15 FPS có thể tăng queue age và tải pose | Replay cùng clip ở 3/5/10/15 FPS, đo event recall, onset error, FP/camera-hour, track fragmentation và P95 frame age; chọn mức thấp nhất đạt mục tiêu đã duyệt |
| Pose hiện có nhưng chưa quyết định event | Ưu tiên chứng minh pose tạo lợi ích trước thêm temporal classifier. So rule-only với pose verifier cùng tập; pose missing phải có trạng thái coverage rõ | Report gain về recall/FP, coverage và latency; không biến thiếu keypoints thành “an toàn”. Giữ đường persistent-lying khi onset không quan sát được |
| Pixel velocity/aspect ratio dùng chung site | 15 px/s, aspect ratio 1.2 và dwell 3s là heuristic lab, không quy đổi vật lý hoặc probability. Detector score đang được đưa thành incident confidence; không diễn giải như xác suất ngã | A/B motion chuẩn hóa theo chiều cao bbox và camera/site; held-out test. Chỉ thêm homography khi use case cần, không giả định khớp nằm trên mặt đường |
| ODD “normal” | Brightness/contrast bình thường không chứng minh đủ pixel người, không che khuất hoặc không freeze | Tách image-quality signal khỏi supported-ODD acceptance; version policy/site và kiểm tra blur/freeze/ROI invalid. ROI chân bbox có thể loại nhầm người đang nằm sát biên; thử polygon overlap/center trên hard negatives trước đổi rule |
| Latest-frame/drain | Hợp lý cho live latency nhưng bỏ frame làm giảm temporal coverage; default flag chưa đủ chứng minh entrypoint áp dụng đúng | Đo frame age, dropped coverage và continuity; reset certainty qua gap. Raw recorder tiếp tục độc lập; không dùng latest-only cho deterministic replay |
| NMS/scale parity | Giữ golden-v1 hiện tại; “sửa toán học” không đủ lý do phá parity | Khi có lỗi chất lượng đo được: version model/postprocess/golden mới, ghi migration và event regression; không sửa golden chỉ để test xanh |
| RKNN/INT8/board | Chưa nên chọn từ TOPS hoặc giá box. Ưu tiên workload thật và phương án ONNX hiện có | Pin toolkit/runtime/driver/artifact, conversion parity và event quality ngày/đêm, record+upload+pose soak trên board. [RKNN releases](https://github.com/airockchip/rknn-toolkit2/releases) là khả năng SDK, không bằng chứng dự án |
| MongoDB | Giữ lựa chọn đã accepted; đổi database lúc này chưa có bottleneck/TCO report hỗ trợ | Đo transaction latency/outage/restore trên version đang pin. One-member lab có transaction không đồng nghĩa central HA |

### 14.5 Tối ưu evidence và độ bền cần ưu tiên

**Giữ stream-copy raw.** FFmpeg segment muxer cắt theo keyframe nên segment target2s không bảo đảm mọi segment đúng2s; phải đo GOP, actual ranges và gap bằng PTS. Không chuyển sang re-encode chỉ để cửa sổ đẹp hơn nếu chưa có yêu cầu; bản derived cần provenance riêng. [FFmpeg segment documentation](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment)

**Trần upload100 MiB cần sizing và hành vi từ chối rõ.** 30s clip đạt100 MiB ở bitrate trung bình khoảng28 Mb/s (`100×2^20×8/30`), chưa container/GOP margin. Clip dài do segment/keyframe có thể chạm trần sớm hơn. Giữ giới hạn bảo vệ RAM/disk, nhưng xác định max artifact theo VBR/GOP thực, test413 ở edge, bảo toàn local pin và hiển thị operational fault thay vì retry mù. ACK metadata không giải phóng clip. Đo B/U/G và drain backlog khi upload cạnh tranh recording; outage24h vẫn là mục tiêu chưa nghiệm thu.

**SQLite cần xác minh bản vá runtime.** Probe read-only trong lượt này: `.venv-oracle/bin/python -c 'import sqlite3; print(sqlite3.sqlite_version)'` → **3.45.1**. SQLite công bố WAL-reset race khi nhiều connection write/checkpoint đồng thời, sửa ở3.51.3 và backport3.44.6/3.50.7. Số version chưa xác nhận distro có backport; chưa quan sát corruption tại dự án. Đề xuất platform kiểm tra package patch/source ID rồi pin bản đã sửa và chạy recovery/concurrency trước pilot; không tự nâng dependency trong lượt docs. [SQLite WAL §11](https://www.sqlite.org/wal.html#walresetbug)

**Không giảm durability để lấy benchmark đẹp.** Giữ bảo vệ journal/evidence; đo fsync/checkpoint/lock contention, peak WAL, temp+pin overlap và time-to-full trước tuning. Race finalize/prune/release cần stress đa luồng; process kill không thay power-cut/PLP/endurance. WAL, filesystem clip và remote receipt có các crash window riêng, cần reconcile/idempotency xuyên suốt.

### 14.6 Thứ tự thử nghiệm và đầu ra cần có

Owner là vai trò đề xuất, người thực hiện/sign-off còn pending. Bảng này là chương trình nghiên cứu bổ sung vào tickets hiện có, không là backlog Execution thứ hai.

| Ưu tiên / tham chiếu | Owner, dependency | Đầu ra và acceptance |
|---|---|---|
| A. Đóng snapshot/evidence; #02/#19 | QA + edge; commit/config/model/fixture pins | Manifest môi trường, lệnh/run ID và evidence links; xử lý lệch tracker/native naming. Không tự ký G1 từ log409 tests |
| B. Camera correlation/latency; #15/#16/#17/#19 | Edge + QA; camera/firmware/session facts | RTSP thật record+analytics; disconnect/reconnect, frame age và anchor↔PTS, missing/partial; Q16 commit→dashboard đo riêng với clock uncertainty |
| C. Event-quality A/B; #21–#28 | ML + product; ODD/label/split và quyền data | Rule-only/pose, FPS sweep, lying/onset, người nhỏ/đêm/che khuất/hard negatives; event recall/FP, uncertainty và review minutes. Threshold/sign-off pending |
| D. Storage/transfer/recovery; #18/#31/#36/#37/#43 | Platform + backend + QA; bitrate/event burst/quota | SQLite patch verification,413, pin race, crash windows, WAN resume B/U/G, disk pressure; không mất protected data/ACK giả. Power-cut chỉ sau device/recovery approval |
| E. Chọn compute/native; #10/#12/#29–#31 | Edge + ML; kết quả B/C/D | Stage profile, bottleneck, điện/thermal/TCO; A/B native/provider/board cần cùng input và quality. G3 trên target thật, không kế thừa x86 replay |

Nguồn ngoài bổ sung [ORT threading](https://onnxruntime.ai/docs/performance/tune-performance/threading.html) hỗ trợ thử thread-pool contention; không đổi thread count theo số core một cách máy móc. [OmniFall](https://arxiv.org/abs/2505.19889) củng cố nhu cầu đánh giá staged-to-wild, không thay dataset camera đường phố địa phương. [RTMO](https://arxiv.org/abs/2312.07526) chỉ là đối chứng nếu per-person pose burst trở thành bottleneck; chưa có lý do cài thêm framework bây giờ. Nguồn và tiêu chí chi tiết ở [sources](sources.md), [fields](fields.yaml).
