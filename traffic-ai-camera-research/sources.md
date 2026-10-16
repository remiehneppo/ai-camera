# Nguồn nghiên cứu

## Bổ sung implementation/thử nghiệm — 15-10-2026

Mốc theo môi trường. Nguồn chính thức được truy xuất cho cập nhật kỹ thuật; không refresh retailer, hardware specs, giấy phép thương mại hoặc pháp lý. Ngày truy cập không là ngày xuất bản. Nguồn mô tả khả năng công cụ/paper, không chứng minh dự án đã đạt chất lượng/capacity.

| Nguồn | Dùng cho nhận định | Giới hạn |
|---|---|---|
| [ORT profiling](https://onnxruntime.ai/docs/performance/tune-performance/profiling-tools.html), [thread management](https://onnxruntime.ai/docs/performance/tune-performance/threading.html) | Profile operator/stage/thread contention trước quyết định native/provider | Tuning vẫn phải đo trên workload dự án; không suy Python rewrite sẽ tăng FPS |
| [FFmpeg segment muxer](https://ffmpeg.org/ffmpeg-formats.html#segment_002c-stream_005fsegment_002c-ssegment) | Keyframe/segment duration và actual evidence ranges | Không bảo đảm source PTS mapping hoặc recorder isolation đã pass |
| [SQLite WAL §11](https://www.sqlite.org/wal.html#walresetbug), [release history](https://www.sqlite.org/changes.html) | WAL-reset race và bản sửa3.51.3/backports3.44.6/3.50.7 | Lab probe3.45.1 chưa xác nhận distro backport, không là quan sát corruption |
| [MMPose deployment](https://github.com/open-mmlab/mmpose/blob/main/docs/en/user_guides/how_to_deploy.md) | Pin preprocess/export/backend parity của pose | Cấu hình backend có sẵn không chứng minh checkpoint/board đã được dự án test |
| [RKNN-Toolkit2 releases](https://github.com/airockchip/rknn-toolkit2/releases) | Pin toolkit/runtime/operator/precision khi chọn RKNN | Không lấy release mới nhất làm tổ hợp tương thích mặc định |
| [OmniFall paper](https://arxiv.org/abs/2505.19889) (2025) | Nhu cầu staged-to-wild/domain-shift evaluation | Không thay held-out road-camera data hoặc clearance từng video |
| [RTMO paper](https://arxiv.org/abs/2312.07526) (2023, CVPR2024) | Đối chứng one-stage pose khi per-person burst là bottleneck | Chỉ nghiên cứu có điều kiện, không mở thêm framework trong baseline |

Bằng chứng nội bộ chính: [oracle #11](../docs/logs/2026-10-12-ticket-11.md), [dispatch15-10](../docs/logs/2026-10-15-implement-dispatch-summary.md), [review sau sửa](../docs/logs/2026-10-15-code-review-of-implementation.md), [replay artifact](../.scratch/replay-measurements/results-final.jsonl). Artifact replay hiện chưa tracked; log409 tests là lịch sử, không phải chạy lại trong lượt research. Chi tiết phân loại bằng chứng và quyết định đề xuất ở [report §14](report.md#14-cập-nhật-theo-implementation-và-thử-nghiệm-15-10-2026).

## Nguồn lịch sử 09–11-10-2026

Ngày hệ thống khi nghiên cứu: **2026-10-09**. Trang web được đọc trong phiên; không phải ảnh chụp lịch sử và không đảm bảo thời điểm cập nhật website trùng đồng hồ hệ thống. Giá công khai không phải báo giá giao hàng đã xác nhận. Các nguồn dưới đây hỗ trợ từng khẳng định cụ thể; không phải mọi quyền weights/dataset đã được xác minh.

Lượt đồng bộ thiết kế 11-10-2026 không truy xuất lại các nguồn dưới đây. Đặc tả hiện hành ở [docs index](../docs/README.md); nguồn này giữ ngày quan sát và giới hạn xác minh, không là quyết định triển khai.

## Camera, phần cứng, runtime
- NVIDIA lifecycle, devkit không dành cho production: https://developer.nvidia.com/embedded/lifecycle
- Orin Nano không có NVENC: https://docs.nvidia.com/jetson/archives/r35.6.1/DeveloperGuide/SD/Multimedia/SoftwareEncodeInOrinNano.html
- DeepStream benchmark: https://docs.nvidia.com/metropolis/deepstream/8.0/text/DS_Performance.html
- Axis WDR, exposure và artifact: https://www.axis.com/en-nz/solutions/wide-dynamic-range-wdr
- ONVIF T: https://www.onvif.org/profiles/profile-t/
- ONVIF M: https://www.onvif.org/profiles/profile-m/
- Viettel ITS camera: https://viettelhightech.com/en/category-detail/viettel-flagship-camera
- Hailo model zoo: https://github.com/hailo-ai/hailo_model_zoo

## Code và giấy phép
- YOLOX Apache-2.0: https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE
- ByteTrack MIT: https://github.com/FoundationVision/ByteTrack/blob/main/LICENSE
- MMDetection: https://github.com/open-mmlab/mmdetection/blob/main/LICENSE
- RTMDet: https://github.com/open-mmlab/mmdetection/tree/main/configs/rtmdet
- MMPose: https://github.com/open-mmlab/mmpose/blob/main/LICENSE
- RTMPose: https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose
- MMAction2: https://github.com/open-mmlab/mmaction2/blob/main/LICENSE
- PaddleDetection: https://github.com/PaddlePaddle/PaddleDetection/blob/develop/LICENSE
- RT-DETR: https://github.com/lyuwenyu/RT-DETR
- RT-DETR Apache: https://raw.githubusercontent.com/lyuwenyu/RT-DETR/main/LICENSE
- Ultralytics AGPL/Enterprise: https://www.ultralytics.com/license
- Supervision MIT: https://github.com/roboflow/supervision/blob/main/LICENSE.md
- ONNX Runtime MIT: https://github.com/microsoft/onnxruntime/blob/main/LICENSE
- OpenVINO Apache: https://github.com/openvinotoolkit/openvino/blob/master/LICENSE
- TensorRT SDK agreement: https://docs.nvidia.com/deeplearning/tensorrt/latest/reference/sla.html
- DeepStream legal: https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Legal.html
- GStreamer licensing: https://gstreamer.freedesktop.org/documentation/application-development/appendix/licensing.html
- FFmpeg licensing: https://ffmpeg.org/legal.html
- MediaMTX license/dependency: https://mediamtx.org/docs/misc/license
- MediaMTX recording/proxy: https://github.com/bluenviron/mediamtx

## Dataset và nghiên cứu
- DoTA paper: https://arxiv.org/abs/2004.03044
- DoTA repo: https://github.com/MoonBlvd/Detection-of-Traffic-Anomaly
- DAD: https://github.com/smallcorgi/Anticipating-Accidents
- TAD surveillance: https://github.com/UnicomAI/UnicomBenchmark/tree/main/TADBench
- UR Fall, CC BY-NC-SA 4.0: http://fenix.ur.edu.pl/~mkepski/ds/uf.html
- UP-Fall: https://sites.google.com/up.edu.mx/har-up/
- UP-Fall article: https://doi.org/10.3390/s19091988
- Le2i original (không truy cập thành công trong phiên): https://le2i.cnrs.fr/Fall-detection-Dataset?lang=en
- OmniFall: https://arxiv.org/abs/2505.19889
- OmniFall data: https://huggingface.co/datasets/simplexsigil2/omnifall

## Pháp lý Việt Nam
- Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15: https://vanban.chinhphu.vn/?docid=214590&pageid=27160&typegroupid=3
- Khai thác dữ liệu phục vụ phát hiện vi phạm TTATGT: https://xaydungchinhsach.chinhphu.vn/tu-1-1-2025-khai-thac-du-lieu-tu-thiet-bi-giam-sat-hanh-trinh-de-phat-hien-vi-pham-ve-ttatgt-duong-bo-119241221083121091.htm

## Giá bán
Xem prices.csv để đối chiếu SKU, số tiền và mức độ xác minh. Giá đã đọc trực tiếp từ nội dung trang hoặc HTML/schema trong phiên, không lấy giá MSRP làm giá bán.


## Bổ sung từ các quyết định camera và kiến trúc (10-10-2026)

- RTSP/ONVIF Tapo, Camera Account và hạn chế streams: https://www.tp-link.com/vn/support/faq/2680/
- H1c OEM specs (không công bố RTSP trên trang đã đọc): https://www.ezviz.com/product/h1c/47789
- H1c compatibility bên thứ ba, RTSP /11 và /channel1: https://www.ispyconnect.com/camera/ezviz
- Hikvision native events/API và optical specs: https://www.hikvision.com/ph/products/IP-Products/Network-Cameras/Pro-Series-EasyIP-/ds-2cd2t43g2-2i-4i/?subName=DS-2CD2T43G2-4I
- IMX219-160 sensor/FOV/aperture/IR variants: https://www.waveshare.com/product/ai/cameras/single-cameras/imx219-160-camera.htm
- Hshop module đúng SKU: https://hshop.vn/imx219-camera-module-160-degree-for-jetson-nano-and-raspberry-pi
- Camera budget: URL và4giá đã đọc lại10-10-2026 trong prices.csv. Không refresh16giá cũ; không có giá H1c mới.
- [Kiến trúc chi tiết](../docs/architecture/system-architecture.md): quyết định thiết kế, không nguồn chứng minh SDK/FPS đã chạy.

Không suy compatibility list thành mọi firmware hoặc hỗ trợONVIF; không suy hãng công bố AIevents thành dense tracking metadata. Giá retail và nguồn giao thức hãng là hai loại bằng chứng riêng.
