# M06 — Orchestrator và scheduling (P1–P3)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: Edge/platform; người phụ trách cụ thể chưa gán.
Phase: P1–P3
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `src/traffic_camera/application/{pipeline,scheduling}/, native/src/core/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Per-camera observations + budgets → ordered pipeline calls/events.
- SOLID cần kiểm: SRP: application điều phối, domain quyết định sự kiện; DIP: fake ports kiểm scheduling độc lập vendor.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §1 PerceptionPipeline; §3 durable event→pin; §7 stress; §8 target gate](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### O01 — Wiring per-camera session + registry pipeline tính năng + ordered observations + event callbacks

Phụ thuộc nguồn: `N05,I01,J01`.

- [ ] **O01.01** — Wire source/native/scheduler/feature factories và event callbacks qua ports.
- [ ] **O01.02** — Tạo state/config/lifecycle theo camera/session/pipeline; chia sẻ perception chỉ khi model/input/rate/semantics tương thích.
- [ ] **O01.03** — Test pipeline register/reset/disabled và event journal callback; domain không import runtime/DB.
- [ ] **O01.AC** — Nghiệm thu: Registry dùng factory allowlist; state/reset/config theo camera/session/pipeline; thêm pipeline không sửa logic pipeline hiện có; domain không import runtime/DB.
- [ ] **O01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### O02 — Bounded queues, drop/release stale work, deadlines/cancel và shutdown

Phụ thuộc nguồn: `O01`.

- [ ] **O02.01** — Đặt bounds/deadlines cho frame/result/pose queues và bounded reorder theo camera.
- [ ] **O02.02** — Drop/cancel phải release buffer, timeout/drain khi shutdown; event durable không dùng frame-drop policy.
- [ ] **O02.03** — Inject slow detector/pipeline/consumer và kiểm RAM/freshness/recorder continuity.
- [ ] **O02.AC** — Nghiệm thu: Inject slow detector/consumer không tăng RAM vô hạn; recorder không bị backpressure.
- [ ] **O02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### O03 — Degradation/recovery hysteresis: pose→analysis FPS→optional work; capability visibility

Phụ thuộc nguồn: `O02,P02,H01`.

- [ ] **O03.01** — Dùng H01 metrics để chọn degrade thứ tự pose→analysis FPS→optional work trong envelope.
- [ ] **O03.02** — Đặt hysteresis/cooldown/recovery ramp theo benchmark, publish capability/reason tới event và UI.
- [ ] **O03.03** — Test overload-recover lặp; thiếu required capability phải degraded/unsupported, không âm tính giả.
- [ ] **O03.AC** — Nghiệm thu: Không báo healthy khi use case mất capability; recovery không dao động liên tục.
- [ ] **O03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### O04 — Shared runtime serialization/fairness và upload/record contention benchmark

Phụ thuộc nguồn: `O03,C05,I05; A03 nếu RKNN`.

- [ ] **O04.01** — Serialize shared inference context nếu runtime không thread-safe; gán fairness/budget theo camera.
- [ ] **O04.02** — Benchmark nhiều camera và pose burst cùng recording/upload sau conformance target (A03 nếu RKNN); ghi per-camera age/drop/coverage.
- [ ] **O04.03** — Dùng cùng integration run với A05, khóa accepted workload/headroom; không tạo dependency O04↔A05.
- [ ] **O04.AC** — Nghiệm thu: Multi-camera có per-camera freshness/drop/pose coverage; chốt capacity từ số đo.
- [ ] **O04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M06-ERR01 | Events không drop như frames. | Overload frame/result queues trong lúc event được tạo; event/outbox vẫn durable hoặc fault commit rõ, không frame-drop valid event; X06/X12. |
| M06-ERR02 | Consumer chậm không chặn recorder. | Block một consumer/pipeline rồi đo recorder gaps và memory bounds; X06/X07. |
| M06-ERR03 | Shared context không thread-safe phải serialize. | Stress concurrent requests trên shared runtime; dùng serialization/fairness policy và report per-camera starvation/age; X22/X26. |

Ca tích hợp cần phối hợp: **X05, X06, X07, X22, X26**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
