# M12 — Backend ingestion, repository và evidence (P1–P4)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: Backend; người phụ trách cụ thể chưa gán.
Phase: P1–P4
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `apps/server/, schemas/, deploy/ server Compose`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Authenticated metadata/uploads → revisions/current view/receipts/download APIs.
- SOLID cần kiểm: SRP: API validation, use case, repository, evidence storage tách trách nhiệm; DIP theo transaction/storage seam thực có.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §2 snapshot/identity; §4 evidence; §5 review freshness; §6 eligibility](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### S01 — Device auth baseline, request limits/schema + revision persist/receipt

Phụ thuộc nguồn: `C03,Q3`.

- [ ] **S01.01** — Bootstrap FastAPI + exact MongoDB version, một-member replica set persistent volume trong Compose và readiness transaction probe.
- [ ] **S01.02** — Authenticate device/scope rồi validate schema/size/rate; transaction revision/current/outbox intent với unique device/event/revision.
- [ ] **S01.03** — Commit theo ADR-0003 trước receipt; unknown commit dùng idempotency reconciliation, same key/different hash conflict.
- [ ] **S01.AC** — Nghiệm thu: Unique authenticated device/event/revision; same key/different hash conflict; ACK sau durable commit.
- [ ] **S01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### S02 — Event history/current projection, query/filter/pagination và API evidence/review states

Phụ thuộc nguồn: `S01`.

- [ ] **S02.01** — Tách immutable revision history với current projection và review version; newer AI revision không reset review.
- [ ] **S02.02** — Implement filtered cursor pagination theo site/camera/time/type/review với indexes phù hợp query.
- [ ] **S02.03** — Test out-of-order/duplicate/concurrent updates, stable pagination và site/camera authz trên list/detail/history.
- [ ] **S02.AC** — Nghiệm thu: Older revision không lùi current view/reset review; authorization site/camera áp mọi query.
- [ ] **S02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### E01 — Evidence init/upload/finalize; server-controlled object ownership/hash/size

Phụ thuộc nguồn: `S01,C03`.

- [ ] **E01.01** — Định nghĩa upload init/chunk-or-multipart/finalize API với server-controlled evidence/object ownership.
- [ ] **E01.02** — Stage pending object, check size/hash/limits, chỉ finalize và cấp receipt sau xác minh trạng thái durable.
- [ ] **E01.03** — Test traversal/key overwrite/cross-device upload, disconnect và finalize duplicate/conflict; pending không available giả.
- [ ] **E01.AC** — Nghiệm thu: Không overwrite key camera/device khác; pending không giả thành complete.
- [ ] **E01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### E02 — DB/object-store reconciliation, authorized download/proxy và immutable receipt

Phụ thuộc nguồn: `E01`.

- [ ] **E02.01** — Reconcile Mongo metadata với filesystem adapter lab, không giả transaction chung DB/object.
- [ ] **E02.02** — Download raw/proxy qua authorization, range/content type phù hợp; proxy derived có lineage/hash riêng.
- [ ] **E02.03** — Test missing/corrupt/orphan, restart giữa object/DB commit và playback H.265/proxy trên browser mục tiêu.
- [ ] **E02.AC** — Nghiệm thu: Object missing/corrupt/orphan có trạng thái; raw/proxy lineage rõ; H.265 playback path được thử.
- [ ] **E02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### E03 — Retention/delete/export policy, backup/restore và storage failure tests

Phụ thuộc nguồn: `E02,T01`.

- [ ] **E03.01** — Khóa retention/delete/export theo policy và RBAC/audit, xử lý pinned/legal policy nếu được yêu cầu.
- [ ] **E03.02** — Backup cả DB/object/manifests và chạy restore/reconcile vào môi trường tách biệt.
- [ ] **E03.03** — Test storage unavailable/delete partial/restore missing files, report RPO/RTO; production storage topology là gate riêng.
- [ ] **E03.AC** — Nghiệm thu: Không xóa khi trái policy; restore tái dựng metadata↔object state có report RPO/RTO.
- [ ] **E03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M12-ERR01 | Mongo standalone không đạt transaction contract. | Chạy readiness/transaction probe trên standalone phải fail; replica set lab restart có persistent data và transaction atomic; X14. |
| M12-ERR02 | Current projection không lùi vì revision cũ. | Ingest revision mới rồi cũ + concurrent duplicate/conflicting hash; history đúng, current không lùi và review không reset; X13/X17. |
| M12-ERR03 | Filesystem lab không là production object store/HA đã ký. | Restore Mongo + filesystem lab vào env tách biệt và verify every manifest/object/hash; production HA/storage gate vẫn mở nếu chưa có ADR/SLA; X35. |

Ca tích hợp cần phối hợp: **X13, X14, X15, X16, X17, X18, X35**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
