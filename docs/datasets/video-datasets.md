# Sổ đăng ký Video Dataset và Ràng buộc ODD

**Cập nhật:** 2026-10-30 · **Nguyên tắc kiểm chứng:** Mọi phân loại trong sổ này đều phải dựa trên kết quả đọc trực tiếp luồng media (`ffprobe`, kiểm tra chuyển động nền toàn khung hình và đối chiếu nhãn độc lập), tuyệt đối không suy diễn từ tên thư mục hay lời giới thiệu của tập dữ liệu gốc. Toàn bộ tệp video nằm ngoài Git (`data/` đã được `.gitignore`); sổ này chỉ lưu đường dẫn chuẩn, độ phân giải, mục đích sử dụng và trạng thái hợp lệ ODD.

---

## 1. Quy tắc Ràng buộc ODD Bắt buộc (100% Fixed Traffic CCTV 720p–1080p)

Hệ thống AI Camera giao thông khóa chặt phạm vi thiết kế, tinh chỉnh tham số và nghiệm thu chất lượng (`G2`) trong miền điều kiện sau:
1. **Góc máy cố định hoàn toàn (Static Background CCTV):** Camera lắp cố định trên cột đèn, cầu vượt hoặc mặt tiền hướng ra lòng đường/vỉa hè đô thị. Nền khung hình phải đứng yên theo thời gian.
2. **Độ phân giải chuẩn HD đến Full HD:** Chiều cao khung hình từ **720p (`1280×720`) đến 1080p (`1920×1080`)**.

**Hai nhóm dữ liệu bị loại trừ vĩnh viễn khỏi nghiệm thu chất lượng ODD (`G2`) và tinh chỉnh ngưỡng (threshold tuning):**
- **Camera hành trình / camera di động / video zoom-reframing (Dashcam & Non-stationary Camera):** Chuyển động của bản thân camera tạo ra dịch chuyển hộp giới hạn toàn cục (ego-motion), phá vỡ giả định tọa độ ảnh tĩnh, làm sai lệch hoàn toàn vận tốc/gia tốc va chạm, thời gian đỗ xe (`dwell_seconds`) và độ phân tán đám đông.
- **Video độ phân giải thấp (`< 720p`, như CIF/360p/240p):** Mật độ điểm ảnh trên đối tượng quá thấp khiến detector và pose estimator suy giảm ngoài miền vận hành thực tế. *(Chỉ được phép dùng cho bài kiểm tra smoke/crash phần mềm nếu cần).*

---

## 2. Phân loại Thực tế Các Tập Video Cục bộ (Sau Kiểm định 2026-10-30)

Đợt kiểm tra chéo chuyển động nền và replay 17 clip ngày 2026-10-30 ([biên bản chi tiết](../logs/2026-10-30-pre-camera-dataset-replay.md)) đã đính chính toàn bộ các phân loại sai trước đây:

| Đường dẫn cục bộ (`data/...`) | Nguồn & Đặc tính kỹ thuật thực đo | Phân loại hợp lệ hiện tại | Giới hạn sử dụng bắt buộc |
|---|---|---|---|
| `data/benchmark/unidata/fall_0001.mp4` .. `fall_0005.mp4` | **UniDataPro Fall Detection** · `1920×1080 @ 30 FPS` (5 clip, trong nhà & ngoài trời, diễn tập ngã cố định góc máy) | **Supplemental Staged Person-down** *(Dữ liệu bổ trợ diễn tập)* | Dùng kiểm tra hồi quy nhánh `person_down` + `RTMPose` (xem [truy vết `fall_0005`](../logs/2026-10-30-fall-0005-anomaly-trace.md)); **không** thay thế CCTV giao thông thực địa |
| `data/benchmark/shibuya_crossing_1080p.mp4` | Wikimedia CC BY-SA 4.0 · `1920×1080` · **Có thao tác zoom quang học** trong clip | **Compute & Smoke Diagnostic Only** | Chỉ dùng đo thông lượng CPU/RAM trong `tools/run_benchmark.py`; **không** dùng nghiệm thu ODD |
| `data/benchmark/intersection_traffic_1080p.mp4` | Wikimedia CC BY-SA 4.0 · `1920×1080` · **Có bước nhảy khung hình/reframing** ở `0.4s→3.8s` (`503` RANSAC background inliers dịch chuyển trung vị `~290.4 px`) | **Compute & Smoke Diagnostic Only** | Chỉ dùng đo thông lượng CPU/RAM; **đã rút khỏi diện hard-negative CCTV cố định** |
| `data/traffic_cctv_hd/000001.mp4` .. `000010.mp4` | Trích từ tập `eys34/AccidentBench` · `1280×720 @ 30 FPS` (10 clip) · **Thực tế là video dashcam trên xe đang chạy**, từng bị đặt nhầm tên thư mục `traffic_cctv_hd` | **Retracted — Dashcam Diagnostic Only** | **Cấm** dùng làm bằng chứng Fixed CCTV ODD hoặc chỉnh ngưỡng `vehicle_incident`/`illegal_parking` |
| `data/research/A3D_2.0/`, `data/research/DAD/` | **A3D 2.0 & Dashcam Accident Dataset** · `1280×720` dashcam | **Out-of-ODD (Dashcam)** | Không dùng cho đánh giá hay tinh chỉnh pipeline CCTV cố định |
| `data/research/URFD/`, `UCF_Crime/`, `UCSD_Anomaly/` | `640×240`, `320×240`, `238×158` (`< 720p`) | **Out-of-ODD (Low Resolution)** | Chỉ dùng kiểm tra khả năng chịu tải I/O phần mềm nếu cần; loại khỏi mọi báo cáo chất lượng AI |

> **Kết luận trạng thái dữ liệu hiện tại:** Kho cục bộ hiện **chưa có** cohort CCTV giao thông cố định 720p–1080p có nhãn sự kiện độc lập đủ điều kiện để ký vượt cổng `G2`. Trước khi lắp camera thật, ưu tiên số 1 về dữ liệu là thu thập và xác minh nền tĩnh cho cohort CCTV giao thông thực sự dưới đây.

---

## 3. Nguồn Dataset Ứng viên Cho Cohort CCTV Giao thông Cố định Tiếp Theo

Các nguồn công khai dưới đây có góc quay camera giám sát nút giao/đường phố phù hợp để tuyển chọn vào cohort kiểm định `G2`. **Lưu ý bắt buộc:** Trước khi đưa bất kỳ clip nào từ các nguồn này vào manifest `G2`, phải chạy kiểm tra độ ổn định nền (loại bỏ các clip PTZ xoay, cắt cảnh biên tập hoặc dashcam trộn lẫn) và lập file nhãn sự kiện độc lập.

| Tập dữ liệu ứng viên | Đặc tính kỳ vọng | Nhóm tình huống mục tiêu | Yêu cầu kiểm tra khi nhập kho |
|---|---|---|---|
| **NVIDIA AI City Challenge (Track 4 — Traffic Anomaly)** | `1920×1080 @ 30 FPS`, camera giám sát cao tốc/nút giao dài hạn | `#47` Tai nạn/xe dừng bất thường, `#62` Đỗ xe sai quy định, `#28` Negative audit | Cắt theo phiên camera tĩnh liên tục, kiểm tra quyền sử dụng học thuật/nội bộ |
| **CADP (CCTV Traffic Accidents) / TAD / SO-TAD** | `720p–1080p`, tổng hợp clip camera giao thông nút giao | `#47` Tai nạn xe (`vehicle_incident`), `#25/#26` Người văng/nằm trên lòng đường | Bắt buộc lọc từng clip vì nguồn tổng hợp YouTube thường trộn lẫn clip cắt cảnh, chữ chèn hoặc camera cầm tay |
| **ShanghaiTech Campus Surveillance** | `1280×720` / `1920×1080`, camera cố định ngoài trời khuôn viên/lối đi | `#57` Xâm nhập vùng nguy hiểm, `#63` Đám đông tụ tập / di chuyển bất thường | Kiểm tra chiều cao pixel người và ánh xạ vùng ROI thực tế |
| **Footage trích xuất từ chính Camera CCTV mục tiêu (Pilot Site)** | `720p–1080p` đúng codec/bitrate/góc lắp thực địa | Toàn bộ 5 module đang bật + đánh giá false alerts/camera-day | Phê duyệt quyền riêng tư dữ liệu site và gán nhãn độc lập hai vòng |

---

## 4. Quy trình và Công cụ Đánh giá Replay Chuẩn ([ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md))

Ba công cụ đánh giá dưới đây đều chạy trực tiếp qua `PerceptionPipeline.process_frame` và `apps/edge/snapshot.py`, xuất báo cáo kèm cấu hình hiệu lực (`effective_config`) và trạng thái chất lượng khung hình:

1. **Đánh giá baseline `person_down` + `RTMPose` trên một hoặc nhiều clip:**
   ```sh
   .venv-oracle/bin/python tools/eval_clip.py data/benchmark/unidata/fall_0001.mp4 --sample-fps 10 --json
   ```
2. **Đánh giá chuyên biệt nhánh sự cố phương tiện (`vehicle_incident`):**
   ```sh
   .venv-oracle/bin/python tools/eval_vehicle.py <fixed_cctv_clip.mp4> --sample-fps 10 --json
   ```
3. **Đánh giá đồng thời đa nhóm kịch bản (`person_down`, `vehicle_incident`, `illegal_parking`, `crowd_incident`, tuỳ chọn `danger_zone` qua ROI):**
   ```sh
   .venv-oracle/bin/python tools/eval_all_scenarios.py <fixed_cctv_clip.mp4> --sample-fps 10 --json
   ```

**Nguyên tắc đọc kết quả Replay:**
- Kết quả của `tools/eval_*.py` trên video chưa có nhãn độc lập chỉ là **đầu mối kiểm tra kỹ thuật (review leads)**, tuyệt đối không coi `0 events` là `0 false negatives` hay coi sự kiện máy phát ra là ground truth.
- Mọi thay đổi ngưỡng phát hiện phải chứng minh đồng thời trên cả clip dương tính và tập đối chứng âm tính (hard negatives) đã khóa hash.
