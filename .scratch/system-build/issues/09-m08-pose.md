# M08 — PoseScheduler & PoseEstimator (P2)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: ML + Edge; người phụ trách cụ thể chưa gán.
Phase: P2
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `src/traffic_camera/application/scheduling/, native/src/models/, model_manifests/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Track ROI requests/budget → versioned pose + coverage/status.
- SOLID cần kiểm: SRP: scheduler chọn ROI, adapter crop/infer/decode; LSP: keypoint/coordinate semantics ổn định.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §1 pose terminal outcome/correlation/epoch và mixed statuses](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

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
- [ ] **P03.03** — So pose oracle/native và test timeout/cancel/restart/ID switch không gắn nhầm pose. Accepted requests có terminal outcome, mixed statuses; crash epoch kết thúc outstanding và buffer được release.
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

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
