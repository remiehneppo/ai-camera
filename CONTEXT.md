# AI Camera giao thông

Hệ thống quan sát sự kiện an toàn đô thị từ video, giữ bằng chứng và hỗ trợ người trực xác minh. Ngôn ngữ dưới đây phản ánh [thiết kế hiện hành](docs/architecture/system-architecture.md); không ngụ ý đã triển khai.

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
_Avoid_: Partial có lý do nên vẫn complete; clip đầy đủ nghĩa là quan sát trọn sự kiện kéo dài.

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

**Alert-condition anchor**: Mốc trên thời gian nguồn khi diễn biến đủ điều kiện tạo cảnh báo theo vùng, lịch và ngưỡng của tình huống.
_Avoid_: Mặc nhiên là onset, thời điểm dashboard nhận hoặc thời điểm người trực review.

**Observation duration**: Khoảng thời gian hệ thống có quan sát hỗ trợ một trạng thái, với giới hạn về độ phủ được thể hiện rõ.
_Avoid_: Video chứng minh toàn bộ thời gian tồn tại của sự kiện.

**Urban safety scenario**: Nhóm tình huống an toàn đô thị cần người trực xác minh, được định nghĩa bằng dấu hiệu quan sát và ranh giới riêng.
_Avoid_: Một khả năng đã triển khai; kết luận nguyên nhân, ý định hoặc trách nhiệm.

**Vehicle incident**: Sự cố đường bộ nghi ngờ có xe tham gia (xe–xe, xe–người, xe tự ngã/lật hoặc đâm dải phân cách/vật cản cố định) được phân loại theo động học và xung lực va chạm thực tế.
_Avoid_: Tự kết luận lỗi vi phạm, ý định hoặc trách nhiệm pháp lý.

**Pairwise interaction risk**: Phân tích rủi ro tương tác cặp giữa các phương tiện hoặc giữa xe và người trong không gian ảnh 2D (tốc độ thu hẹp khoảng cách closing speed, tỉ lệ giao nhau IoU và tốc độ giãn nở IoU, cấp độ rủi ro TTC).
_Avoid_: Coi TTC thấp hoặc bounding box overlap riêng lẻ là bằng chứng va chạm đã xác định.

**Illegal parking**: Tình huống phương tiện cơ giới đứng yên liên tục trong vùng cấm đỗ (ROI) hoặc ngoài khung giờ cho phép vượt quá thời gian ngưỡng dwell_seconds.
_Avoid_: Xe dừng chờ đèn đỏ, xe kẹt trong dòng ùn tắc giao thông, hoặc xe dừng đỗ ngắn hạn hợp lệ ngoài lịch cấm.

**Dwell duration**: Khoảng thời gian phương tiện đứng yên liên tục được đo đạc sau khi đã loại trừ rung giật bounding box và yêu cầu tối thiểu 2 frame quan sát liên tục.
_Avoid_: Bịa đặt thời gian đứng yên qua khoảng mất dấu camera (track gap) hoặc giả định đứng yên ngay ở frame đầu tiên (zero-history assumption).

**Crowd concentration**: Tập trung đông người theo số lượng người N và thời gian duy trì T trong vùng quan sát.
_Avoid_: Mặc nhiên suy diễn thành gây rối trật tự.

**Suspected public disorder**: Nghi ngờ gây rối trật tự dựa trên hành vi phân tán hoảng loạn của nhiều người cùng lúc (multi-actor dispersal divergence), xung đột động học vận tốc cao, hoặc biến thiên góc hướng hỗn loạn trong một cụm không gian cục bộ.
_Avoid_: Đám đông tụ tập trật tự, hàng đợi xe buýt, một cá nhân vận động/chạy bộ riêng lẻ hoặc gom gộp người ở hậu cảnh xa không cùng cụm.

**Danger-zone intrusion**: Tình huống người đi vào và duy trì hiện diện trong vùng nguy hiểm (ROI) đang trong khung lịch giám sát theo cấu hình camera, không suy diễn danh tính hoặc quyền truy cập.
_Avoid_: Người đi ngoài ROI, ngoài khung giờ hiệu lực, hoặc kết luận xâm nhập trái phép về mặt pháp lý.

**Suspected property vandalism**: Nghi ngờ tác động đập/đá/phá kéo hoặc ném vật vào tài sản; độc lập với tương tác bạo lực giữa người.
_Avoid_: Thiệt hại hoặc ý định đã xác định; mọi thao tác sửa chữa/dọn dẹp.

**Fixed CCTV Traffic Camera ODD**: Phạm vi điều kiện hoạt động chuẩn của camera giám sát giao thông gắn cố định trên cột đèn, ngã tư hoặc cầu vượt, có độ phân giải từ HD (720p / 1280×720) đến 2MP (Full HD 1080p / 1920×1080).
_Avoid_: Camera hành trình (dashcam - chuyển động di động tạo luồng quang học giả), camera quay quét lia liên tục, camera độ nét thấp (<720p).

## Tài liệu liên quan

- [Mục lục tài liệu](docs/README.md) và [hợp đồng tích hợp](docs/architecture/contracts.md).
- [Requirement tình huống an toàn đô thị](docs/requirements/urban-safety-scenarios.md).
- [Plan theo module](docs/architecture/implementation-plan.md).
- [Deployment readiness](docs/architecture/deployment-readiness.md).
- Quyết định chưa chốt nằm trong plan/readiness; không coi đề xuất là quyết định accepted.
