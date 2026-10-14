# M16 — Health, trust, control và rollout (P1 baseline; P4 đầy đủ)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: Edge + Backend + Operations/security; người phụ trách cụ thể chưa gán.
Phase: P1 H01/baseline; P4 đầy đủ
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `Platform/fleet adapters, server fleet APIs, deploy/, docs/runbooks/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Health/device identity/signed commands → observed state, faults, authorized activation.
- SOLID cần kiểm: SRP: health/trust/rollout use cases riêng; DIP theo platform/control ports, không service locator.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §2 origin guard; §6 eligibility; §8 rollout trên target đã chọn](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### H01 — Structured logs + health states + basic frame age/disk/outbox/recorder/backend metrics

Phụ thuộc nguồn: `B03,J02,R04`.

- [x] **H01.01** — Structured logs/health starting/healthy/degraded/unavailable với component reason và capability.
- [x] **H01.02** — Xuất frame age/drop/recorder gap/disk/outbox/backend metrics, bounded labels/spool và redact secrets.
- [x] **H01.03** — Test deadlock/native failure/recorder mất dữ liệu không báo healthy; telemetry đầy không ăn state reserve.
- [x] **H01.AC** — Nghiệm thu: Mask secrets; bounded cardinality/spool; analytics unhealthy không chỉ báo process running.
- [x] **H01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### H02 — Synthetic end-to-end probe và alert contracts/runbooks/routing

Phụ thuộc nguồn: `H01,S01,W02 guard`.

- [ ] **H02.01** — Tạo synthetic probe E2E qua decode/infer/journal/server với source/origin immutable guard.
- [ ] **H02.02** — Định nghĩa alert metric/window/threshold/severity/owner/runbook/recovery theo site profile.
- [ ] **H02.03** — Inject probe fail/pin gap/deadlock; fault route riêng và synthetic không đi notification thật.
- [ ] **H02.AC** — Nghiệm thu: Probe giữ synthetic origin; deadlock/record gap/pin failure báo fault, không cứu hộ.
- [ ] **H02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### T01 — Device enroll/provision/activate/rotate/quarantine/revoke/decommission; site RBAC/audit/privacy record

Phụ thuộc nguồn: `S01,F06`.

- [ ] **T01.01** — Implement device enroll/provision/activate/rotate/quarantine/revoke/decommission có audit.
- [ ] **T01.02** — Site/camera/evidence RBAC và privacy approval record có người/ngày/phạm vi trước field data pilot.
- [ ] **T01.03** — Test cross-site deny, rotated/revoked credentials và raw/export audit; baseline P1 không đợi full fleet lifecycle.
- [ ] **T01.AC** — Nghiệm thu: Cross-site deny tests, revoked device bị chặn, named approval trước field data pilot.
- [ ] **T01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### T02 — Signed bundle target/hash/length/sequence/expiry/canonical bytes + bootstrap/trusted keys

Phụ thuộc nguồn: `T01,C05,I05; A03 nếu RKNN`.

- [ ] **T02.01** — Khóa signed bundle canonical bytes, target/hash/length/sequence/expiry/trusted roles và bootstrap keys.
- [ ] **T02.02** — Verify trước activation, persist high-water mark, policy uncertain-clock/offline giữ authorized last-known-good.
- [ ] **T02.03** — Test tamper/wrong target/bad signature/expired/old sequence/clock uncertain và restart không hạ trust sequence.
- [ ] **T02.AC** — Nghiệm thu: Reject wrong target/bad signature/old sequence/expired/uncertain-clock; persist high-water mark.
- [ ] **T02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### T03 — Outbound HTTPS long-poll command với IDs/auth/expiry/replay guard; retrieval job

Phụ thuộc nguồn: `T01,J03,R05`.

- [ ] **T03.01** — Implement outbound HTTPS long-poll commands với ID/target/auth/expiry/replay guard, không remote shell.
- [ ] **T03.02** — Tạo retrieval job states pending/offline/expired/completed và idempotent retry/receipt.
- [ ] **T03.03** — Test mất kết nối/duplicate/out-of-order/revoked/clip expired và cleanup trong lúc truy hồi.
- [ ] **T03.AC** — Nghiệm thu: Offline/pending/expired, retry idempotent; không remote shell hoặc arbitrary executable payload.
- [ ] **T03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### T04 — Canary activation/last-known-good, authorized rollback sequence mới, state/data compatibility

Phụ thuộc nguồn: `T02,B04 contract`.

- [ ] **T04.01** — Dùng local B04 activation contract và T02 trust verification để stage/canary/activate bundle.
- [ ] **T04.02** — Lưu desired/observed/LKG, reset/compatibility policy cho state/schema/model; recorder tiếp tục khi restart analytics.
- [ ] **T04.03** — Test activate lỗi→LKG, rollback authorization sequence mới trỏ artifact cũ, không bypass signature/high-water mark.
- [ ] **T04.AC** — Nghiệm thu: Update failure rollback đúng; không hạ trust sequence hoặc trộn model versions im lặng.
- [ ] **T04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### T05 — Reproducible image/provisioning, least-privilege services, SBOM/build provenance

Phụ thuộc nguồn: `T04,A05`.

- [ ] **T05.01** — Build reproducible image/provisioning/service units với least privilege và SBOM/provenance.
- [ ] **T05.02** — Kiểm device node/runtime ACL, watchdog heartbeat, resource budget và deploy/restore runbook.
- [ ] **T05.03** — Provision thiết bị sạch rồi repeat upgrade/restore; hardening không làm mất recorder/runtime access.
- [ ] **T05.AC** — Nghiệm thu: Test device-node/runtime ACL/watchdog heartbeat; deploy/restore bằng runbook lặp lại được.
- [ ] **T05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### T06 — Native crash/RTO gate và quyết định process isolation nếu cần

Phụ thuộc nguồn: `A05,H02`.

- [ ] **T06.01** — Inject native crash/hang và đo analytics recovery/session reset theo RTO đã ký.
- [ ] **T06.02** — Nếu in-process không đạt, ghi ADR process isolation; chọn bounded metadata IPC tối thiểu và deadline/restart policy.
- [ ] **T06.03** — Rerun stale epoch/IPC conformance/fault suite/capacity khi đổi boundary; không tự thêm shared memory.
- [ ] **T06.AC** — Nghiệm thu: Nếu tách process: bounded IPC/timeouts/epoch/restart conformance; không bắt buộc shared memory.
- [ ] **T06.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M16-ERR01 | Synthetic không đi notification. | Run synthetic probe end-to-end + retry/revision và kiểm notification guard; fault route khác rescue route; X31. |
| M16-ERR02 | Rollback không hạ high-water mark. | Accept sequence mới rồi restart và thử old bundle/rollback trái phép; high-water mark durable, authorized rollback sequence mới; X33. |
| M16-ERR03 | Process isolation chỉ sau fault/RTO evidence. | Đo X34 in-process trước; chỉ mở isolation ADR khi crash/RTO evidence cần, sau đổi IPC rerun conformance/capacity. |

Ca tích hợp cần phối hợp: **X04, X06, X08, X16, X26, X27, X30, X31, X32, X33, X34, X35**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
