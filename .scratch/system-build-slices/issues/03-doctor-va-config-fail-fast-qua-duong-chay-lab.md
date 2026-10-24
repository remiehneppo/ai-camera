# 03: Doctor và config fail-fast qua đường chạy lab

Status: ready-for-agent
Execution: partial (delta slice module x camera da implement; full PerceptionPipeline/factory + RKNN/RTSP con mo)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Người triển khai kiểm config/artifact rồi start analytics; enabled config sai dừng rõ, disabled có reason và không lộ secrets.

**Blocked by:** [#01: Event synthetic xuất hiện trên dashboard](01-event-synthetic-xuat-hien-tren-dashboard.md), [#06: Recorder file replay giữ raw ring độc lập](06-recorder-file-replay-giu-raw-ring-doc-lap.md), [#11: ONNX oracle xuất detection có provenance](11-onnx-oracle-xuat-detection-co-provenance.md).

## Acceptance criteria

- [ ] Allowlisted factories và immutable config hash/provenance; wrong artifact/backend/field làm startup nonzero.
- [ ] Doctor báo capability thực; không silent fallback, recorder độc lập không bị stop vì analytics config sai.

## Delta requirement được duyệt — 2026-10-20

- [ ] Cấu hình độc lập module × camera gồm enabled/disabled, ROI, lịch, ngưỡng và ngoại lệ; cấu hình enabled thiếu/sai trường bắt buộc phải fail-fast với lỗi có ngữ cảnh, không lộ secrets hoặc silent skip.
- [ ] Disabled có reason/capability rõ; module đăng ký độc lập giữ state/config theo camera/session, chia sẻ perception tương thích; đăng ký thêm module không mặc nhiên chứng minh capacity chạy đồng thời.

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
- 2026-10-13 edge config & doctor wave: Bổ sung `apps/edge/config.py` và `apps/edge/doctor.py` riêng cho edge runtime; cấu hình bất biến frozen dataclass kèm SHA-256 fingerprint; kiểm tra preflight artifact ONNX và ORT CPU provider thật qua `OracleDetector`/`load_manifest`; từ chối cấu hình sai/unsupported không lộ secrets; doctor CLI với `--start` tích hợp trực tiếp `EdgeRuntime`, phân biệt rõ preflight capability với runtime execution; analytics lỗi trong lúc chạy báo nonzero sau khi recorder hoàn tất. Giữ nguyên `apps/server/doctor.py`. Execution tiếp tục `blocked`: chưa có full PerceptionPipeline/factory, và RKNN/RTSP vẫn là capability chưa nghiệm thu. Chi tiết: [dispatch log](../../../docs/logs/2026-10-13-runtime-dispatch.md).

- 2026-10-20: Đồng bộ breakdown T3 theo [requirement tình huống/Q36](../../../docs/requirements/urban-safety-scenarios.md) và [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md). Chỉ bổ sung phạm vi/acceptance/gates và dependency được duyệt; giữ Status/Execution, checked criteria, evidence và lịch sử cũ. Không có evidence implementation/benchmark/nghiệm thu mới; mọi acceptance bổ sung còn unchecked.

- 2026-10-24 (wave 0): Implement **delta requirement module x camera** — chưa nghiệm thu acceptance gốc.
  Thêm `domain/alert_module_config.py`: contract thuần (no I/O) cho config theo **module × camera** gồm
  enabled/disabled + reason, ROI normalised [0,1], lịch theo weekday/second-of-day, ngưỡng do module definition
  khai báo, ngoại lệ có reason. Parse **fail-fast** với context `module`/`camera`/`field`, message **không echo
  giá trị** và từ chối field giống secret (kể cả nested). `AlertModuleRegistry` giữ activation state **độc lập theo
  (module, camera)**: `stage` chỉ ghi desired (`pending`/`disabled`), `activate` là boundary ghi observed, version cũ
  hơn observed bị `rejected: stale_config_version` và giữ LKG, `reset_session` chỉ reset camera đó và giữ config.
  Consumer thật: `apps/edge/doctor.py` thêm `--module-config` (lặp được) + `module_capabilities`; preflight báo
  `capabilities.modules` theo từng camera (`enabled`/`disabled`/`not_activated` + reason + config_hash) và trả exit
  code 1 khi config enabled sai; không document thì `not_configured`; report không claim capacity.
  Commands: `.venv-oracle/bin/python -m pytest tests/test_alert_module_config.py tests/test_module_config_doctor.py -q`
  ra **27 passed**; `tests/test_edge_doctor.py tests/test_edge_config.py` ra 12 passed (13 subtests); full suite
  `.venv-oracle/bin/python -m pytest -q` ra **553 passed, 126 subtests** (baseline trước slice: 526).
  `mypy domain/alert_module_config.py apps/edge/doctor.py`: 0 lỗi mới (2 lỗi `_SQLITE_FIXED.get` ở doctor.py:32 là
  pre-existing, ngoài scope slice).
  Còn mở (giữ nguyên như comment 2026-10-12): full `PerceptionPipeline` port + factory/artifact manifest, capability
  RKNN/RTSP; mọi acceptance gốc vẫn unchecked. Phân rã và thứ tự wave:
  [2026-10-24 work breakdown](../../../docs/logs/2026-10-24-work-breakdown-next-wave.md).

- 2026-10-24 (code review, chưa fix): review 2 trục trên commit `ae66f22` (fixed point `340b5f2`), kèm tham chiếu
  `ocr` (`@alibaba-group/open-code-review` 1.13.3). Findings đã verify bằng lệnh thật, **chưa sửa code**:
  1. **Blocking** `apps/edge/doctor.py:61` — `entry.get('cameras') or {}` ép falsy non-dict thành `{}` nên bỏ qua
     `isinstance(cameras, dict)`: document `"cameras": []` và `"cameras": false` được accept âm thầm (module
     xuất hiện với 0 camera) thay vì fail-fast.
  2. **Blocking** `apps/edge/doctor.py:67-68` — `frozenset(...)` trên input không phải collection:
     `required_fields: 5` → `TypeError` không bắt được (crash preflight thay vì `ConfigError`); `thresholds: "minscore"`
     bị tách thành 8 tên threshold 1 ký tự `['c','e','i','m','n','o','r','s']` và **vẫn accepted** — fail-fast bị vượt.
  3. Judgement `domain/alert_module_config.py:282-300` — Duplicated Code: `_parse_roi` lặp lại 2 luật mà
     `RegionOfInterest.__post_init__` (dòng 165, 171) đã sở hữu, trong khi `_parse_schedule`/`_parse_exceptions` đều
     delegate. Sửa: catch `ConfigError` rồi re-raise qua `place.fail(..., field='roi')`.
  4. Minor `domain/alert_module_config.py:517` — `_Place("*", camera_id)` làm lộ sentinel `module=*` trong lỗi
     operator-facing của `session_id`.
  5. Minor `domain/alert_module_config.py:404` — `ActivationState.describe()` không có caller (grep toàn repo);
     `capabilities()` tự dựng dict riêng. Dead API / speculative generality.
  Spec (partial, đúng phạm vi đã khai báo nhưng cần ghi rõ): registry chưa có **allowlisted factory** hay handle
  **perception chia sẻ** như ADR-0001 yêu cầu; và không consumer nào ngoài doctor đọc module config
  (`apps/edge/runtime.py`, `live_pipeline.py`, `pipeline.py` không tham chiếu), nên ROI/lịch/ngưỡng/enabled chưa tới
  perception — #57 vẫn phải nối dây. Ngoài ra doctor chỉ `stage()` nên `capabilities.modules` không bao giờ báo
  `enabled`, chỉ `not_activated`/`disabled`.
