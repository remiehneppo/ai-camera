# Code Review Fixes (Wave 2 & Wave 3) — 2026-10-27

Sửa toàn bộ các phát hiện từ đợt Code Review hai trục (Standards & Spec) trên commit `09f2990`.

## 1. Trục Standards (Coding Standards & Fowler Smells)

| # | Phát hiện | Khắc phục | File tác động |
|---|---|---|---|
| 1 | **Secret Redaction Standard**: bộ lọc khóa chỉ kiểm tra `("password", "token", "secret", "auth")`, bỏ sót `"credential"`, `"bearer"`, `"private_key"`. | Chuẩn hóa regex nhận diện bí mật dùng chung `r"secret|token|passw|credential|api[_-]?key|private[_-]?key|bearer|signature|auth"` (khớp với `_SECRET_KEY` trong `signed_config`), đồng thời loại bỏ scope creep khi che giấu nhầm `key_frame`, `camera_key`. | `domain/storm_guard.py`, `apps/edge/health.py` |
| 2 | **Production Invariant via Assert**: dùng `assert` để kiểm tra tính toàn vẹn của receipt khi đối soát manifest. | Thay `assert` bằng việc ném `RetentionError("receipt_mutation_detected", ...)` có ngữ cảnh cụ thể, an toàn khi chạy Python với cờ `-O`. | `apps/server/retention.py` |
| 3 | **Duplicated Code**: logic dựng `config_descs`, tính `canonical_bundle_hash`, đóng gói `provenance` và snapshot LKG bị lặp lại ở cả `activate_local` và `activate_signed_bundle`. | Trích xuất thành phương thức static dùng chung `_build_lkg_snapshot` trong `ConfigActivationManager`. | `apps/edge/config_activation.py` |
| 4 | **Data Clump**: `_event_context` trả về tuple 3 phần tử `(decision, severity, site_id)`. | Gom thành `@dataclass(frozen=True) class EventContext` rõ ràng về kiểu dữ liệu và trách nhiệm. | `apps/server/retention.py` |

## 2. Trục Spec (Correctness & Invariant Validation)

| # | Phát hiện | Khắc phục | File tác động |
|---|---|---|---|
| 1 | **Reconciliation phân loại sai clip expired thành missing**: khi restore và đối soát, tệp media đã bị retention sweep xóa hợp lệ bị coi là missing. | Thêm trạng thái `RECONCILE_EXPIRED` vào `domain/retention_contract.py`: `classify_manifest_and_file` giữ nguyên trạng thái `expired`, không ghi đè thành `missing`, và `clean` report vẫn đạt khi không có missing/corrupt thực sự. | `domain/retention_contract.py`, `tests/test_central_retention_backup.py` |
| 2 | **Delete evidence bỏ sót kiểm tra pinned**: `delete_evidence()` chỉ kiểm tra `legal_hold` và `open_retrieval`. | Bổ sung kiểm tra cờ `pinned` trên cả record và manifest, ném `RetentionError("pinned_or_legal_hold_protected", ...)` khi có pin. | `apps/server/retention.py` |
| 3 | **Pin gap stage validation**: `record_pin_gap` nhận bất kỳ stage nào thuộc `STAGES` dù catalog chỉ hỗ trợ `journal` và `delivery`. | Kiểm tra `pin_gap_fault_code(stage) in FAULT_CATALOG`, ném `ValueError` ngay tại call site nếu stage chưa có cataloged pin gap fault. | `domain/probe_contract.py` |
| 4 | **Session continuity reset**: `ConfigActivationManager` thiếu API ủy quyền `reset_session`. | Bổ sung `reset_session(self, camera_id: str, session_id: str) -> Tuple[str, ...]` ủy quyền tới `self.registry.reset_session`. | `apps/edge/config_activation.py` |
| 5 | **Runbook path**: thiếu tài liệu runbook theo liên kết khai báo. | Tạo `docs/runbooks/synthetic-probe-operational-fault.md` dẫn chiếu chính xác đến `docs/architecture/contracts.md#synthetic-probe-operational-fault`. | `docs/runbooks/synthetic-probe-operational-fault.md` |

## 3. Bằng chứng kiểm thử sau sửa đổi
- Toàn bộ 11 file nguồn/test liên quan:
  `mypy domain/probe_contract.py apps/edge/probe.py apps/edge/runtime.py domain/storm_guard.py apps/edge/health.py domain/signed_config.py apps/edge/config_activation.py domain/retention_contract.py apps/server/retention.py tests/test_central_retention_backup.py tests/test_signed_config_activation.py`
  ⇒ **Success: no issues found in 11 source files**.
- Toàn bộ Test Suite:
  `pytest -q` ⇒ **714 passed, 126 subtests passed** trong 142.12s.
