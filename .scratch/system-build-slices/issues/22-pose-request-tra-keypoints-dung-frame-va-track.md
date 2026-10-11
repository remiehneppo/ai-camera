# 22: Pose request trả keypoints đúng frame và track

Status: ready-for-agent
Execution: not-started
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Gửi ROI request có deadline tới native ORT pose và nhận pose/status trong observation metadata.

**Blocked by:** [#11: ONNX oracle xuất detection có provenance](11-onnx-oracle-xuat-detection-co-provenance.md); [#13: Native tracks có time và session semantics](13-native-tracks-co-time-va-session-semantics.md).

## Acceptance criteria

- [ ] Oracle/native RTMPose crop/affine/SimCC/schema parity; original coordinate/missing keypoints rõ.
- [ ] Bounded buffer cache; expired/skipped/stale/ID switch không gắn pose nhầm frame; request fixture dùng trước automatic scheduling.

## Traceability

Task nguồn: P01, P03, C05.

Task IDs là mapping phạm vi baseline/integration/hardening; chỉ Blocked by mới là dependency ticket. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
