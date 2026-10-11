# M13 — Alert/review workflow, dev demo và bàn giao UI

Status: needs-triage
Execution: not-started
Scope claimed: chưa claim
Owner: Backend/dev demo; đội UI sản phẩm sau; người phụ trách cụ thể chưa gán.
Phase: P1 UI01/UI02; P4 UI03/UI04
Updated: 2026-10-11

> Đây là issue/checklist kế hoạch. Không checkbox nào chứng minh runtime đã implement. Triage state khác trạng thái thực hiện; cần gán owner trước khi claim.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `apps/server/ workflow + static demo; apps/dashboard/ chỉ khi đội UI bắt đầu`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Review actions + API → versioned review state và browser flow.
- SOLID cần kiểm: SRP: backend sở hữu transitions, UI trình bày; ISP: đội UI dùng API/schema, không DB/native SDK.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

- [ ] Owner cụ thể nhận module và ghi task/phase sẽ làm trong Comments.
- [ ] Đọc CONTEXT.md, ADR liên quan, kiến trúc và task nguồn; ghi conflict trước khi đổi quyết định.
- [ ] Các prerequisites ở từng task có artifact hoặc fake/fixture contract đã thống nhất; fake chỉ mở unit/contract work, không thay acceptance tích hợp.
- [ ] Chốt input/output/error/reset/version semantics với producer/consumer; số chưa đo ghi null/preliminary, không tự đặt threshold sản phẩm.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### W01 — Review FSM/API unreviewed/confirmed/false_positive/resolved + revision audit

Phụ thuộc nguồn: `S02`.

- [ ] **W01.01** — Implement review transitions unreviewed→confirmed/false_positive và confirmed→resolved độc lập AI FSM.
- [ ] **W01.02** — Conditional expected version update và actor/time/reason audit; định nghĩa invalid transition/conflict API.
- [ ] **W01.03** — Test hai reviewer concurrent và AI revision tới giữa review không ghi đè quyết định/operator confidence.
- [ ] **W01.AC** — Nghiệm thu: Review không sửa AI confidence; concurrent update conflict rõ; review không bị AI revision reset.
- [ ] **W01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### W02 — Notification outbox trong transaction, retry/idempotency, assignment/escalation theo protocol

Phụ thuộc nguồn: `W01,I04`.

- [ ] **W02.01** — P1 persist downstream intent đúng transaction S01, delivery disabled explicit theo dashboard-only lab.
- [ ] **W02.02** — Sau I04/protocol bật: triển khai worker/provider cần thiết, key idempotency/retry/dead-letter và assignment/escalation.
- [ ] **W02.03** — Guard synthetic/replay trước notification outbox ở mọi revision/retry; không tạo no-op publisher báo delivered hoặc thêm broker khi chưa cần.
- [ ] **W02.AC** — Nghiệm thu: Synthetic/replay bị chặn trước outbox kể cả revisions/retry; provider thiếu dedup ghi residual duplicate risk.
- [ ] **W02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### UI01 — Dev demo list/filter/detail, video player, clip states và pipeline/quality status

Phụ thuộc nguồn: `S02,E01`.

- [ ] **UI01.01** — Tạo HTML/CSS/JS dev demo do FastAPI phục vụ, list/filter/detail qua public API.
- [ ] **UI01.02** — Hiển thị metadata trước clip, evidence/quality/pipeline states và loading/empty/error; polling bounded có error handling.
- [ ] **UI01.03** — Đo commit→render theo Q16 với correlation/clock uncertainty; test API chậm/401/403/500 và clip pending/failed.
- [ ] **UI01.AC** — Nghiệm thu: Gọi API thật; metadata trước clip, empty/loading/error rõ; polling đáp ứng Q16.
- [ ] **UI01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### UI02 — Nút review cơ bản và API auth/raw/download flow; bàn giao OpenAPI/fixtures

Phụ thuộc nguồn: `UI01,W01`.

- [ ] **UI02.01** — Thêm review controls theo W01, handle conflict bằng refetch và yêu cầu thao tác mới rõ ràng.
- [ ] **UI02.02** — Playback/download/raw qua API auth; semantic HTML/labels/keyboard và escaped text không inject event payload vào HTML.
- [ ] **UI02.03** — Browser list→detail→play→review; bàn giao OpenAPI/schema/errors/auth/version fixtures cho đội UI.
- [ ] **UI02.AC** — Nghiệm thu: Browser list→detail→play→review; API deny unauthorized; đội UI có đủ schemas/examples và conflict/error semantics.
- [ ] **UI02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### UI03 — Đội UI phase sau: annotation feedback + on-vehicle queue + operator workload

Phụ thuộc nguồn: `UI02,I03,D02`.

- [ ] **UI03.01** — Đội UI phase sau nhận feedback/annotation contract có version và linked evidence/event provenance.
- [ ] **UI03.02** — Tạo on-vehicle/ambiguous queue, sửa nhãn audit và operator workload từ API; không sửa AI output.
- [ ] **UI03.03** — Browser test quyền annotation, stale labels/conflicts, missing evidence và accessibility với reviewer.
- [ ] **UI03.AC** — Nghiệm thu: Không thuộc dev demo; labels tách AI outputs; ambiguous case có context.
- [ ] **UI03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### UI04 — Đội UI phase sau: fleet/retrieval/audit UX

Phụ thuộc nguồn: `UI02,T03,H02`.

- [ ] **UI04.01** — Đội UI phase sau dùng fleet/retrieval/audit API, status offline/pending/expired/revoked rõ.
- [ ] **UI04.02** — Implement raw/export permissions, desired/observed versions và job feedback theo backend contract.
- [ ] **UI04.03** — Test responsive/keyboard/accessibility và cross-site/revoked/expired download cùng API thật trước pilot.
- [ ] **UI04.AC** — Nghiệm thu: Không thuộc dev demo; offline/expired/revoked rõ; raw/export audit và production responsive/accessibility acceptance.
- [ ] **UI04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M13-ERR01 | Lab dashboard-only, không notification ngoài. | Tạo synthetic/replay revisions/retry rồi kiểm notification intent/send bằng 0; lab provider disabled không delivered giả; X31. |
| M13-ERR02 | AI update không reset review. | Hai reviewer cùng expected version và AI revision chen giữa; conflict/refetch rõ, review không reset; X17. |
| M13-ERR03 | Demo không thay nghiệm thu UI production. | Browser demo chạy API flow X18; UI product X37 chưa chạy thì không đánh dấu G4a/G5 UX đã đạt. |

Ca tích hợp cần phối hợp: **X16, X17, X18, X19, X23, X31, X37**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

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
