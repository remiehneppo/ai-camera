# Architecture Decision Records (ADRs)

Danh mục các quyết định kiến trúc cấp hệ thống đã được phê duyệt (`accepted`). Theo quy ước MADR, các ADR đã `accepted` giữ nguyên lịch sử quyết định; khi thay đổi kiến trúc phải tạo ADR mới thay thế (`supersedes`) thay vì viết đè quyết định cũ.

| ADR | Quyết định | Trạng thái | Điểm thực thi chính trong mã nguồn |
|---|---|---|---|
| [ADR-0001](0001-feature-pipeline-boundaries.md) | Mỗi nhóm cảnh báo là một feature pipeline có rule/state/config độc lập, chia sẻ perception tương thích | `accepted` | `apps/edge/pipeline.py` (`ALLOWLISTED_FACTORIES`), `domain/alert_module_config.py`, 5 engines trong `apps/edge/` |
| [ADR-0002](0002-server-downstream-event-publishing.md) | Server commit event bền vững cùng downstream intent trước khi phát thông báo mở rộng; lab giữ dashboard-only | `accepted` | `apps/server/store.py`, `domain/downstream_contract.py` |
| [ADR-0003](0003-fastapi-mongodb-backend.md) | Backend dùng FastAPI + MongoDB replica set (multi-document ACID transactions & `$setWindowFields`) | `accepted` | `apps/server/main.py`, `apps/server/store.py`, `docker-compose.yml` |
| [ADR-0004](0004-integration-contracts.md) | Khóa hợp đồng tích hợp ngữ nghĩa giữa `PerceptionPipeline`, full event snapshot, evidence lifecycle, review freshness và replay | `accepted` | `domain/event_contract.py`, `domain/evidence_contract.py`, `domain/review_contract.py`, `docs/architecture/contracts.md` |
| [ADR-0005](0005-incident-snapshot-ownership.md) | Tập trung quyền dựng và validate full snapshot `Suspected incident` tại một module stateless duy nhất ([Sơ đồ H01](diagrams/H01-incident-snapshot-ownership.drawio)) | `accepted` (Python reference) | `apps/edge/snapshot.py` (`build_incident_snapshot`), `apps/edge/pipeline.py` |
| [ADR-0006](0006-semantic-replay-pipeline-reuse.md) | Các công cụ đánh giá replay dùng chung `PerceptionPipeline.process_frame` với cấu hình hiệu lực tường minh ([Sơ đồ H02](diagrams/H02-semantic-replay-reuse.drawio)) | `accepted` (Python reference) | `tools/eval_clip.py`, `tools/eval_vehicle.py`, `tools/eval_all_scenarios.py` |
