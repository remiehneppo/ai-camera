# Báo cáo thực thi Lát G1 trên Camera Thật và Đo Trễ X19

Ngày: 2026-11-01
Git HEAD: `5060908ab513dad78b367d0fbda584a115466f49`
Mục tiêu: Ticket #03 (fail-fast config module x camera), Ticket #15 (RTSP ring recorder), Ticket #19 (Lát G1 khả thi).

---

## 1. Môi trường & Thiết lập

- **Edge Runtime**: Linux x86_64, Python 3.12 (`.venv-oracle`), FFmpeg 6.1.1, Playwright 1.64.1 (Firefox 157.0).
- **Server Lab HTTPS**:
  - URL: `https://127.0.0.1:8443` (hỗ trợ SAN `127.0.0.1` và `192.168.1.190`).
  - Chứng chỉ: `/tmp/lab-cert.pem`, khóa riêng `/tmp/lab-key.pem`.
  - Database: MongoDB `192.168.96.2:27017` replica set `rs0`, database `camera_lab_g1_20261101`.
  - Auth: `DEVICE_TOKENS` gắn `fixture-device-token: lab-edge-01`, `DASHBOARD_TOKEN=fixture-dashboard-token`.
- **Camera Lab RTSP**:
  - Target: IP camera cố định trên mạng lab (H.264 1920x1080 @ 15.0 fps).
  - Cấu hình an toàn: URL stream chứa thông tin xác thực được quản lý qua `load_rtsp_config()`, che giấu (redacted) trong toàn bộ log và report.

---

## 2. Kết quả Probe phiên RTSP & Quyết định Kiến trúc (Bước 6–7)

- Lệnh probe:
  ```sh
  .venv-oracle/bin/python -m tools.rtsp_session_probe --output data/benchmark/rtsp-probe-20261101.json --duration 20 --max-sessions 3
  ```
- Kết quả đo lường (`data/benchmark/rtsp-probe-20261101.json`):
  - `k=1`: 301 packets / 300 expected (100.3%), exit_code = 0, `ok: true`.
  - `k=2`: 2 phiên đồng thời, mỗi phiên 301 packets / 300 expected, exit_code = 0, `ok: true`.
  - `k=3`: 3 phiên đồng thời, mỗi phiên 301 packets / 300 expected, exit_code = 0, `ok: true`.
- Quyết định kiến trúc ([ADR-0007](../adr/0007-rtsp-stream-ownership.md)):
  - Chọn **dual-session**: `RtspRingRecorder` (ffmpeg stream-copy) và `LivePerceptionRunner` (`cv2.VideoCapture`) mở 2 phiên TCP upstream độc lập lên camera.
  - Không cần xây dựng module relay trung gian; không chia sẻ frame ID, ánh xạ thời gian thuần túy qua event-time và `time_uncertainty`.

---

## 3. Kết quả Đo Trễ X19 (Bước 9)

- Lệnh thực thi:
  ```sh
  DEVICE_TOKEN=fixture-device-token DASHBOARD_TOKEN=fixture-dashboard-token SSL_CERT_FILE=/tmp/lab-cert.pem \
    .venv-oracle/bin/python -m tools.g1_latency --server-url https://127.0.0.1:8443 \
    --events 50 --interval 2.0 --output data/benchmark/g1-x19-20261101.json
  ```
- Kết quả đo (`data/benchmark/g1-x19-20261101.json`):
  - Số lượng event: 50 gửi, 50 render thành công trên DOM dashboard (`article.event`).
  - Số event thất lạc (`missing_event_ids`): 0.
  - **Độ trễ (edge durable commit -> dashboard DOM render)**:
    - Mean: **1.310s**
    - P50: **1.286s**
    - P90: **2.305s**
    - **P95: 2.325s** (Mục tiêu: $\le 5.0s$ $\rightarrow$ **ĐẠT**)
    - Max: **2.380s**
  - Cơ sở đồng hồ: Single host (`time.time()` trên edge và `Date.now()` trong Firefox cùng máy), độ bất định $\approx 17$ms.
  - Trạng thái của lần đo: **PASS trên loopback** (`pass: true`), không phải nghiệm thu X19 trên LAN. Lần đo dùng UI đang sửa trong working tree, không chứng minh harness chạy với dashboard đã commit; xem kiểm tra tương thích ở mục 7.

---

## 4. Kiểm chứng Chạy Live trên Camera Thật (Bước 8)

- Lệnh thực thi:
  ```sh
  SERVER_URL=https://127.0.0.1:8443 DEVICE_TOKEN=fixture-device-token SSL_CERT_FILE=/tmp/lab-cert.pem \
    .venv-oracle/bin/python run_edge.py --module-config infra/edge-modules.lab.json \
    --root data/edge-live-20261101 --status-log data/edge-live-20261101/status.jsonl
  ```
- Dòng startup JSON xác nhận fail-fast vượt qua kiểm tra:
  ```json
  {"scope": "startup", "status": "ok", "camera_id": "lab-camera-01", "session_id": "efd0a888-1655-45ab-8e5b-a5ff0c84dfed", "analytics_enabled": true, "disabled_reason": null, "modules": [{"module": "danger_zone", "factory": "danger_zone", "perception_profile": "danger_zone"}, {"module": "person_down", "factory": "person_down", "perception_profile": "person_down"}], "disabled_modules": []}
  ```
- Tiến trình chạy thời gian thực:
  - `status.jsonl` ghi nhận `core_epoch=1`, `health.capabilities.analytics="active"`, `health.capabilities.backend="reachable"`, `health.capabilities.camera="active"`.
  - Đã xử lý 56 frames thời gian thực trong phiên khói 30 giây.
  - Ring buffer recorder lưu thành công 4 segments stream-copy thực tế từ camera tại `data/edge-live-20261101/ring/efd0a888-1655-45ab-8e5b-a5ff0c84dfed/`:
    - `segment-00000.mkv` (551.97 KB, codec: h264, frame_interval: 0.067s ~ 15fps)
    - `segment-00001.mkv` (507.37 KB, codec: h264, frame_interval: 0.067s ~ 15fps)
    - `segment-00002.mkv` (557.16 KB, codec: h264, frame_interval: 0.067s ~ 15fps)
    - `segment-00003.mkv` (372.23 KB, codec: h264, frame_interval: 0.067s ~ 15fps)
    Tổng dung lượng stream-copy: 1.97 MB; mỗi segment đều đi kèm file metadata JSON chuẩn.
- **Phần chưa chạy (Pending physical human operator)**:
  - Thao tác người đi vào góc máy tại phút thứ 3 và thứ 7, cùng thao tác rút cáp mạng camera tại phút thứ 5 cần có sự hiện diện vật lý của operator trong phòng lab.
  - Hành vi disconnect/reconnect và tăng `core_epoch` chính xác 1 lần đã được chứng minh tự động qua test suite regression: `tests/test_live_pipeline.py::TestLivePipelineP0P1Improvements::test_session_id_invariant_across_disconnect_fallback_and_reconnect` và `test_reconnect_increments_core_epoch_exactly_once_no_double_increment`.
  - Vé #15 và #19 **không** đánh dấu done; giữ trạng thái partial/in-progress cho tới khi operator vật lý hoàn thành kịch bản tại chỗ.

## 5. Sửa các mục review — 2026-11-02

Phạm vi T1: ba mục của review gần nhất; không sửa UI có sẵn, hợp đồng event hay quyết định kiến trúc.

- `MetadataDeliveryWorker.stop()`: cảnh báo khi hết thời gian join mà thread vẫn sống; giữ tham chiếu để `start()` không tạo worker delivery thứ hai. Chỉ xóa tham chiếu khi thread đã thoát và vẫn là thread đang được quản lý. Không ép hủy callback hoặc flush outbox khi dừng.
- `run_edge.py`: dùng `ExitStack` quản lý một file handle cho `--status-log` và runner; đóng tài nguyên khi thoát hoặc có exception. Ghi status đầu tiên sau khi runner khởi động, flush từng dòng để tiến trình khác đọc được ngay. Flush không có nghĩa là fsync hoặc khóa file; không thay đổi chính sách độ bền của status log.
- `tools/g1_latency.py`: lấy phiên bản bằng `importlib.metadata.version("playwright")`, bỏ fallback do đọc thuộc tính `playwright.__version__` không tồn tại. Không thêm dependency, không sửa artifact đo X19 cũ.

Kiểm chứng trong lần sửa này:

- Regression `test_stop_timeout_keeps_worker_owned_until_delivery_returns`: trước sửa thất bại vì không có warning; sau sửa kiểm tra timeout, giữ thread, không tạo thread mới khi delivery còn chặn, join lại và restart thành công. Đồng bộ bằng `threading.Event`, không chờ bằng sleep.
- `.venv-oracle/bin/python -m pytest -q tests/test_live_pipeline.py tests/test_run_edge_startup.py`: exit 0, **31 passed**.
- `.venv-oracle/bin/python -m mypy domain/ apps/ tools/ run_edge.py`: exit 0, **75 source files**, không có lỗi.
- `.venv-oracle/bin/python -m pytest -q`: exit 0, **905 passed, 360 warnings, 188 subtests passed**, 152.64s; không có test skipped trong summary.
- Smoke CLI với video `testsrc2` H.264 1280×720, file/root/status log tạm; lệnh `run_edge.py --source file --file <temporary-video> --module-config infra/edge-modules.lab.json --root <temporary-root> --status-log <temporary-status>`. Đọc được hai dòng status trước khi dừng, dòng đầu `status=running`, dòng sau `frames_processed=16`; gửi SIGTERM, tiến trình thoát 0. File tạm được dọn sau smoke.
- `.venv-oracle/bin/python -c 'from tools.g1_latency import version; print(version("playwright"))'`: exit 0, **1.64.1**.

Không chạy lại camera, rút cáp, browser X19 hoặc phép đo LAN. Callback delivery đang bị chặn vẫn phải tự trả về; timeout chỉ cảnh báo và giữ quyền quản lý thread, không bảo đảm callback đã kết thúc.

## 6. Commit và push — 2026-11-02

- Người dùng yêu cầu commit và push các thay đổi của phiên. Tạo nhánh `fix/03-edge-config-g1-live` từ `master`; giữ nguyên `origin` đã cấu hình, không push trực tiếp vào `master`.
- Commit runtime: `1b8ad08` — `fix(edge): validate live config and deliver metadata asynchronously`. Công cụ probe/X19 và tài liệu đi trong commit riêng.
- Không stage `.omp/`, thay đổi UI trong `apps/server/static/index.html`, log UI hoặc dữ liệu camera trong `data/`. Kết quả trước sửa tương thích UI ở mục 5; mã harness được sửa tiếp theo mục 7 trước khi công bố.

## 7. Sửa phụ thuộc vào UI chưa commit — 2026-11-02

- Kiểm tra `git show HEAD:apps/server/static/index.html` xác nhận dashboard đã commit khởi tạo token rỗng, nhận token qua nút `#auth` và `window.prompt`; không đọc sessionStorage, không có `#filter-limit`. Cách chèn token qua sessionStorage của harness cũ chỉ chạy với UI redesign bị loại khỏi commit.
- `tools/g1_latency.py` trả lời prompt từ thao tác `#auth`, chờ response GET `/v1/events` thành công trước khi gửi events; token sai gây lỗi xác thực. Chỉ chọn limit 100 khi trang có control đó. Dùng context manager cho browser để luôn đóng cả khi xác thực thất bại; kiểm tra âm ban đầu phát hiện lỗi teardown event loop khi browser không được đóng, đã sửa trước khi chạy lại.
- Smoke tạm `.venv-oracle/bin/python /tmp/g1-committed-ui-smoke.py`: phục vụ nguyên HTML lấy từ `HEAD` qua FastAPI thật trên cổng loopback tạm, dùng Mongo replica set với database test tên riêng; kiểm tra SHA-256 nội dung trang trước khi chạy Firefox. Không sửa hoặc stage UI redesign.
- Kết quả smoke: exit 0; dashboard SHA-256 `a82d6e3a0fe6796643bf737813e509174f5bb239830075cade376c41710ddd2d`; token sai bị từ chối; token đúng có **3/3 events rendered**, P95 **1.189s**, phiên bản Playwright **1.64.1**. Artifact cục bộ: `data/benchmark/g1-x19-committed-ui-20261102.json`.
- Database test được xóa, backend dừng và thư mục tạm được dọn. Đây là kiểm tra tương thích 3 mẫu trên loopback HTTP, không thay thế nghiệm thu X19 50 mẫu trên LAN hoặc kịch bản camera/operator. Không giữ smoke script như test suite browser mới vì repo chưa có gate cài Firefox; kiểm chứng chạy thật và giới hạn được ghi tại đây.
- `.venv-oracle/bin/python -m mypy domain/ apps/ tools/ run_edge.py`: exit 0, **75 source files**, không có lỗi sau sửa xác thực.
- `.venv-oracle/bin/python -m pytest -q` sau sửa tương thích dashboard: exit 0, **905 passed, 360 warnings, 188 subtests passed**, 151.43s.
