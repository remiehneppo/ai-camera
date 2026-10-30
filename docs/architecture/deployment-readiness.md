# Hồ sơ sẵn sàng triển khai (Deployment Readiness)

**Cập nhật:** 2026-10-30 · **Trạng thái:** Hồ sơ kiểm soát điều kiện trước pilot và sản xuất. Bản tham chiếu phần mềm trong lab đã hoàn thiện logic cho 5 nhóm cảnh báo (`896` tests / `188` subtests / `72` files `mypy`), nhưng **chưa có phần cứng nhúng đích hoặc dữ liệu thực địa để ký nghiệm thu capacity (`G3`) hay field readiness (`G4–G5`)**.

Tài liệu liên quan: [Kiến trúc hệ thống](system-architecture.md) · [Hợp đồng tích hợp](contracts.md) · [Kế hoạch triển khai](implementation-plan.md) · [Hồ sơ lab](lab-profile.md) · [Checklist tích hợp & G0–G5](../implementation-checklists/integration-release.md).

---

## 1. Phân ranh vai trò nghiệm thu

Mọi giá trị `TBD`, `null` hoặc `REQUIRED` trong hồ sơ site là dữ liệu còn thiếu, tuyệt đối không coi là đã đạt. Trước pilot phải gán định danh người chịu trách nhiệm thực tế cho từng vai trò:

| Vai trò | Phạm vi chịu trách nhiệm | Đầu ra bắt buộc trước Pilot (`G4a`) |
|---|---|---|
| **Product / Operations Owner** | Ký phạm vi use case, ngưỡng cảnh báo, năng lực ca trực review và nghiệm thu thực địa | Chữ ký phê duyệt site profile, SLO sơ bộ và ngân sách phút review/camera-ngày |
| **Edge / Platform Lead** | Khóa SKU camera & board nhúng, stream ownership, đồng bộ thời gian, quota đĩa và bảo mật thiết bị | Báo cáo `G1` (live RTSP + crash/pin) và `G3` (soak 24–72h trên thiết bị đích) |
| **ML / Evaluation Owner** | Quản lý artifact mô hình, hiệu chuẩn hình học/ROI, tập kiểm định CCTV cố định và negative audit | Báo cáo `G2` trên tập CCTV cố định held-out có nhãn độc lập + hồ sơ bản quyền weights |
| **Backend / QA Lead** | Độ bền lưu trữ event/evidence, quy trình khôi phục thảm họa, storm guard và kiểm thử lỗi xuyên module | Biên bản vượt ma trận lỗi `X01–X45` trong [integration-release.md](../implementation-checklists/integration-release.md) |

---

## 2. Mẫu hồ sơ điểm lắp đặt tối thiểu (Site Profile Template)

Thông số đầu vào mặc định đang áp dụng trong software lab: **pre-roll 10 giây**, **post-roll 20 giây**, **event ring 10 phút**, **server giữ clip 7 ngày**, **ngân sách tự chủ mất WAN 24 giờ cho clip chưa ACK**. Các con số này là tham số thiết kế ban đầu; khi ra site phải đo bitrate thực, tần suất sự kiện và tốc độ đường truyền để chốt quota đĩa. Không đưa mật khẩu hoặc RTSP URI chứa thông tin xác thực vào hồ sơ.

```yaml
site:
  id: REQUIRED
  facts_sheet_ref: REQUIRED
  physical_diagram_ref: REQUIRED
  privacy_approval_ref: REQUIRED
camera:
  id: REQUIRED
  sku_firmware: REQUIRED
  mount_type: fixed_traffic_cctv # Bắt buộc cố định; loại trừ dashcam/PTZ quét liên tục
  resolution_profile: REQUIRED   # Bắt buộc trong dải 1280x720 .. 1920x1080
  main_stream_profile_ref: REQUIRED
  sub_stream_profile_ref: REQUIRED # Hoặc ghi rõ unsupported
  verified_concurrent_sessions: null
  stream_ownership_adr: REQUIRED
odd:
  profile_ref: REQUIRED # Chiều cao pixel người tối thiểu, ánh sáng/thời tiết, vùng che khuất/ROI
workload:
  enabled_alert_modules: ["person_down"] # Các module mở rộng phải có G4b riêng
  camera_count_per_edge: null
  analysis_fps_per_camera: null
  pose_mean_roi_per_second: null
  pose_burst_roi_per_second: null
evidence:
  mode: event_ring
  pre_roll_seconds: 10
  post_roll_seconds: 20
  ring_minutes: 10
  pinned_retention_policy_ref: REQUIRED
  quota_and_reserve_ref: REQUIRED
network:
  measured_uplink_mbps: null
  expected_maximum_outage_hours: 24
acceptance:
  preliminary_slo_ref: REQUIRED
  capacity_report_ref: REQUIRED
  field_acceptance_ref: REQUIRED
  approved_by: null
  approved_at: null
```

---

## 3. Quy tắc tính dung lượng Evidence, SQLite và Phục hồi sau mất WAN

1. **Bao phủ khoảng thời gian yêu cầu (`contracts.md §3`):** Với ring 10 phút, hệ thống phải đảm bảo tổng độ trễ từ mốc neo (`evidence_anchor_time`) đến lúc ghim segment (`verification + scheduling + crash recovery + pre_roll 10s + keyframe margin`) nằm trong 10 phút. Nếu vượt ngân sách, hệ thống báo `partial` hoặc `missing` trung thực; không đánh dấu `complete` chỉ vì xuất được file video.
2. **Công thức giải tỏa hàng đợi sau mất WAN (`contracts.md §10`):** Gọi $B$ là dung lượng backlog tồn đọng, $U$ là băng thông tải lên hữu dụng dành cho đồng bộ bù (đã trừ băng thông sự kiện mới) và $G$ là tốc độ phát sinh bằng chứng mới. Nếu $U \le G$, hàng đợi không thể tự thoát (`recovery_impossible`); nếu $U > G$, thời gian giải tỏa ước tính là $T = B / (U - G)$. Ngân sách mất WAN 24 giờ **không** phải là TTL để xóa dữ liệu chưa được Server ACK.
3. **Độ bền SQLite và xử lý lỗi tải lên quá cỡ (`HTTP 413`):**
   - Outbox và manifest evidence tại Edge chạy SQLite `journal_mode=WAL`, `synchronous=FULL`. `apps/edge/doctor.py` kiểm tra phiên bản SQLite runtime để cảnh báo rủi ro WAL-reset trên các bản `< 3.51.3` chưa xác minh bản vá distro ([chi tiết](../logs/2026-10-17-sqlite-upload.md)).
   - Khi Server trả `HTTP 413` (clip vượt trần dung lượng upload), Edge phân loại là `operational_fault`, ngừng retry vô ích, giữ nguyên file pin cục bộ ở trạng thái `failed` và không giải phóng clip dù metadata sự kiện đã được ACK.
4. **Giới hạn của số đo hiệu năng trong Lab hiện tại:**
   - Trên máy trạm CPU x86 (`Intel Core i5-12400F`, ONNX Runtime CPU), pipeline chuẩn đạt **16.35–20.10 FPS** (Baseline `YOLOX-Tiny` + `ByteTrack`) và **8.84–15.88 FPS** khi bật thêm `RTMPose-Tiny` trên luồng 1080p chẩn đoán ([báo cáo chi tiết](../reports/2026-10-21-pipeline-benchmark-report.md)).
   - Các clip từng dùng để thử tải và kiểm tra hồi quy phần mềm (`shibuya_crossing_1080p.mp4`, `intersection_traffic_1080p.mp4`, và các clip dashcam gán nhầm nhãn cũ) **đã được rút khỏi diện bằng chứng chất lượng ODD** theo [đợt kiểm định 2026-10-30](../logs/2026-10-30-pre-camera-dataset-replay.md). Không dùng số FPS trên CPU x86 hoặc kết quả trên clip chẩn đoán làm bằng chứng vượt `G2` hay `G3`.

---

## 4. Mẫu Manifest Benchmark Phần cứng Đích (`G3`)

Mọi trường chưa đo thực tế trên thiết bị đích phải giữ `null` kèm lý do trong `missing_measurements`.

```json
{
  "device_profile_hash": null,
  "camera_profiles_hash": null,
  "model_artifact_hash": null,
  "config_snapshot_hash": null,
  "dataset_manifest_hash": null,
  "duration_hours": null,
  "workload": {
    "camera_count": null,
    "enabled_modules": ["person_down"],
    "analysis_fps_per_camera": null,
    "pose_mean_roi_per_second": null,
    "pose_burst_roi_per_second": null,
    "recording_and_upload_profile_ref": null
  },
  "clock_basis": null,
  "results": {
    "frame_age_p95_ms": null,
    "frame_age_p99_ms": null,
    "event_latency_p95_ms": null,
    "event_latency_p99_ms": null,
    "recorder_gap_seconds": null,
    "evidence_completeness_ratio": null,
    "fsync_p99_ms": null,
    "max_wal_bytes": null,
    "peak_outbox_bytes": null,
    "max_temperature_c": null,
    "sustained_power_watts": null,
    "resource_timeseries_ref": null,
    "event_quality_report_ref": null
  },
  "missing_measurements": ["Template only; target hardware SKU not yet selected"],
  "accepted_capacity": null,
  "approval_ref": null
}
```

---

## 5. Sổ đăng ký rủi ro trước Pilot

| Rủi ro | Mức ưu tiên | Dấu hiệu / Bằng chứng kiểm tra | Biện pháp kiểm soát bắt buộc |
|---|---|---|---|
| Recorder bị ảnh hưởng khi Analytics treo/crash | **P0** | Kill/treo tiến trình AI làm hở segment video | Tách luồng đọc stream theo Camera Stream ADR; kiểm chứng lỗi `X01/X02` ở `G1` |
| Đầy đĩa, mòn thẻ nhớ/SSD hoặc lỗi ghi I/O | **P0** | `disk_time_to_full_estimate` giảm, lỗi `fsync`, vượt reserve | Áp dụng `StorageQuotaGuard`, bảo vệ clip unACK, dự phòng vùng trống cho SQLite WAL |
| Quá nhiệt hoặc sụt FPS khi chạy dài ngày trên board đích | **P0** | `frame_age` tăng, thermal throttle trong bài soak 24–72h | Giảm số camera/module trên mỗi thiết bị hoặc nâng SKU phần cứng; không hạ ngưỡng AI tùy tiện |
| Trượt miền dữ liệu (domain shift) giữa clip lab và CCTV thực địa | **P0** | Tăng báo động giả hoặc bỏ sót qua negative audit | Khóa chặt ODD CCTV cố định 720p–1080p, bổ sung `person_lying_persistent` và kiểm định `G2` theo site |
| Chưa hoàn tất bản quyền weights hoặc phê duyệt quyền riêng tư | **P0** | Thiếu hồ sơ cấp phép thương mại cho model/dataset hoặc site | Chặn triển khai thương mại cho tới khi có hồ sơ pháp lý ký duyệt (`YOLOX` Apache-2.0 khác với quyền dùng từng bộ weights/tập huấn luyện) |
| Kích hoạt nhầm cấu hình lỗi, tấn công replay cấu hình hoặc lệch đồng hồ | **P0** | Bundle sai chữ ký, sai target, `trust_sequence <= HWM` hoặc `clock_synchronized=False` | Đã có `SignedConfigStore` + HWM đơn điệu + giữ nguyên LKG + canary auto-rollback (`#34, #35`) |
| Bão gói tin rác (malformed storm) từ thiết bị lỗi hoặc bị xâm nhập | **P1** | Tăng đột biến lỗi schema `4xx` trên endpoint ingestion | Đã có `MalformedStormGuard` cô lập theo từng thiết bị (`429` có giới hạn forensic sample, `#41`) |
| Quá tải nhân sự trực xác minh (review overload) | **P1** | Số cảnh báo cần duyệt × số phút/cảnh báo vượt ca trực | Đo thực tế từ pilot (`ReviewHours/month`), điều chỉnh ROI/lịch/ngưỡng trước khi nhân rộng |
