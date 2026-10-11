# Bản đề xuất tracer-bullet tickets

Ngày: 2026-10-11. Trạng thái: approved-published. Người dùng đã duyệt bằng “đồng ý”; [50 ticket riêng đã publish](../../.scratch/system-build-slices/PRD.md). Chưa claim hoặc thay đổi parent issues.

Nguồn: [checklist hiện hành](README.md), [plan](../architecture/implementation-plan.md), [skill to-tickets](/home/tieubaoca/.agents/skills/to-tickets/SKILL.md).

50 lát cắt bao phủ đủ 89 task nguồn. Một task có thể xuất hiện ở nhiều ticket theo mốc baseline/integration/hardening; không có nghĩa phải hoàn thành toàn task/module trước mọi consumer. Mapping dưới đây là traceability, không tự là blocking edge.

## Quy ước đề xuất

- Mỗi ticket hoàn tất một luồng hẹp qua các layer liên quan và có demo hoặc kiểm chứng độc lập; tooling/facts/hardware gate là deliverable verifiable, không ép thêm UI không cần thiết.
- Không có source runtime để prefactor theo hồ sơ hiện hành; baseline được xây tăng dần. Không tạo ticket scaffold/interface tổng quát.
- Blocked by chỉ là ticket thực sự phải hoàn tất trước. Hardware/camera/rights/owner/threshold approvals là external prerequisites ghi riêng; không tự giả đã có.
- Những ticket hardware, privacy/policy/sign-off hoặc đội UI cần người tương ứng; khi publish chọn ready-for-human/needs-info nếu còn điều kiện ngoài chưa đủ, không auto-ready-for-agent cho công việc chưa đặc tả đủ.
- Ticket42 downstream và 46–48 vehicle có điều kiện bật; không nằm trong blocker của person-down pilot nếu tính năng đó không bật.
- Giữ nguyên PRD/issues theo module hiện có. Sau duyệt, publish mỗi slice một file trong feature tracker riêng, đánh số dependency order; không đóng/sửa parent issues.

## Các ticket đề xuất

### 01: Event synthetic xuất hiện trên dashboard

**Blocked by:** None (can start immediately).

**What it delivers:** Gửi một event synthetic từ edge lab, lưu event cùng delivery intent bền vững, server commit rồi hiển thị metadata trên demo.

Traceability: C01 C03 B01 J01 S01 UI01.

Tiêu chí dự kiến:

- [ ] Mongo replica set lab có persistent volume và readiness transaction; device auth/schema limits có ngay trong luồng đầu.
- [ ] SQLite event/outbox và Mongo revision/current/downstream intent atomic; receipt chỉ sau commit; synthetic không notification.

### 02: Hồ sơ lab, ODD và protocol nghiệm thu

**Blocked by:** None (can start immediately).

**What it delivers:** Probe môi trường hiện có và tạo hồ sơ facts/workload/ODD/sizing/failure protocol dùng để quyết định các nhánh live và hardware.

Traceability: F01 F02 F03 F04 F05 F06 D01.

Tiêu chí dự kiến:

- [ ] Facts có nguồn probe, camera chưa có/board chưa chọn/threshold chưa duyệt ghi pending, không bịa capacity.
- [ ] Target Q6/Q16, quyền samples/model và owner/gap/RPO/RTO/quality/review protocol được phân biệt với số đo.

### 03: Doctor và config fail-fast qua đường chạy lab

**Blocked by:** #01.

**What it delivers:** Người triển khai kiểm config/artifact rồi start analytics; enabled config sai dừng rõ, disabled có reason và không lộ secrets.

Traceability: B01 B02 F05.

Tiêu chí dự kiến:

- [ ] Allowlisted factories và immutable config hash/provenance; wrong artifact/backend/field làm startup nonzero.
- [ ] Doctor báo capability thực; không silent fallback, recorder độc lập không bị stop vì analytics config sai.

### 04: Review event có kiểm soát phiên bản

**Blocked by:** #01.

**What it delivers:** Reviewer mở detail, xác nhận/false_positive/resolve qua API và thấy kết quả audit trên demo.

Traceability: W01 UI02 S02.

Tiêu chí dự kiến:

- [ ] Hai reviewer cùng expected version có một conflict rõ; UI refetch và chờ thao tác mới.
- [ ] Review không sửa AI confidence hoặc bị AI revision reset; unauthorized/invalid transition bị reject.

### 05: Retry và revision không làm mất hoặc lùi event

**Blocked by:** #01.

**What it delivers:** Edge retry sau mất response; dashboard vẫn giữ một lịch sử event đúng và current view mới nhất.

Traceability: J02 S01 S02 C03 W02.

Tiêu chí dự kiến:

- [ ] Duplicate/reorder/cùng revision khác hash được xử lý rõ; crash sau server commit trước response không tạo duplicate side effect.
- [ ] Downstream intent bền vững nhưng disabled/pending ở lab; không no-op delivered hoặc notification synthetic.

### 06: Recorder file replay giữ raw ring độc lập

**Blocked by:** #02.

**What it delivers:** Chạy recorder từ file cleared theo thời gian nội dung; dừng analytics vẫn query được raw segments và actual ranges.

Traceability: V01 R01 C01 C03.

Tiêu chí dự kiến:

- [ ] Compressed segments có codec/keyframe/PTS/session metadata và ring lifecycle; raw không overlay.
- [ ] Fast/realtime giữ semantic time; pre-roll chưa có báo rõ, không giả RTSP camera test đã chạy.

### 07: Event pin được clip pre/post từ ring

**Blocked by:** #01, #06.

**What it delivers:** Event synthetic yêu cầu interval và nhận manifest clip có requested/actual ranges, complete hoặc partial.

Traceability: R02 R03 C03 I01.

Tiêu chí dự kiến:

- [ ] Pin ACK atomic với cleanup, overlap/duplicate/release không làm mất segment còn chủ.
- [ ] Pending→temp→fsync file→rename→fsync dir→DB finalize; đủ dữ liệu giữ pre10/post20, gap là partial.

### 08: Upload evidence và phát lại trên detail

**Blocked by:** #07.

**What it delivers:** Clip edge upload tới server, người trực xem/download qua detail kể cả event metadata đến trước clip.

Traceability: J03 E01 E02 UI01 UI02.

Tiêu chí dự kiến:

- [ ] Upload retry/resume cùng evidence identity, verify hash/size trước receipt; metadata/clip ACK tách.
- [ ] Server kiểm object ownership/authz, range/content type; pending/failed rõ, H.265 có playback path được kiểm hoặc lỗi rõ.

### 09: Khôi phục event/evidence sau process crash

**Blocked by:** #05, #08.

**What it delivers:** Restart edge/server giữa các bước commit và upload; detail phản ánh đúng clip còn, thiếu, partial hoặc corrupt.

Traceability: J04 R03 E02.

Tiêu chí dự kiến:

- [ ] Inject pending/temp/final/orphan/missing/corrupt và uploading unknown response; reconcile có expected state.
- [ ] Không DB complete giả khi file thiếu; không orphan tăng vô hạn, dữ liệu protected giữ và faults rõ.

### 10: File replay đi qua native boundary an toàn

**Blocked by:** #03, #06.

**What it delivers:** Nguồn file qua C++ software decode và binding metadata-only, start/stop/poll/reopen kiểm chứng được.

Traceability: C02 C04 N01 V03.

Tiêu chí dự kiến:

- [ ] Một nguồn struct/enum authoritative, generation/version mismatch/round-trip tests; stride/color/lifetime fixtures.
- [ ] GIL release lúc block, typed error, bounded output và buffer release cả drop/cancel/partial startup.

### 11: ONNX oracle xuất detection có provenance

**Blocked by:** #02.

**What it delivers:** Replay mẫu cleared qua detector oracle, xuất canonical detections/timing/transform để đối chiếu deployment.

Traceability: N02 C05 V01 F05.

Tiêu chí dự kiến:

- [ ] Exact model/hash/label/pre-post/runtime pinned; bbox original coords, empty/invalid output phân biệt.
- [ ] Golden fixture hashes/tolerances có version; chạy không yêu cầu board đích hoặc target SDK.

### 12: Native detector đạt parity với oracle

**Blocked by:** #10, #11.

**What it delivers:** C++ decode/preprocess/ORT/postprocess xuất metadata detection đúng semantic kit.

Traceability: N03 N04 C05.

Tiêu chí dự kiến:

- [ ] Golden tolerance và inverse transform/color/NMS đạt; không double normalize.
- [ ] ASan/UBSan phù hợp cùng slow consumer/drop/cancel/restart không leak/use-after-free; timings từng stage có report.

### 13: Native tracks có time và session semantics

**Blocked by:** #12.

**What it delivers:** Detection qua ByteTrack oracle/native, consumer nhận track lifecycle/history bounded theo từng camera.

Traceability: K01 K02 N05 C02.

Tiêu chí dự kiến:

- [ ] Variable FPS/gaps/out-of-order/reset có same policy; measured/predicted rõ và aging theo thời gian.
- [ ] Hai camera/epoch cùng local track ID không trộn state; Python hot path không nhận pixels.

### 14: Pipeline baseline biến observations thành event

**Blocked by:** #05, #07, #13.

**What it delivers:** Observation metadata đi qua feature factory và pure IncidentEngine để event xuất hiện trên dashboard có pipeline provenance.

Traceability: O01 O02 I01 C03.

Tiêu chí dự kiến:

- [ ] Per-camera/session/pipeline state riêng, chia sẻ perception tương thích; synthetic fixture chưa coi là person-down quality.
- [ ] Queue/deadline/cancel bounded; slow consumer không chặn recorder, valid events không drop như frames.

### 15: Camera RTSP live giữ correlation với recorder

**Blocked by:** #02, #14.

**What it delivers:** Một camera thực đồng thời record và analytics; disconnect/reconnect/codec change vẫn tạo event/clip có time mapping rõ.

Traceability: V02 V03 V04 F04 R01.

Tiêu chí dự kiến:

- [ ] Stream ADR dựa probe firmware/sessions; dual hoặc recorder-owned relay, không analytics-owned upstream.
- [ ] Session/discontinuity/uncertainty và actual ranges đúng; thiếu camera giữ ticket blocked, không thay bằng file demo.

### 16: Startup/shutdown giữ recorder và state đúng

**Blocked by:** #09, #14.

**What it delivers:** Người vận hành restart analytics, delivery và recorder theo lifecycle; pre-roll chưa đủ/boot mới hiển thị đúng.

Traceability: B03 R06 N01.

Tiêu chí dự kiến:

- [ ] Reconcile trước analytics, graceful drain có timeout, forced kill vẫn recover và reset epoch.
- [ ] Kill/hang analytics không dừng recorder; đo gaps theo protocol, không gắn config sai thành runtime recovery.

### 17: Health phản ánh khả năng quan sát thực

**Blocked by:** #14.

**What it delivers:** Dashboard/health API cho biết starting/degraded/unavailable và lý do, frame age/outbox/disk/recorder thay vì chỉ process running.

Traceability: H01 UI01.

Tiêu chí dự kiến:

- [ ] Logs correlation/secret masking, bounded labels/spool; không event/frame ID làm metric label.
- [ ] Inject deadlock/queue stall/record gap có fault, thiếu clock mapping báo receive age thay capture age giả.

### 18: Quota bảo vệ pinned evidence và journal

**Blocked by:** #09, #17.

**What it delivers:** Khi disk áp lực, hệ thống cleanup dữ liệu eligible rồi báo degraded/partial cho clip mới mà không xóa unACK.

Traceability: R04 J01 R05 F03.

Tiêu chí dự kiến:

- [ ] Quotas tính pins/postroll/temp/proxy/WAL/reserve; disk95/100/write/fsync/checkpoint errors có test.
- [ ] State reserve hết thì không commit/ACK giả; outage24h không là TTL xóa protected evidence.

### 19: Nghiệm thu vertical slice G1 trên lab

**Blocked by:** #04, #08, #15, #16, #17, #18.

**What it delivers:** Reproduce file/live event→clip→server→review và ký report latency/completeness/recovery của lab.

Traceability: F06 C05 UI01 R06.

Tiêu chí dự kiến:

- [ ] Case X01–X19 và baseline X27/X31 có manifest/results; browser API thật, metadata trước clip.
- [ ] P95 durable edge commit→render ≤5s trên LAN có sample count/clock uncertainty; không ký AI quality/hardware capacity.

### 20: Feedback review thành nhãn dataset có lineage

**Blocked by:** #02, #04, #08.

**What it delivers:** Reviewer correction được lưu như nhãn có version/audit rồi export dataset được phép với exact event/clip/model/config revision.

Traceability: D01 D02 UI03.

Tiêu chí dự kiến:

- [ ] API/export kiểm scope, ambiguous labels rõ; correction không overwrite nhãn gốc/AI outputs.
- [ ] Split site-camera-time và quyền dữ liệu được kiểm; sensitive data không commit vào repo.

### 21: Quality và ODD đi xuyên tới event/detail

**Blocked by:** #17.

**What it delivers:** Blur/dark/freeze/missing/camera-moved được native đo, domain áp policy và event/detail hiển thị uncertainty.

Traceability: QL01 QL02 QL03.

Tiêu chí dự kiến:

- [ ] Cảnh tĩnh khác frozen; metrics missing/stale không negative, pixels không đi Python mỗi frame.
- [ ] Site thresholds có version, recovery reason rõ; camera-moved P2 không chờ calibrated geometry.

### 22: Pose request trả keypoints đúng frame và track

**Blocked by:** #11, #13.

**What it delivers:** Gửi ROI request có deadline tới native ORT pose và nhận pose/status trong observation metadata.

Traceability: P01 P03 C05.

Tiêu chí dự kiến:

- [ ] Oracle/native RTMPose crop/affine/SimCC/schema parity; original coordinate/missing keypoints rõ.
- [ ] Bounded buffer cache; expired/skipped/stale/ID switch không gắn pose nhầm frame; request fixture dùng trước automatic scheduling.

### 23: Track gap không tạo certainty hoặc motion giả

**Blocked by:** #13, #02.

**What it delivers:** Replay occlusion/ID switch/variable FPS từ dataset và xuất history/association uncertainty đáng tin cho consumers.

Traceability: K03 D01.

Tiêu chí dự kiến:

- [ ] Report fragmentation/ID switch theo ODD; nối history thận trọng, không dùng track ID làm danh tính.
- [ ] Expected sequences qua epoch/gaps và pose association có regression, không hard-code nối bằng bbox proximity.

### 24: Pose scheduling và degradation có coverage

**Blocked by:** #21, #22, #23.

**What it delivers:** Fast-fall, slow-collapse và lying được sampling công bằng; overload giảm công việc có capability reason tới dashboard.

Traceability: P02 P04 O03 O02.

Tiêu chí dự kiến:

- [ ] Đo scheduled/attempted/skipped/failed/stale và coverage từng nhánh, không chỉ trigger y spike.
- [ ] Burst/deadline/fairness/hysteresis/recovery test; recorder tiếp tục và mất capability không báo healthy/negative.

### 25: Person fall có onset quan sát

**Blocked by:** #14, #24.

**What it delivers:** Replay ca ngã nhanh/chậm có onset qua pose/history thành suspected person_fall và evidence/review flow.

Traceability: I02 I05.

Tiêu chí dự kiến:

- [ ] Pure FSM durations/hysteresis theo event-time; unsupported/unknown không kết luận chắc.
- [ ] Positive/hard-negative/occlusion/reset sequences có expected transitions; event rule/model/config provenance giữ.

### 26: Persistent lying khi thiếu onset

**Blocked by:** #25.

**What it delivers:** Người nằm bền vững trong ROI vẫn vào review khi onset bị mất hoặc không quan sát được.

Traceability: I02 I05.

Tiêu chí dự kiến:

- [ ] Missing onset/ID switch/gaps/lying from first frame có fixtures; không rơi vào khoảng trống fall-only.
- [ ] Taxonomy/severity/duration riêng, evidence coverage và uncertainty được hiển thị; không chẩn đoán y khoa.

### 27: On-vehicle vẫn review với ưu tiên riêng

**Blocked by:** #26.

**What it delivers:** Người ngả trên xe đã stationary/upright tạo event review ưu tiên thấp; xe đổ/ngã cạnh xe có danger override.

Traceability: I03 I04 UI03.

Tiêu chí dự kiến:

- [ ] Association có uncertainty/history, không suppress vì bbox overlap hoặc kết luận ngủ/bất tỉnh.
- [ ] Lab không notification khẩn; product protocol chưa ký vẫn lưu/review event, chưa bật hazard scope ngoài yêu cầu.

### 28: Negative audit và quality regression G2

**Blocked by:** #20, #27.

**What it delivers:** Lấy mẫu no-alert trước ring expiry, review độc lập rồi xuất report recall/FP/coverage/review load có uncertainty.

Traceability: D03 D04 D05 I05 R04.

Tiêu chí dự kiến:

- [ ] Sampling probability/site-time-weather/rights/budget/coverage lưu được; expected-count fixture và held-out splits pass.
- [ ] Reports golden+event regression versioned; G2 cần target/sample/owner đủ, alerts-only không được báo recall.

### 29: Build artifact target reproducible

**Blocked by:** #02, #11.

**What it delivers:** Sau khi chọn board, convert ONNX→RKNN offline và xuất target manifest/report có thể tái tạo.

Traceability: A01 F05.

Tiêu chí dự kiến:

- [ ] Pin SDK/runtime/operator/quantization data/terms/hashes; unsupported conversion có lỗi rõ.
- [ ] No startup conversion; chưa chọn target/weights clearance thì chưa target release, baseline lab vẫn độc lập.

### 30: RKNN thay engine giữ event semantics

**Blocked by:** #28, #29.

**What it delivers:** Chạy target detector/pose/RGA adapter qua same pipeline, đối chiếu oracle/native và event regression.

Traceability: A02 A03 C05.

Tiêu chí dự kiến:

- [ ] Shape/layout/dtype/color/stride/dequant/transform/lifetime đạt conformance; failures/fallback explicit.
- [ ] Golden+held-out detections/pose/tracks/events trong tolerance; đổi engine startup/restart analytics không dừng recorder.

### 31: Capacity target dưới record/upload/pose load

**Blocked by:** #30, #18.

**What it delivers:** Profile rồi soak workload thực trên BOM để ký camera/FPS/pose envelope và headroom.

Traceability: A04 A05 O04 P04.

Tiêu chí dự kiến:

- [ ] 24–72h có per-camera P95/P99/gaps/fsync/WAL/outbox/thermal/power/copies và actual workload manifest.
- [ ] Tối ưu bottleneck đo được, shared runtime serialization/fairness; không ký camera capacity từ detector FPS riêng.

### 32: Retained evidence truy hồi có authorization

**Blocked by:** #08, #18.

**What it delivers:** Người có quyền yêu cầu clip edge/server qua outbound command và thấy pending/offline/expired/completed.

Traceability: R05 T03 UI04.

Tiêu chí dự kiến:

- [ ] Long-poll ID/auth/target/expiry/replay guard, retry idempotent; không remote shell/arbitrary executable.
- [ ] Cleanup/download/retrieval race được kiểm; metadata ACK không release clip, retention/delete scope rõ.

### 33: Device lifecycle và site access được enforce

**Blocked by:** #05, #08, #17.

**What it delivers:** Enroll/rotate/quarantine/revoke thiết bị và giới hạn reviewer/raw/export theo site/camera xuyên API.

Traceability: T01 F05.

Tiêu chí dự kiến:

- [ ] Cross-site/cross-device/read/upload/review/export deny tests; revoked credentials không còn hoạt động.
- [ ] Trust/privacy/license hồ sơ có owner/phạm vi; approval thật trước field data, checklist không tự cấp clearance.

### 34: Config local và signed activation giữ LKG

**Blocked by:** #03, #16, #33.

**What it delivers:** Stage config local rồi nhận signed bundle hợp lệ; activate tại boundary với desired/observed versions và trust sequence durable.

Traceability: B04 T02.

Tiêu chí dự kiến:

- [ ] Canonical bytes/target/hash/length/expiry/trusted keys được verify; bad/expired/old/uncertain-clock reject.
- [ ] Local config sai giữ LKG; high-water mark survives reboot, event snapshot/reset semantics đúng, recorder tiếp tục.

### 35: Canary và rollback có authorization mới

**Blocked by:** #34, #30.

**What it delivers:** Canary bundle, theo dõi observed version rồi rollback artifact cũ bằng authorization sequence mới.

Traceability: T04 B04.

Tiêu chí dự kiến:

- [ ] Failed activation giữ LKG; state/schema/model compatibility policy rõ, không trộn lineage im lặng.
- [ ] Rollback không bypass signature/downgrade trust sequence; retry và reboot giữa activation có tests.

### 36: WAN outage giữ event/evidence rồi resume

**Blocked by:** #18, #32.

**What it delivers:** Ngắt WAN/central theo budget lab và workload đã sizing, phục hồi upload/retrieval mà không mất dữ liệu protected trái policy.

Traceability: J05 J03 R05.

Tiêu chí dự kiến:

- [ ] 24h target được đo autonomy/time-to-full/backlog, quá budget báo degraded, không TTL unACK.
- [ ] Metadata ưu tiên clip, receipt/retry/dedup đúng và report RPO/RTO trong scope; không hứa chịu disk loss.

### 37: Power-cut kiểm chứng local durability

**Blocked by:** #09, #18, #02.

**What it delivers:** Cắt điện BOM lab tại commit/temp/rename/checkpoint rồi recover và đối chiếu IDs/hashes.

Traceability: J05 R03 J01.

Tiêu chí dự kiến:

- [ ] Protocol lab/hardware/restore được owner thống nhất; power-cut thật, kill-9 không thay bằng chứng.
- [ ] Committed metadata/finalized clips có report RPO/RTO/gaps và storage flush/media assumptions; target chưa có giữ blocked.

### 38: Native crash recovery đạt RTO

**Blocked by:** #16, #17, #31.

**What it delivers:** Inject native segfault/hang/restart loop, analytics reset session và recorder tiếp tục trong fault boundary.

Traceability: T06 R06 O02.

Tiêu chí dự kiến:

- [ ] Fault không healthy, stale results bị reject, RTO/gaps đo theo signed target.
- [ ] Chỉ mở ADR/process isolation nếu evidence cần; nếu đổi IPC rerun semantic/timeout/restart/capacity, không mặc định shared memory.

### 39: Provisioning và watchdog tái tạo được

**Blocked by:** #35, #38.

**What it delivers:** Provision thiết bị sạch, deploy service least privilege, upgrade/restore theo runbook và kiểm watchdog thực.

Traceability: T05.

Tiêu chí dự kiến:

- [ ] Build/SBOM/provenance pinned; runtime/device node/recorder ACL được kiểm trên target.
- [ ] Watchdog có heartbeat thật; resource limits không phá recorder/native access, restore lặp lại được.

### 40: Synthetic probe báo operational fault riêng

**Blocked by:** #17, #05.

**What it delivers:** Probe đi qua decode/inference/journal/server và báo lỗi khi capability hoặc delivery ngừng tiến triển.

Traceability: H02 W02.

Tiêu chí dự kiến:

- [ ] Synthetic taxonomy immutable qua revisions/retry, notification guard trước outbox; fault route không rescue.
- [ ] Metric/window/threshold/owner/runbook/recovery và secret/cardinality budgets được kiểm bằng injected deadlock/pin gap.

### 41: Malformed storm không ăn hết state reserve

**Blocked by:** #18, #05.

**What it delivers:** Flood payload sai schema và theo dõi bounded forensic samples/counters/truncation ở edge/health.

Traceability: J04 H01.

Tiêu chí dự kiến:

- [ ] Duplicate compact nhưng valid incident/revision không compact; unique storm có truncation/degraded rõ.
- [ ] Quota/limits/rate/counters/retention được kiểm; media không ghi được thì không hứa giữ forensic fact vô hạn.

### 42: Downstream delivery theo protocol được bật

**Blocked by:** #27, #05, #33.

**What it delivers:** Khi được cho phép, worker phát downstream từ durable intent, retry/audit/assignment/escalation theo human-review protocol.

Traceability: W02 I04.

Tiêu chí dự kiến:

- [ ] Lab default disabled; provider/broker chỉ thêm khi use case chọn, không fake delivered.
- [ ] Synthetic/replay luôn bị chặn; downstream outage không rollback ingestion, provider thiếu dedup ghi residual duplicate risk.

### 43: Central retention và backup/restore có proof

**Blocked by:** #08, #33.

**What it delivers:** Retention/delete/export đúng policy rồi restore Mongo metadata và evidence vào môi trường tách biệt.

Traceability: E03 E02.

Tiêu chí dự kiến:

- [ ] Restore/reconcile pending/missing/corrupt/orphan/hash/scope và immutable receipts; DB/file không transaction chung.
- [ ] Production topology/storage/HA/SLA có decision owner; report RPO/RTO, Mongo one-member lab không coi HA.

### 44: UI sản phẩm cho review và annotation

**Blocked by:** #20, #27, #28.

**What it delivers:** Đội UI tích hợp API thật thành queue person-down/on-vehicle/ambiguous và annotation feedback phục vụ người trực.

Traceability: UI03 D02 I04.

Tiêu chí dự kiến:

- [ ] Label correction/version/conflict/audit độc lập AI, missing/expired evidence và auth states rõ.
- [ ] Operator workload, keyboard/responsive/accessibility theo scope được review; dev demo không thay sign-off UI sản phẩm.

### 45: UI fleet, retrieval và audit

**Blocked by:** #32, #33, #34.

**What it delivers:** Đội UI hiển thị device offline/revoked, retrieval expiry, desired/observed versions và authorized raw/export audit.

Traceability: UI04 T03 H02.

Tiêu chí dự kiến:

- [ ] API/version/error fixtures handoff; scope deny/revoked/expired raw URLs được browser kiểm.
- [ ] Loading/error/retry và keyboard/responsive/accessibility; business transitions vẫn backend sở hữu.

### 46: Calibration valid đi xuyên tới observations

**Blocked by:** #28.

**What it delivers:** Khi mở vehicle scope, survey/calibrate contact-point projection và xuất validity/uncertainty tới pipeline/detail.

Traceability: G01 G02 QL03.

Tiêu chí dự kiến:

- [ ] Mốc held-out/multi-plane/PTZ/occluded contact points được kiểm; invalid trả unknown.
- [ ] Camera shift invalidate geometry, không auto-restore do compensation; không m/s giả khi uncalibrated.

### 47: Vehicle motion và suspected-incident flow

**Blocked by:** #46.

**What it delivers:** Tracks/time/ground quality thành motion/risk features và vehicle pipeline event vào cùng evidence/review flow.

Traceability: M01 M02 I06.

Tiêu chí dự kiến:

- [ ] Variable Δt/jitter/gaps/epoch và predicted/measured không tạo acceleration giả.
- [ ] Near-miss/red-light stop/jam/crash fixtures; TTC/overlap không proof collision, state độc lập person-down.

### 48: Nghiệm thu vehicle riêng G4b

**Blocked by:** #47.

**What it delivers:** Chạy vehicle E2E và report recall/FP/evidence/review load trên site calibration/dataset riêng.

Traceability: M03 D04.

Tiêu chí dự kiến:

- [ ] Dataset/provenance/threshold/uncertainty đủ và ký G4b theo use case được bật.
- [ ] Vehicle disabled ghi deferred; không chặn person-down pilot, không suy G2 person-down thành vehicle đạt.

### 49: Nghiệm thu person-down pilot readiness G4a

**Blocked by:** #19, #28, #31, #36, #37, #39, #40, #41, #43, #44, #45.

**What it delivers:** Reproduce báo cáo lab và fault/security/UI proofs để quyết định có đủ điều kiện bắt đầu person-down field pilot.

Traceability: F03 F06 T01.

Tiêu chí dự kiến:

- [ ] G4a trước field data có privacy/license/production infra/restore/operator protocol và đủ fault/soak proofs, named owner ký.
- [ ] Notification chỉ nếu được bật/duyệt ticket42, vehicle chỉ nếu đạt48; unresolved hoặc thiếu evidence không pass, có pause/rollback protocol.

### 50: Field pilot và final acceptance G5

**Blocked by:** #49.

**What it delivers:** Thu observations field theo ODD, đánh giá quality/review load và ký final SLO cùng quyết định scale.

Traceability: D04 D05 F03.

Tiêu chí dự kiến:

- [ ] Ngày/đêm/mưa/occlusion/camera-days/sampling đủ theo protocol; reports có uncertainty, missed events và operator workload.
- [ ] Central restore/revoke/canary drills theo SLA, TCO dùng số đo; đổi site/camera/engine ngoài envelope cần tái kiểm, chưa đủ mẫu không ký scale.

## Kết quả review / publish

Người dùng đã duyệt breakdown bằng “đồng ý”. Đã publish 50 ticket riêng cùng blockers/acceptance/mapping vào local tracker; triage theo external prerequisites như quy ước đã duyệt. Nội dung các slices bên trên giữ làm bản đối chiếu, còn trạng thái thực hiện theo tracker.
