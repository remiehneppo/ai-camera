# M03 — VideoSource, demux và decoder (P1)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: Edge/platform; người phụ trách cụ thể chưa gán.
Phase: P1; hardware path P3
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `src/traffic_camera/adapters/video/, native/src/decode/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: File/RTSP packets → metadata + native buffers + discontinuity.
- SOLID cần kiểm: SRP: transport/decode nội bộ adapter, reconnect không chứa event rules; domain không biết FFmpeg.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §7 semantic replay/watermark khác realtime stress](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### V01 — File replay PTS + deterministic clock, fast/realtime modes và local sink

Phụ thuộc nguồn: `C01`.

- [ ] **V01.01** — Đọc file bằng PTS/timebase, cung cấp deterministic clock và local synthetic sink.
- [ ] **V01.02** — Tạo semantic replay fast/paced với fixed sampling/watermark; realtime stress đo coverage riêng; log discontinuity thay vì dùng tốc độ vòng lặp làm event time.
- [ ] **V01.03** — Test EOF/seek/timestamp bất thường và guard không gửi notification thật.
- [ ] **V01.AC** — Nghiệm thu: Đổi tốc độ replay không đổi duration rules; không gửi notification thật.
- [ ] **V01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### V02 — RTSP auth/timeouts/backoff+jitter/session reset và liveness/freeze signal

Phụ thuộc nguồn: `F04,C02`.

- [ ] **V02.01** — Mở RTSP với secret reference, deadline và backoff+jitter bounded; log lỗi redact URI.
- [ ] **V02.02** — Phát session/discontinuity/health khi mất nguồn, reconnect, codec/profile change; reset downstream state.
- [ ] **V02.03** — Inject disconnect/freeze/auth failure và stop lúc retry; kiểm không retry spin hoặc treo shutdown.
- [ ] **V02.AC** — Nghiệm thu: Disconnect/reconnect/codec change sinh discontinuity và health lý do rõ.
- [ ] **V02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### V03 — Native software decode baseline portable; hardware decode truth-path khi đã chọn board

Phụ thuộc nguồn: `Q1,V02`.

- [ ] **V03.01** — Implement native software decode baseline với plane stride/color/lifetime đúng contract.
- [ ] **V03.02** — Chạy fixtures và source profile hỗ trợ; công khai software path và unsupported codec.
- [ ] **V03.03** — Sau khi có board, kiểm native NV12/import/release thật và đo contention; không dùng CPU fixture ký hardware gate.
- [ ] **V03.AC** — Nghiệm thu: P1: stride/color/lifetime đúng với fixtures, software path explicit. Target gate: NV12/native buffer được kiểm trên hardware thật trước ký capacity/pilot.
- [ ] **V03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### V04 — Stream ownership dual-session hoặc relay đã chọn; correlation analytics↔recording

Phụ thuộc nguồn: `F04,V03,R01`.

- [ ] **V04.01** — Dùng F04/C03 stream/pin contract và recorder R01; giữ IDs hai nhánh riêng.
- [ ] **V04.02** — Map khoảng event sang segment time với uncertainty và actual range; không join bằng frame_id trùng giả.
- [ ] **V04.03** — Test drift/reconnect/main-sub skew, recorder restart và out-of-range request tạo partial/unknown rõ.
- [ ] **V04.AC** — Nghiệm thu: Không giả PTS/session ID hai session trùng; uncertainty/range thực tế được lưu.
- [ ] **V04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M03-ERR01 | PTS không tự là UTC. | Đổi timebase/replay speed và thiếu UTC mapping; kiểm output không gọi PTS là capture UTC, frame age có clock basis; X01/X02/X19. |
| M03-ERR02 | Reconnect không giữ track continuity giả. | RTSP reconnect rồi đưa result/session cũ; tracker/FSM reset và result bị drop có reason; X02. |
| M03-ERR03 | Analytics socket không sở hữu upstream của recorder. | Kill analytics socket/process, kiểm recorder upstream riêng và segment intervals; X07. |

Ca tích hợp cần phối hợp: **X01, X02, X03, X07, X08**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
