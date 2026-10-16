# Cập nhật research theo implementation — 2026-10-15

## Phạm vi và thao tác

Yêu cầu: cập nhật nghiên cứu từ kết quả thử nghiệm/implementation hiện có, đánh giá quyết định tiếp theo và phản biện lựa chọn chưa hợp lý. Áp dụng skill research; dùng khung implementation/evidence/gaps/tradeoffs/acceptance, hỏi tùy chọn phạm vi và thời gian nguồn. Chưa có trả lời trong lúc làm: dùng tiêu chí repo, ưu tiên nguồn chính thức từ2024 và nguồn nền tảng cũ cần thiết. Cấu hình outline execution là mặc định chưa được user xác nhận, không khởi động deep research.

- Đọc hướng dẫn domain/tracker, research hiện có, readiness/lab profile, PRD, README và log triển khai/review12–15-10.
- CodeGraph files/context/explore xác định pipeline/tracker/incident/live; đọc đoạn nguồn đã xác định để kiểm tra pose→incident và heuristic thực tế.
- Ghi commit nền `6fff369f4c30dd6faff0150b660cf5e065207daa`; kiểm tra status trước sửa, giữ nguyên toàn bộ file untracked có sẵn.
- Một web researcher không khởi chạy được do model provider không hỗ trợ; agent mặc định thay thế hoàn thành bổ sung nguồn, không sửa file. Truy xuất trực tiếp thêm ORT/FFmpeg/SQLite.
- Probe read-only `.venv-oracle/bin/python -c 'import sqlite3; print(sqlite3.sqlite_version)'` →3.45.1. Distro backport chưa kiểm tra.
- Sandbox shell lỗi `bwrap: loopback: Failed RTM_NEWADDR`; các lệnh đọc/kiểm tra dùng escalation, không thay cấu hình sandbox.

## Kết luận và quyết định biên tập

- Research report §14 là đánh giá hiện trạng mới; phần giá/hardware lịch sử giữ nguyên mốc, không làm mới quote/clearance.
- Runtime Python/ORT/FFmpeg tách khỏi thiết kế native C++; pose có estimator/scheduler nhưng outcomes chưa tham gia IncidentEngine. Tracker constant-velocity prediction không gọi là full Kalman/reference ByteTrack.
- 409 passed là kết quả log, replay synthetic là metadata callback/memory envelope theo snapshot cũ; không tạo claim benchmark mới/G1/G2/G3/pilot.
- Đề xuất mở lại thứ tự native sau profiling, A/B rule/pose/FPS, kiểm tra ODD/PTS/camera,413/bitrate, SQLite patch và pin concurrency. Chưa thay quyết định accepted/ADR/contracts.
- Ghi tracker lệch giữa đoạn frontier và bảng #08, cùng tên native #13 so implementation Python; không tự đóng/mở ticket hoặc đổi Execution.
- Cập nhật report, research README/outline/fields/sources và docs index. Dùng lại outline/fields hiện có, không sinh thư mục research/backlog thứ hai.

## Kiểm tra và giới hạn

Kiểm tra whitespace diff, YAML và relative file links cho tài liệu thay đổi; kết quả ghi cuối log sau khi chạy. Không chạy suite/benchmark, camera/browser/board, power-cut, deploy hoặc refresh giá/pháp lý. Không sửa runtime, tests, cấu hình chạy, ADR hoặc ticket Execution. Chưa commit/push.

- `git diff --check`: pass.
- Python hệ thống + PyYAML:2 YAML parse thành mapping;51 relative file links tồn tại. Không kiểm tra anchor Markdown hoặc toàn bộ URL lịch sử.
- `.venv-oracle` thiếu PyYAML nên lần kiểm tra đầu dừng ở import; dùng Python hệ thống sẵn có, không cài dependency.
- Parse JSONL lưu sẵn:12 records,12 callback trước EOF; first callback0,079467–0,104759s; Python RSS21.320–22.316KiB, simultaneous RSS71.996–74.712KiB. Đây là tổng hợp artifact cũ, không chạy lại replay.
