# M14 — Data engine và evaluation (P0 samples; P2 vận hành)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: ML + Product/QA; người phụ trách cụ thể chưa gán.
Phase: P0 samples; P2 evaluation
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `Dataset manifests, replay/evaluation tooling, authorized data storage`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Cleared clips/review labels/sampling → reproducible quality reports.
- SOLID cần kiểm: SRP: labels/metrics tách inference; pure metric functions test bằng expected counts.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §5 exact reviewed revisions; sampling weighting/denominator theo D03/D04](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### D01 — Dataset manifest/quyền sử dụng/splits theo site-camera-time, labels onset/lying/uncertain

Phụ thuộc nguồn: `F02,F05`.

- [ ] **D01.01** — Thu dataset manifest có quyền, hash và labels onset/lying/uncertain; P0 có mẫu nhỏ cleared.
- [ ] **D01.02** — Split site-camera-time để chống leakage và bổ sung hard negatives đêm/mưa/on-vehicle/occlusion.
- [ ] **D01.03** — Version labels/splits và expected scenarios; dữ liệu nhạy cảm ở storage được phép, không commit video thật vào git.
- [ ] **D01.AC** — Nghiệm thu: Không leak cùng cảnh giữa train/test; có hard negatives đêm/mưa/yên xe và ca đối chứng.
- [ ] **D01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### D02 — Liên kết reviewer labels với event/model/config/clip revision; export có quyền

Phụ thuộc nguồn: `D01,W01`.

- [ ] **D02.01** — Liên kết reviewer label với exact event/review/model/config/clip revision và actor.
- [ ] **D02.02** — Export authorized dataset feedback; correction append audit, không overwrite nhãn gốc.
- [ ] **D02.03** — Test relabel/concurrent update/evidence expired/permission deny; ambiguous có biểu diễn riêng.
- [ ] **D02.AC** — Nghiệm thu: Không overwrite nhãn gốc; correction/audit và ambiguous labels rõ.
- [ ] **D02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### D03 — Negative audit phân tầng clip không có alert; sampling/retention/privacy budget

Phụ thuộc nguồn: `D01,R04`.

- [ ] **D03.01** — Thiết kế stratified sampling clip không có alert theo site/time/weather với privacy/retention budget.
- [ ] **D03.02** — Lưu probability, coverage và missing intervals; lấy được no-event clips từ ring theo budget trước expiry, không đợi ring 10 phút bị xóa.
- [ ] **D03.03** — Review mẫu độc lập và báo uncertainty/bias; alerts-only không dùng để khẳng định recall ngoài đời.
- [ ] **D03.AC** — Nghiệm thu: Lưu sampling probability/coverage; báo uncertainty và bias, không tuyên bố recall tuyệt đối từ alerts-only.
- [ ] **D03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### D04 — Event-level matching/dedup, recall/precision/FP camera-day và review minutes

Phụ thuộc nguồn: `D02,D03,I05`.

- [ ] **D04.01** — Định nghĩa event matching windows, dedup, denominator/ODD/time coverage và metric evaluation.
- [ ] **D04.02** — Tính event recall/precision/FP camera-day/review minutes cùng missed/unknown/out-of-ODD.
- [ ] **D04.03** — Kiểm trên fixture có expected counts, báo số mẫu và uncertainty; tách lab diễn xuất khỏi field quality. Pin matching windows/denominator/minimum samples; tính weighted estimate theo inclusion probability, report missing coverage.
- [ ] **D04.AC** — Nghiệm thu: Định nghĩa denominator/ODD/time coverage; report cả unavailable/out-of-ODD và missed events.
- [ ] **D04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### D05 — Regression release report, chọn rule/model tuning hoặc training theo lỗi đã đo

Phụ thuộc nguồn: `D04`.

- [ ] **D05.01** — Chạy release regression trên held-out sites với artifact/config/dataset hashes.
- [ ] **D05.02** — Phân loại nguyên nhân detector/pose/track/rule/ODD trước quyết định tuning hoặc training.
- [ ] **D05.03** — Candidate phải cải thiện metric đã chọn và giữ conformance; không thêm classifier/training khi chưa có lỗi đo được.
- [ ] **D05.AC** — Nghiệm thu: Không fine-tune/action classifier chỉ vì có toolkit; candidate cải thiện trên held-out sites và giữ parity.
- [ ] **D05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M14-ERR01 | Không leak cùng site-camera-time giữa splits. | Kiểm split manifest theo site-camera-time/scene groups và duplicate clip hashes; fail evaluation nếu leakage. |
| M14-ERR02 | No-event audit phải lấy trước ring expiry theo budget. | Run sampling trước ring expiry với probability/retention budget rồi verify no-event clip còn đọc được; coverage thiếu được báo; X24. |
| M14-ERR03 | Alerts-only không chứng minh recall. | Fixture có missed events/no-alert intervals; expected-count evaluation phải tính denominator/missed/uncertainty, không lấy alerts-only làm recall; X24. |

Ca tích hợp cần phối hợp: **X21, X23, X24, X25, X37**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
