# 08: Upload evidence và phát lại trên detail

Status: ready-for-agent
Execution: done
Owner: Codex (Edge/Backend/UI evidence pipeline)

**What to build:** Clip edge upload tới server, người trực xem/download qua detail kể cả event metadata đến trước clip.

**Blocked by:** [#07: Event pin được clip pre/post từ ring](07-event-pin-duoc-clip-pre-post-tu-ring.md).

## Acceptance criteria

- [x] Upload retry/resume cùng evidence identity, verify hash/size trước receipt; metadata/clip ACK tách.
- [x] Server kiểm object ownership/authz, range/content type; pending/failed rõ, H.265 có playback path được kiểm hoặc lỗi rõ.

- [x] Partial clip upload/ACK vẫn partial; expired/corrupt location không bị receipt lịch sử làm available; hash/bytes finalized bất biến.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: J03, E01, E02, UI01, UI02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.
- 2026-10-13: Hoàn thành triển khai upload evidence và phát lại trên server detail (Ticket #08):
  - Edge: Thêm `apps/edge/uploader.py` (`EdgeUploader`) trích xuất clip từ `FileRecorder`, tính toán/kiểm thực SHA-256 và size, upload qua HTTP PUT kèm metadata, nhận receipt và cập nhật outbox SQLite sang `state='acknowledged'`. Hỗ trợ backoff retry cho lỗi 503 và xử lý idempotent replay.
  - Server: Cấu hình `EVIDENCE_DIR`, bổ sung endpoint `PUT /v1/evidence/{device_id}/{event_id}/{request_id}` xác thực token, kiểm tra SHA-256 và lưu file nguyên tử qua fsync + replace. Bổ sung `GET /v1/evidence/.../media` hỗ trợ HTTP 206 Partial Content (Range requests) cho playback video trên web.
  - UI: Cập nhật `apps/server/static/index.html` hiển thị trạng thái pending, nhúng thẻ `<video controls>` phát trực tiếp, link Download và thông tin actual_range/completeness.
  - TDD: 22 unit & integration tests (`tests/test_server_evidence.py`, `tests/test_edge_uploader.py`) và toàn bộ 178 tests repository đều pass. Execution: `done`. Chi tiết: [evidence dispatch log](../../../docs/logs/2026-10-13-evidence-dispatch.md).
- 2026-10-17: Đồng bộ: Execution done (software lab) khớp bảng PRD; đoạn 'Cách chọn việc' đã sửa theo.
