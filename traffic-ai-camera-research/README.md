# Nghiên cứu AI Camera giao thông edge

## Tài liệu

- [report.md](report.md): nghiên cứu phần cứng/phần mềm/data/license/chi phí; đồng bộ thiết kế11-10-2026; person-down/native/HTTPS/FastAPI/MongoDB và gate theo target.
- [prices.csv](prices.csv): 20 quan sát giá, đúng SKU/URL/điều kiện, không phải báo giá giao hàng.
- [sources.md](sources.md): nguồn hãng, retail, nghiên cứu và compatibility bên thứ ba.
- [outline.yaml](outline.yaml), [fields.yaml](fields.yaml): đối tượng và tiêu chí nghiên cứu.
- [Kiến trúc hệ thống](../docs/architecture/system-architecture.md): modules/contracts/pipelines/source tree đề xuất.

## Ngày và mức độ bằng chứng

Nghiên cứu ban đầu09-10-2026; đồng bộ thiết kế11-10-2026 theo đồng hồ môi trường. Lượt11-10 không refresh giá: bốn giá Tapo đọc ngày10-10,16giá còn lại ngày09-10; BOM là tham khảo lịch sử. Giá cần RFQ/checkout trước mua. Chưa đo FPS pipeline hoặc benchmark board.

## Định hướng hiện hành

- Bản đầu một camera person-down, ONNX software decode; native detector/tracker P1, pose P2; Python giữ domain/control và oracle. RKNN chỉ nếu chọn target, capacity vẫn phải đo trên target thật.
- H1c được iSpy liệt kê RTSP /11 và /channel1; verify đúng firmware, không suyONVIF. Chưa có giá H1c được ghi.
- Camera native AI: event/trigger/dense metadata là ba mức khác nhau; Hikvision đang bàn chưa xác minh mức dense.
- Chuyển camera/board qua semantic ports/adapters; artifacts/calibration/quality tests vẫn phải làm lại.
- Kiến trúc chi tiết là nguồn tham chiếu implementation; nghiên cứu giữ lý do, nguồn và bất định, không duplicate toàn đặc tả.

- [Mục lục thiết kế](../docs/README.md), [contracts](../docs/architecture/contracts.md) và [tracker](../.scratch/system-build-slices/PRD.md) là nguồn chuẩn; research không có backlog/timeline riêng.
