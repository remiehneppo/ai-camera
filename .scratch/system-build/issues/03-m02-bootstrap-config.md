# M02 — Config, composition và artifact bootstrap (P1; mở rộng P3–P4)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: Edge/platform; người phụ trách cụ thể chưa gán.
Phase: P1; activation P4
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `src/traffic_camera/bootstrap/, apps/edge/, model_manifests/, configs/examples/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Config/secret refs/artifacts → validated immutable snapshot + lifecycle.
- SOLID cần kiểm: DIP: chỉ composition root chọn concrete adapters; OCP bằng allowlist factories, không dynamic imports từ payload.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §1 activation boundary và epoch](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### B01 — Config schema tối thiểu cho source/analysis/model/record/server, secret references và immutable snapshot hash

Phụ thuộc nguồn: `C03,F03`.

- [ ] **B01.01** — Tạo config tối thiểu source/model/pipeline/record/delivery với secret references và schema version.
- [ ] **B01.02** — Validate mọi pipeline enabled trước analytics start; disabled hiển thị reason=disabled; lỗi field/pipeline rõ và redact secret.
- [ ] **B01.03** — Tạo immutable snapshot/hash cho event provenance; lưu config examples không có credentials.
- [ ] **B01.AC** — Nghiệm thu: Reject config sai/capability không có; error mask URI credentials.
- [ ] **B01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### B02 — Allowlisted factories + doctor/warmup, kiểm hash/shape/backend/license gate theo môi trường

Phụ thuộc nguồn: `B01,F05`.

- [ ] **B02.01** — Đăng ký factory allowlist tại composition root và kiểm required capabilities theo config enabled.
- [ ] **B02.02** — Doctor kiểm hash/shape/runtime/device và license gate phù hợp lab/release; warmup input hợp lệ.
- [ ] **B02.03** — Inject artifact sai/backend thiếu/registry ID lạ; fail exit nonzero, không fallback im lặng.
- [ ] **B02.AC** — Nghiệm thu: Wrong artifact/unsupported backend fail rõ; không âm thầm fallback.
- [ ] **B02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### B03 — Lifecycle startup/reconcile/start recorder/start analytics/shutdown timeout

Phụ thuộc nguồn: `B02,R03,J01,N01`.

- [ ] **B03.01** — Wire reconcile journal/evidence trước analytics; recorder được service manager quản lý độc lập.
- [ ] **B03.02** — Start source/native/health/delivery theo readiness; pre-roll chưa đủ có trạng thái incomplete, boot tạo session mới.
- [ ] **B03.03** — Implement drain/cancel/shutdown timeout và release; kiểm analytics start lỗi không dừng recorder đang chạy.
- [ ] **B03.AC** — Nghiệm thu: Khởi động chưa đủ pre-roll có trạng thái incomplete; restart không hồi sinh track RAM cũ.
- [ ] **B03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### B04 — Stage/validate/activate/rollback config tại boundary và lưu desired/observed version

Phụ thuộc nguồn: `B03,T02`.

- [ ] **B04.01** — Khóa local stage/validate/activate/rollback contract và desired/observed versions; local activation không chờ trust rollout P4.
- [ ] **B04.02** — Activate ở boundary rõ, reset state khi continuity thay đổi và gắn snapshot đúng vào event.
- [ ] **B04.03** — Reject config mới sai và giữ last-known-good; signed authorization T02/T04 là gate tích hợp remote production.
- [ ] **B04.AC** — Nghiệm thu: Activation failure giữ last-known-good; event chứa snapshot version đúng.
- [ ] **B04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M02-ERR01 | Enabled config sai: analytics exit nonzero, recorder vẫn sống. | Enabled thiếu field hoặc artifact hash sai phải nonzero analytics startup; kiểm recorder vẫn ghi; X04. |
| M02-ERR02 | Disabled: unavailable reason=disabled. | Disabled thiếu config nghiệp vụ được chấp nhận nhưng capability reason=disabled; không đánh dấu healthy cho use case bị tắt; X04. |
| M02-ERR03 | Runtime fault sau startup: bounded recovery, không dùng để bỏ qua config validation. | Inject runtime model/pipeline exception sau startup hợp lệ, kiểm retry count/deadline/reset/fault; không biến config error thành recovery; X06/X34. |

Ca tích hợp cần phối hợp: **X04, X05, X33, X34**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
