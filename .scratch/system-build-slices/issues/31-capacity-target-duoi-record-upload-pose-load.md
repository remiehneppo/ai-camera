# 31: Capacity target dưới record/upload/pose load

Status: ready-for-agent
Execution: partial (exploratory harness implemented; no measured workload, no capacity sign-off)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Profile rồi soak workload thực trên BOM để ký camera/FPS/pose envelope và headroom.

**Blocked by:** [#28: Negative audit và quality regression G2](28-negative-audit-va-quality-regression-g2.md); [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md).

**Conditional blockers (RKNN):** [#30: RKNN thay engine giữ event semantics](30-rknn-thay-engine-giu-event-semantics.md).

Target ONNX dùng C05/N05/P03/I05 và actual-target conformance; target chưa chọn hoặc thiếu report thì acceptance chưa đạt.

**Conditional blockers (deployment đã chọn):** [#56: Orin NX actual baseline conformance](56-orin-nx-actual-baseline-conformance.md) khi deploy Orin NX; [#54: RF-DETR candidate](54-rf-detr-candidate-qua-detection-event-evidence.md) khi deploy RF-DETR; [#55: ViTPose candidate](55-vitpose-candidate-qua-pose-event-evidence.md) khi deploy ViTPose. Không áp dụng cho ứng viên chưa chọn/disabled.

## Acceptance criteria

- [ ] 24–72h có per-camera P95/P99/gaps/fsync/WAL/outbox/thermal/power/copies và actual workload manifest.
- [ ] Tối ưu bottleneck đo được, shared runtime serialization/fairness; không ký camera capacity từ detector FPS riêng.

- [ ] Trên target ONNX: native/oracle detector/pose/tracker/event conformance và actual decode/buffer tests trước soak; target khác baseline phải rerun. RKNN thêm #30, không bỏ G3 khi deferred RKNN.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Delta requirement được duyệt — 2026-10-20

- [ ] Capacity sign-off khóa actual SKU/RAM/OS/SDK, camera profiles, danh sách module enabled và exact model/config versions trong workload manifest; đo toàn pipeline decode/perception/tracking/temporal rules/ring/clip/upload đồng thời, queue/drop/gaps và headroom, không chỉ inference FPS.
- [ ] Exploratory profiling/measurement được chạy trước signed G2 với workload và missing gates ghi rõ; chỉ capacity acceptance mới cần approved quality/ODD/workload và named owner ký. Số đo exploratory không được ghi thành accepted capacity hoặc production clearance.
- [ ] Conditional target/model gates chỉ áp dụng thành phần thực sự được deploy: Orin NX cần [#56: Orin NX actual baseline conformance](56-orin-nx-actual-baseline-conformance.md); RF-DETR cần [#54: RF-DETR candidate qua detection/event/evidence](54-rf-detr-candidate-qua-detection-event-evidence.md); ViTPose cần [#55: ViTPose candidate qua pose/event/evidence](55-vitpose-candidate-qua-pose-event-evidence.md). Baseline không dùng các ứng viên không bị chặn bởi chúng; RKNN vẫn giữ #30.

## Traceability

Task nguồn: A04, A05, O04, P04.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.

- 2026-10-27: Lát cắt **exploratory capacity harness** theo delta "exploratory profiling trước signed G2". Thêm `apps/edge/capacity_lab.py` (percentiles có p99, gap_totals, upload drainer trên thread riêng, `run_lab` đo per-camera latency/dropped/queue.max_pending_events/coverage/pose) và dùng chung percentile trong `tools/run_benchmark.py`.
  Mọi report mang `accepted_capacity=False`, `disclaimer` và `missing_gates` để không số nào bị đọc thành accepted capacity.
  Mỗi trục chỉ báo cáo khi có nguồn thật (fsync đếm bằng wrapper, WAL qua `PRAGMA journal_mode`, headroom qua `get_storage_breakdown`, coverage qua `actual_range`); trục không đo được ghi `unmeasured` + reason thay vì 0, và `queue.drops` để `None` vì EventOutbox không có counter.
  `pytest tests/test_capacity_lab.py` ⇒ 12 passed; full suite ⇒ **843 passed, 126 subtests**; mypy 2 files sạch.
  **Chưa đóng acceptance**: chưa chạy profile với workload manifest, chưa có số đo, chưa soak 24–72h, chưa có target SKU/thermal/power/WAL endurance, chưa multi-camera fairness. Không ký capacity. Chi tiết: [log](../../../docs/logs/2026-10-27-ticket-31-exploratory-capacity-harness.md).
