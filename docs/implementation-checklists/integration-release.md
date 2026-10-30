# Checklist tích hợp, kiểm lỗi và release gates

Cập nhật: 2026-10-30 · Trạng thái cổng phần cứng/thực địa (`G1–G5`): đang mở (`G0` đã đạt cho phạm vi software-lab). Owner điều phối: QA/operations; bắt buộc gán định danh người ký trước khi chạy nghiệm thu site. [Mục lục](README.md) · [Ranh giới kiến trúc](architecture-analysis.md) · [Readiness](../architecture/deployment-readiness.md).

## 1. Điều kiện chạy và cách ghi bằng chứng

- [ ] **INT-PRE01** — Pin commit/build, hardware/OS/SDK/runtime, model/config/dataset hashes, schema/rule/calibration versions và test manifest.
- [ ] **INT-PRE02** — Gán người kiểm/owner phục hồi; chuẩn bị fixture cleared và lab cô lập, giữ synthetic/replay guard, không bật notification ngoài dashboard.
- [ ] **INT-PRE03** — Ghi preliminary target, measurement clock/uncertainty, recorder gap/RPO/RTO và workload; thiếu số/người duyệt thì gate chưa thể pass.
- [ ] **INT-PRE04** — Xác nhận storage quota/reserve, snapshots/backup cần thiết và cách khôi phục trước fault injection; power-cut chỉ trên thiết bị lab theo protocol đã thống nhất.
- [ ] **INT-PRE05** — Chạy unit/contract trước, sau đó integration bằng adapter thực; dùng fakes để chẩn đoán, không để fake thay proof DB/RTSP/hardware.
- [ ] **INT-PRE06** — Mỗi case lưu expected/actual, command thật, timestamps, correlation IDs, protected data IDs/hashes, log/report và người kiểm. `not-run`, `blocked`, `fail` khác `pass`.

Các lệnh kiểm chứng phần mềm chuẩn đang hoạt động trong repository: kiểm tra kiểu tĩnh `.venv-oracle/bin/python -m mypy domain/ apps/ tools/`, bộ kiểm thử tự động `.venv-oracle/bin/python -m pytest -q` (`896` tests / `188` subtests), conformance `.venv-oracle/bin/python tools/oracle_conformance.py` và bộ đánh giá semantic replay `tools/eval_{clip,vehicle,all_scenarios}.py`. Khi chạy nghiệm thu cổng `G1–G5` trên camera RTSP, Docker/MongoDB thực và thiết bị nhúng đích, owner bắt buộc lưu lệnh thực tế cùng manifest đầu ra vào hồ sơ gate; không lấy kết quả unit test/fake làm bằng chứng vượt cổng phần cứng.

## 2. Ma trận kiểm lỗi xuyên module

Mỗi hàng phải có run record riêng khi nghiệm thu. Với fault có retry, kiểm cả lúc lỗi và sau recovery, không chỉ HTTP status hoặc process còn chạy.

| Case | Module/task | Bước inject / thao tác | Expected và dữ liệu phải kiểm | Gate |
|---|---|---|---|---|
| X01 | C01/V01/I01 | Semantic replay cùng fixed inputs/sampling, fast và paced, virtual clock/watermark | Domain outcomes giống nhau; recorder không chạy vượt consumer; realtime stress ở X06/X22, origin giữ xuyên server | G1 |
| X02 | C01/V02/K02 | Clock jump, RTSP disconnect/reconnect rồi đưa result epoch cũ tới muộn | Session/epoch reset; stale result bị từ chối, không nối tracks hoặc tính motion qua discontinuity | G1/G2 |
| X03 | C02/N03/N04 | NV12/stride khác width, color range, crop/letterbox/rotation fixtures; drop/cancel buffer | Original-coordinate bbox đúng tolerance, không double normalize; không use-after-free/leak | G1, hardware bổ sung G3 |
| X04 | B01/B02/B03 | Enabled thiếu config, factory ID lạ, model hash sai; thử disabled config thiếu | Enabled exit nonzero rõ field/reason, secrets masked; disabled reason rõ; recorder vẫn tiếp tục | G1 |
| X05 | N01/O02 | Poll blocking, stop/cancel/reopen, partial startup fail | GIL được release khi block, timeout bounded, typed error và mọi resources được release | G1 |
| X06 | O01/O02 | Slow detector/consumer và pipeline feature fault, queue đạt bound | Drop stale/release đúng, RAM bounded; durable event không frame-drop; independent pipeline/recorder tiếp tục theo fault contract | G1/G3 |
| X07 | V04/R01/R06 | Kill/hang analytics rồi khởi động lại khi recorder đang ghi | Recorder upstream độc lập; đo segment gap trong approved budget, actual intervals/session mapping đúng | G1 |
| X08 | R01/R06/H01 | Kill recorder/relay, reconnect và đổi codec | Operational fault, evidence gaps/partial rõ, watchdog/reconcile; không báo accident do nguồn chết | G1/G4a |
| X09 | R02/R04 | Race pin vs cleanup; hai event overlap; duplicate pin/release | ACK pin precedes deletion; segment còn reference không mất; duplicate idempotent, pending pins bounded | G1 |
| X10 | R03/J04 | Crash sau pending, lúc temp write, sau file fsync, sau rename, trước/sau DB finalize | Startup xử lý từng state; file hash/range đúng; thiếu pre/post/gap thành partial, không complete giả | G1/G4a |
| X11 | R03/E02/UI01 | Trigger lúc boot chưa đủ ring; trigger khi đủ ring; source gap giữa pre/post | Có dữ liệu đủ thì giữ pre 10s/post 20s theo Q6; nếu không đủ ghi actual/requested/partial reason | G1 |
| X12 | J01 | Crash giữa journal/outbox writes, inject transaction/commit/fsync error | Event và delivery intent atomic; commit lỗi không success ACK; count/IDs trước-sau recover khớp | G1 |
| X13 | S01/J02 | Server commit thành công rồi drop response; retry duplicate/reordered/conflicting hash | Durable receipt idempotent; unique revision, current không lùi; same key/different hash conflict, không overwrite | G1 |
| X14 | S01 | Mongo bootstrap chưa ready/standalone, transient transaction/unknown commit, restart container | Readiness không falsely healthy; DB persistent, revision/current/outbox atomic và receipt sau durable commit | G1 |
| X15 | E01/J03 | Ngắt upload ở chunk/finalize, gửi lại cùng evidence; sai hash/size | Resume/retry đúng identity; receipt riêng clip chỉ sau verify; object pending không available, orphan được reconcile | G1 |
| X16 | S02/E01/E02/T01 | Device/site A thử upload/read/download/review/export dữ liệu B; payload path traversal | Mọi route enforce scope; không overwrite object/key khác, không lộ local path/secret; denial có audit thích hợp | G1 baseline/G4a lifecycle |
| X17 | S02/W01/UI02 | Hai reviewer submit cùng version; AI revision tới giữa review; invalid transition | Một update hợp lệ, conflict rõ; refetch rồi thao tác mới; AI không reset review, review không sửa AI confidence | G1 |
| X18 | UI01/UI02/E02 | Browser list→detail→play→review; API chậm/401/403/500; evidence pending/missing/expired | State/loading/error rõ; API thật, raw access authorized; H.265 unsupported có derived playback path hoặc lỗi rõ | G1 |
| X19 | UI01/C01/J01 | Đo nhiều event durable edge commit→browser render trên LAN với polling thực | P95 ≤5s theo Q16, sample count/clock correlation/uncertainty ghi rõ; tách temporal verification và postroll/upload | G1 |
| X20 | QL01/QL02 | Static scene vs frozen PTS/frame stream; dark/blur/rain/missing quality | Freeze khác ít chuyển động; reason/coverage rõ, unknown không negative, event không bị suppress im lặng | G2 |
| X21 | K03/P03/I02 | Ngã nhanh/chậm/nằm sẵn, occlusion/ID switch/missing onset/track gap | Fall yêu cầu onset hỗ trợ; thiếu onset có persistent-lying path; missing pose/track là uncertainty | G2 |
| X22 | P02/P03/P04 | Pose burst, expired ROI buffer và stale frame/track association | Fast/slow/lying coverage được đo riêng; skipped/failed/stale rõ; pose cũ không gán frame mới, RAM bounded | G2/G3 |
| X23 | I03/I04 | Người ngả trên xe stationary/upright, xe đổ/ngã cạnh xe/xe dừng đột ngột | On-vehicle vẫn event/review ưu tiên riêng, danger override; policy chưa ký không notification | G2/G4a |
| X24 | D01/D03/D04 | Split kiểm leakage, lấy stratified no-alert samples trước ring expiry, evaluate expected-count fixture | Có sampling probability/coverage/uncertainty; report missed/ODD/FP camera-day/review load, không recall từ alerts-only | G2/G5 |
| X25 | C05/A03/I05 | Chạy ONNX oracle/native/target cùng golden + held-out clips | Coordinate/status/track/pose/event parity trong tolerance versioned; fail chặn backend release | G3 |
| X26 | A04/A05/O04/R06 | 24–72h recording+analytics+upload, camera/pose bursts, heat/throttle | P95/P99 per-camera freshness/drop/coverage/gap/fsync/WAL/outbox/power theo signed workload; capacity không từ model FPS | G3/G4a |
| X27 | R04/J01/J04/H01 | Disk 95%/100%, quota/reserve hết, write/fsync errors và WAL/checkpoint pressure | Eligible cleanup, pinned/unACK không bị xóa; degraded/partial/fault; hết journal reserve không commit/ACK giả | G1 baseline/G4a đầy đủ |
| X28 | J05/R05/J03 | WAN/central outage theo 24h budget rồi phục hồi; kéo dài quá budget để kiểm policy | Metadata/clip giữ trong giới hạn đo; backlog resume và receipts đúng; 24h không tự TTL xóa unACK, thiếu chỗ báo degraded | G4a |
| X29 | J05/R03 | Power-cut BOM thật tại DB commit/temp/rename/checkpoint, reboot/recover | Kiểm IDs đã commit và finalized hashes; RPO/RTO báo scope/flush/media assumptions; không dùng kill-9 thay power-cut | G4a |
| X30 | J04/H01 | Malformed duplicate flood và unique-payload flood đến forensic quota | Bounded samples/compact duplicate counters, valid revisions không compact; truncation/degraded rõ, reserve bảo vệ | G4a |
| X31 | S01/W02/H02 | Synthetic/replay initial event + revisions/retry; worker/downstream outage | Synthetic/replay không notification intent/send; downstream pending/disabled không delivered giả; ingestion không rollback vì downstream | G1 guard/G4a |
| X32 | T01/T03 | Rotate/revoke identity, replay/expired/wrong-target command, offline retrieval | Revoked credentials bị chặn; command idempotent/expiry/authorization; pending/offline/expired rõ, không arbitrary executable/shell | G4a |
| X33 | B04/T02/T04 | Activate bundle hợp lệ trước; sau đó bad signature/hash/length/target, old sequence/expired/uncertain clock; failed canary/rollback | Bundle hợp lệ activate và observed version đúng; invalid reject trước activation, LKG giữ; high-water mark durable không hạ; rollback cần authorization sequence mới | G4a |
| X34 | T05/T06/O02 | Native segfault/deadlock, restart loop, least-privilege deploy, watchdog không heartbeat | Fault không healthy; reset epoch/drop stale result, recorder không bị stop; nếu RTO fail thì ADR isolation + rerun IPC conformance | G4a |
| X35 | E03/T01 | Backup DB/object, restore vào env tách biệt; delete/export policy và object missing/corrupt/orphan | Reconcile đúng ownership/hash/state, audit quyền; RPO/RTO theo SLA, không giả metadata backup đủ giữ clips | G4a/G5 |
| X36 | G01/G02/QL03/M01/M02/I06 | Invalid plane/contact point/camera shift/PTZ, jitter/gap, near-miss/stop/traffic jam | Invalid→unknown không calibrated m/s; compensation không tự restore calibration; vehicle report riêng, TTC không collision proof | G4b |
| X37 | UI03/UI04/D02/T03 | Product UI annotation/fleet/retrieval/audit, keyboard/mobile, stale labels và access bị revoke | Business transitions qua API; label corrections audited, permission/download/expiry rõ, operator ký UX | G4a/G5 |
| X38 | C03/J01/R02/J04 | Crash event commit trước pin, recorder ACK trước edge receipt, recorder reboot rồi retry | Durable request/receipt idempotent; overlap giữ owner, quá ring terminal partial/missing có fault; không unowned pin | G1 |
| X39 | C03/I02/R02 | Onset0/trigger15, lying thiếu onset, anchor revised, ring không đủ | Requested [-10,20] cho fall; lying có anchor_kind riêng; request mới cho range mới; partial đúng coverage | G1/G2 |
| X40 | R03/J03/E01/UI01 | Finalized partial upload→retry→ACK rồi server expire/corrupt | Completeness không mất; historical receipt không giả availability; UI/SLI vẫn partial, checksum/bytes bất biến | G1 |
| X41 | C03/S01/S02 | Snapshot3→1→2, chỉ3, camera/session/origin substitution, sent_at thay ở retry | Current max revision, identity/origin bất biến, canonical content hash ổn định; history gaps rõ | G1 |
| X42 | W01/S02/UI02/D02 | False_positive rồi severity/clip complete mới; stale action, correction/reopen, evidence corrupt | needs_re_review có reason; decision cũ/audit giữ, viewed revisions đúng, metadata-only không trigger | G1/G4a |
| X43 | N05/P03/O01 | Cùng consumer oracle/native; late pose, detection-ok/pose-skipped, terminal queue pressure và epoch crash | Một tracker update/frame, per-stage statuses; requests kết thúc rõ, stale result reject; không pixel hot-path qua Python | G1 baseline/G2 pose |
| X44 | C05/A04/A05/T04 | Traverse target ONNX và RKNN, chạy exact-target conformance/soak/rollout | ONNX không cần conversion RKNN; RKNN bắt A01–A03/#30; cả hai có hardware/quality/capacity proof, không N/A giả | G3/G4a |
| X45 | S01/W02 | Bật provider sau disabled lâu, retry quá expiry, authorized integration backfill | Không phát notification cũ ngoài policy; terminal retention bounded; origin guard giữ, event history không bị xóa theo expiry side effect | G4a nếu downstream bật |

## 3. Gate checklist

### G0 — Sẵn sàng bắt đầu lab

- [ ] **G0.01** — F01–F06 có facts lab/site/ODD/scenarios/owners; target board chưa chọn ghi pending, không chặn ONNX/replay.
- [ ] **G0.02** — C01–C03 semantic contracts/schema examples, Q1–Q19 scope, exact cleared artifacts và D01 mẫu đã được review.
- [ ] **G0.03** — Preliminary SLO/storage/review/failure protocols có owner, số thiếu rõ; camera chưa có thì live gate còn pending.
- [ ] **G0.04** — Claim tasks/ownership và contract handoff; không có conflicting accepted ADR bị âm thầm thay.

### G1 — Vertical slice lab

- [ ] **G1.01** — File replay và RTSP branch thực chạy native ONNX detector/tracker, journal/outbox, recorder và server/demo; RTSP chưa chạy thì G1 live chưa đạt.
- [ ] **G1.02** — Event synthetic/replay fixture xuyên event→pin/postroll→clip→upload→list/detail/play/review có provenance; không gọi đây là person-down AI quality đã đạt.
- [ ] **G1.03** — X01–X19, X38–X42 và baseline X27/X31/X43 đạt theo phạm vi, config/runtime fault không nhập nhằng, recorder independence/gaps đã đo.
- [ ] **G1.04** — Latency Q16 P95 ≤5s có clock correlation, sample count và report; actual pre/post/gaps manifest đúng Q6.
- [ ] **G1.05** — Device auth/authz basic, schema/upload limits, state reserve, transaction/receipt và synthetic notification guard đã chạy thực.
- [ ] **G1.06** — Browser flow và lệnh reproduce được ghi; native buffer ownership/stride đã kiểm, không ký target hardware capacity tại G1.

### G2 — Person-down có chất lượng được đo

- [ ] **G2.01** — K03/QL01–QL02/P01–P04/I02–I05/D02–D05 có reports theo site ODD và thresholds preliminary đã duyệt.
- [ ] **G2.02** — X20–X24 và X43 đạt; missing onset/unknown/on-vehicle/ID switch/coverage có expected transitions và regression.
- [ ] **G2.03** — Negative audit sampling/rights/coverage/uncertainty và FP/review load có dữ liệu, không chỉ alerts đã phát hiện.
- [ ] **G2.04** — Quality report phân lab/held-out/field, sample sufficiency và unsupported conditions; chưa có target/sample đủ thì gate chưa pass.

### G3 — Target portability và lab capacity

- [ ] **G3.01** — Board/OS/SDK/storage/model target được chọn/pin; hardware decoder/buffer thật được kiểm nếu dùng, software-only capacity có giới hạn đo rõ.
- [ ] **G3.02** — C05/N05/P03/I05 trên target, A04/A05/O04, X25/X26/X44 và actual-target X03/X22 đạt; thêm A01–A03/#29/#30 chỉ khi target RKNN. Native/oracle/target conformance + full event regression vẫn bắt buộc.
- [ ] **G3.03** — Soak manifest có recording/upload contention/thermal/headroom/pose coverage và P95/P99; owner ký lab envelope đúng BOM/workload.

### G4a — Person-down field pilot readiness

- [ ] **G4a.01** — G1–G3 theo target đã chọn và X27–X35 đạt đầy đủ; trust/reliability/native RTO/runbooks/backup và restore có evidence.
- [ ] **G4a.02** — Production server/storage/network/PKI/topology có ADR/owner/SLA; lab one-member Mongo không bị coi là HA.
- [ ] **G4a.03** — Site privacy/model/checkpoint/dataset clearance có tên/ngày/phạm vi; đây là hồ sơ approval cần có, checklist không tự xác nhận clearance.
- [ ] **G4a.04** — I04 human-review protocol và UI vận hành phù hợp tích hợp API đã nghiệm thu; X37 theo feature được bật. Dev demo lab không tự thay UI production.
- [ ] **G4a.05** — Notification nếu được bật có authorization/protocol, worker thật, X45 eligibility/expiry/no-backfill và retry/dedup limits rõ; nếu disabled ghi scope, không làm gate giả delivered.
- [ ] **G4a.06** — Có phương án pause/rollback pilot và incident owner; vehicle disabled không làm G4a phụ thuộc G4b.

### G4b — Vehicle readiness khi bật nhánh

- [ ] **G4b.01** — G01/G02/M01–M03/I06 + X36, calibration uncertainty/site validity và vehicle recall/FP/evidence riêng đã đạt.
- [ ] **G4b.02** — Không suy person-down acceptance thành vehicle acceptance; nhánh chưa bật ghi deferred thay vì pass.

### G5 — Field acceptance và scale

- [ ] **G5.01** — Field pilot có ngày/đêm/mưa/che khuất/đám đông đúng ODD và đủ samples/camera-days theo protocol.
- [ ] **G5.02** — Final quality/SLO/review capacity/privacy/retention và residual risks được owner ký; G4b nếu vehicle được bật.
- [ ] **G5.03** — Restore, identity revoke, canary/rollback và incident-response drills đạt SLA production; report TCO dùng số đo thực.
- [ ] **G5.04** — Có quyết định mở rộng cụ thể workload/site/BOM; đổi camera/engine/site/firmware ngoài envelope phải tái kiểm các gate chịu ảnh hưởng.

## 4. Xử lý khi test/gate trượt

1. Ghi `fail` hoặc `blocked` với case/task ID, expected/actual, reproduction và protected data impact; không tick checkbox.
2. Truy về module gốc: clock/association/buffer/ODD/rule/storage/transport/auth; dùng CodeGraph context/impact khi có source, không vá UI để giấu lỗi trạng thái.
3. Tạo issue lỗi theo tracker dưới `.scratch/<feature>/issues/`, liên kết task và regression fixture; gán owner. Chỉ thay accepted contract/threshold khi được review và ghi ADR/policy phù hợp.
4. Sửa nguyên nhân, chạy test tái hiện + affected contract/integration/regression; đổi runtime/fault boundary phải rerun parity/recovery/capacity tương ứng.
5. Cập nhật report và readiness; gate vẫn mở nếu hardware/rights/threshold/owner chưa đủ. Không rerun rộng không có lý do sau khi checks cần thiết đã pass.

## 5. Mẫu gate record

| Gate | Scope/workload/site | Cases pass/fail/blocked/not-run | Reports/manifests | Residual risks | Owner ký/ngày | Kết luận |
|---|---|---|---|---|---|---|
| G0–G5, mỗi gate một dòng khi chạy | Chưa gán | not-run | Chưa có | Xem readiness | Chưa gán | Chưa nghiệm thu |

Ghi riêng việc implementation hoàn thành, tests pass và acceptance signed. Không dùng một checkbox “done” thay cả ba.
