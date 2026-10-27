# Cập nhật Ràng buộc ODD & Bộ Dataset Camera Giao thông Cố định (HD 720p - 2MP 1080p) — 2026-10-27

Thực hiện theo chỉ đạo của người dùng:
1. **Khóa vĩnh viễn quy tắc ODD**: Tuyệt đối **không dùng camera hành trình (dashcam)** và **camera độ nét thấp (< 720p)**. Chỉ sử dụng video từ **camera giao thông cố định (Fixed CCTV)** có độ nét từ **HD (720p)** đến **2MP (Full HD 1080p)**.
2. **Xây dựng công cụ tải & kiểm định dữ liệu**: `tools/fetch_traffic_cctv_dataset.py` tự động tải và kiểm tra chất lượng (ffprobe $\ge 1280\times 720$, tính hash SHA-256) các clip tai nạn giao thông từ camera CCTV tĩnh (`Open-Space-Reasoning/AccidentBench`).
3. **Nâng cấp bộ công cụ đánh giá đa tình huống**: `tools/eval_all_scenarios.py` chạy toàn diện trên 10 clip đạt chuẩn ODD 100% camera tĩnh (1080p UniDataPro, 1080p Shibuya, 1080p Pie-IX, và 720p Fixed CCTV Accidents).

## 1. Ràng buộc ODD và Lý do Kỹ thuật
- **Loại bỏ Dashcam (như DAD_A3D)**: Camera di chuyển theo xe (40–80 km/h) gây ra luồng chuyển động biểu kiến (ego-motion), làm sai lệch toàn bộ vector vận tốc tương đối và gia tốc của vật thể tĩnh ven đường, vi phạm nguyên lý thiết kế camera tĩnh của Edge Pipeline.
- **Loại bỏ video độ nét thấp (< 720p)**: Các video 240p/320×240 (UCF-Crime) hoặc 238×158 (UCSD) làm mờ nát bounding box, detector YOLOX bỏ sót hoặc nhảy giật kích thước khung hình, sinh gia tốc va chạm ảo.
- **Tiêu chuẩn ODD áp dụng**: Camera CCTV cố định góc cao, gắn trên cột đèn/ngã tư/cầu vượt, độ phân giải $\ge 1280\times 720$ (HD) đến $1920\times 1080$ (2MP).

## 2. Công cụ `tools/fetch_traffic_cctv_dataset.py`
- Tải về và xác thực danh mục clip camera tĩnh từ Hugging Face (`Open-Space-Reasoning/AccidentBench`):
  - Tự động kiểm tra độ phân giải qua `ffprobe`, ném lỗi nếu độ phân giải $< 1280\times 720$.
  - Tính toán SHA-256 hash và tạo tệp manifest `data/benchmark/traffic_cctv_hd/manifest.json`.
  - Media tải về nằm trong `data/benchmark/traffic_cctv_hd/` (tuân thủ quy tắc gitignored, không commit file video lớn vào git).

## 3. Kết quả Chạy Benchmark Đa Tình huống (`tools/eval_all_scenarios.py`)
Chạy trên 10 video clips đạt chuẩn ODD 100% camera tĩnh:
- **fall_0001.mp4 (1080p @ 30fps)**: Bắt chính xác 2 sự kiện `person_lying_persistent` (t=14.6s) và `person_fall` (t=14.7s), 0 báo động sai sang các engine khác.
- **fall_0003.mp4 (1080p @ 30fps)**: Đối chứng âm người sinh hoạt bình thường $\rightarrow$ **0 sự kiện (Clean)**.
- **intersection_traffic_1080p.mp4 (1080p @ 30fps)**: Đối chứng âm giao thông ngã tư bình thường $\rightarrow$ **0 sự kiện (Clean)**.
- **000001.mp4 đến 000005.mp4 (1280×720 @ 10fps Fixed CCTV)**: Phát hiện chính xác các vụ va chạm xe–xe (`vehicle_vehicle`) và lật xe/đâm dải phân cách (`vehicle_rollover_or_barrier`) kèm mốc thời gian và ID xe va chạm cụ thể.
- **000006.mp4 (1280×720 @ 10fps Fixed CCTV)**: Phương tiện di chuyển chậm bình thường $\rightarrow$ **0 sự kiện (Clean)**.

## 4. Bằng chứng kiểm thử & Chất lượng mã nguồn
- `mypy tools/fetch_traffic_cctv_dataset.py tools/eval_all_scenarios.py` ⇒ **Success: no issues found in 2 source files**.
- Toàn bộ Test Suite toàn dự án: `pytest -q` ⇒ **823 passed, 360 warnings, 126 subtests passed in 148.68s**.
