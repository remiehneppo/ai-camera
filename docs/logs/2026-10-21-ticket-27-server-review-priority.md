# Ticket #27 — Server review-queue priority cho on-vehicle (2026-10-21)

## Phạm vi

Lát cắt server-side của [#27](../../.scratch/system-build-slices/issues/27-on-vehicle-van-review-voi-uu-tien-rieng.md):
`person_on_stationary_vehicle` vẫn tạo event/review, nhưng nằm ở hàng đợi ưu tiên thấp và
không trở thành ứng viên notification khẩn trong lab. Phần association/history trên edge do
lát cắt edge đảm nhiệm; server chỉ tin taxonomy/severity trong event snapshot.

## Thay đổi

### `apps/server/store.py`
- `LOW_PRIORITY_TAXONOMIES = {"person_on_stationary_vehicle"}`, `SEVERITY_VALUES`, và
  `review_priority_for(payload)` → `low | standard | urgent`.
  - `severity` high/critical → `urgent` (danger override không bị hạ ưu tiên).
  - taxonomy on-vehicle hoặc `severity == "low"` → `low`.
  - còn lại → `standard`.
- `list_current(limit, cursor, severity=None, taxonomy=None)`: lọc theo
  `event.payload.severity` / `event.payload.taxonomy` kết hợp cursor; mỗi row trả thêm
  `taxonomy`, `severity`, `review_priority`.
- Outbox lab vẫn `eligibility="ineligible"` cho mọi event (không có consumer gửi notification
  trong repo), đồng thời lưu `taxonomy`, `severity`, `review_priority` để audit vì sao event
  không đủ điều kiện khẩn.
- `record_review` lưu `reviewed_taxonomy`, `reviewed_severity`, `reviewed_review_priority`
  trong cả review state và audit entry, nên quyết định review on-vehicle truy vết được.

### `apps/server/main.py`
- `GET /v1/events` nhận `severity` và `taxonomy` (validate: severity ∈ low/medium/high/critical;
  taxonomy 1–128 ký tự, sai → 422) và chuyển xuống `list_current`.
- `GET /v1/dataset/export` nhận cùng hai filter, truyền vào `export_dataset_records`.
- Review API và nội dung `meaningful_content_hash` không đổi: taxonomy/severity đã là phần
  nội dung có nghĩa nên revision đổi severity vẫn tạo 409/re-review như cũ.

### `apps/server/dataset.py`, `apps/server/export_dataset.py`
- Record export có thêm `taxonomy`, `severity`, `review_priority`; `original_ai_payload`,
  `reviewed_decision`, `reviewed_event_revision`, `reviewed_event_hash`, `review_audit_trail`
  và evidence manifest vẫn giữ nguyên lineage.
- `export_dataset_records(..., taxonomy=None, severity=None)` và CLI `--taxonomy/--severity`
  cho phép xuất riêng nhóm on-vehicle hoặc nhóm khẩn.

### `apps/server/static/index.html`
- Card on-vehicle hiển thị badge `On-vehicle (Low priority)` (class `badge-priority-low`).
- Badge priority chung: `Emergency priority` / `Standard priority`; dòng metadata thêm
  `review priority <low|standard|urgent>` để reviewer phân biệt hàng đợi.

## Kiểm chứng

- `tests/test_review_priority.py` (mới, 6 tests): phân lớp priority, filter store/API, outbox lab
  ineligible, audit snapshot, export on-vehicle giữ lineage + review decision.
- Regression bắt buộc:
  `.venv-oracle/bin/python -m pytest tests/test_server_evidence.py tests/test_review_api.py tests/test_dataset_lineage.py tests/test_review_priority.py -q`
  → **34 passed**.

## Chưa làm / giới hạn

- Chưa có consumer downstream notification thật; kết luận "không notification khẩn" dựa trên
  outbox lab `ineligible` và metadata priority, chưa phải protocol đã ký.
- Chưa đổi thứ tự sắp xếp mặc định (giữ `updated_at` desc) để không phá cursor pagination;
  phân biệt ưu tiên bằng tag/filter. Nếu cần sort urgent-first phải đổi cursor contract.
- Chất lượng association/ODD của on-vehicle thuộc edge + QA, không được đo trong lát cắt này.
