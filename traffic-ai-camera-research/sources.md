# Nguồn nghiên cứu

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
