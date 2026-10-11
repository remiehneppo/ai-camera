# M10 — Recorder, pin và RetentionManager (P1 tối thiểu; P4 đầy đủ)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: Edge/platform; người phụ trách cụ thể chưa gán.
Phase: P1; retention P4
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `Recorder service, src/traffic_camera/application/evidence/, adapters/evidence/, deploy/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Encoded stream + pin ranges → raw segments/complete hoặc partial manifest.
- SOLID cần kiểm: SRP: recorder sở hữu lifecycle/cleanup; analytics pin qua contract, không khóa DB recorder lâu.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §3 durable pin request/receipt/recovery; §4 evidence dimensions](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### R01 — Recorder process, RTSP ownership và compressed segment rotation; raw unchanged

Phụ thuộc nguồn: `F04,C03`.

- [ ] **R01.01** — Dùng stream ADR F04 để recorder tự sở hữu upstream/demux hoặc relay độc lập analytics.
- [ ] **R01.02** — Rotate raw compressed segments có codec/PTS/keyframe/session/gap metadata; không overlay/transcode bản raw.
- [ ] **R01.03** — Test analytics không chạy recorder vẫn ghi, reconnect tạo segment boundaries rõ.
- [ ] **R01.AC** — Nghiệm thu: Record độc lập analytics; ghi codec/PTS/discontinuity và ranges thật.
- [ ] **R01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### R02 — Pin interval atomic với cleanup, ACK trước xóa; overlapping events và postroll

Phụ thuộc nguồn: `R01,C03`.

- [ ] **R02.01** — Implement pin/query/release contract có idempotent request và ACK pin trước cleanup.
- [ ] **R02.02** — Atomic hóa pin với segment cleanup, overlap reference counting và bounded pending postroll.
- [ ] **R02.03** — Race test pin vs cleanup, duplicate/retry/release và hai event overlap không xóa segment còn chủ. Crash sau event commit trước pin, sau recorder ACK trước local receipt, recorder reboot; query/retry cùng ID không mất owner.
- [ ] **R02.AC** — Nghiệm thu: Race pin/cleanup không xóa segment đã ACK pin; bounded pending pins.
- [ ] **R02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### R03 — Finalize/remux keyframe-aware và local commit/reconcile

Phụ thuộc nguồn: `R02,J01`.

- [ ] **R03.01** — Ghi pending intent trong DB trước temp; remux keyframe-aware giữ actual/requested ranges.
- [ ] **R03.02** — Theo thứ tự temp→fsync file→rename→fsync directory→DB finalize; gaps thành partial.
- [ ] **R03.03** — Crash từng boundary và startup reconcile; verify codec/hash/duration, không coi rename là transaction DB. Finalized partial vẫn upload được; requested range đổi tạo request/artifact mới, không rewrite bytes finalized.
- [ ] **R03.AC** — Nghiệm thu: Pending intent→temp→fsync file→rename→fsync dir→DB finalize; gap thành partial.
- [ ] **R03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### R04 — Quota/reserve/ring expiry/temp cleanup tối thiểu + disk-full behavior

Phụ thuộc nguồn: `F03,R03`.

- [ ] **R04.01** — Cấp quota ring/pin/temp/proxy và reserve state/WAL/telemetry/update theo F03.
- [ ] **R04.02** — Cleanup eligible data trước, giữ pinned/unACK; nếu thiếu thì degraded + partial/failed và fault.
- [ ] **R04.03** — Inject ENOSPC/write/fsync/checkpoint failure; journal reserve hết không commit/ACK giả.
- [ ] **R04.AC** — Nghiệm thu: Budget tính pins/postroll/temp/WAL; không chiếm state reserve hoặc pin vô hạn.
- [ ] **R04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### R05 — Retention nhiều lớp, release sau receipt theo policy và retrieval giữa cleanup

Phụ thuộc nguồn: `R04,E02`.

- [ ] **R05.01** — Version retention/release policy theo receipt và access/delete/export rules.
- [ ] **R05.02** — Query/retrieval phối hợp cleanup và pins; hết hạn trả expired/unavailable rõ.
- [ ] **R05.03** — Test metadata ACK không tự release clip, request đang đọc vs cleanup, outage quá 24h không tự xóa unACK.
- [ ] **R05.AC** — Nghiệm thu: Policy version/access/delete rõ; thiếu clip→expired/unavailable, không URL hỏng giả thành available.
- [ ] **R05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### R06 — Service resource priority và kill/hang/OOM-boundary/recorder-restart drills

Phụ thuộc nguồn: `R04,O02`.

- [ ] **R06.01** — Cấu hình recorder service/resource priority độc lập analytics; ghi host/disk/power failure domain.
- [ ] **R06.02** — Kill/hang/OOM analytics trong boundary đã cấu hình rồi restart recorder/relay riêng.
- [ ] **R06.03** — Đo recorder gap/recovery theo signed budget, lưu traces; gap budget chưa ký không đánh dấu pass.
- [ ] **R06.AC** — Nghiệm thu: Kill analytics recorder vẫn trong signed gap budget; host/disk/power SPOF ghi rõ.
- [ ] **R06.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M10-ERR01 | Pin ACK phải precede cleanup. | Barrier concurrency giữa pin transaction và cleanup; assert ACK pin không trỏ file đã xóa, overlap reference còn giữ file; X09. |
| M10-ERR02 | Metadata ACK không là clip ACK. | Chỉ trả metadata receipt rồi chạy retention; assert clip unACK không được release trái policy; X13/X15/X28. |
| M10-ERR03 | 24h outage là sizing budget, không TTL xóa unACK. | Advance simulated outage quá 24h và fill quota; assert protected data giữ, new clip partial/failed + fault, không TTL unACK; X27/X28. |

Ca tích hợp cần phối hợp: **X07, X08, X09, X10, X11, X27, X28, X29**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
