# M07 — Quality & ODD Monitor (P2)

Status: needs-triage
Execution: not-started
Scope claimed: chưa claim
Owner: ML + Domain; người phụ trách cụ thể chưa gán.
Phase: P2; geometry P4
Updated: 2026-10-11

> Đây là issue/checklist kế hoạch. Không checkbox nào chứng minh runtime đã implement. Triage state khác trạng thái thực hiện; cần gán owner trước khi claim.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `native quality feature extraction, src/traffic_camera/domain/policies/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Native quality metrics + site ODD → QualityReport/capability state.
- SOLID cần kiểm: SRP: native tính metric, domain áp policy; domain không đọc pixels/SDK.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

- [ ] Owner cụ thể nhận module và ghi task/phase sẽ làm trong Comments.
- [ ] Đọc CONTEXT.md, ADR liên quan, kiến trúc và task nguồn; ghi conflict trước khi đổi quyết định.
- [ ] Các prerequisites ở từng task có artifact hoặc fake/fixture contract đã thống nhất; fake chỉ mở unit/contract work, không thay acceptance tích hợp.
- [ ] Chốt input/output/error/reset/version semantics với producer/consumer; số chưa đo ghi null/preliminary, không tự đặt threshold sản phẩm.

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
