# Nghiên cứu AI Camera giao thông edge

## Tài liệu

- [report.md §14](report.md#14-cập-nhật-theo-implementation-và-thử-nghiệm-15-10-2026): hiện trạng implementation/thử nghiệm đến15-10-2026, phản biện lựa chọn kỹ thuật và thứ tự nghiên cứu tiếp theo. Các phần1–13 giữ nghiên cứu nền/phần cứng/data/chi phí và lịch sử quyết định.
- [prices.csv](prices.csv): 20 quan sát giá, đúng SKU/URL/điều kiện, không phải báo giá giao hàng.
- [sources.md](sources.md): nguồn hãng, retail, nghiên cứu và compatibility bên thứ ba.
- [outline.yaml](outline.yaml), [fields.yaml](fields.yaml): đối tượng và tiêu chí nghiên cứu.
- [Kiến trúc hệ thống](../docs/architecture/system-architecture.md): modules/contracts/pipelines/source tree đề xuất.

## Ngày và mức độ bằng chứng

Nghiên cứu ban đầu09-10-2026; đồng bộ thiết kế11-10 và implementation15-10 theo đồng hồ môi trường. Lượt15-10 đối chiếu mã/log và artifact replay, bổ sung nguồn chính thức; không chạy lại suite/benchmark. Log ghi409 tests passed, replay có số đo synthetic; chưa có event-quality acceptance, FPS toàn pipeline hay target-board benchmark. Bốn giá Tapo giữ ngày10-10,16giá còn lại ngày09-10; BOM là tham khảo lịch sử, cần RFQ/checkout trước mua.

## Định hướng hiện hành

- Bản đầu một camera person-down, ONNX/software decode. Runtime được đối chiếu là Python + ORT/FFmpeg; tracker có two-stage association/tentative/constant-velocity prediction. Pose estimator/scheduler có mã nhưng outcomes chưa tham gia quyết định incident.
- Native detector/tracker P1, pose P2 vẫn là thiết kế đã duyệt; đề xuất mở lại thứ tự đầu tư sau profiling, chưa đổi ADR. RKNN chỉ nếu chọn target, capacity vẫn phải đo trên target thật.
- Ưu tiên camera/PTS/frame-age proof, event-quality A/B rule/pose và FPS,413/storage recovery, sau đó mới chọn hotspot/native/board. Đề xuất không đồng nghĩa quyết định accepted.
- H1c được iSpy liệt kê RTSP /11 và /channel1; verify đúng firmware, không suyONVIF. Chưa có giá H1c được ghi.
- Camera native AI: event/trigger/dense metadata là ba mức khác nhau; Hikvision đang bàn chưa xác minh mức dense.
- Chuyển camera/board qua semantic ports/adapters; artifacts/calibration/quality tests vẫn phải làm lại.
- Kiến trúc chi tiết là nguồn tham chiếu implementation; nghiên cứu giữ lý do, nguồn và bất định, không duplicate toàn đặc tả.

- [Mục lục thiết kế](../docs/README.md), [contracts](../docs/architecture/contracts.md) và [tracker](../.scratch/system-build-slices/PRD.md) là nguồn chuẩn; research không có backlog/timeline riêng.
