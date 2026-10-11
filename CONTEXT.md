# AI Camera giao thông

Hệ thống quan sát sự kiện đường bộ từ video, giữ bằng chứng và hỗ trợ người trực xác minh. Ngôn ngữ dưới đây phản ánh [thiết kế hiện hành](docs/architecture/system-architecture.md); không ngụ ý đã triển khai.

## Language

**Alert feature pipeline**: Luồng quan sát và đánh giá dành cho một tính năng cảnh báo, tạo sự kiện nghi ngờ trong phạm vi của tính năng đó. Nhiều pipeline có thể cùng quan sát một camera.
_Avoid_: Kênh gửi thông báo, toàn bộ hệ thống camera, một engine inference.

**Person-down**: Nhóm tình huống người ngã, quỵ xuống hoặc nằm bền vững cần xác minh bằng quan sát. Không phải chẩn đoán tình trạng y tế.
_Avoid_: Đột quỵ, bất tỉnh đã xác định.

**Person fall**: Tình huống nghi ngờ người ngã có quan sát được diễn biến hạ thấp hoặc va chạm trước tư thế nằm.
_Avoid_: Mọi người đang nằm.

**Person lying persistent**: Tình huống người nằm bền vững trong vùng lòng đường nhưng không quan sát đủ diễn biến bắt đầu.
_Avoid_: Không ngã vì không thấy ngã.

**Person on stationary vehicle**: Tình huống người có tư thế nằm/ngả gắn với xe đã đứng yên và đứng thẳng từ trước, cần review với mức ưu tiên riêng.
_Avoid_: Người ngủ đã xác định, sự kiện được phép bỏ qua.

**Suspected incident**: Sự kiện nghi ngờ từ quan sát của hệ thống, có thể còn thiếu bằng chứng hoặc chưa được người trực xác minh.
_Avoid_: Tai nạn đã xác nhận.

**Review confirmation**: Kết quả người trực xác nhận một sự kiện trong phạm vi nghiệp vụ quan sát.
_Avoid_: AI confidence tăng, kết luận y khoa hoặc pháp lý.

**Evidence**: Video/ảnh cùng thông tin nguồn gốc và khoảng thời gian hỗ trợ xác minh một sự kiện.
_Avoid_: Bằng chứng pháp lý mặc nhiên.

**Raw evidence**: Bản ghi từ nguồn chưa bị thay đổi nội dung điểm ảnh để thêm chú thích, che dữ liệu hoặc tăng cường hình ảnh.
_Avoid_: Video có overlay, proxy hoặc redaction.

**Derived evidence**: Bản được tạo từ evidence khác và có thể khác nội dung hoặc cách biểu diễn.
_Avoid_: Bản gốc.

**Complete evidence**: Evidence bao phủ đủ khoảng thời gian được yêu cầu và không có gap vượt mức cho phép.
_Avoid_: Partial có lý do nên vẫn complete.

**ODD**: Phạm vi điều kiện hiện trường mà một khả năng quan sát đã được kiểm thử và chấp nhận hỗ trợ.
_Avoid_: Mọi cảnh camera nhìn thấy.

**Unknown observation**: Quan sát không đủ độ tin cậy hoặc độ phủ để kết luận tình huống tương ứng.
_Avoid_: Kết quả âm tính.

**Operational fault**: Tình trạng hệ thống mất hoặc giảm khả năng quan sát, giữ evidence hoặc chuyển giao dữ liệu.
_Avoid_: Sự kiện tai nạn.

**Track**: Chuỗi quan sát được liên kết theo thời gian trong một phiên camera.
_Avoid_: Danh tính người, định danh liên camera.

**Origin**: Nguồn chạy live, replay hoặc synthetic; bất biến suốt event và độc lập taxonomy nghiệp vụ.
_Avoid_: Đổi replay thành live ở revision sau.

**Review freshness**: Quan hệ giữa quyết định review và event/evidence versions đã được người trực xem. Thông tin mới có ý nghĩa tạo cờ cần xem lại, không tự xóa quyết định trước.
_Avoid_: Mọi AI revision mới tự reset review.

## Tài liệu liên quan

- [Mục lục tài liệu](docs/README.md) và [hợp đồng tích hợp](docs/architecture/contracts.md).
- [Plan theo module](docs/architecture/implementation-plan.md).
- [Deployment readiness](docs/architecture/deployment-readiness.md).
- Quyết định chưa chốt nằm trong plan/readiness; không coi đề xuất là quyết định accepted.
