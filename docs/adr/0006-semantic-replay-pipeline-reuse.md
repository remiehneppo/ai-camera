---
status: accepted
---

# Replay dùng chung Alert feature pipeline module

Ngày: 2026-10-29 (duyệt thiết kế), 2026-10-30 (triển khai Python reference). Phân loại: T3 theo thay đổi quyền điều phối caller. Trạng thái: accepted; đã triển khai và kiểm chứng trên Python reference, chưa phải nghiệm thu native/target hardware.

## Context

Hai evaluator eval_all_scenarios và eval_vehicle tự gọi detector, Track và feature module; eval_clip đã dùng PerceptionPipeline. Commit b60d5db sửa cùng lỗi clock/status ở hai evaluator. Cấu hình tracker/feature và phạm vi timing khác nhau, nên dùng chung mã không tự tạo policy parity.

Nguồn: [log quyết định](../logs/2026-10-29-architecture-deepening-review.md#final-recommendation-agreement), [hợp đồng semantic replay](../architecture/contracts.md#7-replay-và-realtime-stress), [ADR-0004](0004-integration-contracts.md). Thực hiện sau seam snapshot của [ADR-0005](0005-incident-snapshot-ownership.md).

## Decision

Các evaluator kiểm chứng đường chạy Alert feature pipeline qua PerceptionPipeline/PerceptionExecution hiện hữu. Caller giữ đọc video, sampling, cấu hình đầu vào và tổng hợp kết quả; xóa orchestration detector/Track/pose/feature lặp bên ngoài module.

- Dùng adapter detector replay và recorder/outbox cục bộ hiện hữu, Origin=replay, không có uploader hoặc giao nhận mạng.
- Giữ từng cấu hình hiện tại của command và caller hàm khi chuyển đổi, truyền tường minh vào pipeline. Không lấy default pipeline thay default evaluator; không đồng nhất các ngưỡng khác nhau bằng refactor.
- Fail-fast sau observation detection ngoài ok/ok_empty: pipeline xử lý status/gap trước, evaluator kết thúc lỗi thay vì báo lượt chạy thành công hoặc negative. Pose skipped/failed tiếp tục được biểu diễn riêng theo semantics hiện hữu.
- Đo latency từ trước process_frame đến khi process_frame trả về, gồm việc dựng/persist snapshot cục bộ. Không gồm decode, sampling, khởi tạo model hoặc giao nhận mạng. Báo rõ phạm vi mới và không so với số đo cũ như cùng một đại lượng.
- Tổng hợp từ observation và snapshot pipeline phát/persist; zero events chỉ là số đầu ra, không gắn nhãn clean hoặc chứng minh negative pass.

Cấu hình hiệu lực hiện hữu, fail-fast và phạm vi timing đã được duyệt ngày 2026-10-29. Không đặt thêm ngưỡng nghiệm thu, mục tiêu chất lượng hoặc hiệu năng.

![Hình H02: Caller replay cung cấp frame/cấu hình; Alert feature pipeline dùng chung perception và feature state, không có giao nhận mạng](diagrams/H02-semantic-replay-reuse.drawio)

## Alternatives considered

### Giữ evaluator là feature experiment độc lập

Dễ sửa rule thăm dò nhưng không tạo leverage cho kiểm chứng runtime; giữ lặp clock/status/dispatch và không giải quyết mục tiêu đã chốt. Đưa thăm dò rule vào test feature module, không duy trì một đường runtime thứ hai.

### Framework replay mới với adapter registry

Có thể điều phối nhiều kiểu runner nhưng chưa có nhu cầu biến thiên bổ sung. Không chọn: tăng interface/lifecycle mà phần thực thi cần dùng lại đã có; một adapter giả định không tạo seam có giá trị.

### Dùng pipeline defaults hoặc tiếp tục chạy sau detection failure

Default chung làm thay policy của command; tiếp tục rồi chỉ báo event count có thể che thời gian không quan sát được. Không chọn mặc định; nếu cần tiếp tục để phân tích degraded intervals, phải duyệt hành vi và báo cáo riêng trước, không ngụy trang thành negative pass.

## Consequences

- Locality tập trung clock/status/continuity và snapshot; depth ở process_frame tăng leverage cho runtime lẫn replay. The interface is the test surface: kiểm outcome/status/snapshot thay vì mock lời gọi nội bộ.
- Cấu hình khác nhau vẫn được phép cho kết quả khác nhau. Bằng chứng tương đương cần cùng model, input/sampling, feature policy và cách kiểm tra outcome; không đòi UUID hoặc wall-clock giống giữa hai lượt chạy mới.
- Temporary recorder/outbox không tạo raw video coverage. Không nhận Complete evidence, server receipt/review, native conformance, realtime stress hoặc target capacity từ lượt replay này.
- Lỗi mở video/khởi tạo/inference không được báo thành công; tài nguyên và dữ liệu tạm phải đóng/dọn ở cả đường bình thường và đường lỗi.
- Không đổi schema lưu trữ, quyền camera/site, datastore hoặc ngưỡng phát hiện. Thay datastore không giải quyết các vòng điều phối trùng trong hai command.

## Acceptance and evidence

Người dùng duyệt ADR-0005, ADR-0006 và interface/design ngày 2026-10-29 và cho phép triển khai ngày 2026-10-30. Ba evaluator (`eval_clip`, `eval_vehicle`, `eval_all_scenarios`) đã chuyển sang dùng chung `PerceptionPipeline.process_frame` (xem [tasks.md](../../openspec/changes/deepen-incident-snapshots-and-replay/tasks.md) và [log kiểm chứng](../logs/2026-10-29-architecture-deepening-review.md#implementation-authorized--2026-10-30)). Native/target conformance vẫn mở. Giữ ADR-0001–0004.
