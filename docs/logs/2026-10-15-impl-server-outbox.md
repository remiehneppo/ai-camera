# Nhật Ký Thực Hiện: Cải Tiến Server Evidence Streaming, Outbox Delivery & Store Pagination

- **Ngày thực hiện:** 2026-10-15
- **Tác vụ:** Sửa lỗi P1-01, P1-05, P1-06, P2-04, P2-05, P2-06, P2-07 theo báo cáo `docs/logs/2026-10-15-full-flow-code-review.md`.
- **Tài liệu tham chiếu:** `docs/adr/0002-server-downstream-event-publishing.md`, `docs/adr/0003-fastapi-mongodb-backend.md`, `docs/adr/0004-integration-contracts.md`, `docs/architecture/contracts.md`.

---

## 1. Chi Tiết Thực Hiện Từng Mục

### [P1-01] apps/server/main.py: Streaming Chunk Upload & FileResponse Download Evidence

- **Vấn đề cũ:**
  - Endpoint upload evidence `PUT /v1/evidence/{device_id}/{event_id}/{request_id}` sử dụng `await request.body()`, nạp toàn bộ file media vào RAM Python gây nguy cơ OOM khi tải file lớn hoặc có nhiều client upload đồng thời.
  - Endpoint download `GET /v1/evidence/{device_id}/{event_id}/{request_id}/media` đọc toàn bộ file `f.read()` vào RAM khi không có `Range` header.
- **Giải pháp đã triển khai:**
  - **Upload:**
    - Thay thế `await request.body()` bằng streaming qua `async for chunk in request.stream()`.
    - Tính SHA-256 cuộn (`hasher.update(chunk)`) và đếm `size_bytes` đồng thời khi ghi thẳng vào file tạm `.{request_id}.{uuid}.tmp`.
    - Áp dụng giới hạn `MAX_EVIDENCE_BYTES = 100 * 1024 * 1024` (100 MiB); nếu vượt quá lập tức ngắt stream và trả HTTP 413 Payload Too Large.
    - Đảm bảo tính nguyên vẹn: sau khi stream xong, kiểm tra SHA-256 khớp với header `X-Evidence-Sha256` (422 nếu lệch), so sánh `size_bytes` với `metadata["size_bytes"]` nếu có (422 nếu lệch).
    - Gọi `f.flush()`, `os.fsync(f.fileno())`, liên kết nguyên tử `os.link(temp_file, target_file)`, `fsync` toàn bộ thư mục cha, và dọn dẹp `temp_file.unlink()` trong khối `finally`.
  - **Download:**
    - Thay thế toàn bộ logic đọc file thủ công và phân tích header Range bằng FastAPI/Starlette `FileResponse(file_path, media_type=media_type, headers={"Accept-Ranges": "bytes"}, content_disposition_type=None)`.
    - `FileResponse` hỗ trợ stream từ disk trực tiếp ra client theo chunk, xử lý đầy đủ các trường hợp `Range: bytes=0-9`, suffix `Range: bytes=-20`, và trả về HTTP 416 khi range nằm ngoài phạm vi (`bytes */size`).

### [P1-05] apps/edge/send_synthetic.py: Bounded Retry với Exponential Backoff & Jitter cho deliver_pending

- **Vấn đề cũ:**
  - Hàm `deliver_pending` duyệt `outbox.pending()` và gọi `urlopen()` với 1 lần duy nhất; nếu lỗi mạng, hàm ném ngoại lệ ngay lập tức làm ngắt toàn bộ tiến trình gửi batch mà không giãn cách thời gian retry.
- **Giải pháp đã triển khai:**
  - Bổ sung vòng lặp retry có giới hạn với `max_retries = 3`, `backoff_base = 0.5s`, `max_backoff = 8.0s`.
  - Tích hợp Exponential Backoff kèm Full Jitter: `delay = rng(0.0, raw_delay) if jitter else raw_delay` với `raw_delay = min(max_backoff, backoff_base * (2 ** (attempt - 1)))`.
  - Hỗ trợ Dependency Injection cho `sleep_fn`, `clock_fn`, `rng_fn` nhằm phục vụ kiểm thử đơn vị độc lập với clock hệ thống.
  - Phân loại lỗi chính xác:
    - Lỗi mạng tạm thời (`URLError`, `TimeoutError`, `OSError`) và mã HTTP tạm thời (`429`, `500`, `502`, `503`, `504`) được phép retry.
    - Lỗi 4xx (400, 401, 403, 422) và `ValueError` (lệch receipt) bị ném ra ngay lập tức mà không retry vô ích.
  - Mỗi lần thất bại đều gọi `outbox.record_attempt(message_id, type(exc).__name__)` để đảm bảo ghi nhận lịch sử thử nghiệm trung thực.
  - Giữ vững ngữ nghĩa Idempotency: Header `Idempotency-Key` và canonical content hash giữ nguyên qua các lần retry.

### [P1-06] apps/server/store.py & apps/server/main.py: Cursor Pagination Ổn Định Theo (updated_at, _id)

- **Vấn đề cũ:**
  - Hàm `list_current(self, limit: int)` chỉ sắp xếp theo `updated_at` giảm dần và `limit()`, không có cơ chế phân trang để xem các trang sau khi số lượng sự kiện lớn.
- **Giải pháp đã triển khai:**
  - Tạo compound index `current_event_cursor` trên `[("updated_at", -1), ("_id", -1)]` trong `EventStore.ensure_ready()`.
  - Thiết kế hàm mã hóa và giải mã cursor an toàn URL Base64 (`encode_cursor`, `decode_cursor`) chứa `updated_at` (chuỗi ISO) và `_id` (`ObjectId`).
  - Trong `EventStore.list_current(limit, cursor)`:
    - Nếu có `cursor`, lọc bản ghi theo điều kiện:
      `{"$or": [{"updated_at": {"$lt": cursor_updated_at}}, {"updated_at": cursor_updated_at, "_id": {"$lt": cursor_id}}]}`
    - Truy vấn `limit + 1` bản ghi; nếu vượt quá `limit` thì trích xuất `next_cursor` từ phần tử cuối trang và cắt danh sách về đúng `limit`.
    - Trả về đối tượng `PaginatedEvents` (kế thừa `list`, đính kèm thuộc tính `.next_cursor`). Nhờ kế thừa `list`, mã nguồn hiện có duyệt vòng lặp hoặc kiểm tra phần tử không bị phá vỡ.
  - Cập nhật endpoint `/v1/events`:
    - Nhận tham số truy vấn `limit: int = 50` và `cursor: str | None = None`.
    - Trả về payload JSON dạng: `{"events": [...], "next_cursor": "<base64>" | null, "review_enabled": bool}`.
    - Bắt lỗi giải mã cursor không hợp lệ và trả về HTTP 422 Unprocessable Entity.

### [P2-04] Tách Interface Store (Quyết Định Thiết Kế & YAGNI)

- **Đánh giá:**
  - Đề xuất tách `BaseEventStore` và `InMemoryEventStore`.
  - Tuy nhiên, toàn bộ các bài test hiện tại (`test_server_evidence.py`, `test_review_fixes.py`) đã chạy trực tiếp trên MongoDB Replica Set 7.0.43 (khởi chạy thông qua Docker container cục bộ tại `192.168.96.2:27017`) với tốc độ nhanh (< 15 giây cho toàn bộ suite).
  - Không có unit test nào yêu cầu InMemoryStore hay gặp rào cản do thiếu interface store.
- **Quyết định (YAGNI):**
  - **KHÔNG THỰC HIỆN** tách interface store nhằm tuân thủ nguyên tắc YAGNI và yêu cầu của bài toán ("chỉ tách interface store nhỏ nếu tests hiện tại cần; nếu không, KHÔNG làm (YAGNI) và ghi lý do vào log"). Tránh việc tạo abstraction dư thừa không có consumer thực tế.

### [P2-05] apps/edge/outbox.py: Từ Chối Revision Không Tăng Nghiêm Ngặt

- **Vấn đề cũ:**
  - `EventOutbox.enqueue` chỉ kiểm tra nếu cùng `(device_id, event_id, revision)` đã tồn tại hay chưa, không kiểm tra tính tăng đơn điệu nghiêm ngặt đối với các revision mới.
- **Giải pháp đã triển khai:**
  - Trong `EventOutbox.enqueue`:
    - Nếu tìm thấy bản ghi cùng revision và cùng hash -> Trả về `prior["message_id"]` (Idempotent replay).
    - Nếu cùng revision nhưng khác hash -> Ném `EventConflict("same event revision was already stored with different content")`.
    - Nếu là revision mới: truy vấn `MAX(revision)` hiện có của `(device_id, event_id)`. Nếu `event["revision"] <= max_rev` -> Ném `EventConflict` từ chối revision không tăng nghiêm ngặt.

### [P2-06] compose.yaml & README.md: Ghi Rõ Yêu Cầu MongoDB >= 5.0

- **Nội dung bổ sung:**
  - Thêm chú thích vào `compose.yaml` tại cấu hình service `mongo`:
    `# Requires MongoDB >= 5.0 for $setWindowFields and replica set multi-document ACID transactions (pinned to 7.0.43).`
  - Cập nhật `README.md` mục "Run the lab stack": Ghi rõ backend bắt buộc sử dụng MongoDB phiên bản từ 5.0 trở lên do phụ thuộc vào multi-document ACID transactions và toán tử `$setWindowFields` trong pipeline tổng hợp review audit của `list_current`.

### [P2-07] apps/server/main.py: Suy Luận File Extension & Content-Type Từ Metadata Codec

- **Giải pháp đã triển khai:**
  - Xây dựng 2 hàm helper `_infer_evidence_extension` và `_infer_media_type` trong `apps/server/main.py`.
  - Phân tích metadata có sẵn (`content_type`, `content-type`, `mime_type`, hoặc `codec`):
    - `jpeg`, `mjpeg`, `jpg`, `image/jpeg` -> lưu file đuôi `.jpg`, phục vụ MIME `image/jpeg`.
    - `png`, `image/png` -> lưu file đuôi `.png`, phục vụ MIME `image/png`.
    - `mp4`, `video/mp4` -> lưu file đuôi `.mp4`, phục vụ MIME `video/mp4`.
    - Mặc định: file đuôi `.mkv`, phục vụ MIME `video/x-matroska`.
  - Giữ nguyên cấu trúc dữ liệu, không tự ý sáng tác thêm trường metadata mới.

### Bổ sung EdgeUploader: Injectable Sleep Function

- Trong `apps/edge/uploader.py`, bổ sung tham số `sleep_fn: Any = None` vào `EdgeUploader.__init__`, gán `self._sleep = sleep_fn if sleep_fn is not None else time.sleep`.
- Giúp các bài test uploader có thể mock hàm sleep để chạy tức thì mà không phải chờ wall-clock sleep thật.

---

## 2. Kết Quả Kiểm Thử Thực Tế

Lệnh kiểm thử quy chuẩn:
```sh
PYTHONPATH=. .venv-oracle/bin/pytest tests/test_server_evidence.py tests/test_event_delivery.py tests/test_edge_uploader.py tests/test_server_config.py tests/test_review_fixes.py -q
```

Kết quả:
```text
..................................................................    [100%]
66 passed, 73 warnings, 3 subtests passed in 15.30s
```

100% test case (66 passed) hoàn thành xuất sắc và không có lỗi hồi quy.
