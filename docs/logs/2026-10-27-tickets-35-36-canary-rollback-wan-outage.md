# Triển khai Hoàn tất Ticket #35 (Canary & Rollback) và Ticket #36 (WAN Outage) — 2026-10-27

Ghi chép hành động, quyết định và kết quả kiểm thử cho 2 lát cắt hạ tầng tin cậy:
- Ticket #35: Canary release & authorized rollback với sequence mới (`.scratch/system-build-slices/issues/35-canary-va-rollback-co-authorization-moi.md`).
- Ticket #36: WAN outage 24h autonomy, ưu tiên metadata và mô hình giải tỏa backlog B/(U-G) (`.scratch/system-build-slices/issues/36-wan-outage-giu-event-evidence-roi-resume.md`).

## 1. Xuất phát điểm
- HEAD: `e724861`, 737 tests pass.
- Đồ thị phụ thuộc:
  - #35: đã đủ blockers (#34 done, #28 done).
  - #36: đã đủ blockers (#18 done, #32 done).

## 2. Chi tiết triển khai

### Ticket #35: Canary Deployment & Authorized Rollback
- `domain/signed_config.py`:
  - Thêm role ủy quyền mới: `ROLE_CONFIG_ROLLBACK = "config_rollback"`.
  - Cập nhật `TrustedKeyRing.verify` cho phép xác thực đa role (`required_role`).
  - Xây dựng `CanarySpec` xác định tập camera/module chạy thử nghiệm, ngưỡng lỗi `max_error_rate` và thời gian quan sát.
  - Xây dựng `CompatibilityPolicy` bảo đảm tính tương thích của schema, factory, và ma trận model lineage, cấm việc âm thầm trộn lẫn các lineage không tương thích qua các lần rollback.
- `apps/edge/config_activation.py`:
  - `activate_canary`: triển khai cấu hình mới trên một tập camera/module canary, giữ nguyên LKG cơ sở trong SQLite và nâng HWM để chống tấn công replay.
  - `record_canary_observation`: theo dõi tỷ lệ lỗi; tự động abort và khôi phục LKG nếu vượt ngưỡng lỗi hoặc health degraded.
  - `abort_canary` và `promote_canary`: cơ chế hủy bỏ hoặc mở rộng toàn bộ canary sạch sẽ.
  - Rollback bắt buộc dùng `trust_sequence` mới cao hơn HWM hiện tại (không hạ sequence), khôi phục cấu hình mục tiêu, và cập nhật LKG.
  - SQLite WAL+FULL lưu trữ bền vững trạng thái canary, rollback sequence, và LKG qua reboot/crash.

### Ticket #36: WAN Outage 24h Autonomy, Metadata Priority, & Backlog Drain
- `domain/wan_outage.py` (mới):
  - `AutonomySizingModel`: mô hình hóa tốc độ sinh event (B/s), tốc độ sinh clip (B/s), tính toán thời gian tự chủ 24h (86,400s) và time-to-full có bảo vệ ngưỡng dự trữ 50MB state reserve. Báo `degraded: wan_outage_budget_exceeded` khi quá 24h.
  - Chính sách No-TTL: `evaluate_evidence_ttl_eligibility` bảo đảm không bao giờ xóa hay đặt hạn chót TTL cho các clip và event chưa được server ACK (chống mất mát dữ liệu).
  - `MetadataPriorityPolicy`: ưu tiên hàng đầu cho việc đẩy metadata sự kiện trước các clip media dung lượng lớn khi mạng có lại.
  - `BacklogDrainModel`: mô hình hóa $B$ (backlog), $U$ (tốc độ upload), $G$ (tốc độ sinh dữ liệu). Khẳng định không thể giải tỏa khi $U \le G$; khi $U > G$ tính toán thời gian giải tỏa $T = B / (U - G)$ và đối soát quỹ đạo $B(t)$.
  - Báo cáo RPO=0s và RTO kèm disclaimer rõ ràng không cam đoan chống hỏng đĩa vật lý.
- `apps/edge/wan_resilience.py` (mới):
  - `WanOutageCoordinator`: theo dõi trạng thái mạng WAN, tích hợp `EdgeHealthMonitor.backend_checker`.
  - Quản lý outbox metadata và uploader clips: ngắt mạng không làm rơi rớt dữ liệu, retry có backoff và jitter, khi khôi phục mạng ưu tiên xả toàn bộ metadata trước khi upload video.
  - Đo lường và đối soát quá trình giải tỏa backlog thực tế theo mô hình lý thuyết.

## 3. Bằng chứng kiểm thử & Nghiệm thu
- **Mypy**:
  `mypy domain/signed_config.py apps/edge/config_activation.py domain/wan_outage.py apps/edge/wan_resilience.py tests/test_canary_rollback.py tests/test_wan_outage_resilience.py`
  ⇒ **Success: no issues found in 6 source files**.
- **Pytest module mới**:
  `pytest tests/test_canary_rollback.py tests/test_wan_outage_resilience.py -v`
  ⇒ **35 passed in 0.79s** (14 canary/rollback + 21 wan outage).
- **Full Test Suite toàn dự án**:
  `pytest -q`
  ⇒ **774 passed, 360 warnings, 126 subtests passed in 140.52s** (0 regressions, +37 tests mới so với 737).
