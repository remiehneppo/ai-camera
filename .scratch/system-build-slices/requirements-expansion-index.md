# Index đối chiếu requirements expansion — T3 ngày 2026-10-20

**Phạm vi publish:** 12 issue cũ cập nhật acceptance/dependency, 16 issue mới #53–68, 7 issue cũ được chủ ý giữ nguyên. Đây là index **phạm vi thay đổi**, không thay PRD cha hoặc tạo nguồn tiến độ thứ hai. Không có implementation/benchmark/field acceptance từ việc publish backlog.

Nguồn chuẩn: [requirement tình huống](../../docs/requirements/urban-safety-scenarios.md), [ứng viên công nghệ](../../docs/requirements/technology-candidates.md), [contracts/Q36](../../docs/architecture/contracts.md), [quyết định T1–T3](../../docs/logs/2026-10-20-requirements-tickets.md), [CONTEXT](../../CONTEXT.md). Cả 13 nhóm gốc + nhánh phá hoại có mapping dưới đây. Giá trị Status/Execution/Owner/checkbox/report **đọc trực tiếp trong từng issue được link**; không sao chép snapshot vào bảng này. `ready-for-agent` là triage của scope specified, không chứng minh blockers/gates đã đạt.

## 12 issue cũ cập nhật, không thay lịch sử

| Nguồn Status/Execution hiện tại | Phạm vi cập nhật |
|---|---|
| [#03 — Doctor và config fail-fast qua đường chạy lab](issues/03-doctor-va-config-fail-fast-qua-duong-chay-lab.md) | Config module × camera và validation local; không ký site config bằng defaults. |
| [#07 — Event pin được clip pre/post từ ring](issues/07-event-pin-duoc-clip-pre-post-tu-ring.md) | Q36 policy theo loại, nhóm mới qua carrier #57, complete ≠ full episode. |
| [#21 — Quality và ODD đi xuyên tới event/detail](issues/21-quality-va-odd-di-xuyen-toi-event-detail.md) | Quality/ODD theo capability; unknown không là negative. |
| [#28 — Negative audit và quality regression G2](issues/28-negative-audit-va-quality-regression-g2.md) | G2 person-down độc lập; report per-capability tái sử dụng, quality targets/held-out không giả pass. |
| [#31 — Capacity target dưới record/upload/pose load](issues/31-capacity-target-duoi-record-upload-pose-load.md) | Capacity gate actual workload, candidate/Orin conditional; không duplicate #56. |
| [#34 — Config local và signed activation giữ LKG](issues/34-config-local-va-signed-activation-giu-lkg.md) | Module × camera desired/observed config; local fail-fast độc lập signed activation. |
| [#44 — UI sản phẩm cho review và annotation](issues/44-ui-san-pham-cho-review-va-annotation.md) | Review nhiều nhãn/priority/evidence; UI không hard phụ thuộc quality report G2. |
| [#46 — Calibration valid đi xuyên tới observations](issues/46-calibration-valid-di-xuyen-toi-observations.md) | Metric calibration chỉ khi geometry cần, không gate mọi nhóm mới. |
| [#47 — Vehicle motion và suspected-incident flow](issues/47-vehicle-motion-va-suspected-incident-flow.md) | Nghi sự cố có xe theo US08, trạng thái tĩnh không suy va chạm. |
| [#48 — Nghiệm thu vehicle riêng G4b](issues/48-nghiem-thu-vehicle-rieng-g4b.md) | G4b vehicle riêng, disabled deferred không coi pass. |
| [#49 — Nghiệm thu person-down pilot readiness G4a](issues/49-nghiem-thu-person-down-pilot-readiness-g4a.md) | G4a person-down không hard chờ toàn catalog/candidate/vehicle. |
| [#50 — Field pilot và final acceptance G5](issues/50-field-pilot-va-final-acceptance-g5.md) | G5 theo capability/site được bật, không suy một nhóm đạt thành toàn danh mục. |

Các dòng Status/Execution/Owner, checkbox đã tích, evidence và Comments cũ giữ nguyên; chỉ thêm acceptance mở/ghi nhận mới trong đúng file được duyệt. Các issue khác không thuộc 12 trên không bị tác vụ này sửa.

## 16 issue mới và approved hard DAG

Mũi tên `ticket → prerequisites` ở đây là **hard implementation dependency**, không release activation. #58–68 đều phụ thuộc carrier có consumer thật #57, nhưng **độc lập nhau**; không nối chain giữa các nhóm hoặc hard dependency model/Orin/calibration/signed config mặc định.

| Nguồn Status/Execution | Hard prerequisites | Ranh giới giao việc |
|---|---|---|
| [#53 — Pose outcomes đi vào person-down flow](issues/53-pose-outcomes-di-vao-person-down-flow.md) | #14, #22, #24 | Integration lab/fixtures; không production gate |
| [#54 — RF-DETR candidate qua detection/event/evidence](issues/54-rf-detr-candidate-qua-detection-event-evidence.md) | #11, #14 | External inputs pending, xem nguồn issue |
| [#55 — ViTPose candidate qua pose/event/evidence](issues/55-vitpose-candidate-qua-pose-event-evidence.md) | #22, #53 | External inputs pending, xem nguồn issue |
| [#56 — Actual Orin NX baseline conformance](issues/56-orin-nx-actual-baseline-conformance.md) | #14, #07, #08 | External inputs pending, xem nguồn issue |
| [#57 — Vùng nguy hiểm: module × camera E2E](issues/57-vung-nguy-hiem-module-camera-e2e.md) | #03, #14, #07, #04, #21 | External inputs pending, xem nguồn issue |
| [#58 — Lửa và khói độc lập đến evidence/review](issues/58-lua-khoi-doc-lap-den-evidence-review.md) | #57 | External inputs pending, xem nguồn issue |
| [#59 — Ngập theo vùng/mốc đến evidence/review](issues/59-ngap-theo-vung-moc-den-evidence-review.md) | #57 | External inputs pending, xem nguồn issue |
| [#60 — Rác: hành vi và tồn lưu đến review](issues/60-rac-hanh-vi-va-ton-luu-den-review.md) | #57 | External inputs pending, xem nguồn issue |
| [#61 — Chiếm dụng vỉa hè theo camera đến review](issues/61-chiem-dung-via-he-theo-camera-den-review.md) | #57 | External inputs pending, xem nguồn issue |
| [#62 — Đỗ xe sai vùng/giờ đến review](issues/62-do-xe-sai-vung-gio-den-review.md) | #57 | Software lab engine + scenario tests pass (partial); field held-out pending |
| [#63 — Đông người và nghi gây rối đến review](issues/63-dong-nguoi-va-nghi-gay-roi-den-review.md) | #57 | Software lab engine + scenario tests pass (partial); field held-out pending |
| [#64 — Ẩu đả theo chuỗi tương tác đến review](issues/64-au-da-theo-chuoi-tuong-tac-den-review.md) | #57 | External inputs pending, xem nguồn issue |
| [#65 — Vật bỏ quên: hai nhãn đến review](issues/65-vat-bo-quen-hai-nhan-den-review.md) | #57 | External inputs pending, xem nguồn issue |
| [#66 — Cây/cành lớn đã đổ đến review](issues/66-cay-canh-lon-da-do-den-review.md) | #57 | External inputs pending, xem nguồn issue |
| [#67 — Đèn không sáng theo lịch đến review](issues/67-den-khong-sang-theo-lich-den-review.md) | #57 | External inputs pending, xem nguồn issue |
| [#68 — Tác động phá hoại tài sản đến review](issues/68-tac-dong-pha-hoai-tai-san-den-review.md) | #57 | External inputs pending, xem nguồn issue |

Conditional: #56 chỉ cần #54 khi chạy RF-DETR, chỉ cần #55 khi chạy ViTPose; baseline target không mặc định chờ hai candidate. #54 và #55 không hard phụ thuộc nhau; #55 dùng consumer follow-up #53. #56 conformance baseline trên actual Orin cung cấp evidence cho #31; **#56 không phụ thuộc #31**, không tạo ticket capacity song song. #31/#49 chỉ lấy #54/#55/#56 khi backend/target thực tế đã chọn, theo conditional blockers trong issue nguồn. #57 không phụ thuộc #49/#48/#34/#46 hoặc #54–56.

## 7 issue giữ nguyên có chủ đích

| Nguồn Status/Execution hiện tại | Lý do không sửa |
|---|---|
| [#04 — Review event có kiểm soát phiên bản](issues/04-review-event-co-kiem-soat-phien-ban.md) | Review baseline/version/history giữ; nguồn Status/Execution thật không phải snapshot PRD. |
| [#14 — Pipeline baseline biến observations thành event](issues/14-pipeline-baseline-bien-observations-thanh-event.md) | Baseline pipeline hiện có là seam được tái dùng, không reopen. |
| [#17 — Health phản ánh khả năng quan sát thực](issues/17-health-phan-anh-kha-nang-quan-sat-thuc.md) | Health hiện có giữ lịch sử; mở quality nằm #21. |
| [#22 — Pose request trả keypoints đúng frame và track](issues/22-pose-request-tra-keypoints-dung-frame-va-track.md) | Pose request done software được giữ; candidate riêng #55. |
| [#24 — Pose scheduling và degradation có coverage](issues/24-pose-scheduling-va-degradation-co-coverage.md) | Scheduler done software được giữ; consumer follow-up riêng #53. |
| [#29 — Build artifact target reproducible](issues/29-build-artifact-target-reproducible.md) | Nhánh build RKNN giữ, không repurpose Orin. |
| [#30 — RKNN thay engine giữ event semantics](issues/30-rknn-thay-engine-giu-event-semantics.md) | Nhánh RKNN semantics giữ, không gate target ONNX/Orin mặc định. |

Bảy issue này không phải đều done/accepted; các trạng thái và caveat thực tế nằm trong file nguồn. #53 không reopen #24; #54/#55 không thay đổi completion lịch sử của oracle/pose; #56 không repurpose #29/#30.

## Coverage requirement → tracer bullets

| Nhóm | Lát cắt / gate liên quan |
|---|---|
| US01 lửa/khói riêng | [#58 — Lửa và khói độc lập đến evidence/review](issues/58-lua-khoi-doc-lap-den-evidence-review.md) |
| US02 ngập theo vùng/mốc | [#59 — Ngập theo vùng/mốc đến evidence/review](issues/59-ngap-theo-vung-moc-den-evidence-review.md) |
| US03 rác: hành vi và tồn lưu | [#60 — Rác: hành vi và tồn lưu đến review](issues/60-rac-hanh-vi-va-ton-luu-den-review.md) |
| US04 chiếm dụng vỉa hè | [#61 — Chiếm dụng vỉa hè theo camera đến review](issues/61-chiem-dung-via-he-theo-camera-den-review.md) |
| US05 đỗ sai vùng/giờ | [#62 — Đỗ xe sai vùng/giờ đến review](issues/62-do-xe-sai-vung-gio-den-review.md) |
| US06 đông người + nghi gây rối | [#63 — Đông người và nghi gây rối đến review](issues/63-dong-nguoi-va-nghi-gay-roi-den-review.md) |
| US07 ẩu đả | [#64 — Ẩu đả theo chuỗi tương tác đến review](issues/64-au-da-theo-chuoi-tuong-tac-den-review.md) |
| US08 tai nạn có xe | [#47 — Vehicle motion và suspected-incident flow](issues/47-vehicle-motion-va-suspected-incident-flow.md), [#48 — Nghiệm thu vehicle riêng G4b](issues/48-nghiem-thu-vehicle-rieng-g4b.md) |
| US09 person-down | [#25 — Person fall có onset quan sát](issues/25-person-fall-co-onset-quan-sat.md), [#26 — Persistent lying khi thiếu onset](issues/26-persistent-lying-khi-thieu-onset.md), [#27 — On-vehicle vẫn review với ưu tiên riêng](issues/27-on-vehicle-van-review-voi-uu-tien-rieng.md), [#53 — Pose outcomes đi vào person-down flow](issues/53-pose-outcomes-di-vao-person-down-flow.md), G2 [#28 — Negative audit và quality regression G2](issues/28-negative-audit-va-quality-regression-g2.md) |
| US10 người vào vùng nguy hiểm/carrier | [#57 — Vùng nguy hiểm: module × camera E2E](issues/57-vung-nguy-hiem-module-camera-e2e.md) |
| US11 vật bỏ quên hai nhãn | [#65 — Vật bỏ quên: hai nhãn đến review](issues/65-vat-bo-quen-hai-nhan-den-review.md) |
| US12 cây/cành lớn đã đổ | [#66 — Cây/cành lớn đã đổ đến review](issues/66-cay-canh-lon-da-do-den-review.md) |
| US13 đèn không sáng theo lịch | [#67 — Đèn không sáng theo lịch đến review](issues/67-den-khong-sang-theo-lich-den-review.md) |
| US14 nghi tác động phá hoại | [#68 — Tác động phá hoại tài sản đến review](issues/68-tac-dong-pha-hoai-tai-san-den-review.md) |
| Candidate detector/pose/hardware | [#54 — RF-DETR candidate qua detection/event/evidence](issues/54-rf-detr-candidate-qua-detection-event-evidence.md), [#55 — ViTPose candidate qua pose/event/evidence](issues/55-vitpose-candidate-qua-pose-event-evidence.md), [#56 — Actual Orin NX baseline conformance](issues/56-orin-nx-actual-baseline-conformance.md); capacity duy nhất [#31 — Capacity target dưới record/upload/pose load](issues/31-capacity-target-duoi-record-upload-pose-load.md) |

## External gates và activation, không biến thành hard chain

- Release theo thứ tự **person-down G2 (#28) → vehicle G4b (#48) → kích hoạt nhóm mở rộng**. Có thể implement/integration lab song song theo hard DAG; lab pass không cho phép bỏ activation gate, không ép #49 chờ toàn bộ catalog hoặc vehicle.
- Mỗi nhóm cần ML cung cấp nguồn capability phù hợp, exact artifacts và quyền dùng code/weights/data; person detector + pose không tự chứng minh lửa/nước/rác/action. Product/operations khóa profile ROI/lịch/ngưỡng/ngoại lệ/priority và ODD/quality/review targets; QA có real held-out positives từng nhánh/hard negatives/unknown và protocol độc lập; privacy/site owner cấp phép dữ liệu. Hiện chưa có đầu vào đầy đủ: issue giữ `needs-info`, ghi rõ người cung cấp/điều kiện chuyển ready.
- Synthetic/mock chỉ integration/fault/clock plumbing, không thay real held-out detection evidence. Số recall/FP/latency/camera/FPS/timer chưa duyệt giữ pending; sign-off do người có trách nhiệm, không bịa số để đóng issue.
- #57 tạo seam được US10 tiêu thụ thật: registry/config local module × camera, linked labels/dedup, source-time alert-condition anchor10/20 có policy version. Không framework rỗng, không engine/process per module mặc định.
- Q36: baseline person-down fall onset/persistence first qualifying observation giữ nguyên; nhóm mới dùng mốc đủ điều kiện cảnh báo. Cả hai 10/20, requested interval/ACK lineage bất biến, complete clip không full episode và metadata duration không thay video.
- Actual Orin SKU/RAM/carrier/OS/JetPack/SDK, artifact clearance và target conformance ở #56; capacity full-system recording/upload/thermal soak chỉ ký tại #31. Engine export chạy được không chứng minh event quality hoặc whole-catalog capability.
- Signed rollout/calibration chỉ conditional khi deployment/geometry cụ thể cần; không chặn default lab local module hoặc áp metric calibration cho count/ROI không cần metric.

## Frontier chọn việc mà không đóng băng tiến độ

1. Đọc Status/Execution và **Blocked by** trong issue nguồn; kiểm dependency đã thật sự đạt đúng scope, không chỉ `done` chung của phần software.
2. Trong nhóm mới, #53 có scope integration lab/fixtures specified; chỉ claim khi #14/#22/#24 evidence đáp ứng consumer contract. Field/quality/capacity vẫn không nằm trong chữ ready này.
3. #54/#55/#56 và #57–68 cần external inputs mô tả tại issue. Công việc đầu tiên có thể là cung cấp/duyệt đầu vào; không chạy triển khai nhận diện với mock rồi đổi status thành pass.
4. Khi #57 đạt seam E2E và từng nhóm có inputs được duyệt, #58–68 có thể chọn độc lập theo hard DAG. Áp release activation riêng, không suy mỗi module đều cần RF/ViT/Orin.
5. Không cập nhật tiến độ ở index này; claim/ghi command/report/blocker vào issue thực thi và source task checklist liên quan.

## Ghi chú lịch sử / PRD cha không sửa

Trạng thái cập nhật đến 2026-10-30: trong nhóm mở rộng, `#53` (pose outcomes), `#57` (`danger_zone`), `#62` (`illegal_parking`) và `#63` (`crowd_incident`) đã hoàn thành logic & integration tests trong software lab (cùng `#47` `vehicle_incident`), sử dụng chung `apps/edge/snapshot.py` (ADR-0005) và bộ đánh giá replay `tools/eval_*.py` (ADR-0006); phần nghiệm thu trên tập video CCTV cố định held-out (`G2/G4b`) và các nhóm `#58–#61, #64–#68` vẫn mở theo đúng điều kiện đầu vào tại từng issue nguồn. Các Status lịch sử ngoài canonical labels ở những issue đợt đầu được giữ nguyên để bảo toàn dấu vết audit.
