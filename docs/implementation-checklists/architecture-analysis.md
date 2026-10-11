# Hướng dẫn review ranh giới khi triển khai

Nguồn chuẩn: [kiến trúc](../architecture/system-architecture.md), [contracts](../architecture/contracts.md), [plan](../architecture/implementation-plan.md). Thứ tự thực hiện theo [tracker slices](../../.scratch/system-build-slices/PRD.md); tài liệu này chỉ giữ tiêu chí review, không sao chép graph hoặc trạng thái backlog.

## SOLID tại các ranh giới thực

| Nguyên tắc | Quy tắc triển khai | Cách review có thể kiểm |
|---|---|---|
| S — Single responsibility | Tách inference, temporal evaluation, evidence lifecycle, delivery và review; module không mặc định là service/process | Thay retry policy không sửa FSM; thay model không sửa server review; recorder lỗi không biến thành accident |
| O — Open/closed | Feature pipeline đăng ký bằng factory allowlist; chia sẻ perception tương thích; backend mới là adapter + manifest | Thêm feature chỉ thêm factory/config/fixtures, không sửa logic feature đã có; không tạo plugin system tổng quát |
| L — Liskov substitution | Adapter thay thế phải giữ clock/status/coordinate/reset/provenance semantics, không chỉ signature | Cùng C05 vectors và event regression cho oracle/native/RKNN; unsupported/failure không giả empty |
| I — Interface segregation | Tách metadata khỏi buffer; detector/pose/tracker khỏi tensor engine; delivery receipts metadata/clip riêng | Domain consumer không cần pixel/SDK; UI consumer không cần edge internals; interface tối thiểu cho use case |
| D — Dependency inversion | Domain không biết infrastructure; application phụ thuộc semantic ports; composition root inject concrete adapters | Review import/dependency direction và test qua fake nhỏ; không service locator, không abstract base class cho mọi helper |

Không dùng số lượng class/interface làm tiêu chí SOLID. Protocol/struct/function trực tiếp là đủ nếu biểu đạt contract và giữ đúng dependency direction.

## Điểm phải kiểm khi tích hợp

| Ranh giới | Invariant | Contract / bằng chứng |
|---|---|---|
| Application/perception | Một PerceptionPipeline cho oracle/native, không duplicate tracker; pixels trong implementation | Contracts §1; conformance cùng consumer |
| Event/server | Full snapshot, identity/origin bất biến, current max revision; review không bị ghi đè | Contracts §2; 3→1→2/conflict/auth tests |
| Analytics/recorder | Durable request/receipt, pin không phụ thuộc analytics sống; bounded interval/range | Contracts §3; crash trước pin/sau ACK, cleanup race |
| Evidence/UI | Partial và acknowledged cùng tồn tại; expired không available | Contracts §4; partial-uploaded/recovery/download tests |
| Review/AI update | Viewed revisions, re-review có lý do; correction append audit | Contracts §5; stale view/concurrency tests |
| Ingestion/downstream | Durable decision; eligibility khác delivery; không auto-backfill | Contracts §6; activation/expiry/origin tests |
| Replay/scheduler | Semantic parity cùng input; realtime drops đo riêng | Contracts §7; X01 khác X06/X22 |
| Target/release | Actual-target conformance/soak; RKNN có điều kiện | Contracts §8; ONNX/RKNN gate traversal |

B04 local activation làm trước remote trust integration; remote chỉ bật sau T02. QL03 camera-moved P2 không chờ geometry; G01/G02 validity bắt buộc khi bật vehicle. O04/A05 dùng cùng capacity run sau conformance target, không chờ vòng nhau. F04/C03 khóa stream/pin contract trước R01/V04 integration; camera chưa có thì live gate chưa đạt. S01 lưu eligibility/intent ngay P1; W02 worker chỉ khi protocol bật.

Mọi thay đổi shared contract phải rà producer, consumer, schemas, bindings, config và fixtures. Đọc [release checklist](integration-release.md) để xác định tests và artifact cần có; mock/unit không thay RTSP/DB/browser/hardware proof.
