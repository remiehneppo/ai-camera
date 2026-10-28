# Ticket #21 — Quality scope theo capability × camera/site — 2026-10-27

## Quyết định phạm vi (người dùng chốt)
- Lát cắt: quality status theo **capability × camera**, `site_id` **optional**; không suy site từ device/camera naming.
- Policy phải **tường minh và có `version`**; thiếu policy ⇒ `unknown`, không dùng `DEFAULT_ODD_POLICY` cho mọi capability.
- Chỉ pure/helper assessment + tests. Chưa nối module registry/runtime/event-detail, nên hai acceptance delta của #21 vẫn mở.
- CodeGraph MCP không khả dụng trong session (`tool_activate` → unknown paged namespace); Beads workspace không tồn tại. Khảo sát trực tiếp files.

## Thay đổi
- `apps/edge/pipeline.py`: thêm `assess_capability_quality(rgb, *, capability, camera_id, site_id=None, policy=None, reason=None)`
  cùng helper `_validated_policy` và hai hằng `_CAPABILITY_REQUIRED_THRESHOLDS` / `_CAPABILITY_OPTIONAL_THRESHOLDS`.
  - Scope trả về `{capability, camera_id, site_id}`; `site_id` thiếu thì giữ `None`, không suy diễn.
  - Khoá `capability` theo convention domain (`domain/quality_eval.py`).
  - **Không kế thừa ngưỡng**: policy phải khai báo tường minh `low_light_mean`, `glare_mean`, `low_contrast_std`
    (finite number); thiếu ⇒ `ValueError` thay vì merge `DEFAULT_ODD_POLICY`.
  - `blur_laplacian_var` optional nhưng **được validate** (finite number hoặc `None`) để lỗi ra `ValueError`
    thay vì `TypeError` trong `assess_quality`.
  - `freeze_frames` **không** thuộc capability policy: freeze cần state giữa các frame và nằm ở `PerceptionPipeline`,
    nên helper stateless không được ngụ ý đã đánh giá freeze.
  - Thiếu policy ⇒ `unknown`/`odd_supported=None`/`reason="policy_unconfigured"`; nếu caller có truyền `reason`
    thì giữ ở `observation_reason`, không ghi đè và không bị bỏ im lặng.
- `tests/test_quality_odd.py`: `TestCapabilityQualityScope` — 9 test bao phủ scope tách biệt, missing policy,
  policy thiếu ngưỡng, ngưỡng phi số/không hữu hạn, blur sai kiểu, freeze không ảnh hưởng, giữ cả hai tín hiệu reason,
  scope/version sai fail-fast, và missing frame có policy ⇒ `unknown`/`invalid_frame`.

## Kiểm chứng
- `.venv-oracle/bin/python -m pytest tests/test_quality_odd.py -q` ⇒ **23 passed**.
- `.venv-oracle/bin/python -m mypy apps/edge/pipeline.py` ⇒ **Success: no issues found**.
- `.venv-oracle/bin/python -m pytest -q` ⇒ **832 passed, 360 warnings, 126 subtests** (baseline 823).
- `git diff --check` sạch.

## Review hai trục và cách xử lý
- Standards (`906215df`): không vi phạm cứng. Đã sửa: inline `_unknown_quality` (một call site, Speculative Generality),
  tách hằng required/optional (Shotgun Surgery), đổi tên `_capability_policy` → `_validated_policy` (Mysterious Name).
- Spec (`d0616f74`): đã sửa ba lỗi thật — `freeze_frames` không còn bị ngụ ý đánh giá, `blur_laplacian_var` được validate,
  `reason` của caller được giữ ở `observation_reason` thay vì bị bỏ.
- Giữ nguyên có lý do: Data Clump (gói scope type sẽ đổi public API đã chốt), chia sẻ phép đo giữa N capability
  (cần wiring, ngoài lát cắt), và hai điểm `index.html` (thuộc #44, đã accepted làm demo evidence).

## Còn mở (không claim)
- Chưa có chiều ngày/đêm/mưa hay bounds đã kiểm thử **theo capability**; đây là điều kiện của acceptance delta đầu tiên
  và cần ngưỡng site được duyệt, không thể tự suy trong software lab.
- Chưa có input continuity/out-of-ODD nên "ngoài ODD" chưa biểu diễn được.
- `capability` chưa gắn với allowlist registry; `site_id` chưa có consumer đối chiếu registry authoritative.
- Chưa nối vào `PerceptionPipeline`/event payload/detail UI.
- Native C++ measurement và camera-moved vẫn mở như ghi nhận trước đó.
