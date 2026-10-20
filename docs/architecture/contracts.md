# Hợp đồng tích hợp hệ thống

Đặc tả cập nhật 2026-10-11; ghi chú implementation đồng bộ 2026-10-12. Một số schema/runtime/tests đã được nghiệm thu theo slices #01/#05/#06/#07/#11; không có nghĩa toàn bộ hợp đồng hoặc release gates đã đạt. [Kiến trúc](system-architecture.md) xác định module và fault boundary; tài liệu này xác định semantics tại các ranh giới. [Plan](implementation-plan.md) và [tracker](../../.scratch/system-build-slices/PRD.md) giao việc thực hiện.

## 1. PerceptionPipeline

Application sử dụng một port `PerceptionPipeline` cho cả native core và Python reference: `open(config, model_specs)`, `start`, `poll(timeout)`, `request_pose(request)`, `capabilities`, `health`, `stop`, `close`. Detector/Tracker/PoseEstimator là stage nội bộ implementation và điểm kiểm thử; application không gọi lại detect/update trên kết quả core đã xử lý. Python reference giữ vai trò oracle; deployment native giữ pixels trong C++.

- Mỗi handle scoped theo camera/session/core epoch. Implementation sở hữu decode, buffer lifetime, result ordering và tracker; tracker update tối đa một lần cho mỗi frame được nhận xử lý. Late pose là observation bổ sung, không chạy lại tracker.
- `ObservationBatch` mang camera/session/epoch/frame, event-time/timebase, model/config versions, transforms, quality/coverage và status riêng cho detection/tracking/pose. `ok_empty` chỉ là suy luận hợp lệ không có đối tượng; failed/missing/skipped/stale không chuyển thành negative.
- Pose request mang request ID, camera/session/epoch/frame, track IDs, deadline và clock domain. Native kiểm association/buffer còn hợp lệ, trả acceptance hoặc rejection rõ. Request được nhận có đúng một terminal outcome trong epoch đang sống: ok, skipped, failed, cancelled hoặc stale. Terminal outcome có reason; detection thành công không xóa pose failure.
- Queue và số request in-flight bounded. Consumer chậm không làm mất terminal outcome im lặng: giữ slot tới khi consumer nhận hoặc phát fault/reset epoch. Sau native crash, consumer kết thúc các request còn outstanding của epoch đó bằng failed/reset; không đợi response từ process đã chết.
- `stop/close` drain/cancel có timeout và release buffers; reopen tăng epoch. Result/pose từ epoch cũ bị loại. Blocking bindings release GIL; exceptions chuyển typed failure.
- Startup config là nguồn ROI/FPS ban đầu. Runtime `set_analysis_fps/set_roi`, nếu dùng, phải đi qua activation boundary với observed config version; không sửa ROI lặng lẽ giữa hai observations.

Conformance chạy cùng application consumer với hai implementation: original coordinates/status, một tracker update/frame, mixed detection-ok/pose-skipped, late pose, queue pressure, stop/reopen và stale epoch. Không ép tensor ABI hoặc numeric equality tuyệt đối giữa backends.

Implementation note (#11, `e47d6cf`): `OracleDetector` và pixel file replay là detector-stage oracle/conformance tool, không phải implementation đầy đủ của port lifecycle `PerceptionPipeline`. Canonical output có camera/session/epoch/frame, source PTS/event-time, original-coordinate boxes, transform/model/config/runtime provenance và detection status. Tracking/pose/lifecycle/queue-pressure/native conformance còn mở. Bằng chứng: [log #11](../logs/2026-10-12-ticket-11.md).

Implementation note (2026-10-14): `PerceptionExecution` tập trung execution, detection status, lineage validation và public model provenance cho edge processing/preview. `OracleDetector` chỉ nhận replay; `LiveDetector` dùng chung ONNX implementation và giữ origin live. Execution có cache một observation theo toàn bộ frame metadata trên cùng handle; caller chỉ chia sẻ handle khi model/config/source tương thích. Edge loại duplicate/stale trước tracker, reset state khi camera/session/epoch/origin/config thay đổi; explicit failed/missing/stale/skipped ngắt chuỗi temporal evidence chưa phát event, giữ cooldown và event đã persist. Preview đổi session khi chuyển nguồn/loop file; file dùng capture PTS, RTSP dùng acquisition monotonic clock được ghi rõ, chưa chứng minh mapping sang clock recorder. Đây là phần cải thiện Python lab, chưa hoàn tất lifecycle/pose/native conformance của port ở trên.

## 2. Event snapshot và identity

Mỗi AI revision là **full snapshot**, không phải delta. Identity revision là `(authenticated device_id, event_id, revision)`, revision là số nguyên dương tăng dần do edge cấp bền vững. Payload chứa schema version, camera/session, pipeline ID/version, taxonomy, origin, timestamps/uncertainty, lifecycle/severity/score, tracks/ROI, model/config/calibration provenance và evidence request references.

- `origin = live | replay | synthetic` độc lập taxonomy nghiệp vụ, bất biến suốt event. Replay vẫn có taxonomy `person_fall` để đánh giá, nhưng không thể biến thành live ở revision sau. Origin do composition/source mode xác định; server kiểm identity/mode được cấp quyền, không tin flag của UI để cho gửi notification.
- Device/event/camera/session/producer pipeline identity và origin bất biến. Session mất continuity đóng/reset event theo policy và sự kiện mới dùng UUID mới; liên kết sự kiện cũ là reference, không sửa identity cũ. Model/config lineage có thể được ghi bổ sung theo revision nhưng không rewrite history.
- Server nhận 3→1→2 vẫn lưu ba snapshots và current=3. Không đợi revision 1 để dựng current. Validate schema/identity/snapshot invariants, không bắt buộc có đủ các intermediate FSM transitions tại ingestion. Edge chịu trách nhiệm allowed transitions; history ghi revision gaps để audit. Snapshot đến đầu tiên khởi tạo identity binding trong scope device/camera được phép; mọi revision sau phải khớp, kể cả revision cũ.
- Cùng key/cùng canonical content hash trả receipt cũ; khác hash là conflict/quarantine. Transaction server ghi immutable revision, conditional newer current projection và downstream intent. Review state/version ở nhánh riêng, không bị `$set` từ snapshot AI ghi đè.
- Hash dùng canonical JSON theo schema version cho toàn nội dung snapshot: identity, schema, produced_at, provenance, payload và evidence request references. Loại transport attempt ID, sent_at, retry counter và server receipt khỏi hash. `produced_at` cố định khi tạo revision; retry không tái tạo snapshot. C03 phải pin canonicalization/numeric encoding và test vector trước producer/consumer code; không tự chọn serialization khác nhau giữa Python/C++.
- `message_id` nhận diện thông điệp logic và giữ qua retry; attempt ID là transport metadata riêng. Schema upgrade phải qua compatibility tests; không đổi nội dung/hash của revision đã persist để retry schema mới.

Fixtures bắt buộc: 3→1→2, chỉ có revision 3, hai writer concurrent, same-key/different-hash, camera/origin/session substitution, retry đổi sent_at nhưng không đổi hash và AI update xen review.

## 3. Evidence request, anchor và pin receipt

Lab dùng event ring 10 phút, pre10/post20 giây, server clips 7 ngày; outage24h là sizing budget, không phải TTL xóa unACK. Timestamp khoảng evidence dùng source event-time và mapping sang recorder session kèm uncertainty, không join frame IDs giữa hai RTSP sessions.

| Trường hợp | Anchor | Requested interval |
|---|---|---|
| Person fall có onset quan sát | onset estimate có provenance | anchor − 10s đến anchor + 20s |
| Persistent lying/on-vehicle thiếu onset | first qualifying observation của chuỗi persistence đang dùng | anchor − 10s đến anchor + 20s; không gọi anchor này là onset |
| Synthetic fixture | thời điểm anchor khai báo trong fixture | cùng policy pre/post |

Manifest/request mang `evidence_anchor_kind`, `evidence_anchor_time`, `requested_start/end`, mapping uncertainty, policy version và actual ranges/gaps. Complete được tính trên requested interval với gap tolerance đã ký. Trigger muộn tại t=15 với onset t=0 vẫn yêu cầu [-10,20], không lấy [5,35]. Khi onset/interval thay đổi tạo request mới có `supersedes_request_id`; không sửa requested range của ID đã ACK. Event revision mới liên kết request mới, artifact cũ vẫn giữ lineage/audit.

MVP pin khi event cần evidence được persist; **không tạo candidate pins mặc định**. F03 phải chứng minh ring10 phút bao phủ maximum anchor-to-pin delay (verification + scheduling/handoff + recovery), pre-roll và mapping/keyframe margin. Nếu không đủ, báo partial/missing; không ký completeness cho profile đó. Tăng ring hoặc thêm candidate hold chỉ qua policy/budget được duyệt, không pin vô hạn hoặc làm yếu bảo vệ unACK.

**Mở rộng nhóm mới — Q36 ngày 2026-10-20:** Bảng baseline person-down phía trên giữ nguyên: fall dùng onset estimate, persistent lying/on-vehicle thiếu onset dùng first qualifying observation của chuỗi persistence. Các nhóm mới trong [requirement tình huống an toàn đô thị](../requirements/urban-safety-scenarios.md) dùng source-time tại **mốc đủ điều kiện tạo cảnh báo** theo rule/ROI/lịch/ngưỡng đã phê duyệt. Cả hai policy giữ requested interval cố định anchor − 10s đến anchor + 20s; `evidence_anchor_kind` và policy version phải phân biệt theo loại, không đồng nhất onset với alert-condition anchor. Đây là đặc tả mở rộng, không tuyên bố code đã đổi; nhóm mới cần fixtures/conformance và event regression trước triển khai. Không thay protocol request/ACK hoặc sửa interval của request đã có.

Với sự kiện kéo dài, complete chỉ xác nhận coverage requested interval, không có nghĩa full episode. Mốc bắt đầu quan sát/duration/vùng/config phải có provenance; metadata không thay video hoặc chứng minh toàn bộ thời gian tồn tại. Onset ngoài clip/không quan sát được phải thể hiện rõ; không tự thêm nhiều clip hoặc NVR dài ngày.

### 3.1 Protocol commit và recovery

1. Cùng SQLite transaction: persist event revision, delivery outbox và evidence request intent (`request_id`, owner event/revision, immutable interval, state=requested). Metadata được gửi trước clip; chưa pin xong không chặn ingestion.
2. Worker gửi `pin(request_id, interval, owner)` tới recorder. Recorder atomic hóa với cleanup, ghi pin/reference và receipt bền vững trước ACK. Retry cùng ID/cùng nội dung trả receipt cũ; nội dung khác conflict. Receipt nêu coverage đã giữ và phần post-roll đang chờ, không giả có đủ dữ liệu ngay.
3. Edge lưu receipt; nếu crash trước bước này, query/retry theo request ID. Recorder reboot phải khôi phục pin ownership. Recovery đối chiếu cả request chưa ACK và pins đã ACK; không tự release pin chỉ vì analytics đang offline.
4. Recorder thu post-roll rồi tạo manifest pending; file commit theo §3.2. Worker cập nhật request thành fulfilled, partial hoặc failed với reason. Hết dữ liệu trong ring phải kết thúc rõ, không pending vô hạn.
5. Release idempotent theo request ID sau durable evidence receipt và retention policy; overlap còn owner khác vẫn giữ segment. Đổi requested interval không release artifact cũ trước khi policy cho phép. Candidate cancellation chỉ áp dụng nếu policy candidate hold riêng đã được duyệt.

Không có distributed transaction giữa analytics DB và recorder. RPC deadline/retry/query là bounded; khi recorder không truy cập được, lưu pending + operational fault, reconcile khi phục hồi. Ring hết trước recovery không thể tái tạo video đã mất.

Implementation note (2026-10-14): `EvidenceLifecycle` là chủ orchestration persist intent → pin → finalize → transfer receipt/recovery. Các entry point outbox/uploader cũ chuyển tiếp tới cùng module. File lock trên mỗi recorder root tuần tự hóa các coordinator trong cùng process hoặc khác process; recorder tiếp tục ghi độc lập. `trigger_upload()` không tự kết thúc session; caller EOF/session-loss phải truyền `finish_sessions` rõ. Recovery lấy status/manifest receipt từ recorder, không tự suy completeness từ tên file. Recorder dọn scratch của pin đã biết dưới SQLite write lock dùng chung với finalize; file chưa xác định ownership được giữ lại. Request lỗi I/O tạm thời giữ khả năng retry; receipt đã ACK được phục hồi vào outbox. Schema lưu trữ và receipt giữ nguyên; không thêm timeout policy.

### 3.2 File commit

Manifest pending intent → temp write → fsync(file) → rename → fsync(directory) → DB finalized + hash/size/actual ranges/completeness. Cùng evidence ID không được overwrite bytes sau finalized; thay nội dung tạo artifact mới có lineage. DB/file không chung transaction. Reconciliation xử lý pending/temp/final/orphan/missing/corrupt; không xóa dữ liệu có pin owner chỉ vì chưa thấy receipt phía analytics.

## 4. Các chiều trạng thái evidence

| Chiều | Giá trị semantic |
|---|---|
| Build lifecycle | pending, collecting, finalized, failed |
| Completeness | unknown, complete, partial; luôn giữ requested/actual/gaps và reason |
| Transfer | not_started, uploading, acknowledged, failed |
| Availability theo location edge/server | pending, available, missing, expired, quarantined |
| Integrity theo artifact/location | unverified, verified, corrupt |

Pin/request lifecycle thuộc §3, không dùng chung enum với artifact. Finalized có thể partial; partial vẫn được upload. Receipt ràng buộc evidence ID + hash + byte size + durable server location/commit, không chứng minh đủ pre/post. Download chỉ available khi đúng quyền và artifact hợp lệ; ACK lịch sử không biến một file đã hết hạn thành available.

Ví dụ semantic (không thay network schema):

```json
{
  "evidence_id": "clip-01",
  "build_state": "finalized",
  "completeness": "partial",
  "completeness_reason": "missing_preroll",
  "transfer_state": "acknowledged",
  "locations": {
    "edge": {"availability": "expired", "integrity": "unverified"},
    "server": {"availability": "available", "integrity": "verified"}
  }
}
```

Sau server retention, server availability thành expired; receipt/history vẫn tồn tại theo metadata policy. SLI completeness chỉ đếm complete, không đếm partial vì upload thành công. Manifest version tăng khi metadata trạng thái thay đổi; immutable artifact hash/bytes giữ nguyên.

## 5. Review freshness và correction

Review action lưu actor/time/reason, `review_version`, `reviewed_event_revision`, evidence IDs/manifest versions đã xem và decision. Review không sửa AI confidence hoặc xóa decision cũ. D02 dataset export dùng đúng revisions đã review, không join vào current rồi làm sai nhãn.

- Reviewer ghi decision bằng expected review version và exact viewed event/evidence versions. Nếu view đã cũ do thay đổi có ý nghĩa, API trả conflict để refetch và thao tác mới; không tự quyết định thay người trực.
- Lab đặt `needs_re_review` khi severity tăng, taxonomy thay đổi, evidence mới available/complete thay pending/partial, hoặc evidence đã dùng ra quyết định trở thành missing/corrupt. Update retry, URI, timestamp vận chuyển và trạng thái upload trung gian không kích hoạt. So sánh nội dung có ý nghĩa, không chỉ bất kỳ manifest version mới.
- Cờ không reset confirmed/false_positive/resolved; queue hiển thị lý do và quyết định trước. Reviewer có quyền correction/reopen bằng expected version, reason và viewed revisions; append audit, tăng review version. Reopen chuyển về unreviewed rõ do actor, không do AI tự reset.
- Xử lý AI/evidence update xen review phải atomic/conditional để không bỏ sót cờ: nếu content đổi sau action thì cờ được tính lại. Luật freshness versioned; operator duyệt policy site trước pilot.

Tests: false_positive khi clip pending rồi clip complete; severity tăng; evidence corrupt; hai reviewer concurrent; stale action; correction audit; metadata-only update không tạo bão review. Lab vẫn dashboard-only.

## 6. Downstream eligibility

Event snapshot commit cùng durable downstream decision/intent theo ADR-0002. Ý định disabled không được gọi là pending eligible; không cần broker để lưu quyết định này.

- Mỗi destination/side-effect có policy version, eligibility reason, created_at và expiry nếu policy cần. Lab: disabled, không worker phát notification. Synthetic/replay: ineligible cho notification ở mọi revision.
- Chỉ eligible intent mới vào pending→sending→delivered/retry/dead_letter/expired. Disabled/ineligible là terminal decision cho policy tại ingestion; bật provider không đổi chúng thành pending.
- Không tự backfill notification cũ. Nếu cần backfill integration feed, operator tạo job có destination/time scope/authorization và idempotency, qua policy riêng; không được dùng backfill để bỏ origin guard.
- Retry không vượt notification expiry; side-effect hết hạn vẫn giữ event history. Cleanup terminal intents theo audit/retention policy có budget; không giữ queue vô hạn. Delivered không được dùng thay disabled, broker ACK không thay receipt ingestion.

Tests: bật provider sau nhiều tuần disabled không phát backlog; policy change không tự tái gửi; retry/expiry/dedup; origin guard và downstream outage không rollback ingestion.

## 7. Replay và realtime stress

**Semantic replay:** cùng observation sequence hoặc fixed sampling plan, PTS/virtual event clock, bounded queues có backpressure và watermark source–recorder–consumer. Recorder không xoay ring vượt watermark analytics chưa xử lý. Event-time deadlines được mô phỏng theo policy fixture, không drop vì tốc độ wall-clock máy test. Fast hay paced phải cho cùng domain outcomes trên cùng inputs; perception numeric parity theo tolerance.

**Realtime stress:** nguồn chạy tốc độ thực, deadlines/queue-age/drop/fairness thật. Kiểm freshness, coverage, memory, recorder gap và degraded state; không yêu cầu event set giống semantic replay nếu quan sát bị drop. Cả hai mode giữ origin=replay và chặn notification.

## 8. Target gate có điều kiện

G3 bắt buộc **conformance + capacity trên target thực đã chọn**, không bắt buộc vendor RKNN. ONNX target: native/oracle detector/pose/track/event regression trên target + hardware/software decode path thực + soak recording/upload. RKNN target: thêm conversion A01, backend A02/A03 và #29/#30 trước capacity/rollout. Backend khác chỉ mở khi được chọn và phải có gate tương đương, không dùng N/A để bỏ target testing.

Ticket #31 và #35 có blockers chung, cộng `Conditional blockers (RKNN): #30`; #29/#30 deferred khi target không phải RKNN. PRD tracker là nguồn graph thực thi. Không coi baseline x86 pass là Raspberry Pi hoặc board khác đã đạt.
