# 36: WAN outage giữ event/evidence rồi resume

Status: ready-for-agent
Execution: done (software lab; 24h autonomy sizing + no-TTL on unACKed evidence + metadata priority + B/(U-G) drain model pass)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Ngắt WAN/central theo budget lab và workload đã sizing, phục hồi upload/retrieval mà không mất dữ liệu protected trái policy.

**Blocked by:** [#18: Quota bảo vệ pinned evidence và journal](18-quota-bao-ve-pinned-evidence-va-journal.md); [#32: Retained evidence truy hồi có authorization](32-retained-evidence-truy-hoi-co-authorization.md).

## Acceptance criteria

- [x] 24h target được đo autonomy/time-to-full/backlog, quá budget báo degraded, không TTL unACK.
- [x] Metadata ưu tiên clip, receipt/retry/dedup đúng và report RPO/RTO trong scope; không hứa chịu disk loss.

- [x] Đo B/U/G và backlog drain: U≤G không ký recovery thoát backlog; nếu U>G đối chiếu thời gian B/(U−G) với số đo cùng recording.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: J05, J03, R05.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
- 2026-10-27: Hoàn thành triển khai software lab cho #36.
  `domain/wan_outage.py`: Mô hình tính toán 24h autonomy (86,400s), time-to-full bảo vệ reserve 50MB; chính sách No-TTL trên unACK evidence; chính sách ưu tiên metadata event trước clip; mô hình giải tỏa backlog $B / (U - G)$ với kiểm tra $U \le G$ từ chối ký thoát backlog và $U > G$ xác thực quỹ đạo $B(t)$. Báo cáo RPO=0s và RTO kèm disclaimer không cam kết chống hỏng đĩa vật lý.
  `apps/edge/wan_resilience.py`: `WanOutageCoordinator` điều phối outbox và upload qua các đợt ngắt mạng WAN; tích hợp `EdgeHealthMonitor.backend_checker`; ưu tiên đẩy toàn bộ outbox metadata trước khi upload clip; retry với bounded exponential backoff mà không làm mất unACK evidence; giải tỏa backlog sạch sẽ khi có mạng trở lại.
  Evidence: `pytest tests/test_wan_outage_resilience.py -v` ⇒ **21 passed**; `mypy` sạch.