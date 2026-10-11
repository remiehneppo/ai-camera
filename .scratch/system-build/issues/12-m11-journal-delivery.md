# M11 — EventJournal, Outbox & Uploader (P1; harden P4)

Status: needs-triage
Execution: not-started
Scope claimed: chưa claim
Owner: Edge + Backend contract; người phụ trách cụ thể chưa gán.
Phase: P1; hardening P4
Updated: 2026-10-11

> Đây là issue/checklist kế hoạch. Không checkbox nào chứng minh runtime đã implement. Triage state khác trạng thái thực hiện; cần gán owner trước khi claim.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `src/traffic_camera/adapters/{persistence,transport}/, application/delivery/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Event/manifest → durable intent → HTTPS → separate receipts.
- SOLID cần kiểm: DIP: application phụ thuộc journal/transport ports; SRP: retry delivery khác FSM incident.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

- [ ] Owner cụ thể nhận module và ghi task/phase sẽ làm trong Comments.
- [ ] Đọc CONTEXT.md, ADR liên quan, kiến trúc và task nguồn; ghi conflict trước khi đổi quyết định.
- [ ] Các prerequisites ở từng task có artifact hoặc fake/fixture contract đã thống nhất; fake chỉ mở unit/contract work, không thay acceptance tích hợp.
- [ ] Chốt input/output/error/reset/version semantics với producer/consumer; số chưa đo ghi null/preliminary, không tự đặt threshold sản phẩm.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### J01 — SQLite schema/migrations, journal+outbox atomic; WAL/FULL/checkpoint/reserve

Phụ thuộc nguồn: `C03,F03`.

- [ ] **J01.01** — Tạo SQLite migrations và transaction ghi event revision + delivery intent, unique identity.
- [ ] **J01.02** — Pin WAL/FULL, checkpoint/max-WAL/reserve/error policy; không giữ DB lock chặn recorder.
- [ ] **J01.03** — Crash giữa writes và inject commit/fsync error; chỉ trả local durable thành công sau commit.
- [ ] **J01.AC** — Nghiệm thu: Crash giữa writes không tạo event không delivery intent; fsync/write errors không ACK thành công.
- [ ] **J01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### J02 — HTTPS metadata retry/backoff/jitter, revision idempotency và metadata receipt

Phụ thuộc nguồn: `J01,S01`.

- [ ] **J02.01** — Gửi HTTPS metadata với auth/limits, bounded backoff+jitter và per-revision hash/idempotency.
- [ ] **J02.02** — Chỉ mark metadata ACK theo durable server receipt; timeout unknown thành query/retry, không assume rollback.
- [ ] **J02.03** — Test duplicate/reorder/conflict/server commit rồi mất response; clip chưa xong không chặn metadata.
- [ ] **J02.AC** — Nghiệm thu: Duplicate/reordered delivery không overwrite history; conflict cùng revision khác hash có lỗi rõ.
- [ ] **J02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### J03 — Evidence resumable/chunk-or-multipart upload, hash/size verify và clip receipt

Phụ thuộc nguồn: `R03,E01,J02`.

- [ ] **J03.01** — Chọn chunk hoặc multipart resumable nhỏ nhất theo E01 contract, giữ evidence identity xuyên retry.
- [ ] **J03.02** — Verify hash/size/server ownership và clip receipt riêng metadata; metadata ưu tiên bandwidth.
- [ ] **J03.03** — Inject ngắt giữa upload/finalize/mất response; retry không tạo object mới vô hạn hoặc ACK trước verify.
- [ ] **J03.AC** — Nghiệm thu: Disconnect retry hoàn tất một evidence identity; metadata tới trước clip vẫn xem được.
- [ ] **J03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### J04 — Startup reconcile/dead-letter/operator recovery và bounded forensic malformed

Phụ thuộc nguồn: `J03,R04`.

- [ ] **J04.01** — Startup reconcile manifest pending/temp/final/missing/corrupt/orphan và upload state.
- [ ] **J04.02** — Dead-letter có reason/operator retry; forensic malformed có quota/sample/compaction, valid revision không bị compact.
- [ ] **J04.03** — Inject unique malformed flood và all recovery states; publish truncation/degraded khi không còn ghi đủ.
- [ ] **J04.AC** — Nghiệm thu: Inject pending/temp/final/missing/corrupt/orphan; unique malformed flood báo truncation/degraded.
- [ ] **J04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### J05 — WAN outage/storage exhaustion/power-cut trên BOM thật

Phụ thuộc nguồn: `J04,R06`.

- [ ] **J05.01** — Chạy WAN outage theo workload Q6 và disk exhaustion với quota/reserve đo thực.
- [ ] **J05.02** — Cắt điện trên BOM thật tại commit/rename/checkpoint rồi recover và so committed IDs/hashes.
- [ ] **J05.03** — Báo autonomy/RPO/RTO/physical durability boundary; kill -9 chỉ là process-crash test.
- [ ] **J05.AC** — Nghiệm thu: Đo autonomy/RPO/RTO trong scope; kill -9 không thay power-cut; không hứa chống disk loss.
- [ ] **J05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M11-ERR01 | DB/file không cùng transaction. | Crash tại pending/temp/fsync/rename/finalize; reconcile checksum/ranges/state từng boundary; X10/X12. |
| M11-ERR02 | WAN outage không chặn detection trong budget. | Ngắt WAN trong budget đã sizing; event local commit vẫn tiếp tục, outbox resume sau recovery, bounds/reserve đo được; X28. |
| M11-ERR03 | Write/fsync failure không ACK giả. | Inject ENOSPC/EIO/fsync error ở DB/file; không local/server receipt giả, health fault và recovery report; X12/X27/X29. |

Ca tích hợp cần phối hợp: **X10, X12, X13, X15, X27, X28, X29, X30**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

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
