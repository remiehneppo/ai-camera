# Wave 2 Hoàn tất (#40, #41, #43) & Wave 3 Mở (#34) — 2026-10-27

Thực hiện theo kế hoạch Wave 2 hoàn tất và mở Wave 3 sau khi trao đổi làm rõ và chốt quyết định cùng người dùng:
1. Hoàn tất #40 (pin-gap injection + scheduler).
2. Hoàn tất #41 (edge storm guard + media write failure handling).
3. Hoàn tất #43 (central retention manager + backup/restore reconciliation proof).
4. Hoàn tất #34 (local & signed config activation + durable SQLite HWM/LKG + recorder isolation).

## 1. Xuất phát điểm
- HEAD: `4d651ca`, 676 tests pass.
- Các ticket Wave 2 đang ở trạng thái partial: #40 (thiếu pin-gap + scheduler), #41 (thiếu edge counter + media failure), #43 chưa bắt đầu.
- Nút thắt lớn Wave 3: #34 (Config local & signed activation giữ LKG).

## 2. Chi tiết triển khai

### Ticket #40: Pin-gap Fault Injection & Runtime ProbeScheduler
- `domain/probe_contract.py`:
  - Thêm exception class `PinGapDetected(message, gap_seconds)`.
  - Khai báo `PIN_GAP_FAULT_CODE = "probe_journal_pin_gap"` và `probe_delivery_pin_gap` trong `FAULT_CATALOG` với đầy đủ metadata vận hành.
  - `ProbeLedger` bổ sung `record_pin_gap`, `clear_pin_gap`, `pin_gaps()`, cập nhật `evaluate()` và `reset()`.
- `apps/edge/probe.py`:
  - Thêm helper factory `make_journal_pin_stage` để inject lỗi pin-gap hoặc verify với recorder coverage.
  - Xây dựng `ProbeScheduler` hỗ trợ cả deterministic tick pacing (`tick(now)`) cho synthetic clock và background thread loop (`start()`, `stop()`).
  - Bảo đảm AST import constraint: chỉ import `{__future__, time, typing, uuid, domain.probe_contract, threading}`, không phụ thuộc outbox/incident.
- `apps/edge/runtime.py`:
  - Tích hợp hook `probe_scheduler` vào `EdgeRuntime`: start scheduler khi runtime start, tick scheduler và gắn probe report vào `status()["probe"]`, chuyển `degraded = True` nếu probe phát hiện fault, stop scheduler an toàn khi runtime stop.

### Ticket #41: Edge Storm Counter & Media-Failure Forensic Guard
- `domain/storm_guard.py`:
  - Hỗ trợ `forensic_sink`, `storage_available` predicate, `record_media_failure` / `record_sink_failure`.
  - Xử lý an toàn khi ghi forensic/media bị lỗi (`OSError` disk full hoặc storage reserve chạm ngưỡng): bỏ qua việc giữ sample, tăng `dropped_samples` và `sink_failures` (`media_write_failures`), set `forensic_storage_degraded: True`.
  - Tự động che giấu thông tin nhạy cảm trong detail với `_is_secret_key`.
- `apps/edge/health.py`:
  - Tích hợp edge `StormGuard` vào `EdgeHealthMonitor`, tự động kiểm tra dung lượng còn lại so với `quota_manager.min_state_reserve_bytes` và critical percent.
  - Expose các API: `record_ingest_outcome`, `record_malformed_payload`, `record_media_failure`.
  - Chuyển `HealthStatus.DEGRADED` với primary reason `malformed_storm_detected` (thuộc `DEGRADED_REASONS`) khi storm guard bị degraded/truncated/storage degraded.

### Ticket #43: Central Retention Policy & Backup/Restore Reconciliation Proof
- `domain/retention_contract.py` (mới):
  - Khóa retention window mặc định: 7 ngày (604,800s theo Q6/contracts §3).
  - Quy tắc bảo vệ: từ chối xóa clip chưa hết hạn, clip đang có retrieval command mở (`pending`/`claimed`), clip có legal hold / pinned, và sự kiện unreviewed có severity high/critical.
  - Expiry an toàn: chuyển `file_status` sang `expired` nhưng bảo toàn 100% receipt gốc (`sha256`, `size_bytes`, requested/actual intervals, IDs) theo contracts §4.
  - RBAC và audit record bất biến cho delete/export actions.
  - Phân loại reconciliation độc lập: `verified`, `pending`, `missing`, `corrupt`, `orphan`.
- `apps/server/retention.py` (mới):
  - `CentralRetentionManager`: quét và dọn dẹp các clip đã hết hạn trên filesystem, đồng bộ trạng thái metadata mà không giả định cross-system transaction giữa Mongo và đĩa.
  - `create_backup_bundle`: snapshot toàn bộ 9 metadata collections + evidence clips vào bundle cách ly kèm manifest SHA-256.
  - `restore_and_reconcile`: restore vào môi trường mới, đối soát và phân loại từng manifest, tính toán RPO/RTO thực tế và gắn disclaimer bắt buộc `ha_disclaimer: "lab_single_replica_not_production_ha"` (M12-ERR03).

### Ticket #34: Local & Signed Config Activation with Durable High-Water Mark and LKG
- `domain/signed_config.py` (mới):
  - Canonical JSON serialization (`canonical_bundle_bytes`) bảo đảm tính tất định.
  - `TrustedKey` / `TrustedKeyRing` hỗ trợ role-based key allowlisting (`config_signer`), key revocation, stdlib HMAC-SHA256, và pluggable custom signature verifier.
  - `verify_signed_bundle`: kiểm tra canonical bytes length, SHA-256, target matching (device/site/profile), trusted key authorization, monotonic `trust_sequence` > durable high-water mark, expiry, và uncertain clock (`clock_synchronized=False`).
- `apps/edge/config_activation.py` (mới):
  - `DurableConfigStateStore`: SQLite WAL + `synchronous=FULL` bảo đảm `high_water_mark` và LKG snapshot không bao giờ bị lùi hay mất sau crash/reboot.
  - `ConfigActivationManager`:
    - Local activation fail-fast module × camera tại boundary: lỗi giữ nguyên LKG.
    - Remote signed activation: xác thực bundle trước khi kích hoạt; nếu bundle sai chữ ký, sai target, sequence cũ, hoặc inner config sai thì giữ nguyên LKG và observed version.
    - Độc lập với recorder: config activation thất bại không làm dừng hay ngắt recorder.

## 3. Bằng chứng kiểm thử và nghiệm thu (Evidence)

1. **Test riêng từng module mới/sửa:**
   - `pytest tests/test_probe.py tests/test_probe_guard.py tests/test_edge_runtime.py -q` ⇒ **42 passed**.
   - `pytest tests/test_storm_guard.py tests/test_storm_api.py tests/test_health.py -q` ⇒ **48 passed**.
   - `pytest tests/test_signed_config_activation.py -q` ⇒ **16 passed**.
   - `pytest tests/test_central_retention_backup.py -q` ⇒ **4 passed**.
2. **Kiểm tra kiểu tĩnh:**
   - `mypy domain/probe_contract.py apps/edge/probe.py apps/edge/runtime.py domain/storm_guard.py apps/edge/health.py domain/signed_config.py apps/edge/config_activation.py domain/retention_contract.py apps/server/retention.py` ⇒ **Success: no issues found in 9 source files**.
3. **Toàn bộ Test Suite toàn dự án:**
   - `pytest -q` ⇒ **714 passed, 126 subtests passed** (baseline 676, +38 tests mới).
