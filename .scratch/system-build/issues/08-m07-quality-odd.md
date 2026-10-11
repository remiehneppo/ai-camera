# M07 — Quality & ODD Monitor (P2)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: ML + Domain; người phụ trách cụ thể chưa gán.
Phase: P2; geometry P4
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `native quality feature extraction, src/traffic_camera/domain/policies/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Native quality metrics + site ODD → QualityReport/capability state.
- SOLID cần kiểm: SRP: native tính metric, domain áp policy; domain không đọc pixels/SDK.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §1 quality/status per-stage không mất capability reason](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### QL01 — Native stats blur/exposure/darkness/frame progression và scene-reference metrics tối thiểu

Phụ thuộc nguồn: `N05,F02`.

- [ ] **QL01.01** — Tính quality statistics tối thiểu tại native, không kéo pixels vào Python hot path.
- [ ] **QL01.02** — Xuất timestamp/source/coverage cho blur/light/frame progression và scene reference.
- [ ] **QL01.03** — Test đứng yên vs frozen, đêm/mưa và metric thiếu; không equate low motion với mất camera.
- [ ] **QL01.AC** — Nghiệm thu: Clip đứng yên khác frozen stream; metrics có timestamp/source.
- [ ] **QL01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### QL02 — Site-specific quality policy, unknown/degraded/out-of-ODD với lý do và recovery

Phụ thuộc nguồn: `QL01`.

- [ ] **QL02.01** — Áp site-specific ODD/quality policy lên metrics và tình trạng không đủ quan sát.
- [ ] **QL02.02** — Publish unknown/degraded/out-of-ODD reason và recovery condition; giữ flags trong event/evidence.
- [ ] **QL02.03** — Test metrics missing/stale, ánh sáng chuyển và recovery; không suppress event im lặng.
- [ ] **QL02.AC** — Nghiệm thu: Missing quality không thành negative; event vẫn giữ evidence/quality flags.
- [ ] **QL02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### QL03 — Camera movement invalidate geometry và policy use-case capabilities

Phụ thuộc nguồn: `QL02,G01`.

- [ ] **QL03.01** — P2 xuất camera-moved flag và degrade person-down theo ODD, chưa đợi ground calibration.
- [ ] **QL03.02** — P4 khóa invalidation interface với G01 trước G02; camera shift invalidate geometry/version.
- [ ] **QL03.03** — Test không tự restore calibration hoặc tiếp tục xuất calibrated speed sau movement.
- [ ] **QL03.AC** — Nghiệm thu: Không tiếp tục xuất calibrated speed khi mất validity; không tự khôi phục calibration.
- [ ] **QL03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M07-ERR01 | Cảnh tĩnh khác frozen. | Clip cảnh tĩnh PTS vẫn tiến khác stream bị treo; assert freeze detector reasons và negative controls; X20. |
| M07-ERR02 | Missing quality không negative. | Xóa/stale quality metrics; assert unknown/degraded flag trong event/UI, không normal certainty; X20/X21. |
| M07-ERR03 | Camera-moved không tự phục hồi calibration. | Inject camera shift sau calibration; calibrated motion disabled tới recalibration hợp lệ, compensation không tự restore; X36. |

Ca tích hợp cần phối hợp: **X20, X21, X36**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
