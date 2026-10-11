# Review tổng thể thiết kế hệ thống — 2026-10-11

Trạng thái: **đã áp dụng vào thiết kế/backlog theo yêu cầu tiếp theo ngày2026-10-11**. Chưa triển khai runtime hoặc nghiệm thu. Phần findings bên dưới giữ mô tả tại thời điểm review, không phải danh sách lỗi thiết kế vẫn đang mở.

## Kết quả xử lý

| Findings | Đặc tả hiện hành / nơi đồng bộ |
|---|---|
| F01 | [Contracts §1](contracts.md): PerceptionPipeline; N01/N05/O01/P03, tickets10/13/14/22, X43 |
| F02/F03 | [Contracts §3](contracts.md): pin intent/receipt, anchor và ring budget; R02/J01/J04, tickets07/09/25/26, X38/X39 |
| F04 | [Contracts §4](contracts.md): evidence dimensions; R03/J03/E01/UI01, tickets07/08/09, X40 |
| F05 | [Contracts §2](contracts.md): snapshots/identity/origin/hash; C03/S01/S02, tickets01/05/40, X41 |
| F06 | [Contracts §5](contracts.md): viewed revisions/re-review/correction; W01/D02/UI02, tickets04/20/44, X42 |
| F07 | [Contracts §8](contracts.md): target-conditional gate; O04/A04/T02, tickets31/35 và tracker graph, X44 |
| F08 | [Contracts §7](contracts.md): semantic replay và realtime stress; V01/C01/X01, tickets06/19 |
| F09 | [Docs index](../README.md): nguồn chuẩn; bỏ draft ticket/graph/status trùng, đồng bộ research |
| F10 | [Contracts §6](contracts.md): eligibility/expiry/no-backfill; S01/W02, tickets05/42, X45 |

Thiết kế được chấp nhận qua [ADR-0004](../adr/0004-integration-contracts.md). [Log cập nhật](../logs/2026-10-11-design-contracts-refactor.md) ghi phạm vi/kiểm chứng. Findings closed ở mức tài liệu; test implementation vẫn pending.

---

Phần sau là nội dung review trước khi áp dụng:

## Kết luận

Kiến trúc có nền tảng tốt để bắt đầu các lát cắt lab: person-down trước, recorder độc lập, semantic contracts, durable ingestion, human review và gates có bằng chứng. Không cần đổi stack hoặc xây thêm service. Điểm yếu chính là **một số hợp đồng tại ranh giới chưa đủ rõ để hai nhóm triển khai độc lập cho kết quả giống nhau**, cùng với sự lệch nội dung giữa các lớp tài liệu.

Có thể bắt đầu ticket #01/#02 theo phạm vi đã duyệt, nhưng phải khóa contract thuộc ticket trước khi triển khai phần tương ứng. Chưa đủ cơ sở ký capacity, chất lượng AI hoặc pilot. Không coi việc chưa có benchmark/board/clearance là lỗi thiết kế mới: tài liệu đã ghi rõ các gate này.

## Phạm vi và bằng chứng

- Đối chiếu CONTEXT, ba ADR accepted, system architecture, implementation plan, deployment readiness và báo cáo nghiên cứu.
- Rà acceptance/checklist của 18 module, 50 ticket triển khai, breakdown, ma trận X01–X37 và gate G0–G5. Log lịch sử được dùng để nhận biết quyết định đã thay thế; không lấy log cũ ghi đè thiết kế hiện hành.
- CodeGraph status/files đúng project trả 0 files/nodes/edges; đọc Markdown trực tiếp. Không dùng index trống làm bằng chứng không có code trong mọi file local. Danh sách Git theo dõi gồm 89 file, tất cả Markdown tại thời điểm kiểm tra.
- Kiểm tra cơ học trước khi thêm báo cáo: 97 Markdown, 468 link local; không có đích link bị thiếu trong workspace. Có một link tuyệt đối tới skill ngoài repo, vì vậy kết quả này không chứng minh checkout trên máy khác tự đầy đủ.
- Graph 50 ticket không có chu trình; đủ mapping 89/89 task của mục backlog, không thiếu/thừa task ID. Mapping đủ không tự chứng minh acceptance semantic đã đầy đủ.
- Local routing toggle không bật; không gọi lma hoặc subagent. Không chạy runtime, hardware, fault injection hoặc benchmark.

## Điểm nên giữ

| Quyết định | Đánh giá |
|---|---|
| Person-down trước; vehicle có gate riêng | Phạm vi phù hợp để kiểm chứng giá trị sớm, tránh để calibration/vehicle trì hoãn luồng chính |
| Recorder sở hữu upstream độc lập analytics | Đã xử lý đúng lỗi phổ biến: tách process nhưng vẫn phụ thuộc socket của analytics |
| Missing/unknown khác negative | Đúng cho tracking, pose, ODD và dữ liệu bị gián đoạn; cần giữ tới UI và metrics |
| Event, review, evidence không đồng nhất | Hướng đúng; cần hoàn thiện một số trường/trạng thái ở F04–F06 |
| Journal/outbox atomic, ACK sau commit, object/file reconciliation | Phù hợp với offline edge và retry; không hứa exactly-once hoặc chống mất cả ổ bằng WAL |
| FastAPI/MongoDB đã chốt; một app + worker khi cần | Không có căn cứ trong review này để đổi DB/framework; giữ ADR-0003 |
| Native hot path, Python policy; oracle và conformance | Giữ lựa chọn đã xác nhận. Tối ưu là làm rõ seam, không mở lại lựa chọn ngôn ngữ |
| Gate phân biệt implemented/tested/accepted | Tốt hơn đánh dấu hoàn thành theo số checkbox; thiếu số đo đã được công khai đúng |

## Findings và đề xuất sửa

P1: cần đóng trước triển khai/nghiệm thu phần bị ảnh hưởng vì có thể gây sai tích hợp hoặc mất thông tin. P2: sửa trong lượt đồng bộ tài liệu hoặc trước bật tính năng liên quan. Đây là rủi ro từ đặc tả, không phải lỗi runtime đã tái hiện. Không có kết luận P0 từ hồ sơ hiện có.

### F01 — P1: API native tự chạy không khớp các port gọi từng stage

**Căn cứ:** [system architecture](system-architecture.md), §6.7a mô tả `open/start/poll`, native tự decode→detect→track và không chuyển pixels qua Python. §6.8/6.11 mô tả `detect(frame)`/`update(detections)`, trong khi §11.1 nói native adapter implement các port Detector/Tracker/Pose như đường reference.

**Failure path:** application gọi các stage riêng nhưng core đã thực hiện tracker; nhóm adapter phải chọn giữa chạy lặp, trả kết quả cache với semantics không rõ, hoặc làm lộ buffer/frame ownership ra Python. Pose bất đồng bộ càng làm một lời gọi đồng bộ theo frame khó tương đương.

**Sửa tối thiểu:** chốt một port ứng dụng cho luồng perception gồm lifecycle, poll observations và request pose. Native core và Python reference cùng implement seam này; detector/tracker/pose stage interfaces giữ nội bộ implementation hoặc dùng trong test. Không thêm service/process. Ghi rõ owner ordering, session reset, queue, deadline và một terminal result cho mỗi pose request; status detection và pose độc lập khi một nhánh thành công, nhánh kia skipped.

**Phạm vi:** C02/C04, N01/N05, O01, P03; ticket #10/#13/#14/#22; §6.7a/6.8/6.11/11.1 và conformance fixtures.

**Acceptance bổ sung:** cùng application consumer chạy với oracle/native; tracker chỉ update một lần/frame; pose đến muộn không update lại tracker; stop/reopen loại result epoch cũ; partial capability không bị gộp thành `ok_empty`.

### F02 — P1: Chưa khóa recovery giữa event commit và recorder ACK pin

**Căn cứ:** [kiến trúc](system-architecture.md) §6.16/6.17/7.2; [M10 R02/R03](../../.scratch/system-build/issues/11-m10-recorder-retention.md); [ticket #07](../../.scratch/system-build-slices/issues/07-event-pin-duoc-clip-pre-post-tu-ring.md). Đã có pin-vs-cleanup atomic và file finalize protocol, nhưng chưa quy định rõ durable pin intent gắn với event trước RPC/IPC pin.

**Failure path:** event đã commit và được gửi server; analytics chết trước khi gửi pin hoặc nhận ACK. Recorder vẫn ghi và xoay ring. Recovery hiện mô tả pending manifest/file, chưa chỉ ra cách tìm và gửi lại yêu cầu pin chưa hoàn tất. Chiều ngược lại, ACK pin rồi crash trước ghi liên kết có thể để segment bị giữ không rõ chủ.

**Sửa tối thiểu:** lưu evidence request ID, event reference, requested range và trạng thái request cùng transaction event/outbox; recorder nhận pin idempotent theo request ID và trả receipt có thể query lại. Ghi pin receipt ở phía recorder bền vững trước ACK; recovery đối chiếu request/receipt, release có chủ và idempotent. Không cần distributed transaction.

Không hứa khôi phục video đã bị ring xóa: nếu recovery vượt cửa sổ còn dữ liệu phải báo partial/missing. Nếu cần bảo đảm trong một RTO cụ thể, sizing ring/hold margin phải bao gồm RTO đó.

**Phạm vi:** C03/R02/J01/J04, #07/#09/#14; mở rộng X09/X10/X12.

**Acceptance bổ sung:** crash sau event commit trước pin; sau recorder ACK trước local receipt; recorder reboot rồi retry; request đã quá ring; không có unowned pin hoặc event bị treo evidence_pending vô hạn.

### F03 — P1: Pre/post chưa có mốc chuẩn và quan hệ với thời gian xác minh

**Căn cứ:** [readiness](deployment-readiness.md) chốt pre10/post20/ring10 phút; [kiến trúc](system-architecture.md) §5.7 lưu candidate/onset/detection, §6.15 có persistent lying và §6.16 chỉ nói pin requested interval. X11 kiểm đủ pre/post nhưng chưa chốt tính quanh thời điểm nào.

**Failure path:** người ngã tại t=0 nhưng suspected sau khi xác minh tại t=15. Clip lấy quanh detection với pre10 bắt đầu t=5, bỏ mất pha ngã dù UI có thể ghi đủ pre-roll. Với verification lâu hơn ring, onset đã bị xóa trước pin.

**Sửa tối thiểu:** thêm `evidence_anchor_kind/time`, requested start/end, time mapping uncertainty và policy version. Quy định riêng fall có onset, lying thiếu onset và event update. Cân nhắc pin tạm từ candidate với budget và release khi rejected/expired theo policy được chốt; hoặc chứng minh ring đủ cho maximum verification delay + pre-roll + handoff/recovery margin. Không tự tạo hold vô hạn.

**Phạm vi:** C03/I01/I02/R02/F03, #07/#25/#26, X11/X21.

**Acceptance bổ sung:** late trigger 15 giây; lying không biết onset; onset điều chỉnh ở revision sau; ring không đủ; timestamp uncertainty. Complete phải tính theo requested interval đã chốt, không chỉ chiều dài file.

### F04 — P1: Evidence completeness đang bị trộn với lifecycle/upload state

**Căn cứ:** [kiến trúc](system-architecture.md) §7.5 đặt `partial/failed/expired` cạnh `finalized_local/uploading/uploaded`; §6.17 bước 3 cho `finalized_local` hoặc `partial`.

**Failure path:** clip thiếu pre-roll nhưng đã upload và hash hợp lệ phải đồng thời là partial và uploaded. Nếu dùng một enum theo chuỗi hiện tại, chuyển sang uploaded có thể làm mất cờ partial, hoặc clip partial không được upload vì chưa ở finalized_local. Trường URI/storage state hiện có giúp phân biệt vị trí nhưng chưa đủ khóa transition/completeness.

**Sửa tối thiểu:** đặc tả các chiều riêng: lifecycle tạo artifact, completeness, transfer state và availability/integrity. Có thể là vài trường enum trên manifest hiện có, không cần module mới. Nêu rõ finalized không đồng nghĩa complete, và receipt chứng minh artifact cụ thể đã lưu chứ không chứng minh đủ interval.

**Phạm vi:** C03/R03/J03/E01/E02/UI01; #07/#08/#09; X10/X15/X18.

**Acceptance bổ sung:** partial finalized→upload retry→receipt vẫn partial; uploaded nhưng bị server retention xóa là expired; corruption không được che bởi trạng thái delivered; UI và SLI completeness dùng đúng trường.

### F05 — P1: Out-of-order revision chưa chốt snapshot hay delta và immutable fields

**Căn cứ:** [kiến trúc](system-architecture.md) §5.7/6.19; [M01 C03](../../.scratch/system-build/issues/02-m01-contracts-conformance.md); [M12 S01/S02](../../.scratch/system-build/issues/13-m12-backend-evidence.md). Đã có unique key/canonical hash/current projection và yêu cầu revision hợp lệ mới hơn, nhưng chưa định nghĩa cách revision đến trước revision đầu tiên vẫn hợp lệ.

**Failure path:** revision 3 tới trước 1/2. Nếu là delta, server không đủ dữ liệu dựng current; nếu validate transition như FSM liên tục thì có thể reject trạng thái hợp lệ chỉ vì mất thứ tự. Nếu cho phép mọi snapshot mới hơn mà không khóa identity/origin, một revision có thể thay camera hoặc biến event replay thành live.

**Sửa tối thiểu:** dùng full snapshot cho mỗi AI revision ở MVP; current = revision hợp lệ cao nhất, history giữ đủ và ghi gap nếu cần. Khóa device/event/camera/origin theo event; chỉ cho đổi session theo policy rõ, không mặc nhiên cho payload mới ghi đè ownership. Tách `origin=live/replay/synthetic` khỏi taxonomy nghiệp vụ; origin không thay đổi qua revisions. C03 đã giao canonical hash: hoàn thiện trường được hash và exclusions của transport, không tạo một framework hash mới.

**Phạm vi:** C03/J02/S01/S02/H02, #01/#05/#14/#40; X13/X17/X31.

**Acceptance bổ sung:** ingest 3→1→2; revision 1 không bao giờ tới; same key different payload; đổi origin/camera bị reject; retry đổi thời gian truyền vẫn giữ identity nội dung đúng. Nếu chọn delta thay snapshot, bắt buộc có base revision/buffer/recovery protocol trước implementation.

### F06 — P1: Giữ review state nhưng chưa biểu diễn review đã lạc hậu

**Căn cứ:** [kiến trúc](system-architecture.md) §7.5; [M13 W01](../../.scratch/system-build/issues/14-m13-review-demo-ui.md); [M14 D02](../../.scratch/system-build/issues/15-m14-data-evaluation.md). D02 đã liên kết label với exact revision, nhưng review workflow chỉ có unreviewed/confirmed/false_positive/resolved và không bị AI revision reset.

**Failure path:** reviewer đánh false_positive khi clip pending/partial. Sau đó clip hoàn chỉnh hoặc severity tăng; hệ thống giữ false_positive đúng như đặc tả nhưng chưa có quy tắc đưa thông tin mới trở lại sự chú ý của người trực. Hai reviewer conflict đã được test không bao phủ ca này.

**Sửa tối thiểu:** lưu `reviewed_event_revision` và evidence version đã xem trong review action; tính cờ cần xem lại theo những thay đổi có ý nghĩa đã được product định nghĩa. Giữ quyết định cũ và audit, không tự tăng confidence hoặc xóa review. Bổ sung thao tác correction/reopen có quyền và expected review version. Có thể dùng cờ trong queue hiện có, không cần workflow engine.

**Phạm vi:** W01/S02/D02/UI02/UI03, #04/#20/#44; X17/X37.

**Acceptance bổ sung:** false_positive rồi evidence mới/severity mới; refresh không tự xác nhận revision chưa xem; reviewer sửa quyết định có reason/audit; update metadata không quan trọng không gây bão re-review.

### F07 — P1 kế hoạch: RKNN trở thành điều kiện bắt buộc của mọi pilot

**Căn cứ:** Q1/Q4 trong [plan](implementation-plan.md) cho ONNX khi board chưa chọn và RKNN khi chọn target. Nhưng [#31](../../.scratch/system-build-slices/issues/31-capacity-target-duoi-record-upload-pose-load.md) bị chặn bởi #30 RKNN; #35 cũng chờ #30, #38/#39/#49 phụ thuộc tiếp. [G3.02 và G4a.01](../implementation-checklists/integration-release.md) bắt buộc A01–A05 và G1–G3.

**Hệ quả:** chọn target x86/ONNX hoặc Raspberry Pi software-only vẫn không có đường hợp lệ qua capacity/rollout/pilot nếu không làm RKNN. Đây là hard blocker trong graph, không chỉ đoạn văn khuyến nghị.

**Sửa tối thiểu:** tách gate “target backend conformance” khỏi nhánh “RKNN portability”. Capacity/soak/rollout cần backend đã chọn và report tương ứng; chỉ bắt #29/#30 khi target là RK3588/RKNN. Giữ nguyên tiêu chuẩn capacity/recovery/hardware, không bỏ G3. Đồng bộ dependency trong ticket, PRD/breakdown, phase diagram và release checklist; không chỉ thêm chú thích.

**Acceptance bổ sung cho tài liệu:** dry-run hai target profiles ONNX và RKNN; cả hai có đường tới G4a, RKNN vẫn bắt conversion/parity, ONNX vẫn bắt native/oracle parity + actual target soak.

### F08 — P2: Deterministic replay và stress realtime cần hai contract khác nhau

**Căn cứ:** [kiến trúc](system-architecture.md) §7.4 drop stale/deadline và §7.6 fast/realtime; [X01](../implementation-checklists/integration-release.md) yêu cầu cùng clip fast/realtime cho outcomes giống nhau.

**Failure path:** fast replay đẩy nguồn nhanh hơn consumer hoặc recorder tiến trước analytics, khiến drop/pose expiry/ring expiry khác realtime. PTS đúng vẫn không bảo đảm cùng tập observations. Test có thể báo fail do scheduler chứ không do FSM, hoặc phải vô hiệu hóa deadline để pass và không còn test realtime thật.

**Sửa tối thiểu:** semantic replay dùng cùng observation sequence/sampling plan, virtual event clock và phối hợp watermark nguồn–recorder–consumer; không áp wall-clock drop ngẫu nhiên. Realtime stress dùng deadline/backpressure thật, kiểm bounded resources/coverage/degraded chứ không hứa event set tuyệt đối giống fast mode. Không thay yêu cầu duration rules theo PTS.

**Phạm vi:** V01/C01/C05/R01/O02, #06/#10/#19; tách expected outcomes X01 khỏi X06/X22.

### F09 — P2: Nhiều nguồn tài liệu còn chứa quyết định đã bị thay thế

**Căn cứ cụ thể:**

- [Research report](../../traffic-ai-camera-research/report.md) §5/8.3/12.1 còn PostgreSQL; ADR-0003 chốt MongoDB. §12.1 còn tracker native C++ “chỉ sau profiling”; Q4 chốt tracker C++ P1.
- [Architecture](system-architecture.md) §6.16/15 còn hỏi event ring hay continuous NVR; Q2 trong plan đã chốt ring cho bản đầu. Có thể vẫn mở cho production tương lai, nhưng chưa được ghi giới hạn đó ngay tại câu hỏi.
- [Plan](implementation-plan.md) đầu file vẫn “chờ xác nhận”; [tracker slices](../../.scratch/system-build-slices/PRD.md) ghi breakdown đã được duyệt. Việc duyệt backlog không đồng nghĩa đã cấp quyền chạy production, nhưng trạng thái tài liệu cần chỉ rõ còn chờ điều gì.
- [Checklist README](../implementation-checklists/README.md) hướng dẫn claim/cập nhật module, trong khi tracker slices nói ticket mới là đơn vị thực thi và không nhân đôi tiến độ.

**Sửa tối thiểu:** ghi thứ tự nguồn chuẩn: ADR/quyết định accepted → kiến trúc/contract hiện hành → ticket thực thi → checklist nghiệm thu; research/log chỉ là căn cứ lịch sử. Đánh dấu các đề xuất cũ superseded và trỏ quyết định mới. Không sửa lại lịch sử log. README checklist cần dẫn tới tracker slices và chỉ rõ chỗ cập nhật tiến độ.

**Acceptance:** không còn hai phát biểu “hiện hành” trái nhau cho DB/native/ring/tracker status; quyết định production chưa chốt vẫn giữ pending. Link skill tuyệt đối ngoài repo được ghi là phụ thuộc môi trường hoặc thay bằng mô tả đủ tự đọc.

### F10 — P2 trước bật downstream: Chưa chốt số phận intent được tích lũy khi disabled

**Căn cứ:** ADR-0002, [M13 W02](../../.scratch/system-build/issues/14-m13-review-demo-ui.md), [#05](../../.scratch/system-build-slices/issues/05-retry-va-revision-khong-lam-mat-hoac-lui-event.md) và [#42](../../.scratch/system-build-slices/issues/42-downstream-delivery-theo-protocol-duoc-bat.md). Đã yêu cầu persist intent và disabled/pending ở lab, không delivered giả.

**Failure path:** sau nhiều tuần mới bật worker, pending intent cũ có thể bị phát hàng loạt; hoặc intent disabled tồn tại không giới hạn dù không bao giờ có consumer. Guard synthetic giải quyết replay/synthetic nhưng không tự giải quyết live events cũ.

**Sửa tối thiểu:** phân biệt disabled/ineligible với pending eligible; lưu routing policy/version và thời hạn side effect nếu cần. Bật provider không tự backfill notification; backfill là hành động có scope rõ. Raw event history và downstream integration feed có thể có retention khác notification. Xác định cleanup intent đã terminal mà vẫn giữ audit cần thiết.

**Phạm vi:** S01/W02/C03, #05/#42, X31; không cần thêm broker hiện tại.

**Acceptance:** bật provider sau thời gian disabled không phát thông báo cũ ngoài policy; event hết hạn side effect vẫn còn history; retry hợp lệ và idempotency không bị phá; synthetic/replay luôn bị chặn notification.

## Tối ưu triển khai sau khi đóng findings

1. **Giữ quy mô hệ thống hiện tại.** Một analytics app, recorder độc lập, một backend + worker cần thiết, MongoDB lab đã chốt. Không thêm Kafka, microservices, shared memory hoặc workflow framework để giải các khoảng trống trên.
2. **Đầu tư vào một bộ ví dụ hợp đồng nhỏ.** Event snapshot, review action, partial-uploaded evidence, pin intent/receipt và pose late result đủ để producer/consumer chốt hành vi. Contract fixtures quan trọng hơn thêm sơ đồ class.
3. **Sửa tài liệu tại nguồn thay vì thêm nhiều lớp checklist.** Cập nhật các mục/ticket đã nêu; báo cáo này chỉ lưu phát hiện và lý do. Có thể thêm docs check cho links, task coverage, DAG và accepted-decision references khi có CI; chưa cần framework quản trị tài liệu.
4. **Sizing theo backlog sau outage, không chỉ 24h tồn tại.** Hồ sơ F03/J05 đã giao sizing; khi điền số cần ghi tốc độ upload hữu dụng U, tốc độ sinh evidence mới G và backlog B. Nếu U ≤ G thì backlog không thoát; nếu U > G, thời gian drain xấp xỉ B/(U−G), cùng đơn vị. Tính thêm pins/postroll/temp/WAL và event burst; số chưa đo vẫn pending.
5. **Quality gate cần protocol cụ thể.** D03/D04 đã yêu cầu sampling probability/uncertainty; hoàn thiện matching window, trọng số sampling, denominator, no-alert missing coverage và tối thiểu mẫu trước G2. Không tính recall bằng cộng raw counts của mẫu phân tầng có xác suất lấy khác nhau. Đây là deliverable đã giao, không phải yêu cầu xây thêm data platform.
6. **Chốt concurrency/persistence từ measured demand.** Serial inference và một worker giao nhận có thể đủ lab; chỉ thêm concurrency khi queue-age/throughput chứng minh cần. Không cắt auth, validation, buffer lifecycle hoặc recorder durability để giảm code.

## Thứ tự chỉnh tài liệu đề xuất

| Đợt | Việc | Mốc cần xong |
|---|---|---|
| A | F05 event snapshots/origin, F04 evidence fields, F02–F03 pin/ranges, F06 review version | Trước các ticket #01/#04/#05/#07/#08 đóng contract/acceptance tương ứng |
| B | F01 native seam và F08 hai chế độ replay | Trước #10/#13/#14/#22 |
| C | F07 target-conditional dependency, F09 nguồn chuẩn/trạng thái tài liệu | Trước claim nhánh target; F09 nên sửa ngay cùng đợt A |
| D | F10 downstream eligibility/backfill và sizing/quality protocol có số thật | Trước bật #42; sizing/quality theo G0/G2/G3 |

Không đề xuất đổi ba ADR accepted. F01 cụ thể hóa seam, F07 làm dependency phù hợp lựa chọn target có điều kiện. Những policy nghiệp vụ mới như re-review, candidate hold/release hoặc notification backfill cần owner chốt khi sửa đặc tả; báo cáo này không tự coi chúng đã accepted.

## Đối chiếu nguồn kỹ thuật bên ngoài và giới hạn

- [SQLite synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous): xác nhận WAL/FULL là lựa chọn phù hợp cho mục tiêu giữ committed transaction qua power failure trong giả định storage thực hiện sync; không thay power-cut test trên BOM.
- [MongoDB transaction production considerations](https://www.mongodb.com/docs/manual/core/transactions-production-consideration/): standalone không hỗ trợ multi-document transaction. Trang production hiện diễn đạt topology multiple-node replica set; không lấy đó làm chứng minh riêng cho lab một-member. ADR-0003 đã yêu cầu exact-version transaction/retry tests, cần thực hiện trước claim lab topology đạt; review này không kết luận one-member đã được chạy hoặc không thể chạy.
- Đã mở [TUF specification](https://theupdateframework.github.io/specification/), nhưng bản trích xuất không đủ nội dung để làm kiểm chứng sâu rollout. Không đưa ra kết luận TUF compliance.

Không refresh giá bán/quote phần cứng, không tái thẩm định toàn bộ luật/license/checkpoint và không coi citation cũ là clearance hiện tại. Chỉ rà tính nhất quán của các gate này. Chưa có test runtime/hardware/browser hoặc số đo chất lượng mới. Mọi nhận xét failure path ở trên là phân tích thiết kế cần chuyển thành fixture/test khi implementation bắt đầu.
