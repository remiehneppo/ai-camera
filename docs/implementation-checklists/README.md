# Bộ checklist triển khai AI Camera giao thông

Ngày: 2026-10-11. Trạng thái: kế hoạch, chưa implement hoặc nghiệm thu runtime.

Bộ này phân rã **18 module, 89 task hiện hành** thành bước thực hiện, acceptance và evidence record. Checklist module nằm trong tracker Markdown `.scratch/system-build/issues/` theo quy ước repo; tài liệu này là điểm vào để theo dõi. [PRD / phạm vi](../../.scratch/system-build/PRD.md).

- [Phân tích kiến trúc, SOLID và dependency](architecture-analysis.md).
- [Kiểm thử xuyên module, 37 failure cases và G0–G5](integration-release.md).
- [Plan gốc và quyết định Q1–Q19](../architecture/implementation-plan.md).
- [Kiến trúc semantic/fault boundaries](../architecture/system-architecture.md).
- [Readiness / mẫu facts và benchmark](../architecture/deployment-readiness.md).
- [Nhật ký tạo checklist](../logs/2026-10-11-implementation-checklists.md).

## 1. Cách dùng và trạng thái

1. Chọn phase và task đủ prerequisites; đọc analysis, CONTEXT/ADR và checklist module. Một module có nhiều phase, chỉ implement phần hiện tại.
2. Gán owner cụ thể, scope file và người tích hợp; cập nhật `Status:` theo [triage labels](../agents/triage-labels.md). Mặc định `needs-triage` vì chưa claim/gán nhân sự, không có nghĩa mọi module thiếu thông tin.
3. Dùng `Execution: not-started | in-progress | blocked | done` để ghi tiến độ module trong phạm vi đã claim. Dependencies chưa xong là blocker thực hiện; `needs-info` chỉ khi thiếu facts/decision cụ thể cần người cung cấp. Không tự biến quyết định đã accepted thành câu hỏi lại.
4. Trước code, xem callers/consumers bằng CodeGraph và liệt kê schema/config/exports/bindings/fixtures/migrations bị ảnh hưởng. Sửa shared contract phải review cả producer lẫn consumer.
5. Tick bước `.01`–`.03` khi có artifact; `.AC` khi acceptance pass; `.EV` khi có evidence record. Không tick toàn module vì một task P1 xong trong khi P4 còn mở.
6. Chạy unit/contract phù hợp rồi integration/regression theo cases trong release checklist. Ghi lệnh thật và phần chưa chạy; mock không thay DB/RTSP/hardware/browser proof.
7. Cập nhật `## Comments` append-only và docs/logs bằng hành động/quyết định/giới hạn. Gate chỉ pass khi có đủ reports và owner sign-off, không từ phần trăm checkbox.

`Status:` là triage role, không là kiểm thử hay chất lượng sản phẩm. Chỉ ghi `Execution: done` khi toàn phạm vi claim đạt acceptance/evidence; nếu claim P1, ghi rõ `Scope claimed: P1` và các phần sau còn deferred. N/A phải có lý do/owner; không dùng N/A cho branch đang bật nhưng test khó chạy.

Không đánh dấu checklist trong lần tạo này. Không có lệnh runtime đã chạy, actual measurement hoặc release approval mới. Checklist source paths là dự kiến, không yêu cầu tạo sẵn mọi folder/interface.

## 2. Checklist từng module

| Module / file riêng | Phase | Tasks nguồn | Owner vai trò |
|---|---|---|---|
| [M00 — Facts, scope và acceptance (P0)](../../.scratch/system-build/issues/01-m00-facts-scope.md) | P0 | F01, F02, F03, F04, F05, F06 | Product/operations + Edge + ML |
| [M01 — Contracts, clock và conformance kit (P0–P1)](../../.scratch/system-build/issues/02-m01-contracts-conformance.md) | P0–P1 | C01, C02, C03, C04, C05 | Domain + Edge + ML + Backend |
| [M02 — Config, composition và artifact bootstrap (P1; mở rộng P3–P4)](../../.scratch/system-build/issues/03-m02-bootstrap-config.md) | P1–P4 | B01, B02, B03, B04 | Edge/platform |
| [M03 — VideoSource, demux và decoder (P1)](../../.scratch/system-build/issues/04-m03-video-decode.md) | P1; hardware P3 | V01, V02, V03, V04 | Edge/platform |
| [M04 — Native core, detector và pre/postprocess (P1)](../../.scratch/system-build/issues/05-m04-native-detector.md) | P1 | N01, N02, N03, N04, N05 | Edge + ML |
| [M05 — Tracker và history (P1; đánh giá sâu P2)](../../.scratch/system-build/issues/06-m05-tracker-history.md) | P1–P2 | K01, K02, K03 | ML/perception |
| [M06 — Orchestrator và scheduling (P1–P3)](../../.scratch/system-build/issues/07-m06-orchestrator-scheduling.md) | P1–P3 | O01, O02, O03, O04 | Edge/platform |
| [M07 — Quality & ODD Monitor (P2)](../../.scratch/system-build/issues/08-m07-quality-odd.md) | P2; geometry P4 | QL01, QL02, QL03 | ML + Domain |
| [M08 — PoseScheduler & PoseEstimator (P2)](../../.scratch/system-build/issues/09-m08-pose.md) | P2 | P01, P02, P03, P04 | ML + Edge |
| [M09 — Pipeline tính năng cảnh báo và IncidentEngine (P1 baseline; P2 person-down; P4 vehicle)](../../.scratch/system-build/issues/10-m09-incident-pipelines.md) | P1/P2; vehicle P4 | I01, I02, I03, I04, I05, I06 | Domain + ML + Product |
| [M10 — Recorder, pin và RetentionManager (P1 tối thiểu; P4 đầy đủ)](../../.scratch/system-build/issues/11-m10-recorder-retention.md) | P1/P4 | R01, R02, R03, R04, R05, R06 | Edge/platform |
| [M11 — EventJournal, Outbox & Uploader (P1; harden P4)](../../.scratch/system-build/issues/12-m11-journal-delivery.md) | P1/P4 | J01, J02, J03, J04, J05 | Edge + Backend contract |
| [M12 — Backend ingestion, repository và evidence (P1–P4)](../../.scratch/system-build/issues/13-m12-backend-evidence.md) | P1–P4 | S01, S02, E01, E02, E03 | Backend |
| [M13 — Alert/review workflow, dev demo và bàn giao UI](../../.scratch/system-build/issues/14-m13-review-demo-ui.md) | P1 demo; UI P4 | W01, W02, UI01, UI02, UI03, UI04 | Backend/dev demo; đội UI phase sau |
| [M14 — Data engine và evaluation (P0 samples; P2 vận hành)](../../.scratch/system-build/issues/15-m14-data-evaluation.md) | P0/P2 | D01, D02, D03, D04, D05 | ML + Product/QA |
| [M15 — Model Registry, conversion và RK3588 (P3)](../../.scratch/system-build/issues/16-m15-rknn-capacity.md) | P3 | A01, A02, A03, A04, A05 | ML + Edge |
| [M16 — Health, trust, control và rollout (P1 baseline; P4 đầy đủ)](../../.scratch/system-build/issues/17-m16-health-trust-rollout.md) | P1 baseline/P4 | H01, H02, T01, T02, T03, T04, T05, T06 | Edge + Backend + Operations/security |
| [M17 — Calibration, GroundProjector và MotionAnalyzer (P4 vehicle branch)](../../.scratch/system-build/issues/18-m17-geometry-vehicle.md) | P4 vehicle | G01, G02, M01, M02, M03 | Domain + ML + Site operations |

## 3. Dependency và phạm vi phối hợp

Bảng này tổng hợp **tham chiếu task xuyên module**, không là graph build bắt buộc phải hoàn thành toàn module. Dependencies task cụ thể nằm ngay trên từng checklist task. M02/M06/M07/M16 có contract và implementation ở nhiều phase; dùng thứ tự tách tại analysis để tránh chờ vòng.

| Module | Nhận đầu vào từ module | Consumers trực tiếp theo backlog |
|---|---|---|
| M00 | — | M01, M02, M03, M04, M07, M08, M09, M10, M11, M14, M15, M16, M17 |
| M01 | M00 | M02, M03, M04, M05, M08, M09, M10, M11, M12, M15 |
| M02 | M00, M01, M04, M10, M11, M16 | M16 |
| M03 | M00, M01, M10 | M04 |
| M04 | M00, M01, M03, M05 | M02, M05, M06, M07, M08, M15 |
| M05 | M01, M04, M14 | M04, M08, M09, M17 |
| M06 | M04, M08, M09, M11, M15, M16 | M10, M15 |
| M07 | M00, M04, M17 | M08, M09, M17 |
| M08 | M00, M01, M04, M05, M07 | M06, M09, M15 |
| M09 | M00, M01, M05, M07, M08, M17 | M06, M13, M14, M15, M17 |
| M10 | M00, M01, M06, M11, M12 | M02, M03, M11, M14, M15, M16 |
| M11 | M00, M01, M10, M12 | M02, M06, M10, M16 |
| M12 | M01, M16 | M10, M11, M13, M16 |
| M13 | M09, M12, M14, M16 | M14, M16 |
| M14 | M00, M09, M10, M13 | M05, M13, M17 |
| M15 | M00, M01, M04, M06, M08, M09, M10 | M06, M16 |
| M16 | M00, M02, M10, M11, M12, M13, M15 | M02, M06, M12, M13 |
| M17 | M00, M05, M07, M09, M14 | M07, M09 |

Consumers theo bảng dependency chưa bao gồm mọi người dùng semantic schema dùng chung. Khi C01–C05/C03 thay đổi phải rà **tất cả** native bindings, journal/upload, server APIs, fixtures và UI consumers, dù không hiện như dependency trực tiếp trong bảng.

Các điểm không được dùng làm hard prerequisite sai phase:

- F04/C03 khóa ownership/pin contract → R01 recorder → V04 correlation.
- B04 local activation có trước T02/T04 signed remote integration; remote không bypass trust gate.
- QL03 camera-moved P2; G01/QL03 validity contract P4 → G02 projection.
- O04/A05 cùng một benchmark integration sau A03, không chờ vòng nhau.
- W02 intent/schema + synthetic guard có baseline P1; worker/provider/assignment/escalation khi protocol được bật, lab dashboard-only.
- M17/G4b chỉ khi vehicle scope bật; person-down G4a/G5 không phải đợi vehicle disabled.

## 4. Ownership để tránh conflict

| Nhánh | File ownership dự kiến | Handoff bắt buộc |
|---|---|---|
| Contracts/Domain | `src/traffic_camera/domain/`, semantic definitions trong `schemas/` | Clock/IDs/status/FSM, compatibility và fixture versions |
| Edge/Native/ML | `native/`, edge `application/`, `adapters/`, `bootstrap/`, `apps/edge/`, manifests/tooling | Metadata-only API, buffer lifecycle, model/track/pose parity, pin/delivery contracts |
| Backend | `apps/server/`, server deploy/DB/storage | Auth/authz, OpenAPI/schema, receipts/revision/review/evidence/health semantics |
| Dev demo | Phần static HTML/JS trong `apps/server/`; phối hợp cùng backend owner | API thật, list/detail/play/review và browser evidence; không frontend service riêng |
| Đội UI sản phẩm | `apps/dashboard/` hoặc repo UI được thống nhất sau; UI03/UI04 | Auth/version/error fixtures, annotation/fleet UX, accessibility/operations acceptance |
| QA/operations | Integration/hardware suites, `deploy/`, reports/runbooks | Protocol fault/restore/rollout, manifest và signed acceptance |

Vai trò không tự cấp quyền sửa cùng file: trước claim gán người chịu trách nhiệm file chia sẻ, đặc biệt `schemas/`, `apps/server/` và deployment Compose. Nếu sửa contract ảnh hưởng nhánh khác, bàn giao schema + examples + failure semantics trước integration. Không đổi scaffold/framework UI sản phẩm trong scope dev demo.

## 5. Definition of Ready / Done dùng chung

**Ready để bắt đầu task:** owner được gán; scope/inputs/dependencies/failure semantics rõ; fixtures có quyền dùng; acceptance và commands dự định được ghi; quyết định thiếu có owner xử lý. Có thể viết pure unit/contract qua fixture trước khi hardware có, nhưng hardware acceptance vẫn blocked.

**Done cho task:** implementation và mọi callers/consumers/config/fixtures/exports liên quan đã cập nhật; tests đúng failure path pass; không vi phạm dependency direction; input trust boundaries/cleanup/bounds được kiểm; artifacts và lệnh reproduce có link; limitations được ghi. `.AC` và `.EV` đều tick mới tính task đã hoàn thành.

**Done cho module/phase:** toàn scope claim đạt task Done, producer/consumer integration thực pass và handoff có owner. **Gate accepted:** thêm SLO/quality/workload evidence và chữ ký owner theo integration-release. Unit pass không thay browser, fault/soak, hardware hoặc field acceptance.

Review SOLID theo analysis và đoạn riêng của từng module. Review tính đúng trước độ ngắn của diff; không bỏ validation/error handling/accessibility/hardware calibration cần cho phạm vi đang bật. Không tạo class/port/service cho helper chỉ để đạt hình thức.

## 6. Target hiện hành và quyết định chưa đo

| Nội dung | Đã xác nhận cho lab | Còn phải đo/chốt theo gate |
|---|---|---|
| Use case | Person-down, camera cố định/ROI lòng đường trước | ODD/pixel-on-target/quality thresholds/site dataset |
| Baseline | ONNX/software decode; tracker C++ P1, native pose P2 | Target board/codec/buffer/SDK thực và RKNN P3 |
| Evidence | Pre 10s/post 20s; ring 10 phút; server clips 7 ngày | Bitrate/event rate/quota/endurance và actual completeness |
| WAN budget | 24h sizing cho clip chưa ACK | Autonomy đo thực; không là TTL xóa pinned/unACK |
| Latency lab | P95 durable edge commit→dashboard ≤5s trên LAN | Clock correlation/uncertainty, sample count và browser render timings |
| Backend | FastAPI/Python, Mongo replica set một member/persistent volume lab | Exact version/bootstrap/transactions, production HA/backup/restore |
| UI | Dev demo HTML/JS tối thiểu gọi API, dashboard-only | UI sản phẩm/operations/accessibility do đội UI tích hợp sau |
| Extension | Server downstream EventPublisher; allowlisted feature pipelines | Chỉ thêm provider/broker/process khi use case/fault/benchmark cần |

Lựa chọn filesystem evidence lab và polling demo là triển khai tối thiểu có thể đổi; không tự biến thành production ADR. Production cloud/on-prem, topology storage/HA, trust/privacy và license clearance vẫn theo readiness.

## 7. Theo dõi tiến độ

Mọi task/gate hiện `not-run/not-started`. Không điền % tiến độ dựa trên tài liệu đã viết. Khi thực hiện, cập nhật bảng sau bằng evidence thật; nếu module làm nhiều phase, thêm dòng cho từng scope claim.

| Scope | Owner người thật | Execution | Task AC+EV xong / tổng scope | Gate/evidence | Blocker / bước tiếp |
|---|---|---|---|---|---|
| P0 | Chưa gán | not-started | 0 / chưa claim | G0 chưa nghiệm thu | Facts/contracts và người ký |
| P1 | Chưa gán | not-started | 0 / chưa claim | G1 chưa nghiệm thu | G0 + vertical slice |
| P2 | Chưa gán | not-started | 0 / chưa claim | G2 chưa nghiệm thu | Person-down datasets/quality |
| P3 | Chưa gán | not-started | 0 / chưa claim | G3 chưa nghiệm thu | Target hardware + parity/capacity |
| P4 | Chưa gán | not-started | 0 / chưa claim | G4a/G4b chưa nghiệm thu | Reliability/trust/UI/vehicle scope |
| P5 | Chưa gán | not-started | 0 / chưa claim | G5 chưa nghiệm thu | Field acceptance/restore/scale |

Thay đổi source/config/tests chưa thuộc lần xây checklist này; không stage/commit/push. Các issue mới là backlog cần triage, không tự claim cho agent hay hứa lịch triển khai.

## 8. Tracker theo lát cắt đã publish

Người dùng đã duyệt breakdown và [50 ticket tracer-bullet đã publish](../../.scratch/system-build-slices/PRD.md), bao phủ đủ 89 task nguồn. Mỗi ticket có blocker/acceptance riêng; frontier ban đầu là #01 và #02. Dùng tracker slices để claim/thực hiện, checklist module để đối chiếu contract/chi tiết/evidence; parent PRD/issues theo module giữ nguyên. Tất cả ticket vẫn not-started, chưa implement hoặc nghiệm thu runtime.
