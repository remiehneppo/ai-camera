# M08 — PoseScheduler & PoseEstimator (P2)

Status: needs-triage
Execution: not-started
Scope claimed: chưa claim
Owner: ML + Edge; người phụ trách cụ thể chưa gán.
Phase: P2
Updated: 2026-10-11

> Đây là issue/checklist kế hoạch. Không checkbox nào chứng minh runtime đã implement. Triage state khác trạng thái thực hiện; cần gán owner trước khi claim.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `src/traffic_camera/application/scheduling/, native/src/models/, model_manifests/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Track ROI requests/budget → versioned pose + coverage/status.
- SOLID cần kiểm: SRP: scheduler chọn ROI, adapter crop/infer/decode; LSP: keypoint/coordinate semantics ổn định.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

- [ ] Owner cụ thể nhận module và ghi task/phase sẽ làm trong Comments.
- [ ] Đọc CONTEXT.md, ADR liên quan, kiến trúc và task nguồn; ghi conflict trước khi đổi quyết định.
- [ ] Các prerequisites ở từng task có artifact hoặc fake/fixture contract đã thống nhất; fake chỉ mở unit/contract work, không thay acceptance tích hợp.
- [ ] Chốt input/output/error/reset/version semantics với producer/consumer; số chưa đo ghi null/preliminary, không tự đặt threshold sản phẩm.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### P01 — Pin RTMPose checkpoint/keypoint schema; ONNX oracle crop/affine/SimCC và original mapping

Phụ thuộc nguồn: `F05,C05,K01`.

- [ ] **P01.01** — Pin RTMPose artifact, keypoint schema/visibility và crop/affine/SimCC parameters.
- [ ] **P01.02** — Chạy ONNX oracle ROI→pose và inverse map original coords, xử lý low-confidence/missing points.
- [ ] **P01.03** — So golden small/occluded/edge ROI cases; không mix COCO17 với schema khác.
- [ ] **P01.AC** — Nghiệm thu: Keypoint missing/low confidence rõ; không trộn schema khác nhau.
- [ ] **P01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### P02 — Fast-fall, slow sampling, persistent-lying scheduling; priority/fairness/deadline

Phụ thuộc nguồn: `K03,QL02,P01`.

- [ ] **P02.01** — Thiết kế fast-fall, slow-collapse sampling và persistent-lying checks trên tracks/quality.
- [ ] **P02.02** — Chọn ROI theo priority/fairness/deadline với per-camera budget; không chỉ trigger y spike.
- [ ] **P02.03** — Dùng scheduling simulation đo coverage/starvation cho cả ba nhánh trước native integration.
- [ ] **P02.AC** — Nghiệm thu: Đo coverage theo nhánh; không chỉ gọi pose khi y spike.
- [ ] **P02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### P03 — Native ROI buffer cache bounded + request_pose/frame/track/deadline; ORT native pose

Phụ thuộc nguồn: `P02,N04`.

- [ ] **P03.01** — Implement bounded native ROI cache/request_pose và buffer lifetime theo frame/session/track.
- [ ] **P03.02** — Tích hợp ORT native crop/affine/SimCC; buffer expired thành skipped, result cũ reject.
- [ ] **P03.03** — So pose oracle/native và test timeout/cancel/restart/ID switch không gắn nhầm pose.
- [ ] **P03.AC** — Nghiệm thu: Buffer đã hết hạn→skipped; pose cũ không gắn frame mới; native/oracle parity.
- [ ] **P03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### P04 — Burst/overload tests và tuning budget theo ODD

Phụ thuộc nguồn: `P03`.

- [ ] **P04.01** — Replay burst đông người/fast-fall đồng thời nhiều ROI với recording/upload.
- [ ] **P04.02** — Đo riêng scheduled/attempted/skipped/failed/stale và coverage từng nhánh, P95/P99 latency.
- [ ] **P04.03** — Tune budget theo ODD đã duyệt; thiếu pose giữ unknown và đưa report vào G2/G3.
- [ ] **P04.AC** — Nghiệm thu: Báo riêng skipped/failed/stale, coverage và end-to-end latency; không suy missing pose thành người bình thường.
- [ ] **P04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M08-ERR01 | Slow collapse và nằm sẵn vẫn được sampling. | Replay slow collapse/nằm sẵn không y-spike, assert pose được schedule theo policy và coverage report; X21/X22. |
| M08-ERR02 | Pose stale không attach frame mới. | Gửi pose response đúng track_id nhưng sai session/frame/deadline; reject, không attach current frame; X22. |
| M08-ERR03 | Cache bounded, expired buffer trả skipped. | Giữ ROI requests quá deadline/đông người; peak cache bounded, release, status skipped/overloaded rõ và track state không âm tính giả; X22. |

Ca tích hợp cần phối hợp: **X21, X22, X25, X26**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

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
