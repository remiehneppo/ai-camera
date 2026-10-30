---
status: accepted
---

# Một module sở hữu snapshot Suspected incident

Ngày: 2026-10-29 (duyệt thiết kế), 2026-10-30 (triển khai Python reference). Phân loại: T3. Trạng thái: accepted; đã triển khai và kiểm chứng trên Python reference, chưa phải nghiệm thu native/target hardware.

## Context

Bốn feature module tạo full snapshot rồi PerceptionPipeline sửa ngữ cảnh và validate lại; Person-down dùng một đường tạo snapshot khác. Các sửa đổi f44a442 và b66e78c đã xử lý config_version, detector lineage và quality trong cùng điểm giao này. Phạm vi thống nhất là tập trung việc tạo snapshot và chuyển toàn bộ caller, không gom rule/state của các tình huống.

Nguồn: [log quyết định](../logs/2026-10-29-architecture-deepening-review.md#final-recommendation-agreement), [ticket #57](../../.scratch/system-build-slices/issues/57-vung-nguy-hiem-module-camera-e2e.md), [hợp đồng tích hợp](../architecture/contracts.md#2-event-snapshot-và-identity).

## Decision

Chọn một module tạo snapshot Suspected incident không giữ temporal state, với một interface dựng full snapshot từ dữ kiện tình huống và ngữ cảnh có thẩm quyền. Feature module chỉ trả dữ kiện; PerceptionPipeline điều phối rồi chuyển snapshot đã validate cho EvidenceLifecycle hiện hữu.

- Feature module giữ rule/state/config độc lập, taxonomy, severity/confidence và lựa chọn anchor.
- Module snapshot sở hữu identity mới, timestamp tạo revision, gắn context/config/lineage/quality, tạo Evidence request bằng policy hiện hữu và validate snapshot.
- Context đến từ lượt xử lý hiện tại, không cache session/quality trong module snapshot. Policy quality vẫn do đường đánh giá hiện hữu tính; module snapshot gắn kết quả theo đúng feature và giữ nhất quán hai trường quality.
- Giữ producer pipeline_id/pipeline_version từ binding hiện hữu của từng feature; không dùng identity pipeline chung đè bốn producer riêng chỉ vì tập trung construction.
- Chuyển đồng thời các caller/fixture liên quan; bỏ full-snapshot output riêng, bước sửa snapshot đã dựng và entry point chuyển tiếp không còn caller. Không giữ hai kiểu output.
- EvidenceLifecycle giữ transaction event/outbox/request intent, pin, finalize, transfer và recovery. Retry sử dụng revision đã persist; không dựng identity mới để retry.

Interface đã được duyệt, không đổi quyết định accepted của [ADR-0001](0001-feature-pipeline-boundaries.md) hoặc [ADR-0004](0004-integration-contracts.md). Thông điệp/lưu trữ giữ schema hiện hữu; không thêm datastore, process hoặc adapter.

![Hình H01: Feature module trả dữ kiện; module snapshot gắn context trước khi EvidenceLifecycle persist intent và pin](diagrams/H01-incident-snapshot-ownership.drawio)

## Alternatives considered

### Hàm không giữ ngữ cảnh, tách khỏi PerceptionPipeline

Chọn một điểm dựng snapshot; context truyền tại thời điểm phát sự kiện. Tạo locality cho validation, lineage và Evidence request; test đi qua cùng interface mà không bắt buộc chạy detector hoặc recorder. Tradeoff: phải quy định rõ context/feature facts và quyền ưu tiên trường, không trải từng trường snapshot thành hàng chục tham số rời.

### Module giữ session và binding theo feature

Giảm dữ liệu truyền lặp nhưng thêm vòng đời bind/rebind khi session, config, model hoặc quality thay đổi. Không chọn làm mặc định vì có nguy cơ stale context và không cần thêm adapter; engine không được nhận trách nhiệm dựng full snapshot trở lại.

### Tạo snapshot chỉ bằng hàm private trong PerceptionPipeline

Leverage cao cho caller process_frame hiện hữu, nhưng test snapshot riêng phải dựng pipeline/lưu trữ và locality của luật snapshot vẫn lẫn với điều phối frame. Giữ PerceptionPipeline là caller chính, không lấy toàn bộ pipeline làm interface kiểm tra việc dựng snapshot.

## Consequences

- Depth tăng khi caller không cần biết metadata nào sẽ bị sửa sau validation; một seam kiểm tra full snapshot thay thế các cách dựng riêng.
- Phải giữ payload đặc thù: dwell/bbox, crowd_count/metrics, interaction_type/track_ids và pose/association. Không ánh xạ mọi tình huống qua danh sách trường Person-down.
- Phải giữ config riêng, rule lineage, Origin và anchor kind, gồm first_qualifying_observation; không mặc định mọi Person-down là onset.
- Input hoặc snapshot lỗi phải trả lỗi hiện hữu trước persist, không phát một snapshot thiếu ngữ cảnh. Lỗi persist giữ nguyên semantics của EvidenceLifecycle, không nuốt exception.
- Chuyển caller là thay đổi interface nội bộ; triển khai phải cập nhật đầy đủ test/fixture và không thay đổi ngưỡng hoặc thông điệp đã persist.
- Thay PostgreSQL/MongoDB không giải quyết hai đường tạo snapshot trong tiến trình. Giữ SQLite/MongoDB và các transaction hiện hữu; không có đề xuất đổi datastore để giải quyết vấn đề này.

## Acceptance and evidence

Người dùng duyệt thiết kế ngày 2026-10-29 và cho phép triển khai ngày 2026-10-30. Đã hoàn tất cutover trên Python reference (`apps/edge/snapshot.py` và 5 feature modules; xem [tasks.md](../../openspec/changes/deepen-incident-snapshots-and-replay/tasks.md) và [log kiểm chứng](../logs/2026-10-29-architecture-deepening-review.md#implementation-authorized--2026-10-30)). Native/target conformance vẫn mở theo G3–G5.
