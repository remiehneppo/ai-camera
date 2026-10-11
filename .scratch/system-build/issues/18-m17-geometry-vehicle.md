# M17 — Calibration, GroundProjector và MotionAnalyzer (P4 vehicle branch)

Status: needs-triage
Execution: not-started
Scope claimed: chưa claim
Owner: Domain + ML + Site operations; người phụ trách cụ thể chưa gán.
Phase: P4 nhánh vehicle có điều kiện
Updated: 2026-10-11

> Đây là issue/checklist kế hoạch. Không checkbox nào chứng minh runtime đã implement. Triage state khác trạng thái thực hiện; cần gán owner trước khi claim.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `src/traffic_camera/domain/motion/, adapters/geometry/, tools/calibration/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Calibration + tracks/time → ground/motion/risk + vehicle acceptance.
- SOLID cần kiểm: SRP: projection khác derivatives và incident decisions; ISP: person-down không bị buộc cần calibrated speed.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

- [ ] Owner cụ thể nhận module và ghi task/phase sẽ làm trong Comments.
- [ ] Đọc CONTEXT.md, ADR liên quan, kiến trúc và task nguồn; ghi conflict trước khi đổi quyết định.
- [ ] Các prerequisites ở từng task có artifact hoặc fake/fixture contract đã thống nhất; fake chỉ mở unit/contract work, không thay acceptance tích hợp.
- [ ] Chốt input/output/error/reset/version semantics với producer/consumer; số chưa đo ghi null/preliminary, không tự đặt threshold sản phẩm.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### G01 — Site survey/intrinsics/distortion/ROI/ground planes, calibration version/validity

Phụ thuộc nguồn: `F02`.

- [ ] **G01.01** — Sau khi mở vehicle scope, survey intrinsic/distortion/road planes và các mốc đo thật.
- [ ] **G01.02** — Version calibration/ROI/PTZ preset/validity và uncertainty map theo vùng với QL03 contract.
- [ ] **G01.03** — Test mốc held-out, multi-plane/che khuất và thay camera; không suy pixel distance thành mét khi chưa valid.
- [ ] **G01.AC** — Nghiệm thu: Mốc đo/uncertainty theo vùng; PTZ/preset/multi-plane xử lý explicit.
- [ ] **G01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### G02 — Ground projection contact-point validity và uncertainty; invalidation do camera shift

Phụ thuộc nguồn: `G01,QL03 contract`.

- [ ] **G02.01** — Map contact points về ảnh gốc rồi ground với plane/version/uncertainty rõ.
- [ ] **G02.02** — Điểm không thấy chân/bánh hoặc sai mặt phẳng trả unknown; movement invalidate geometry.
- [ ] **G02.03** — Test round-trip/uncertainty/camera shift và calibration không tự khôi phục từ compensation.
- [ ] **G02.AC** — Nghiệm thu: Điểm che khuất/khác mặt phẳng→unknown; transform về ảnh gốc không mất reference.
- [ ] **G02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### M01 — Trajectory smoothing/time-aware derivatives/stationary state, measured vs predicted

Phụ thuộc nguồn: `G02,K03`.

- [ ] **M01.01** — Lọc trajectory/outliers và derivatives bằng Δt thật, phân measured vs predicted.
- [ ] **M01.02** — Reset/gate stationary/velocity/acceleration khi gaps/epoch/calibration invalid; history bounded.
- [ ] **M01.03** — Test jitter/variable FPS/occlusion không tạo acceleration giả, không xuất m/s khi geometry unknown.
- [ ] **M01.AC** — Nghiệm thu: Variable Δt/gaps/jitter không tạo acceleration giả; không qua epoch reset.
- [ ] **M01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### M02 — Interaction/TTC risk features với quality và vehicle rule datasets

Phụ thuộc nguồn: `M01,D01`.

- [ ] **M02.01** — Tính interaction/TTC với time/geometry/association quality và unsupported state.
- [ ] **M02.02** — Tạo vehicle feature fixtures near-miss/stop/jam/crash, không tự biến risk thành confirmation.
- [ ] **M02.03** — Test crossing không va chạm, red-light stop và missing geometry; report error theo site ODD.
- [ ] **M02.AC** — Nghiệm thu: Near-miss/red-light stop/traffic jam khác crash; TTC unsupported khi geometry/time kém.
- [ ] **M02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### M03 — Vehicle end-to-end acceptance dataset/report

Phụ thuộc nguồn: `M02,I06,D04`.

- [ ] **M03.01** — Chạy vehicle E2E riêng gồm calibration→motion→I06→evidence→server review.
- [ ] **M03.02** — Tính recall/FP/missed/evidence/review load trên dataset độc lập bằng D04.
- [ ] **M03.03** — Ký G4b theo scope và thresholds riêng; person-down G2/G4a không chứng minh vehicle đạt.
- [ ] **M03.AC** — Nghiệm thu: Có recall/FP/evidence riêng; person-down đạt không tự coi vehicle đạt.
- [ ] **M03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M17-ERR01 | Geometry invalid thì unknown, không m/s giả. | Unknown plane/contact point/camera shift; output ground/motion unknown và không finite calibrated speed giả; X36. |
| M17-ERR02 | TTC không chứng minh collision. | Near-miss/traffic jam/red-light stop fixtures; TTC/overlap không tự thành crash confirmation; X36. |
| M17-ERR03 | G4b riêng, không chặn pilot person-down nếu vehicle disabled. | Vehicle disabled thì G4b deferred, person-down flow độc lập; khi enabled cần M03/G4b report riêng. |

Ca tích hợp cần phối hợp: **X21 negative control, X36; G4b riêng**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

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
