# Sửa hai lỗi review branch edge/G1

Ngày: 2026-11-08. Branch: `fix/03-edge-config-g1-live`, HEAD trước sửa: `524082a`.

## Phạm vi và quyết định

- Người dùng yêu cầu `fix all` cho hai findings P1/P2 của review branch.
- P1: `EvidenceLifecycle` dùng khóa `.evidence-upload.lock` để tuần tự hóa các uploader giữa thread/process. Khóa `.evidence-worker.lock` chỉ giữ trong bước chuẩn bị/kiểm tra artifact và cập nhật ACK/lỗi; không giữ trong HTTP transfer/retry. Pin hiện có tiếp tục bảo vệ artifact cho tới ACK. `upload_pending(reconcile=True)` gọi public `reconcile()` để giữ khóa state đúng cách.
- P2: `tools/rtsp_session_probe.py` dùng `ThreadPoolExecutor`, mỗi phiên sở hữu một `Popen` và gọi `communicate()` ngay trong worker. Các pipe stdout/stderr được drain đồng thời; timeout vẫn kill và drain tiến trình, report vẫn giữ thứ tự phiên và che URL.
- Không thêm dependency. Giữ các thay đổi UI, `.codegraph/.gitignore`, `.omp/` và tài liệu chưa commit có sẵn.
- Nghiên cứu trước triển khai: thư viện chuẩn Python [Popen.communicate](https://docs.python.org/3.12/library/subprocess.html#subprocess.Popen.communicate) và [ThreadPoolExecutor](https://docs.python.org/3.12/library/concurrent.futures.html#threadpoolexecutor). Dùng cơ chế drain pipe/timeout chuẩn thay vì tự viết event loop.

## Đường kiểm chứng và kết quả

- Regression upload: chặn transport bằng `threading.Event`, kiểm tra event mới vẫn persist và reconcile được trước khi thả mạng, artifact vẫn tồn tại và chưa ACK. Chạy cả API upload một request và batch; sau khi thả mạng phải ACK thành công.
- Regression hai coordinator: cùng kho recorder/outbox, upload batch và upload một request chỉ gọi transport một lần.
- Regression probe: barrier yêu cầu hai phiên cùng vào `communicate()`, kiểm tra report/redaction; test riêng timeout xác nhận kill và drain.
- Chạy regression với mã HEAD cũ trong bộ nhớ, không đổi file: lỗi timeout ở cả hai chế độ upload và `BrokenBarrierError` ở probe như dự kiến.
- Kiểm thử hẹp: `.venv-oracle/bin/python -m pytest -q tests/test_edge_uploader.py tests/test_rtsp_session_probe.py tests/test_evidence_lifecycle.py tests/test_architecture_deepening.py`: **44 passed, 10 subtests passed**.
- Kiểu tĩnh: `.venv-oracle/bin/python -m mypy domain/ apps/ tools/ run_edge.py`: **75 source files**, exit 0.
- Smoke pipe thật: thay nguồn camera bằng ba Python subprocess (k=1 rồi k=2), mỗi process ghi 105000 byte stdout và 165000 byte stderr. Hai producer k=2 chỉ thoát khi cả hai đã flush output. Cả ba phiên đạt `ok=true`, không đầy pipe gây chặn.
- Toàn bộ suite: `.venv-oracle/bin/python -m pytest -q`: **909 passed, 360 warnings, 190 subtests passed**, exit 0, 159.80s.
- `git diff --check` trong phạm vi các file sửa của task: sạch. Kiểm tra toàn working tree phát hiện trailing whitespace ở UI đang được sửa ngoài task (`apps/server/static/index.html:922`); không sửa phần đó.

## Giới hạn

- Chưa chạy lại camera thật, X19 trên LAN hoặc nghiệm thu production.
- HTTP transfer đang chạy vẫn tuân theo timeout/retry hiện có; không bổ sung force-cancel hoặc flush khi shutdown. Pin/ACK/crash recovery tiếp tục dùng cơ chế hiện có.

## Commit, push và merge

- Người dùng yêu cầu commit, push và merge sau khi kiểm chứng.
- Chỉ stage hai file runtime/tool, hai file regression test và log này; giữ nguyên mọi thay đổi ngoài task.
- `git fetch origin` xác nhận `origin/master` vẫn ở `5060908` và là tổ tiên của branch; chọn merge fast-forward để giữ nguyên ba commit của branch.
- GitHub CLI trả HTTP 401 nên không tạo/merge PR qua API; thực hiện push branch và cập nhật `master` qua Git SSH. Không dùng force push hoặc bỏ qua branch protection; nếu remote từ chối thì dừng cập nhật nhánh đích.
- Kết quả push/ref cụ thể được xác nhận bằng `git ls-remote` và báo trong phiên thực thi.
