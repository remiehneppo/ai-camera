# M09 — Pipeline tính năng cảnh báo và IncidentEngine (P1 baseline; P2 person-down; P4 vehicle)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: Domain + ML + Product; người phụ trách cụ thể chưa gán.
Phase: P1 baseline; P2 person-down; P4 vehicle
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `src/traffic_camera/domain/incidents/, src/traffic_camera/domain/policies/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Track/pose/quality/time → pure event transitions/revisions.
- SOLID cần kiểm: OCP: thêm pipeline qua registry không sửa FSM pipeline khác; SRP: mỗi feature state riêng; DIP: không I/O/vendor trong evaluate.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §2 snapshot/origin; §3 onset/lying anchor](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### I01 — Taxonomy/FSM/revision/cooldown/dedup baseline và local simulated-event fixture

Phụ thuộc nguồn: `C03,K01`.

- [ ] **I01.01** — Khóa taxonomy, AI FSM, UUID/revision/cooldown/dedup và event provenance pipeline.
- [ ] **I01.02** — Implement evaluate/reset pure domain theo timestamps, không I/O; fixture simulated event gắn synthetic/replay.
- [ ] **I01.03** — Test every allowed/forbidden transition, retry/duplicate/reset và semantic fast/paced cùng inputs cho cùng outcome; chưa tuyên bố AI person-down đạt.
- [ ] **I01.AC** — Nghiệm thu: Deterministic transition tests; event demo được gắn replay/synthetic, chưa tuyên bố nhận diện person-down đạt.
- [ ] **I01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### I02 — Fast/slow fall có onset và persistent lying khi thiếu onset; support/uncertainty provenance

Phụ thuộc nguồn: `P03,QL02`.

- [ ] **I02.01** — Implement nhánh fall có onset quan sát và persistent lying khi onset thiếu.
- [ ] **I02.02** — Đưa quality/track/pose missing vào uncertainty, duration/hysteresis theo event time.
- [ ] **I02.03** — Test ngã nhanh/chậm, nằm sẵn, gaps/ID switch/occlusion và reset không gộp evidence qua session.
- [ ] **I02.AC** — Nghiệm thu: Positives + missing onset/track reset/occlusion/gaps đều có expected transitions.
- [ ] **I02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### I03 — Stationary-upright vehicle association và low-priority review; danger overrides

Phụ thuộc nguồn: `I02,K03`.

- [ ] **I03.01** — Đánh giá association person với xe đã stationary/upright từ trước; giữ confidence/uncertainty.
- [ ] **I03.02** — Tạo person_on_stationary_vehicle ưu tiên thấp vẫn review; danger overrides cho xe đổ/dừng đột ngột.
- [ ] **I03.03** — Test ngủ trên yên, ngã cạnh xe, xe đang chạy/xe đổ và góc camera kém; không silent suppression.
- [ ] **I03.AC** — Nghiệm thu: Ngủ trên yên/xe đổ/ngã cạnh xe: không suppress im lặng; unknown không kết luận chắc.
- [ ] **I03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### I04 — Chốt với product policy review/notification cho ambiguous/on-vehicle và hazard scope

Phụ thuộc nguồn: `I03,F03`.

- [ ] **I04.01** — Ghi bảng severity/review routing cho ambiguous/on-vehicle và traffic hazard scope.
- [ ] **I04.02** — Product/operations ký protocol notification/escalation trước bật side effect thật.
- [ ] **I04.03** — Lab giữ dashboard-only; policy chưa ký chặn notification, không chặn lưu/review event.
- [ ] **I04.AC** — Nghiệm thu: Có quyết định tên/ngày trước pilot; không tự phát notification khẩn.
- [ ] **I04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### I05 — Version rule sets và event regression qua cả oracle/native/backend

Phụ thuộc nguồn: `I02,I03,C05`.

- [ ] **I05.01** — Version rule/config và regression expectations cùng dataset/artifact hashes.
- [ ] **I05.02** — Chạy cùng semantic inputs qua oracle/native/backend và đối chiếu event identity/time/quality/provenance.
- [ ] **I05.03** — Báo drift/recall/FP khi đổi threshold/model; regression fail chặn release, không cập nhật golden để che lỗi.
- [ ] **I05.AC** — Nghiệm thu: Same semantic inputs cho same outcomes; thay threshold có report drift/FP/recall.
- [ ] **I05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### I06 — Rule tai nạn xe tách khỏi person-down: near-miss/stop/crash-suspected

Phụ thuộc nguồn: `G02,M02,I05`.

- [ ] **I06.01** — Chỉ mở vehicle pipeline sau G2 và geometry/motion contracts hợp lệ.
- [ ] **I06.02** — Implement near-miss/stop/crash-suspected rules tách state với person-down.
- [ ] **I06.03** — Test traffic jam/red-light stop vs crash, TTC/overlap không đủ kết luận; report G4b riêng.
- [ ] **I06.AC** — Nghiệm thu: TTC/overlap không đủ tự kết luận; stop đèn đỏ/kẹt xe là negatives; gate riêng.
- [ ] **I06.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M09-ERR01 | Missing onset cần persistent-lying branch. | Fixture che onset nhưng nằm kéo dài trong ROI; assert person_lying_persistent thay vì mất event; X21. |
| M09-ERR02 | On-vehicle hạ ưu tiên không suppress. | Fixture người trên yên xe và xe đổ/ngã cạnh xe; assert vẫn review event và danger override, không suppression; X23. |
| M09-ERR03 | Review không tăng AI confidence. | Confirm review rồi ingest AI revision mới; AI confidence và review state độc lập, actor audit giữ đúng; X17. |

Ca tích hợp cần phối hợp: **X01, X17, X21, X23, X25, X36**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
