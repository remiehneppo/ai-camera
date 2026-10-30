# Spec Delta

## Purpose

Tập trung quyền tạo full snapshot Suspected incident tại một seam để caller nhận dữ kiện, ngữ cảnh và Evidence request nhất quán, trong khi các feature module giữ quyết định tình huống độc lập. Phạm vi và thiết kế đã duyệt; đặc tả không khẳng định mã hiện tại đã thực hiện các yêu cầu.

## ADDED Requirements

### Requirement: Feature output contains scenario facts without snapshot ownership

Feature module SHALL trả dữ kiện tình huống thay full snapshot và SHALL giữ nguyên rule/state/config, taxonomy, severity/confidence, source anchor và payload nghiệp vụ của mình. Caller cần snapshot MUST dùng interface tạo snapshot chung sau khi chuyển đổi, không còn đường full-snapshot tương thích riêng.

#### Scenario: S01 Independent feature decisions reach one snapshot seam
- **WHEN** caller chạy các feature Person-down, vùng nguy hiểm, Vehicle incident, Illegal parking và Crowd concentration với fixture đủ điều kiện tương ứng
- **THEN** mỗi feature trả facts thay event envelope và caller nhận full snapshot qua cùng seam, không thay kết quả quyết định tình huống vì thay quyền dựng snapshot

### Requirement: Runtime context and feature configuration remain authoritative

Module snapshot MUST lấy identity camera/device/session, Origin và detector/calibration provenance từ context runtime hiện tại; MUST giữ producer pipeline_id/pipeline_version, config/rule lineage của feature đang hoạt động và kết quả quality có scope tương ứng. Facts SHALL NOT cung cấp một envelope hoặc thay các trường thuộc quyền runtime; input sai cấu trúc phải bị từ chối trước persist.

#### Scenario: S02 Conflicting snapshot envelope cannot replace runtime context
- **WHEN** caller gửi facts có event envelope hoặc trường kiểm soát camera/session/Origin không thuộc interface facts
- **THEN** việc dựng snapshot báo lỗi và không persist snapshot mang identity do facts cung cấp

#### Scenario: S03 Feature quality and configuration survive context changes
- **WHEN** hai feature có config khác nhau cùng xử lý một camera, một feature có quality policy riêng và feature còn lại dùng quality pipeline
- **THEN** từng snapshot giữ đúng producer pipeline_id/pipeline_version, config/rule lineage, detector provenance và quality của feature đó; không dùng identity/config toàn pipeline đè giá trị riêng hoặc giả quality normal khi chưa được đánh giá

### Requirement: Scenario payload is preserved without mutable aliasing

Module snapshot SHALL giữ các trường dữ kiện đặc thù và giá trị đã được feature quyết định; SHALL NOT ép payload các tình huống theo danh sách trường Person-down. Thao tác dựng snapshot và thao tác caller sửa facts/context sau đó MUST NOT sửa nội dung snapshot đã trả về hoặc đã persist.

#### Scenario: S04 Scenario-specific fields survive snapshot construction
- **WHEN** facts chứa dwell/bbox, crowd_count và metrics, interaction_type/track_ids, hoặc pose_evidence và vehicle association theo tình huống
- **THEN** snapshot giữ nguyên các trường và giá trị tương ứng, không mất trường hoặc tự thêm lifecycle của tình huống khác

#### Scenario: S05 Input mutations do not change a constructed snapshot
- **WHEN** caller dựng snapshot rồi sửa nested detections, quality hoặc rule lineage ở facts/context đã truyền
- **THEN** snapshot đã trả về giữ nội dung ban đầu và facts/context cũng không bị thao tác dựng snapshot sửa tại chỗ

### Requirement: Evidence anchor semantics remain unchanged

Evidence request SHALL dùng source anchor do feature lựa chọn và policy lab-pre10-post20-v1 hiện hữu; MUST phân biệt onset, first_qualifying_observation và alert_condition. Session của request MUST khớp snapshot; thời điểm phát hiện muộn không được thay source anchor.

#### Scenario: S06 Onset and qualifying anchors keep their original interval
- **WHEN** Person fall có onset t=0 nhưng phát hiện t=15, hoặc Person lying persistent/on-vehicle có first qualifying observation riêng, hoặc tình huống khác có alert-condition anchor
- **THEN** request giữ đúng kind/source anchor và khoảng anchor-10 đến anchor+20; trường hợp onset t=0 vẫn yêu cầu [-10,20], không chuyển sang [5,35]

### Requirement: Validation precedes persistence without changing durable ownership

Snapshot lỗi SHALL không được persist. Snapshot hợp lệ SHALL chuyển cho module Evidence lifecycle hiện hữu để commit event/outbox/request intent và pin theo thứ tự đã quy định; snapshot construction SHALL không tự ghi storage hoặc pin.

#### Scenario: S07 Invalid facts or snapshot cannot leave durable intent
- **WHEN** facts/context thiếu trường bắt buộc, có anchor không hữu hạn, session không hợp lệ hoặc dữ liệu vi phạm event contract
- **THEN** caller nhận lỗi trước persist và không có event/outbox/Evidence intent mới cho input đó

#### Scenario: S08 Delivery retry preserves the persisted revision identity
- **WHEN** một snapshot hợp lệ đã persist nhưng giao nhận phải retry hoặc recovery chạy lại
- **THEN** event_id/revision/message_id/produced_at và request_id/interval của revision giữ nguyên; không dựng snapshot mới để thay identity của lần retry

### Requirement: Camera and session transitions retain feature isolation

Context dùng cho snapshot SHALL thuộc camera/session hiện tại. Reset continuity SHALL giữ semantics reset/cooldown đã có và SHALL không thay cấu hình riêng hay làm feature này sử dụng state của feature khác.

#### Scenario: S09 Camera-session changes do not leak context or temporal state
- **WHEN** caller xen kẽ hai camera/context hoặc reset session của một camera có nhiều feature đang hoạt động
- **THEN** snapshot mới dùng đúng camera/session/request binding, không mượn temporal evidence từ camera/feature khác và giữ config riêng sau reset
