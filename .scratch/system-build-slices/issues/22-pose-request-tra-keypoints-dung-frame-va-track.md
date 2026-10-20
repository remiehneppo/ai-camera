# 22: Pose request trả keypoints đúng frame và track

Status: ready-for-review
Execution: done (software lab; chưa có accuracy/capacity target)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Gửi ROI request có deadline tới native ORT pose và nhận pose/status trong observation metadata.

**Blocked by:** [#11: ONNX oracle xuất detection có provenance](11-onnx-oracle-xuat-detection-co-provenance.md); [#13: Native tracks có time và session semantics](13-native-tracks-co-time-va-session-semantics.md).

## Acceptance criteria

- [x] Oracle/native RTMPose crop/affine/SimCC/schema parity; original coordinate/missing keypoints rõ.
- [x] Bounded buffer cache; expired/skipped/stale/ID switch không gắn pose nhầm frame; request fixture dùng trước automatic scheduling.
- [x] Mỗi accepted pose request có terminal outcome; detection-ok/pose-skipped cùng biểu diễn; crash epoch fail outstanding requests, terminal queue không drop im lặng.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: P01, P03, C05.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-14: Hoàn thành triển khai RTMPose Estimator và Pose Request Lifecycle theo hợp đồng:
  - `apps/edge/pose.py`: `RtmposeEstimator` (crop affine 192x256, SimCC split_ratio=2.0, 17 COCO keypoints original coordinate mapping), `PoseManager` (deadline timeout -> skipped, epoch reset -> cancelled, bounded request queue -> skipped, bounded frame buffer cache -> skipped, single terminal outcome per request).
  - `apps/edge/pipeline.py`: Tích hợp `pose_manager`, `request_pose()`, `set_core_epoch()`, và per-frame caching.
  - `tests/test_pose.py`: 12 tests bao phủ dummy/real Shibuya fixtures, deadline timeout, epoch mismatch cancellation, bounded queue/cache, status separation (detection ok vs pose skipped/failed). Tất cả unit tests và regression tests (`test_tracking_incident`, `test_live_pipeline`) đều passed; mypy type check đạt 0 lỗi.
- 2026-10-17: Đồng bộ tracker (docs/logs/2026-10-17-tracker-sync.md). Code tồn tại (grep apps/), pytest nhóm liên quan 188 passed. Execution = done (software lab; chưa có accuracy/capacity target). Status triage và gate giữ nguyên; chưa review/ký.
