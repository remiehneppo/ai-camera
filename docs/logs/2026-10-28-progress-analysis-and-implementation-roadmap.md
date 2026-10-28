# Báo cáo Phân tích Tiến trình Implement & Kế hoạch Tiếp tục Dự án — 2026-10-28

## 1. Mục đích
Ghi nhận kết quả rà soát toàn diện hiện trạng mã nguồn, tiến độ tracker (.scratch/), kết quả kiểm thử, và xác lập kế hoạch hành động cụ thể cho các giai đoạn tiếp theo của dự án AI Camera Giao thông.

## 2. Kết quả Phân tích Hiện trạng (Current State)

### 2.1. Độ tin cậy mã nguồn & Kiểm thử
- **Test suite**: `844 passed, 360 warnings, 126 subtests passed` (thời gian chạy 155.84s, 0 regression).
- **Kiểm tra kiểu tĩnh (Static Typing)**: `mypy domain/ apps/ tools/` đạt 100% không lỗi trên toàn bộ 69 source files.
- **Git status**: Branch `master` sạch, ahead 3 commits so với `origin/master`.

### 2.2. Tiến độ Tracker (.scratch/system-build-slices/PRD.md & 68 issues)
- **Tổng số issue**: 68 issues.
  - **Done (Software Lab)**: 29 tickets.
  - **Partial**: 10 tickets (#03, #06, #07, #15, #21, #23, #31, #51, #62, #63).
  - **Blocked**: 1 ticket (#52).
  - **Not started**: 28 tickets (chủ yếu là native C++ hot path, target hardware soak, production UI và 10 kịch bản mở rộng).
- **Tình trạng 4 nhóm tình huống nghiệp vụ đã code engine**:
  1. **US09 - Person-down**: Fall onset (#25), Persistent lying (#26), On-vehicle priority & danger override (#27), Pose outcomes integration RTMPose (#53).
  2. **US08 - Vehicle incident**: Kinematics smoothing, Pairwise risk TTC, Bounding Box IoU dilation rate, hard negatives rejection (#47).
  3. **US05 - Illegal parking**: `ParkingIncidentEngine`, dwell timing $\ge 2$ frame loại trừ rung giật, ROI, schedule windows, exceptions (#62).
  4. **US06 - Crowd concentration & suspected disorder**: `CrowdIncidentEngine`, Layer 1 tụ tập đông người, Layer 2 giải tán hoảng loạn / đột biến gia tốc, queue exceptions (#63).
- **Hạ tầng Edge - Server - Storage**:
  - Ring buffer, atomic pinning pre-10s/post-20s theo neo chuẩn `alert_condition` (#07, #51).
  - SQLite WAL+FULL EventJournal & Outbox atomic transaction (#01, #05, #09).
  - WAN outage 24h autonomy sizing, zero-TTL unACK evidence, giải tỏa backlog $B/(U-G)$ (#36).
  - Central retention manager & backup/restore reconciliation (#43).
  - Signed configuration, LKG rollback, strictly monotonic sequence number/HWM (#34, #35).
  - Edge storm guard, synthetic probes & operational fault reporting (#40, #41).
  - Exploratory capacity profiling harness (`apps/edge/capacity_lab.py` - #31).
  - Scoped capability quality assessment by camera/site (#21).

### 2.3. Các Khoảng trống & Điểm nghẽn Cần Giải quyết
1. **Thiếu Carrier E2E cho Module × Camera (#57)**: 4 engine nhận diện đã có trong lab nhưng chạy qua các runner/test riêng lẻ; chưa có luồng hợp nhất module allowlist registry và carrier E2E để các module chia sẻ chung detector/tracker.
2. **Native C++ Hot Path chưa khởi tạo (`native/`)**: Toàn bộ pipeline hiện chạy Python reference oracle. C++ software decode (#10), C++ ORT detector (#12), C++ ByteTrack (#13) chưa xây dựng.
3. **Chưa có số đo phần cứng và camera thực địa**: RTSP live stream (#15), soak 24h–72h (#31), và các gate nghiệm thu người dùng (#37 power-cut, #46 geometry calibration, #48 vehicle G4b, #49 person-down G4a, #50 field G5) đang chờ dữ liệu thực tế.
4. **10 Kịch bản an toàn đô thị mở rộng (#54–#68)**: Đang ở trạng thái `needs-info`, cần model checkpoint/dataset và carrier #57.

---

## 3. Kế hoạch Tiếp tục Triển khai (Roadmap)

### Phase 1: Hoàn tất Carrier E2E & Kích hoạt Đa Module (Software Lab) — *Ưu tiên 1*
1. **Implement Ticket #57 (Carrier Vertical: Module × Camera E2E)**:
   - Xây dựng allowlisted module registry tại composition root (`apps/edge/pipeline.py`).
   - Tích hợp 4 engine (`IncidentEngine`, `VehicleIncidentEngine`, `ParkingIncidentEngine`, `CrowdIncidentEngine`) dùng chung output từ `OracleDetector` và `ByteTracker`.
   - Kết nối `assess_capability_quality` (#21) vào event metadata payload.
   - Viết E2E integration test: 1 frame/video flow chạy qua đồng thời các module được cấu hình.
2. **Hoàn thiện Ticket #03 (ModuleConfigDoctor)**:
   - Mở rộng validation fail-fast cho toàn bộ module registry enabled khi khởi động.

### Phase 2: Hoàn thiện Vertical Slice G1 & RTSP Stream Correlation — *Ưu tiên 2*
1. **Ticket #15 (Camera RTSP live correlation)**:
   - Xác lập stream ADR và time mapping giữa live frame và recorder ring buffer.
   - Thử nghiệm trên luồng RTSP mock/LAN.
2. **Ticket #19 (Nghiệm thu Vertical Slice G1)**:
   - Chạy test case X01–X19 và đo P95 latency edge-to-server $\le 5s$.

### Phase 3: Xây dựng Native C++ Hot Path (Giảm tải CPU Edge) — *Ưu tiên 3*
1. **Ticket #10**: Cấu hình CMake, native software decode (FFmpeg C API), zero-copy buffer lifecycle và pybind11 binding.
2. **Ticket #12 & #13**: C++ ONNX Runtime detector và C++ ByteTrack đạt conformance parity với Python oracle.

### Phase 4: Đo đạc Capacity Thực tế & Target Edge Conformance — *Ưu tiên 4*
1. **Ticket #31**: Chạy `apps/edge/capacity_lab.py` với workload manifest 1080p, đo soak 24h, fsync, WAL growth, storage reserve.
2. **Khảo sát Target SKU**: Thử nghiệm trên nền tảng biên mục tiêu (Jetson Orin NX - #56 hoặc RK3588 - #29/#30).

### Phase 5: Mở rộng 8 Kịch bản Còn lại (#58–#68) & Bàn giao UI Sản phẩm (#44, #45) — *Ưu tiên 5*
1. Từng kịch bản mở rộng được triển khai khi có checkpoint model và ODD dataset.
2. Bàn giao OpenAPI/JSON Schema, contract events/re-review và mock fixtures cho đội Frontend UI.
