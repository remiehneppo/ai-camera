# Tracker triển khai theo tracer-bullet slices

Ngày: 2026-10-11. Breakdown đã được người dùng duyệt bằng “đồng ý”; 50 ticket đã publish local, mọi ticket vẫn not-started.

## Phạm vi và nguồn chuẩn

- [Plan triển khai](../../docs/architecture/implementation-plan.md).
- [Checklist theo module](../../docs/implementation-checklists/README.md).
- [Kiến trúc/SOLID/dependencies](../../docs/implementation-checklists/architecture-analysis.md).
- [Plan và quyết định Q1–Q19](../../docs/architecture/implementation-plan.md).
- [Integration/failure cases và G0–G5](../../docs/implementation-checklists/integration-release.md).

Ticket trong tracker này là đơn vị claim/thực hiện và nguồn duy nhất cho Status/Execution/blockers. Checklist module giữ acceptance chi tiết và traceability; không claim/đóng parent như một đơn vị thực thi khác. Cập nhật contract/acceptance module khi thiết kế thay đổi. Không nhân đôi tiến độ: cập nhật ticket và gắn evidence cho task nguồn tương ứng khi thật sự đạt.

## Cách chọn việc

Frontier ban đầu: **#01 và #02**, không có ticket blockers và ready-for-agent. Chưa có ticket nào done. Những ticket khác chỉ mở thực hiện khi Blocked by đã done, Conditional blockers của target áp dụng đã done và external/activation gates được đáp ứng.

Status là triage role; Execution theo not-started/in-progress/blocked/done. ready-for-agent không có nghĩa dependencies đã xong. needs-info chỉ dùng facts/provider/target còn thiếu (#15/#29/#42); ready-for-human cho power-cut/survey/field/sign-off (#37/#46/#48/#49/#50). Ghi rõ lý do trong ticket; sau khi có dữ liệu cập nhật triage, không bỏ gate.

RKNN #29/#30 chỉ khi chọn RK3588; #31/#35 cần thêm #30 khi target RKNN, target ONNX vẫn phải conformance/capacity thật. Notification #42 và vehicle #46–#48 có điều kiện. Person-down #49/#50 chỉ cần #42 hoặc #48 khi nhánh tương ứng được bật; lab dashboard-only không tự phát notification. G4a trước field pilot, G5 sau khi thu đủ dữ liệu field và ký final acceptance.

Không có lệnh implementation/hardware nào được chạy trong lần publish này. Người/phạm vi từng file cần claim trước sửa source, không tạo SDK/framework/folder rỗng ngoài lát cắt.

## Danh sách ticket

| Ticket | Status | Blocked by | Conditional blockers | Execution |
|---|---|---|---|---|
| [01: Event synthetic xuất hiện trên dashboard](issues/01-event-synthetic-xuat-hien-tren-dashboard.md) | ready-for-agent | None | — | done |
| [02: Hồ sơ lab, ODD và protocol nghiệm thu](issues/02-ho-so-lab-odd-va-protocol-nghiem-thu.md) | ready-for-agent | None | — | not-started |
| [03: Doctor và config fail-fast qua đường chạy lab](issues/03-doctor-va-config-fail-fast-qua-duong-chay-lab.md) | ready-for-agent | #01 | — | not-started |
| [04: Review event có kiểm soát phiên bản](issues/04-review-event-co-kiem-soat-phien-ban.md) | ready-for-agent | #01 | — | not-started |
| [05: Retry và revision không làm mất hoặc lùi event](issues/05-retry-va-revision-khong-lam-mat-hoac-lui-event.md) | ready-for-agent | #01 | — | not-started |
| [06: Recorder file replay giữ raw ring độc lập](issues/06-recorder-file-replay-giu-raw-ring-doc-lap.md) | ready-for-agent | #02 | — | not-started |
| [07: Event pin được clip pre/post từ ring](issues/07-event-pin-duoc-clip-pre-post-tu-ring.md) | ready-for-agent | #01, #06 | — | not-started |
| [08: Upload evidence và phát lại trên detail](issues/08-upload-evidence-va-phat-lai-tren-detail.md) | ready-for-agent | #07 | — | not-started |
| [09: Khôi phục event/evidence sau process crash](issues/09-khoi-phuc-event-evidence-sau-process-crash.md) | ready-for-agent | #05, #08 | — | not-started |
| [10: File replay đi qua native boundary an toàn](issues/10-file-replay-di-qua-native-boundary-an-toan.md) | ready-for-agent | #03, #06 | — | not-started |
| [11: ONNX oracle xuất detection có provenance](issues/11-onnx-oracle-xuat-detection-co-provenance.md) | ready-for-agent | #02 | — | not-started |
| [12: Native detector đạt parity với oracle](issues/12-native-detector-dat-parity-voi-oracle.md) | ready-for-agent | #10, #11 | — | not-started |
| [13: Native tracks có time và session semantics](issues/13-native-tracks-co-time-va-session-semantics.md) | ready-for-agent | #12 | — | not-started |
| [14: Pipeline baseline biến observations thành event](issues/14-pipeline-baseline-bien-observations-thanh-event.md) | ready-for-agent | #05, #07, #13 | — | not-started |
| [15: Camera RTSP live giữ correlation với recorder](issues/15-camera-rtsp-live-giu-correlation-voi-recorder.md) | needs-info | #02, #14 | — | not-started |
| [16: Startup/shutdown giữ recorder và state đúng](issues/16-startup-shutdown-giu-recorder-va-state-dung.md) | ready-for-agent | #09, #14 | — | not-started |
| [17: Health phản ánh khả năng quan sát thực](issues/17-health-phan-anh-kha-nang-quan-sat-thuc.md) | ready-for-agent | #14 | — | not-started |
| [18: Quota bảo vệ pinned evidence và journal](issues/18-quota-bao-ve-pinned-evidence-va-journal.md) | ready-for-agent | #09, #17 | — | not-started |
| [19: Nghiệm thu vertical slice G1 trên lab](issues/19-nghiem-thu-vertical-slice-g1-tren-lab.md) | ready-for-agent | #04, #08, #15, #16, #17, #18 | — | not-started |
| [20: Feedback review thành nhãn dataset có lineage](issues/20-feedback-review-thanh-nhan-dataset-co-lineage.md) | ready-for-agent | #02, #04, #08 | — | not-started |
| [21: Quality và ODD đi xuyên tới event/detail](issues/21-quality-va-odd-di-xuyen-toi-event-detail.md) | ready-for-agent | #17 | — | not-started |
| [22: Pose request trả keypoints đúng frame và track](issues/22-pose-request-tra-keypoints-dung-frame-va-track.md) | ready-for-agent | #11, #13 | — | not-started |
| [23: Track gap không tạo certainty hoặc motion giả](issues/23-track-gap-khong-tao-certainty-hoac-motion-gia.md) | ready-for-agent | #13, #02 | — | not-started |
| [24: Pose scheduling và degradation có coverage](issues/24-pose-scheduling-va-degradation-co-coverage.md) | ready-for-agent | #21, #22, #23 | — | not-started |
| [25: Person fall có onset quan sát](issues/25-person-fall-co-onset-quan-sat.md) | ready-for-agent | #14, #24 | — | not-started |
| [26: Persistent lying khi thiếu onset](issues/26-persistent-lying-khi-thieu-onset.md) | ready-for-agent | #25 | — | not-started |
| [27: On-vehicle vẫn review với ưu tiên riêng](issues/27-on-vehicle-van-review-voi-uu-tien-rieng.md) | ready-for-agent | #26 | — | not-started |
| [28: Negative audit và quality regression G2](issues/28-negative-audit-va-quality-regression-g2.md) | ready-for-agent | #20, #27 | — | not-started |
| [29: Build artifact target reproducible](issues/29-build-artifact-target-reproducible.md) | needs-info | #02, #11 | — | not-started |
| [30: RKNN thay engine giữ event semantics](issues/30-rknn-thay-engine-giu-event-semantics.md) | ready-for-agent | #28, #29 | — | not-started |
| [31: Capacity target dưới record/upload/pose load](issues/31-capacity-target-duoi-record-upload-pose-load.md) | ready-for-agent | #28, #18 | #30 nếu RKNN | not-started |
| [32: Retained evidence truy hồi có authorization](issues/32-retained-evidence-truy-hoi-co-authorization.md) | ready-for-agent | #08, #18 | — | not-started |
| [33: Device lifecycle và site access được enforce](issues/33-device-lifecycle-va-site-access-duoc-enforce.md) | ready-for-agent | #05, #08, #17 | — | not-started |
| [34: Config local và signed activation giữ LKG](issues/34-config-local-va-signed-activation-giu-lkg.md) | ready-for-agent | #03, #16, #33 | — | not-started |
| [35: Canary và rollback có authorization mới](issues/35-canary-va-rollback-co-authorization-moi.md) | ready-for-agent | #34, #28 | #30 nếu RKNN | not-started |
| [36: WAN outage giữ event/evidence rồi resume](issues/36-wan-outage-giu-event-evidence-roi-resume.md) | ready-for-agent | #18, #32 | — | not-started |
| [37: Power-cut kiểm chứng local durability](issues/37-power-cut-kiem-chung-local-durability.md) | ready-for-human | #09, #18, #02 | — | not-started |
| [38: Native crash recovery đạt RTO](issues/38-native-crash-recovery-dat-rto.md) | ready-for-agent | #16, #17, #31 | — | not-started |
| [39: Provisioning và watchdog tái tạo được](issues/39-provisioning-va-watchdog-tai-tao-duoc.md) | ready-for-agent | #35, #38 | — | not-started |
| [40: Synthetic probe báo operational fault riêng](issues/40-synthetic-probe-bao-operational-fault-rieng.md) | ready-for-agent | #17, #05 | — | not-started |
| [41: Malformed storm không ăn hết state reserve](issues/41-malformed-storm-khong-an-het-state-reserve.md) | ready-for-agent | #18, #05 | — | not-started |
| [42: Downstream delivery theo protocol được bật](issues/42-downstream-delivery-theo-protocol-duoc-bat.md) | needs-info | #27, #05, #33 | — | not-started |
| [43: Central retention và backup/restore có proof](issues/43-central-retention-va-backup-restore-co-proof.md) | ready-for-agent | #08, #33 | — | not-started |
| [44: UI sản phẩm cho review và annotation](issues/44-ui-san-pham-cho-review-va-annotation.md) | ready-for-agent | #20, #27, #28 | — | not-started |
| [45: UI fleet, retrieval và audit](issues/45-ui-fleet-retrieval-va-audit.md) | ready-for-agent | #32, #33, #34 | — | not-started |
| [46: Calibration valid đi xuyên tới observations](issues/46-calibration-valid-di-xuyen-toi-observations.md) | ready-for-human | #28 | — | not-started |
| [47: Vehicle motion và suspected-incident flow](issues/47-vehicle-motion-va-suspected-incident-flow.md) | ready-for-agent | #46 | — | not-started |
| [48: Nghiệm thu vehicle riêng G4b](issues/48-nghiem-thu-vehicle-rieng-g4b.md) | ready-for-human | #47 | — | not-started |
| [49: Nghiệm thu person-down pilot readiness G4a](issues/49-nghiem-thu-person-down-pilot-readiness-g4a.md) | ready-for-human | #19, #28, #31, #36, #37, #39, #40, #41, #43, #44, #45 | — | not-started |
| [50: Field pilot và final acceptance G5](issues/50-field-pilot-va-final-acceptance-g5.md) | ready-for-human | #49 | — | not-started |

## Mapping 89 task nguồn → tickets

Một task có thể được hoàn thiện dần qua nhiều ticket; task mapping không bổ sung edge chặn ngầm.

| Task nguồn | Ticket slices |
|---|---|
| A01 | [#29](issues/29-build-artifact-target-reproducible.md) |
| A02 | [#30](issues/30-rknn-thay-engine-giu-event-semantics.md) |
| A03 | [#30](issues/30-rknn-thay-engine-giu-event-semantics.md) |
| A04 | [#31](issues/31-capacity-target-duoi-record-upload-pose-load.md) |
| A05 | [#31](issues/31-capacity-target-duoi-record-upload-pose-load.md) |
| B01 | [#01](issues/01-event-synthetic-xuat-hien-tren-dashboard.md), [#03](issues/03-doctor-va-config-fail-fast-qua-duong-chay-lab.md) |
| B02 | [#03](issues/03-doctor-va-config-fail-fast-qua-duong-chay-lab.md) |
| B03 | [#16](issues/16-startup-shutdown-giu-recorder-va-state-dung.md) |
| B04 | [#34](issues/34-config-local-va-signed-activation-giu-lkg.md), [#35](issues/35-canary-va-rollback-co-authorization-moi.md) |
| C01 | [#01](issues/01-event-synthetic-xuat-hien-tren-dashboard.md), [#06](issues/06-recorder-file-replay-giu-raw-ring-doc-lap.md) |
| C02 | [#10](issues/10-file-replay-di-qua-native-boundary-an-toan.md), [#13](issues/13-native-tracks-co-time-va-session-semantics.md) |
| C03 | [#01](issues/01-event-synthetic-xuat-hien-tren-dashboard.md), [#05](issues/05-retry-va-revision-khong-lam-mat-hoac-lui-event.md), [#06](issues/06-recorder-file-replay-giu-raw-ring-doc-lap.md), [#07](issues/07-event-pin-duoc-clip-pre-post-tu-ring.md), [#14](issues/14-pipeline-baseline-bien-observations-thanh-event.md) |
| C04 | [#10](issues/10-file-replay-di-qua-native-boundary-an-toan.md) |
| C05 | [#11](issues/11-onnx-oracle-xuat-detection-co-provenance.md), [#12](issues/12-native-detector-dat-parity-voi-oracle.md), [#19](issues/19-nghiem-thu-vertical-slice-g1-tren-lab.md), [#22](issues/22-pose-request-tra-keypoints-dung-frame-va-track.md), [#30](issues/30-rknn-thay-engine-giu-event-semantics.md) |
| D01 | [#02](issues/02-ho-so-lab-odd-va-protocol-nghiem-thu.md), [#20](issues/20-feedback-review-thanh-nhan-dataset-co-lineage.md), [#23](issues/23-track-gap-khong-tao-certainty-hoac-motion-gia.md) |
| D02 | [#20](issues/20-feedback-review-thanh-nhan-dataset-co-lineage.md), [#44](issues/44-ui-san-pham-cho-review-va-annotation.md) |
| D03 | [#28](issues/28-negative-audit-va-quality-regression-g2.md) |
| D04 | [#28](issues/28-negative-audit-va-quality-regression-g2.md), [#48](issues/48-nghiem-thu-vehicle-rieng-g4b.md), [#50](issues/50-field-pilot-va-final-acceptance-g5.md) |
| D05 | [#28](issues/28-negative-audit-va-quality-regression-g2.md), [#50](issues/50-field-pilot-va-final-acceptance-g5.md) |
| E01 | [#08](issues/08-upload-evidence-va-phat-lai-tren-detail.md) |
| E02 | [#08](issues/08-upload-evidence-va-phat-lai-tren-detail.md), [#09](issues/09-khoi-phuc-event-evidence-sau-process-crash.md), [#43](issues/43-central-retention-va-backup-restore-co-proof.md) |
| E03 | [#43](issues/43-central-retention-va-backup-restore-co-proof.md) |
| F01 | [#02](issues/02-ho-so-lab-odd-va-protocol-nghiem-thu.md) |
| F02 | [#02](issues/02-ho-so-lab-odd-va-protocol-nghiem-thu.md) |
| F03 | [#02](issues/02-ho-so-lab-odd-va-protocol-nghiem-thu.md), [#18](issues/18-quota-bao-ve-pinned-evidence-va-journal.md), [#49](issues/49-nghiem-thu-person-down-pilot-readiness-g4a.md), [#50](issues/50-field-pilot-va-final-acceptance-g5.md) |
| F04 | [#02](issues/02-ho-so-lab-odd-va-protocol-nghiem-thu.md), [#15](issues/15-camera-rtsp-live-giu-correlation-voi-recorder.md) |
| F05 | [#02](issues/02-ho-so-lab-odd-va-protocol-nghiem-thu.md), [#03](issues/03-doctor-va-config-fail-fast-qua-duong-chay-lab.md), [#11](issues/11-onnx-oracle-xuat-detection-co-provenance.md), [#29](issues/29-build-artifact-target-reproducible.md), [#33](issues/33-device-lifecycle-va-site-access-duoc-enforce.md) |
| F06 | [#02](issues/02-ho-so-lab-odd-va-protocol-nghiem-thu.md), [#19](issues/19-nghiem-thu-vertical-slice-g1-tren-lab.md), [#49](issues/49-nghiem-thu-person-down-pilot-readiness-g4a.md) |
| G01 | [#46](issues/46-calibration-valid-di-xuyen-toi-observations.md) |
| G02 | [#46](issues/46-calibration-valid-di-xuyen-toi-observations.md) |
| H01 | [#17](issues/17-health-phan-anh-kha-nang-quan-sat-thuc.md), [#41](issues/41-malformed-storm-khong-an-het-state-reserve.md) |
| H02 | [#40](issues/40-synthetic-probe-bao-operational-fault-rieng.md), [#45](issues/45-ui-fleet-retrieval-va-audit.md) |
| I01 | [#07](issues/07-event-pin-duoc-clip-pre-post-tu-ring.md), [#14](issues/14-pipeline-baseline-bien-observations-thanh-event.md) |
| I02 | [#25](issues/25-person-fall-co-onset-quan-sat.md), [#26](issues/26-persistent-lying-khi-thieu-onset.md) |
| I03 | [#27](issues/27-on-vehicle-van-review-voi-uu-tien-rieng.md) |
| I04 | [#27](issues/27-on-vehicle-van-review-voi-uu-tien-rieng.md), [#42](issues/42-downstream-delivery-theo-protocol-duoc-bat.md), [#44](issues/44-ui-san-pham-cho-review-va-annotation.md) |
| I05 | [#25](issues/25-person-fall-co-onset-quan-sat.md), [#26](issues/26-persistent-lying-khi-thieu-onset.md), [#28](issues/28-negative-audit-va-quality-regression-g2.md) |
| I06 | [#47](issues/47-vehicle-motion-va-suspected-incident-flow.md) |
| J01 | [#01](issues/01-event-synthetic-xuat-hien-tren-dashboard.md), [#18](issues/18-quota-bao-ve-pinned-evidence-va-journal.md), [#37](issues/37-power-cut-kiem-chung-local-durability.md) |
| J02 | [#05](issues/05-retry-va-revision-khong-lam-mat-hoac-lui-event.md) |
| J03 | [#08](issues/08-upload-evidence-va-phat-lai-tren-detail.md), [#36](issues/36-wan-outage-giu-event-evidence-roi-resume.md) |
| J04 | [#09](issues/09-khoi-phuc-event-evidence-sau-process-crash.md), [#41](issues/41-malformed-storm-khong-an-het-state-reserve.md) |
| J05 | [#36](issues/36-wan-outage-giu-event-evidence-roi-resume.md), [#37](issues/37-power-cut-kiem-chung-local-durability.md) |
| K01 | [#13](issues/13-native-tracks-co-time-va-session-semantics.md) |
| K02 | [#13](issues/13-native-tracks-co-time-va-session-semantics.md) |
| K03 | [#23](issues/23-track-gap-khong-tao-certainty-hoac-motion-gia.md) |
| M01 | [#47](issues/47-vehicle-motion-va-suspected-incident-flow.md) |
| M02 | [#47](issues/47-vehicle-motion-va-suspected-incident-flow.md) |
| M03 | [#48](issues/48-nghiem-thu-vehicle-rieng-g4b.md) |
| N01 | [#10](issues/10-file-replay-di-qua-native-boundary-an-toan.md), [#16](issues/16-startup-shutdown-giu-recorder-va-state-dung.md) |
| N02 | [#11](issues/11-onnx-oracle-xuat-detection-co-provenance.md) |
| N03 | [#12](issues/12-native-detector-dat-parity-voi-oracle.md) |
| N04 | [#12](issues/12-native-detector-dat-parity-voi-oracle.md) |
| N05 | [#13](issues/13-native-tracks-co-time-va-session-semantics.md) |
| O01 | [#14](issues/14-pipeline-baseline-bien-observations-thanh-event.md) |
| O02 | [#14](issues/14-pipeline-baseline-bien-observations-thanh-event.md), [#24](issues/24-pose-scheduling-va-degradation-co-coverage.md), [#38](issues/38-native-crash-recovery-dat-rto.md) |
| O03 | [#24](issues/24-pose-scheduling-va-degradation-co-coverage.md) |
| O04 | [#31](issues/31-capacity-target-duoi-record-upload-pose-load.md) |
| P01 | [#22](issues/22-pose-request-tra-keypoints-dung-frame-va-track.md) |
| P02 | [#24](issues/24-pose-scheduling-va-degradation-co-coverage.md) |
| P03 | [#22](issues/22-pose-request-tra-keypoints-dung-frame-va-track.md) |
| P04 | [#24](issues/24-pose-scheduling-va-degradation-co-coverage.md), [#31](issues/31-capacity-target-duoi-record-upload-pose-load.md) |
| QL01 | [#21](issues/21-quality-va-odd-di-xuyen-toi-event-detail.md) |
| QL02 | [#21](issues/21-quality-va-odd-di-xuyen-toi-event-detail.md) |
| QL03 | [#21](issues/21-quality-va-odd-di-xuyen-toi-event-detail.md), [#46](issues/46-calibration-valid-di-xuyen-toi-observations.md) |
| R01 | [#06](issues/06-recorder-file-replay-giu-raw-ring-doc-lap.md), [#15](issues/15-camera-rtsp-live-giu-correlation-voi-recorder.md) |
| R02 | [#07](issues/07-event-pin-duoc-clip-pre-post-tu-ring.md) |
| R03 | [#07](issues/07-event-pin-duoc-clip-pre-post-tu-ring.md), [#09](issues/09-khoi-phuc-event-evidence-sau-process-crash.md), [#37](issues/37-power-cut-kiem-chung-local-durability.md) |
| R04 | [#18](issues/18-quota-bao-ve-pinned-evidence-va-journal.md), [#28](issues/28-negative-audit-va-quality-regression-g2.md) |
| R05 | [#18](issues/18-quota-bao-ve-pinned-evidence-va-journal.md), [#32](issues/32-retained-evidence-truy-hoi-co-authorization.md), [#36](issues/36-wan-outage-giu-event-evidence-roi-resume.md) |
| R06 | [#16](issues/16-startup-shutdown-giu-recorder-va-state-dung.md), [#19](issues/19-nghiem-thu-vertical-slice-g1-tren-lab.md), [#38](issues/38-native-crash-recovery-dat-rto.md) |
| S01 | [#01](issues/01-event-synthetic-xuat-hien-tren-dashboard.md), [#05](issues/05-retry-va-revision-khong-lam-mat-hoac-lui-event.md) |
| S02 | [#04](issues/04-review-event-co-kiem-soat-phien-ban.md), [#05](issues/05-retry-va-revision-khong-lam-mat-hoac-lui-event.md) |
| T01 | [#33](issues/33-device-lifecycle-va-site-access-duoc-enforce.md), [#49](issues/49-nghiem-thu-person-down-pilot-readiness-g4a.md) |
| T02 | [#34](issues/34-config-local-va-signed-activation-giu-lkg.md) |
| T03 | [#32](issues/32-retained-evidence-truy-hoi-co-authorization.md), [#45](issues/45-ui-fleet-retrieval-va-audit.md) |
| T04 | [#35](issues/35-canary-va-rollback-co-authorization-moi.md) |
| T05 | [#39](issues/39-provisioning-va-watchdog-tai-tao-duoc.md) |
| T06 | [#38](issues/38-native-crash-recovery-dat-rto.md) |
| UI01 | [#01](issues/01-event-synthetic-xuat-hien-tren-dashboard.md), [#08](issues/08-upload-evidence-va-phat-lai-tren-detail.md), [#17](issues/17-health-phan-anh-kha-nang-quan-sat-thuc.md), [#19](issues/19-nghiem-thu-vertical-slice-g1-tren-lab.md) |
| UI02 | [#04](issues/04-review-event-co-kiem-soat-phien-ban.md), [#08](issues/08-upload-evidence-va-phat-lai-tren-detail.md) |
| UI03 | [#20](issues/20-feedback-review-thanh-nhan-dataset-co-lineage.md), [#27](issues/27-on-vehicle-van-review-voi-uu-tien-rieng.md), [#44](issues/44-ui-san-pham-cho-review-va-annotation.md) |
| UI04 | [#32](issues/32-retained-evidence-truy-hoi-co-authorization.md), [#45](issues/45-ui-fleet-retrieval-va-audit.md) |
| V01 | [#06](issues/06-recorder-file-replay-giu-raw-ring-doc-lap.md), [#11](issues/11-onnx-oracle-xuat-detection-co-provenance.md) |
| V02 | [#15](issues/15-camera-rtsp-live-giu-correlation-voi-recorder.md) |
| V03 | [#10](issues/10-file-replay-di-qua-native-boundary-an-toan.md), [#15](issues/15-camera-rtsp-live-giu-correlation-voi-recorder.md) |
| V04 | [#15](issues/15-camera-rtsp-live-giu-correlation-voi-recorder.md) |
| W01 | [#04](issues/04-review-event-co-kiem-soat-phien-ban.md) |
| W02 | [#05](issues/05-retry-va-revision-khong-lam-mat-hoac-lui-event.md), [#40](issues/40-synthetic-probe-bao-operational-fault-rieng.md), [#42](issues/42-downstream-delivery-theo-protocol-duoc-bat.md) |

## Comments

- 2026-10-11: Publish 50 tickets theo breakdown đã duyệt, kiểm blockers-first DAG và coverage 89 task. Không claim/implement/đóng parent issues hoặc commit/push.
