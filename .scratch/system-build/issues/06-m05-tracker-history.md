# M05 — Tracker và history (P1; đánh giá sâu P2)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: ML/perception; người phụ trách cụ thể chưa gán.
Phase: P1–P2
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `native/src/tracking/, src/traffic_camera/adapters/tracking/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Detections + timestamps → scoped TrackSnapshot/history.
- SOLID cần kiểm: LSP: tracker oracle/native cùng aging/reset semantics; ISP: không bắt consumer cần track phải nhận pixels.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §1 tracker một update/frame; late pose và reset epoch](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### K01 — ByteTrack oracle adapter; measured/predicted, lost/ended và aging theo thời gian

Phụ thuộc nguồn: `N02,C02`.

- [ ] **K01.01** — Bọc ByteTrack oracle theo DetectionBatch và timestamps thật, scoped camera/session.
- [ ] **K01.02** — Định nghĩa tentative/confirmed/lost/ended, measured/predicted và aging theo thời gian; audit stock frame-count assumptions.
- [ ] **K01.03** — Chạy variable FPS/gaps/out-of-order/reset vectors và lưu track sequences reference.
- [ ] **K01.AC** — Nghiệm thu: Fixtures variable FPS/gaps/out-of-order không dùng frame-count thay duration.
- [ ] **K01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### K02 — Tích hợp ByteTrack C++ vào core theo cùng semantics

Phụ thuộc nguồn: `K01,N03`.

- [ ] **K02.01** — Tích hợp ByteTrack C++ reuse implementation có terms rõ, áp cùng time/reset semantics.
- [ ] **K02.02** — Giữ state/history riêng mỗi camera/epoch, giới hạn reorder và bỏ result quá cũ.
- [ ] **K02.03** — So native/oracle sequences; test hai camera cùng local track IDs không trộn history.
- [ ] **K02.AC** — Nghiệm thu: Conformance track sequences + reset epoch đạt; state không share qua camera.
- [ ] **K02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### K03 — Đo fragmentation/ID switch trên clip thật; nối history thận trọng và policy unknown

Phụ thuộc nguồn: `K02,D01`.

- [ ] **K03.01** — Đo ID switch/fragmentation trên dataset theo ODD, gồm đám đông/che khuất lúc ngã.
- [ ] **K03.02** — Định nghĩa gap handling và association uncertainty; chỉ nối history khi bằng chứng đủ.
- [ ] **K03.03** — Đánh giá tác động lên person-down và pose coverage; lưu ambiguous, không coi track là danh tính.
- [ ] **K03.AC** — Nghiệm thu: Báo cáo lỗi theo ODD; không nhận track ID là danh tính; không nối chỉ vì gần bbox.
- [ ] **K03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M05-ERR01 | Variable FPS không aging bằng stock frame-count mù. | Chạy cùng content time với variable FPS và gaps; lost/ended time đúng policy, không tỷ lệ theo số frame; X02/X21. |
| M05-ERR02 | ID switch không gán pose/history chắc chắn. | Inject ID switch/occlusion cùng pose response cũ; association unknown hoặc reject, không chuyển history chắc chắn; X21/X22. |
| M05-ERR03 | Camera/session không share state. | Hai camera/epochs dùng cùng local track_id; assert history/state tách và reset không ảnh hưởng camera khác; K02 contract suite. |

Ca tích hợp cần phối hợp: **X02, X21, X22, X25**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
