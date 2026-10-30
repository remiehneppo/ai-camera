# Proposal

Trạng thái: phạm vi và thiết kế được duyệt ngày 2026-10-29; kế hoạch/triển khai được cho phép ngày 2026-10-30. Phân loại T3; Python reference đã triển khai, bằng chứng và giới hạn ghi trong log triển khai và tasks.md.

## Why

Bốn feature module dựng snapshot rồi pipeline sửa lại, trong khi Person-down dùng đường dựng khác. Hai evaluator còn lặp orchestration perception; các sửa đổi lineage/quality và timestamp gần đây cho thấy cần tập trung locality thay vì giữ nhiều implementation.

Phạm vi đã thống nhất nằm trong [log quyết định](../../../docs/logs/2026-10-29-architecture-deepening-review.md#final-recommendation-agreement). Hướng kiến trúc dựa trên ADR-0001/0004 và các hợp đồng hiện hữu, không đặt thêm yêu cầu sản phẩm.

## What Changes

- Tạo một module snapshot không giữ session/state, dùng một interface dựng full Suspected incident snapshot từ facts và context hiện tại.
- **BREAKING** đối với interface nội bộ: feature module trả facts thay full snapshot; chuyển toàn bộ caller/fixture liên quan cùng đợt, không giữ đường tương thích cũ.
- Giữ độc lập rule/state/config và anchor; giữ payload đặc thù từng tình huống. EvidenceLifecycle tiếp tục sở hữu durable intent, pin và recovery.
- Chuyển evaluator sang PerceptionPipeline/PerceptionExecution; giữ đọc video/sampling/cấu hình/tổng hợp bên ngoài seam, tái sử dụng adapter hiện hữu.
- Giữ nguyên cấu hình hiệu lực của từng command/caller khi chuyển đổi; không thay bằng pipeline defaults.
- Fail-fast khi detection observation ngoài ok/ok_empty và đo latency quanh process_frame, gồm persist cục bộ. Người dùng đã duyệt các lựa chọn này cùng design.md.
- Phân biệt zero events với negative pass; giữ Origin=replay, lưu trữ tạm cục bộ, không giao nhận mạng.

## Capabilities

### New Capabilities

- `incident-snapshot`: quyền tạo full snapshot, precedence của context, payload/anchor và handoff bền vững; triển khai trước.
- `semantic-replay`: evaluator sử dụng runtime module với cấu hình/status/timing tường minh; phụ thuộc incident-snapshot.

Đây là lần ghi nhận đầu tiên các hành vi này trong OpenSpec, không ngụ ý hệ thống trước đó chưa có snapshot hoặc replay.

### Modified Capabilities

Không có living spec OpenSpec trước change này. Không tạo living spec khẳng định thiết kế đã duyệt là hành vi đã triển khai.

## Impact

- Issue liên quan: #57 carrier multi-module; #21 quality; #13/#14 Track/pipeline. Không thay Execution hoặc claim nghiệm thu của các ticket.
- ADR: [0005 snapshot ownership](../../../docs/adr/0005-incident-snapshot-ownership.md) và [0006 replay reuse](../../../docs/adr/0006-semantic-replay-pipeline-reuse.md), đều accepted và bổ sung ADR-0001–0004; không thay native/target acceptance bằng kiểm chứng Python reference.
- Mã dự kiến: apps/edge/snapshot.py, pipeline.py, năm feature module; tools/eval_all_scenarios.py, eval_vehicle.py, eval_clip.py; test/fixture tương ứng. Kiểm tra caller qua codegraph trước khi sửa exported symbol.
- Wire contract/schema/DB: không đổi; giữ schema version, canonicalization và transaction hiện hữu. Không thêm migration/datastore.
- Quyền camera/site, RBAC, tenant và mobile: không đổi. Context theo camera/session không được lẫn khi tạo snapshot.
- Depth/leverage: caller dùng chung interface; test kết quả qua cùng seam. Không thêm adapter registry, superclass hoặc dependency.

## Out of scope

Không tune model/ngưỡng, thêm nhóm cảnh báo, chuyển datastore, triển khai native lifecycle, sửa realtime stress, giao nhận mạng, tạo Complete evidence hoặc đổi cơ chế review. Không coi replay/integration fixtures là held-out quality hoặc target-hardware proof.

## Approval checkpoint

ADR-0005/0006, interface và ba lựa chọn replay trong design.md được duyệt ngày 2026-10-29; người dùng duyệt [tasks.md](tasks.md) và cho phép triển khai ngày 2026-10-30. Mã Python reference và kiểm chứng đã hoàn tất theo log; không suy quality/native/target acceptance từ kết quả này. Không archive trước merge, không tự commit/push hoặc triển khai môi trường.
