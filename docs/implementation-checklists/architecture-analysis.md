# Hướng dẫn review ranh giới kiến trúc khi triển khai

**Cập nhật:** 2026-10-30 · **Nguồn chuẩn:** [Kiến trúc hệ thống](../architecture/system-architecture.md) · [Hợp đồng tích hợp](../architecture/contracts.md) · [Mục lục ADR](../adr/README.md) · [Kế hoạch triển khai](../architecture/implementation-plan.md).

Tài liệu này cung cấp danh sách các bất biến thiết kế để kiểm tra nhanh trong mọi đợt code review (PR/MR). Không đánh giá SOLID bằng số lượng lớp trừu tượng; một hàm thuần hoặc `TypedDict`/`dataclass` rõ nghĩa luôn tốt hơn các lớp wrapper rỗng.

---

## 1. Nguyên tắc SOLID tại các ranh giới thực tế trong Repo

| Nguyên tắc | Quy tắc bắt buộc trong mã nguồn | Dấu hiệu vi phạm cần chặn khi Review |
|---|---|---|
| **S — Single Responsibility** | Tách biệt rõ: suy luận mô hình (`oracle_detector.py`, `pose.py`), bám vết (`tracker.py`), đánh giá quy tắc thời gian (5 engines), lắp ghép snapshot (`snapshot.py`), vòng đời bằng chứng (`recorder.py`, `evidence.py`), truyền vận (`outbox.py`, `uploader.py`) và xác minh (`apps/server/`) | Sửa chính sách retry lại phải chạm vào FSM phát hiện ngã; lỗi ghi hình của recorder biến thành sự kiện tai nạn giả; module nghiệp vụ tự sinh UUID hoặc tự gọi `validate_event` |
| **O — Open / Closed** | Mở rộng nhóm cảnh báo mới bằng cách thêm cấu hình + engine trả `SnapshotFacts` + đăng ký vào `ALLOWLISTED_FACTORIES` trong `apps/edge/pipeline.py` ([ADR-0001](../adr/0001-feature-pipeline-boundaries.md)) | Cấy nhánh `if taxonomy == ...` rải rác khắp orchestrator/uploader/server hoặc dựng hệ thống plugin nạp mã động không kiểm soát |
| **L — Liskov Substitution** | Mọi adapter thay thế (ví dụ native C++ core hoặc backend TensorRT/RKNN thay cho Python ONNX oracle) phải giữ nguyên hệ tọa độ ảnh gốc, ngữ nghĩa đồng hồ, reset phiên, cổng nhóm nhãn và trạng thái lỗi (`failed`/`skipped` khác `ok_empty`) | Adapter mới chỉ khớp chữ ký hàm nhưng trả tọa độ đã chuẩn hóa `[0,1]`, nuốt lỗi suy luận thành danh sách rỗng hoặc làm lệch kết quả trên bộ golden conformance |
| **I — Interface Segregation** | Tầng nghiệp vụ chỉ nhận metadata đã chuẩn hóa (`Detection`, `Track`, `PoseResult`, `QualityReport`); giao diện người trực chỉ nhận hợp đồng API/review mà không phụ thuộc chi tiết lưu trữ nội bộ của Edge | Truyền con trỏ khung hình thô hoặc đối tượng session ONNX/SQLite xuyên vào hàm tính toán quy tắc nghiệp vụ trong `domain/` |
| **D — Dependency Inversion** | `domain/` hoàn toàn thuần khiết; `apps/edge/` và `apps/server/` phụ thuộc vào hợp đồng tại `domain/`; các công cụ đánh giá `tools/eval_*.py` tái sử dụng trực tiếp `PerceptionPipeline` ([ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md)) | `domain/` import ngược từ `apps/`; công cụ `tools/` tự viết vòng lặp ghép detector → tracker → incident riêng gây trôi dạt ngữ nghĩa |

---

## 2. Mười ranh giới tích hợp bắt buộc kiểm tra khi Review

| Ranh giới | Bất biến không được phá vỡ | Nguồn hợp đồng & Kiểm chứng |
|---|---|---|
| **1. Perception & Tracking** | Mỗi khung hình cập nhật `ByteTracker` tối đa một lần; không cho phép gán hộp xuyên nhóm lớp đối lập (`person` vs `two_wheeler`/`motor_vehicle`); kết quả pose đến muộn không cập nhật lại tracker | `contracts.md §1`, `apps/edge/tracker.py`, `tests/test_tracker_lifecycle.py` |
| **2. Snapshot Ownership ([ADR-0005](../adr/0005-incident-snapshot-ownership.md))** | 5 module cảnh báo chỉ trả `SnapshotFacts`; chỉ `apps/edge/snapshot.py` (`build_incident_snapshot`) dựng full snapshot, gắn lineage phiên hiện tại và gọi `validate_event` | `contracts.md §2`, `apps/edge/snapshot.py`, `tests/test_snapshot.py` |
| **3. Evidence Anchor & Pin ([ADR-0004](../adr/0004-integration-contracts.md))** | `person_down` giữ `onset` / `first_qualifying_observation`; 4 module mở rộng dùng `alert_condition`; cửa sổ `[-10s, +20s]` bất biến theo `request_id`; ghim segment bền vững trước khi ACK | `contracts.md §3`, `apps/edge/evidence.py`, `tests/test_evidence_lifecycle.py` |
| **4. Evidence Completeness & UI** | Phân tách 4 chiều `build_state`, `completeness`, `transfer_state`, `availability`; clip `partial` hoặc đã hết hạn lưu trữ phải hiển thị trung thực, không báo giả là `complete`/`available` | `contracts.md §4`, `apps/server/evidence.py`, `tests/test_server_evidence.py` |
| **5. Versioned Review & Audit** | Quyết định review kiểm tra phiên bản đã xem (`viewed_revision`), tự động chuyển `needs_re_review` khi có bằng chứng hoàn chỉnh hơn hoặc nâng mức nghiêm trọng; mọi chỉnh sửa nối thêm vào lịch sử audit | `contracts.md §5`, `apps/server/store.py`, `tests/test_review_api.py` |
| **6. Downstream Publishing ([ADR-0002](../adr/0002-server-downstream-event-publishing.md))** | Ghi `downstream_intent` cùng transaction với sự kiện; sự cố kênh thông báo ngoài không rollback ingestion; sự kiện `synthetic`/`replay` vĩnh viễn `ineligible` | `contracts.md §6`, `domain/downstream_contract.py`, `tests/test_event_delivery.py` |
| **7. Semantic Replay ([ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md))** | `eval_clip.py`, `eval_vehicle.py`, `eval_all_scenarios.py` gọi chung `PerceptionPipeline.process_frame`, cấu hình fail-fast tường minh và báo cáo đầy đủ `effective_config` | `contracts.md §7`, `tools/eval_*.py`, `tests/test_semantic_replay.py` |
| **8. Operational Probe & Storm Guard** | `SyntheticProbe` phát `taxonomy="operational_fault"` bị `validate_event` từ chối (không bao giờ lọt vào cảnh báo nghiệp vụ); `MalformedStormGuard` cô lập theo từng thiết bị | `contracts.md` (`#synthetic-probe-operational-fault`), `tests/test_probe.py`, `tests/test_storm_guard.py` |
| **9. Signed Config & Rollback** | Cấu hình enabled lỗi phải fail-fast lúc khởi động; kích hoạt từ xa kiểm tra chữ ký/role/target và giữ `trust_sequence` (HWM) tăng đơn điệu kể cả khi rollback về LKG | `contracts.md §9`, `apps/edge/config_store.py`, `tests/test_signed_config_activation.py` |
| **10. WAN Outage & Quota Autonomy** | Mất WAN không làm dừng ghi nhận sự kiện tại biên; `StorageQuotaGuard` dọn dữ liệu thường trước và tuyệt đối không xóa clip chưa được Server ACK theo mốc 24 giờ | `contracts.md §10`, `apps/edge/quota.py`, `tests/test_wan_outage_resilience.py` |
