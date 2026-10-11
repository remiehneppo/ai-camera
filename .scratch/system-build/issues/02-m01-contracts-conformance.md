# M01 — Contracts, clock và conformance kit (P0–P1)

Document role: acceptance/checklist; tiến độ ở tracker slices.
Owner: Domain + Edge + ML + Backend; người phụ trách cụ thể chưa gán.
Phase: P0–P1
Updated: 2026-10-11

> Checklist nghiệm thu theo module; claim/Execution nằm trong [tracker slices](../../system-build-slices/PRD.md). Chỉ tick khi có evidence từ ticket tương ứng.

[Mục lục và quy tắc](../../../docs/implementation-checklists/README.md) · [Plan nguồn](../../../docs/architecture/implementation-plan.md) · [Kiểm tra tích hợp](../../../docs/implementation-checklists/integration-release.md)

## Phạm vi và bàn giao

- Ownership dự kiến: `src/traffic_camera/domain/contracts/, schemas/, native/include/, tests/fixtures/`. Chỉ tạo phần cần cho phase đang làm; đường dẫn source chưa tồn tại là vị trí dự kiến.
- Contract: Metadata/time/observations/events/manifests → shared typed/schema contracts.
- SOLID cần kiểm: SRP: data contracts không chứa I/O; ISP: metadata khác buffer; LSP: cùng semantic suite cho adapters.
- Consumers/callers cần rà: các task có dependency tới task trong module này; xem dependency map tại mục lục. Trước sửa source dùng CodeGraph context/impact và kiểm producer/consumer cùng contract.
- Ngoài phạm vi: chức năng chưa được yêu cầu, SDK/backend chưa chọn, scaffold rỗng; không sửa module người khác khi chưa phối hợp ownership.

## Điều kiện bắt đầu

Áp dụng [Definition of Ready/Done chung](../../../docs/implementation-checklists/README.md). Claim ticket slices, đọc ADR/contracts, thống nhất inputs/owner và prerequisites; fixture chỉ mở unit work, không thay acceptance thật.

## Contract hiện hành

Đối chiếu [contracts §1–§7 schema/perception/snapshot/pin/evidence/review/eligibility/replay](../../../docs/architecture/contracts.md). Protocol tại đây thay các diễn giải sơ lược bên dưới; acceptance phải bao phủ producer/consumer liên quan.

## Các bước triển khai theo task

Phụ thuộc giữ ID của backlog hiện hành. Q là quyết định đã ghi trong plan; dependency ghi “contract” chỉ yêu cầu thống nhất contract trước, implementation/integration vẫn phải đạt gate. Các điều chỉnh thứ tự xem mục lục.

### C01 — Định nghĩa IDs/session/epoch, event-time/receive-time/monotonic và discontinuity

Phụ thuộc nguồn: `F02`.

- [ ] **C01.01** — Định nghĩa device/camera/session/frame/track epoch/event IDs và phạm vi uniqueness.
- [ ] **C01.02** — Tách event-time/PTS, receive UTC và local monotonic; định nghĩa clock uncertainty, boot boundary/discontinuity.
- [ ] **C01.03** — Tạo sequences fast/realtime, clock jump và reconnect có expected duration/reset để mọi module dùng chung.
- [ ] **C01.AC** — Nghiệm thu: Semantic replay fast/paced cùng inputs cho cùng temporal outcome; clock jump không tạo motion giả.
- [ ] **C01.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### C02 — Khóa FrameMetadata/Buffer lifecycle, transforms, observation statuses và track/pose association

Phụ thuộc nguồn: `C01`.

- [ ] **C02.01** — Định nghĩa FrameMetadata riêng FrameBuffer ownership/acquire-release, planes/stride/color và TransformContext.
- [ ] **C02.02** — Khóa Detection/Track/Pose association theo camera/session/frame/epoch, keypoint schema và status missing/stale.
- [ ] **C02.03** — Tạo fixture stride khác width, letterbox/crop/rotation và status ok_empty vs failed; pin expected original coordinates.
- [ ] **C02.AC** — Nghiệm thu: Fixture NV12/stride, ROI/letterbox, missing/stale có expected semantic output.
- [ ] **C02.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### C03 — Khóa IncidentEvent/EvidenceManifest/network revision/receipt và compatibility policy

Phụ thuộc nguồn: `C01`.

- [ ] **C03.01** — Khóa IncidentEvent, pipeline provenance, EvidenceManifest và ba FSM AI/review/evidence độc lập.
- [ ] **C03.02** — Định nghĩa revision identity, canonical payload/hash, schema compatibility, metadata/evidence receipts và conflicts.
- [ ] **C03.03** — Tạo valid/malformed/unknown fixtures; kiểm mandatory unknown explicit, giới hạn input và không lộ secret/local path. Snapshot3→1→2/origin substitution; durable pin receipts; partial-uploaded; stale review và eligibility examples.
- [ ] **C03.AC** — Nghiệm thu: Validate unknown provenance tường minh; malformed khác event hợp lệ; no secrets/local paths in public URL.
- [ ] **C03.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### C04 — Chọn một định nghĩa struct chung và generator tối thiểu cho native/Python; adapter serialization

Phụ thuộc nguồn: `C02`.

- [ ] **C04.01** — Chọn một nguồn struct/enum authoritative và cách generate tối thiểu phù hợp binding P1; ghi quyết định.
- [ ] **C04.02** — Sinh native/Python metadata và adapter serialization, không serialize pixel buffers vào payload.
- [ ] **C04.03** — Kiểm round-trip, enum lạ, version mismatch và reproducible generation trên CI.
- [ ] **C04.AC** — Nghiệm thu: Không duy trì hai enum/struct chép tay; round-trip metadata và version mismatch có tests.
- [ ] **C04.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

### C05 — Xây bộ conformance versioned: transform, detection/pose tolerance, tracker sequences, event outputs

Phụ thuộc nguồn: `C02,C03,F05`.

- [ ] **C05.01** — Version golden frames/clips/transform/tracker/event vectors và manifest hash; xác minh quyền sử dụng.
- [ ] **C05.02** — Chốt tolerance detection/pose và deterministic equality cho clock/FSM/identity với ML và consumers.
- [ ] **C05.03** — Tạo runner xuất diff có fixture ID/provenance; khóa policy chặn release khi parity vượt tolerance.
- [ ] **C05.AC** — Nghiệm thu: Hash fixtures + tiêu chí so sánh rõ; exact equality chỉ cho phần deterministic, không ép tensor parity tuyệt đối.
- [ ] **C05.EV** — Ghi test/fixture ID, expected/actual, lệnh chạy thật và artifact/report path trong Comments; ghi rõ phần chưa chạy hoặc blocked.

## Kiểm lỗi trọng điểm

| ID | Invariant / lỗi cần kiểm | Cách kiểm và bằng chứng |
|---|---|---|
| M01-ERR01 | Unknown khác ok_empty. | Fixture cùng detections=[] nhưng status ok_empty/failed phải tạo hai outcome quan sát khác nhau ở consumer; X20/X21. |
| M01-ERR02 | Malformed/unknown schema không silent accept. | Gửi thiếu provenance/schema_version, enum lạ hoặc revision sai; validate trả malformed/version error và forensic bounded, không accept thành normal. |
| M01-ERR03 | Clock domains và epoch không so/trộn tùy tiện. | Fast/realtime, clock jump và cross-session sequences phải giữ duration/reset semantics; X01/X02. |

Ca tích hợp cần phối hợp: **X01, X02, X03, X13, X20, X21**. Xem bước inject/expected/gate tại [ma trận kiểm lỗi](../../../docs/implementation-checklists/integration-release.md). Chỉ chạy case thuộc phase/scope đang claim; case phase sau giữ not-run.

## Review và hoàn tất

Áp dụng [quy tắc review/Done chung](../../../docs/implementation-checklists/README.md) và [release cases](../../../docs/implementation-checklists/integration-release.md). Lưu artifact/lệnh/expected-actual/giới hạn ở ticket thực thi, liên kết vào evidence record dưới đây; không đánh dấu gate chỉ từ unit tests.

## Evidence record

| Task/case | Commit/config/model/data/platform | Command/fixture | Expected | Actual | Artifact | Người kiểm/ngày |
|---|---|---|---|---|---|---|
| Chưa chạy | — | — | — | not-run | — | Chưa gán |

## Comments

- 2026-10-11: Tạo checklist từ kiến trúc/ADR/plan hiện hành; chưa claim, chưa implement, chưa chạy test runtime.
