# M15 — Model Registry, conversion và RK3588 (P3)

Status: needs-triage
Execution: not-started
Scope claimed: chưa claim
Owner: ML + Edge; người phụ trách cụ thể chưa gán.
Phase: P3 sau target selection
Updated: 2026-10-11

> Đây là issue/checklist kế hoạch. Không checkbox nào chứng minh runtime đã implement. Triage state khác trạng thái thực hiện; cần gán owner trước khi claim.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `model_manifests/, tools/model_conversion/, native RKNN/RGA adapters`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Pinned source artifacts + target → validated target bundle + capacity report.
- SOLID cần kiểm: LSP: thay engine qua conformance cùng event semantics; OCP: thêm adapter không if-board trong domain.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

- [ ] Owner cụ thể nhận module và ghi task/phase sẽ làm trong Comments.
- [ ] Đọc CONTEXT.md, ADR liên quan, kiến trúc và task nguồn; ghi conflict trước khi đổi quyết định.
- [ ] Các prerequisites ở từng task có artifact hoặc fake/fixture contract đã thống nhất; fake chỉ mở unit/contract work, không thay acceptance tích hợp.
- [ ] Chốt input/output/error/reset/version semantics với producer/consumer; số chưa đo ghi null/preliminary, không tự đặt threshold sản phẩm.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### A01 — Pin conversion SDK/runtime/operator matrix và representative quantization dataset

Phụ thuộc nguồn: `F05,C05`.

- [ ] **A01.01** — Sau khi chọn target, pin converter/runtime/driver/operator matrix và quantization representative dataset.
- [ ] **A01.02** — Build source→ONNX→RKNN offline với hash/terms và reproducible conversion report.
- [ ] **A01.03** — Test unsupported op/input/precision, lưu exact target compatibility; không convert khi startup edge.
- [ ] **A01.AC** — Nghiệm thu: Source→ONNX→RKNN có hashes/version/terms; không convert khi edge startup.
- [ ] **A01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### A02 — RKNN engine + dequant/postprocess detector/pose; RGA transforms

Phụ thuộc nguồn: `N05,P03,A01`.

- [ ] **A02.01** — Implement RKNN detector/pose adapter và RGA transforms theo same ModelSpec semantics.
- [ ] **A02.02** — Audit shape/layout/dtype/stride/color, dequant/normalization/postprocess và buffer import/lifetime.
- [ ] **A02.03** — So golden outputs native ONNX/RKNN, đo drift; failure/fallback publish explicit capabilities.
- [ ] **A02.AC** — Nghiệm thu: Shapes/layout/dtype/stride/color đúng; confidence drift có report; không normalize hai lần.
- [ ] **A02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### A03 — Backend conformance và full replay event regression

Phụ thuộc nguồn: `A02,I05`.

- [ ] **A03.01** — Chạy contract + detection/pose/tracker conformance và full event replay regression.
- [ ] **A03.02** — So với tolerance C05 trên golden và held-out, gồm empty/unsupported/stale/quality cases.
- [ ] **A03.03** — Lưu parity report/hash; fail thì chặn release, không gọi đổi backend chỉ là đổi file config.
- [ ] **A03.AC** — Nghiệm thu: Golden + held-out tolerance đạt; failed/fallback không báo normal.
- [ ] **A03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### A04 — Profile copies/queue/infer/fsync/upload/thermal; tối ưu hotspot đã đo

Phụ thuộc nguồn: `A03,O03,R06`.

- [ ] **A04.01** — Profile decode/copies/preprocess/queue/infer/fsync/upload/thermal trên hardware thật.
- [ ] **A04.02** — Tối ưu bottleneck đã đo bằng dependency/platform hiện có; kiểm ownership khi giảm copy.
- [ ] **A04.03** — Benchmark before/after cùng workload recording/upload; zero-copy chỉ ghi đạt nếu có số đo và lifetime proof.
- [ ] **A04.AC** — Nghiệm thu: Report đồng thời recording+analytics+upload; zero-copy chỉ ghi đạt khi import/lifetime và copies đo được.
- [ ] **A04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### A05 — 24–72h lab soak, pose bursts/multi-camera và capacity envelope

Phụ thuộc nguồn: `A04,O04`.

- [ ] **A05.01** — Cùng O04 chạy soak 24–72h với camera/pose bursts/recording/upload profile pinned.
- [ ] **A05.02** — Thu P95/P99/headroom/temperature/throttle/gaps/outbox và power theo manifest readiness.
- [ ] **A05.03** — Ký capacity envelope lab đúng BOM/workload; thiếu hardware hoặc target chưa ký để blocked gate, không pass giả.
- [ ] **A05.AC** — Nghiệm thu: P95/P99, headroom/throttle, evidence gap/coverage đạt preliminary targets; ký lab envelope.
- [ ] **A05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M15-ERR01 | Không convert lúc startup. | Chạy startup từ artifact đã build; nếu converter chưa có nhưng runtime phù hợp thì startup không đòi conversion, wrong target bị reject; A01/A02. |
| M15-ERR02 | Zero-copy cần đo và lifetime proof. | Profile copy counts và exercise buffer lifetime/import/cancel trên hardware thật; zero-copy claim chỉ sau report; X03/X26. |
| M15-ERR03 | FPS inference đơn lẻ không là camera capacity. | Soak recording+upload+analytics X26, so detector-only với frame-age/gap/thermal report; không dùng FPS đơn lẻ ký G3. |

Ca tích hợp cần phối hợp: **X03, X22, X25, X26**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

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
