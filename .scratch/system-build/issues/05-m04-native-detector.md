# M04 — Native core, detector và pre/postprocess (P1)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: Edge + ML; người phụ trách cụ thể chưa gán.
Phase: P1
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `native/src/{core,preprocess,engines,models}/, native/bindings/python/, oracle adapters`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Native buffers + ModelSpec → Detection/ObservationBatch metadata-only.
- SOLID cần kiểm: DIP: engine/tensors trong model adapter; SRP: core không chứa IncidentEngine hay DB/upload.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §1 PerceptionPipeline chung oracle/native, không duplicate stage calls](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### N01 — CMake/build profile + binding lifecycle/poll/capabilities/typed failure; release GIL khi block

Phụ thuộc nguồn: `C04`.

- [ ] **N01.01** — Tạo CMake profile CPU và binding open/start/poll/capabilities/stop/close hẹp.
- [ ] **N01.02** — Release GIL lúc block, convert native exceptions thành typed error; queue output bounded.
- [ ] **N01.03** — Test start-stop-reopen, timeout/cancel/load failure và cleanup khi partial startup.
- [ ] **N01.AC** — Nghiệm thu: Start/stop/reopen, timeout và error conformance chạy được; bounded output queue.
- [ ] **N01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### N02 — Python YOLOX/ORT oracle với manifest pinned, preprocess/label map/transform

Phụ thuộc nguồn: `F05,C05,V01`.

- [ ] **N02.01** — Load YOLOX/ORT oracle từ exact manifest, label map và preprocess pinned.
- [ ] **N02.02** — Implement color/letterbox/normalization/decode/NMS và inverse mapping về ảnh gốc.
- [ ] **N02.03** — Chạy golden frames có empty/multiple/border objects; lưu outputs và timings để native đối chiếu.
- [ ] **N02.AC** — Nghiệm thu: Golden frames: bbox original coords, color/letterbox/NMS đúng.
- [ ] **N02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### N03 — ORT C++ load/run + C++ preprocess/decode outputs/NMS; instrumentation mỗi stage

Phụ thuộc nguồn: `N01,N02,V03`.

- [ ] **N03.01** — Tích hợp ORT C++ và cùng preprocess/postprocess/transform semantics như oracle.
- [ ] **N03.02** — Instrument decode/preprocess/inference/postprocess; không normalize hoặc scale bbox hai lần.
- [ ] **N03.03** — Chạy golden tolerance và kiểm shape/output không hợp lệ thành typed failure.
- [ ] **N03.AC** — Nghiệm thu: Detection parity trong tolerance đã khóa; không double normalize.
- [ ] **N03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### N04 — Buffer pool/release/drop/cancel/error paths và result session/frame correlation

Phụ thuộc nguồn: `N03`.

- [ ] **N04.01** — Thiết lập buffer pool ownership và release cho success/drop/cancel/error/shutdown.
- [ ] **N04.02** — Correlate result với camera/session/frame/model; reject stale epoch và giữ history bounded.
- [ ] **N04.03** — Chạy ASan/UBSan trên build phù hợp và stress slow consumer/restart, đo peak/steady memory.
- [ ] **N04.AC** — Nghiệm thu: ASan/UBSan trên path phù hợp; soak không tăng buffer vô hạn; reject stale epoch.
- [ ] **N04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### N05 — Tích hợp native capture→detector→tracker→ObservationBatch

Phụ thuộc nguồn: `N04,K02`.

- [ ] **N05.01** — Wire native capture→preprocess→detector→tracker và xuất ObservationBatch metadata-only.
- [ ] **N05.02** — Giữ pixels và buffer trong core, apply ordered result/session policy; expose timings/age/drop.
- [ ] **N05.03** — Tích hợp Python poll với fake clock/consumer chậm; xác minh hot path không gửi pixels mỗi frame. Cùng consumer PerceptionPipeline cho oracle/native; tracker một lần/frame, pose late không update tracker lại.
- [ ] **N05.AC** — Nghiệm thu: Python không copy pixels mỗi frame; timings và queue-age đủ đo bottleneck.
- [ ] **N05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M04-ERR01 | Binding không rò C++ exception. | Inject load/run/binding error; Python nhận typed failure, không exception ABI escape hoặc báo ok_empty; X05. |
| M04-ERR02 | Drop/cancel/error đều release buffer. | ASan/UBSan với drop/cancel/timeout/shutdown và slow consumer; đo buffers outstanding về baseline; X03/X05/X06. |
| M04-ERR03 | Không copy pixels mỗi frame sang Python deployment path. | Profile binding/output payload và memory copies ở native hot path; Python chỉ nhận metadata, pixel debug export là đường riêng bounded; N05/A04. |

Ca tích hợp cần phối hợp: **X03, X05, X06, X25**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.

- 2026-10-12 docs sync: N02 software-lab detector stage delivered in #11, commit `e47d6cf`. Exact official model/labels/runtime pins, raw-BGR preprocessing with separate source provenance, original-coordinate NMS/transform/status/timings and independent versioned goldens. Full pinned85/85 tests; original13detections/10person, crop9/7, negative0; border/threshold synthetic vectors separately identified. Evidence: [#11 log](../../../docs/logs/2026-10-12-ticket-11.md). N02 checkboxes/module gate remain open where broader source dependencies/production clearance or native conformance are not accepted; no claim N01/N03/N04 complete. Slice tracker remains execution authority.
