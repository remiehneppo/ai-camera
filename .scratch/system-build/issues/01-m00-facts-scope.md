# M00 — Facts, scope và acceptance (P0)

Status: needs-triage
Execution: not-started
Scope claimed: chưa claim
Owner: Product/operations + Edge + ML; người phụ trách cụ thể chưa gán.
Phase: P0
Updated: 2026-10-11

> Đây là issue/checklist kế hoạch. Không checkbox nào chứng minh runtime đã implement. Triage state khác trạng thái thực hiện; cần gán owner trước khi claim.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `docs/site profiles, ADR stream, readiness records`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Facts/ODD/workload → target có owner và failure protocol.
- SOLID cần kiểm: Giữ facts, targets và kết quả đo riêng; không viết source/config production.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

- [ ] Owner cụ thể nhận module và ghi task/phase sẽ làm trong Comments.
- [ ] Đọc CONTEXT.md, ADR liên quan, kiến trúc và task nguồn; ghi conflict trước khi đổi quyết định.
- [ ] Các prerequisites ở từng task có artifact hoặc fake/fixture contract đã thống nhất; fake chỉ mở unit/contract work, không thay acceptance tích hợp.
- [ ] Chốt input/output/error/reset/version semantics với producer/consumer; số chưa đo ghi null/preliminary, không tự đặt threshold sản phẩm.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### F01 — Ghi hardware/camera/firmware/OS/SDK/storage/power/network đang có; đánh dấu số chưa đo

Phụ thuộc nguồn: `Q1`.

- [ ] **F01.01** — Kiểm kê máy lab/camera thực có, gán ID và ghi OS/runtime/storage/network; board đích chưa chọn ghi pending.
- [ ] **F01.02** — Probe phiên bản và capability bằng công cụ trên thiết bị; lưu output đã bỏ credentials, phân biệt đo trực tiếp với datasheet.
- [ ] **F01.03** — Lập sơ đồ failure domain nguồn điện/host/disk/network và người chịu trách nhiệm bổ sung facts thiếu.
- [ ] **F01.AC** — Nghiệm thu: Facts sheet truy được từng thiết bị; không suy camera marketing thành capability.
- [ ] **F01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### F02 — Chọn một site/ROI person-down và positive/hard-negative scenarios; xác định người ký

Phụ thuộc nguồn: `—`.

- [ ] **F02.01** — Chọn camera cố định và vẽ ROI lòng đường; ghi điều kiện ánh sáng, thời tiết, kích thước người và che khuất cần kiểm thử.
- [ ] **F02.02** — Lập bảng positive, hard-negative, ambiguous và unsupported, gồm ngã nhanh/chậm, thiếu onset, người trên yên và xe đổ.
- [ ] **F02.03** — Gán người duyệt ODD và acceptance; vùng/threshold chưa có dữ liệu giữ preliminary, không coi là hỗ trợ.
- [ ] **F02.AC** — Nghiệm thu: ODD gồm kích thước người, ánh sáng/che khuất và tình huống unsupported.
- [ ] **F02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### F03 — Khóa workload/pre-post/ring/pins/offline/review load và preliminary SLO

Phụ thuộc nguồn: `F01,F02,Q2`.

- [ ] **F03.01** — Ghi target lab Q6/Q16 và workload camera/FPS/pose/event/review; để null các số chưa đo.
- [ ] **F03.02** — Tính ring + clip đang pin/chờ postroll + temp/proxy + journal/WAL + log/update reserve từ bitrate/event rate thực.
- [ ] **F03.03** — Chốt preliminary SLO, recorder gap, RPO/RTO và phạm vi outage với owner; ghi cách đo/time-to-full và residual risk.
- [ ] **F03.AC** — Nghiệm thu: Owner ký target thử nghiệm; capacity chưa đo ghi rõ.
- [ ] **F03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### F04 — Probe RTSP sessions, main/sub/codec, reconnect/time mapping; chọn stream ADR

Phụ thuộc nguồn: `F01`.

- [ ] **F04.01** — Probe codec/profile/main-sub, số RTSP sessions đồng thời, reconnect và thay codec trên camera/firmware thực.
- [ ] **F04.02** — So sánh dual-session với recorder-owned relay; xác định upstream/reconnect owner và policy consumer chậm.
- [ ] **F04.03** — Lưu mapping clock/session giữa analytics và recorder, uncertainty, trace và protocol kill/hang; chỉ accepted stream ADR khi có bằng chứng.
- [ ] **F04.AC** — Nghiệm thu: Có trace/video và kill test thiết kế; main/sub được đánh giá theo pixel-on-target.
- [ ] **F04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### F05 — Kiểm tra exact checkpoint/hash/license, quyền dataset; spike export target

Phụ thuộc nguồn: `F01`.

- [ ] **F05.01** — Ghi exact checkpoint/hash, code/weights/dataset terms và nguồn dữ liệu; gán owner clearance theo môi trường.
- [ ] **F05.02** — Chạy spike ONNX với input/output thật; nếu đã có target thì thử conversion sớm, lưu lỗi/operator không hỗ trợ.
- [ ] **F05.03** — Pin manifest/pre-postprocess/runtime và điều kiện chặn release; không ghi license repo thay license weights.
- [ ] **F05.AC** — Nghiệm thu: Manifest nguồn rõ; production clearance chưa có được đánh dấu gate, không tự suy từ code license.
- [ ] **F05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### F06 — Tạo failure matrix và test manifest template từ readiness

Phụ thuộc nguồn: `F03,F04`.

- [ ] **F06.01** — Liệt kê failure source/native/recorder/WAN/server/disk/clock/config và trạng thái mong đợi.
- [ ] **F06.02** — Với mỗi fault, ghi dữ liệu phải giữ, điểm inject, detection time/RTO/gap budget và rollback/cleanup test.
- [ ] **F06.03** — Chuẩn hóa manifest run gồm commit/config/model/data/hardware hashes, expected/actual, owner và log/report.
- [ ] **F06.AC** — Nghiệm thu: Mỗi lỗi có expected state, protected data, RTO/gap budget, owner và evidence cần thu.
- [ ] **F06.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M00-ERR01 | Thiếu camera: replay dùng dữ liệu cleared, live RTSP còn chờ. | Đối chiếu facts sheet với output probe; nếu camera chưa có, live F04/G1 giữ blocked, replay có fixtures cleared vẫn được làm. |
| M00-ERR02 | Thiếu bitrate/event rate: chưa ký storage/autonomy. | Nhập bitrate/event rate chưa biết vào sizing phải ra missing input, không tự ra capacity; kiểm từng quota/reserve có owner. |
| M00-ERR03 | Board chưa chọn không chặn baseline ONNX. | Rà claim G1 không bắt RKNN/board đã chọn; hardware decoder/capacity còn pending tới G3. |

Ca tích hợp cần phối hợp: **G0; facts/readiness review**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

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
