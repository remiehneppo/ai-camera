# 03: Doctor và config fail-fast qua đường chạy lab

Status: ready-for-agent
Execution: blocked
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Người triển khai kiểm config/artifact rồi start analytics; enabled config sai dừng rõ, disabled có reason và không lộ secrets.

**Blocked by:** [#01: Event synthetic xuất hiện trên dashboard](01-event-synthetic-xuat-hien-tren-dashboard.md), [#06: Recorder file replay giữ raw ring độc lập](06-recorder-file-replay-giu-raw-ring-doc-lap.md), [#11: ONNX oracle xuất detection có provenance](11-onnx-oracle-xuat-detection-co-provenance.md).

## Acceptance criteria

- [ ] Allowlisted factories và immutable config hash/provenance; wrong artifact/backend/field làm startup nonzero.
- [ ] Doctor báo capability thực; không silent fallback, recorder độc lập không bị stop vì analytics config sai.

## Traceability

Task nguồn: B01, B02, F05.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
- 2026-10-12: Bắt đầu implementation cho server lab: dùng chung validator fail-fast trong startup, snapshot config frozen với SHA-256 fingerprint không chứa secret values, thêm `python -m apps.server.doctor` để ping Mongo và báo analytics/recorder capabilities hiện có. Còn thiếu analytics pipeline/factory/model manifest + verification và recorder lifecycle độc lập; không đánh dấu acceptance các phần này. Xem [implementation log](../../../docs/logs/2026-10-12-ticket-03.md).

- 2026-10-12: Tiếp tục rà soát #03; test suite hiện có 15/15 pass và server config modules compile. Chưa thể hoàn thiện các tiêu chí còn mở: chưa có analytics runtime/factory hoặc artifact manifest/backend target (model/license selection còn pending), và chưa có recorder lifecycle để chứng minh analytics config lỗi không dừng recording. Giữ phần server config/doctor đã implement; Execution chuyển blocked đến khi các runtime/target facts tương ứng có mặt. Không tạo factory/artifact/recorder giả.

- 2026-10-12: Người dùng chốt baseline analytics ONNX CPU/x86 và recorder file replay; yêu cầu giữ khả năng đổi backend sang RKNN và source sang RTSP. Giữ `PerceptionPipeline`/event semantics ổn định; ONNX/RKNN dùng artifact/manifest riêng và RTSP chỉ thay source adapter/config, không đổi event schema. RKNN/RTSP vẫn là capability chưa nghiệm thu. #03 phụ thuộc #06 (recorder runtime) và #11 (ONNX model artifact/provenance), nên phần runtime gates giữ blocked trong khi làm ticket độc lập kế tiếp.
