# M04 — Native core, detector và pre/postprocess (P1)

Status: needs-triage
Execution: not-started
Scope claimed: chưa claim
Owner: Edge + ML; người phụ trách cụ thể chưa gán.
Phase: P1
Updated: 2026-10-11

> Đây là issue/checklist kế hoạch. Không checkbox nào chứng minh runtime đã implement. Triage state khác trạng thái thực hiện; cần gán owner trước khi claim.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `native/src/{core,preprocess,engines,models}/, native/bindings/python/, oracle adapters`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Native buffers + ModelSpec → Detection/ObservationBatch metadata-only.
- SOLID cần kiểm: DIP: engine/tensors trong model adapter; SRP: core không chứa IncidentEngine hay DB/upload.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

- [ ] Owner cụ thể nhận module và ghi task/phase sẽ làm trong Comments.
- [ ] Đọc CONTEXT.md, ADR liên quan, kiến trúc và task nguồn; ghi conflict trước khi đổi quyết định.
- [ ] Các prerequisites ở từng task có artifact hoặc fake/fixture contract đã thống nhất; fake chỉ mở unit/contract work, không thay acceptance tích hợp.
- [ ] Chốt input/output/error/reset/version semantics với producer/consumer; số chưa đo ghi null/preliminary, không tự đặt threshold sản phẩm.

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
- [ ] **N05.03** — Tích hợp Python poll với fake clock/consumer chậm; xác minh hot path không gửi pixels mỗi frame.
- [ ] **N05.AC** — Nghiệm thu: Python không copy pixels mỗi frame; timings và queue-age đủ đo bottleneck.
- [ ] **N05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M04-ERR01 | Binding không rò C++ exception. | Inject load/run/binding error; Python nhận typed failure, không exception ABI escape hoặc báo ok_empty; X05. |
| M04-ERR02 | Drop/cancel/error đều release buffer. | ASan/UBSan với drop/cancel/timeout/shutdown và slow consumer; đo buffers outstanding về baseline; X03/X05/X06. |
| M04-ERR03 | Không copy pixels mỗi frame sang Python deployment path. | Profile binding/output payload và memory copies ở native hot path; Python chỉ nhận metadata, pixel debug export là đường riêng bounded; N05/A04. |

Ca tích hợp cần phối hợp: **X03, X05, X06, X25**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Checklist review và hoàn tất module

- [ ] Mỗi nhánh/loop/parser hoặc state transition mới có unit/contract test meaningful; không chỉ test mock được gọi.
- [ ] Happy path, invalid/missing/stale input, retry/duplicate/concurrency nếu áp dụng, failure và recovery đã được kiểm; ghi N/A có lý do khi không liên quan.
- [ ] Rà tất cả callers/consumers, schema fixtures, config examples, exports/bindings/migrations và docs chịu ảnh hưởng; không bỏ consumer cũ.
- [ ] Review SRP/OCP/LSP/ISP/DIP theo seam thật của module; không thêm interface cho helper hoặc generic framework để đạt hình thức.
- [ ] Integration với producer/consumer thực đã chạy cho phase này; fake/unit pass không tự đánh dấu module hoặc gate đạt.
- [ ] Logs/errors có correlation và redact secrets; bounds/timeout/release/cleanup/security cần thiết đã kiểm.
- [ ] Ghi report và giới hạn vào docs/logs; chỉ tick task đã có evidence, task phase sau vẫn mở.
- [ ] Handoff có schema/config/artifact versions, commands để reproduce, residual risks và owner gate tiếp theo.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
