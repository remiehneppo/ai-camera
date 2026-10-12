# Hồ sơ lab và protocol nghiệm thu

**Cập nhật:** 2026-10-12. **Trạng thái:** inventory host đã probe; chưa nghiệm thu ODD, capacity, chất lượng hoặc recovery.

Đây là snapshot của workstation dùng trong lab, không phải hồ sơ site hay edge target. Số probe chỉ mô tả máy tại thời điểm ghi; giá trị `pending` cần người chịu trách nhiệm và evidence/sign-off, không được thay bằng ước lượng.

## Facts đã probe

| Hạng mục | Quan sát | Giới hạn |
|---|---|---|
| OS/kernel | Linux, Ubuntu-packaged kernel `7.0.0-31-generic`, x86_64 | Chưa pin image/OS deployment cho edge |
| CPU | Intel Core i5-12400F, 6 cores / 12 threads | Workstation host; không suy ra camera capacity |
| RAM | 31 GiB total, 13 GiB available lúc probe | Snapshot động, không phải budget của service |
| Accelerator | NVIDIA GeForce RTX 5060 Ti, 16311 MiB; driver 595.84 | Không phải target RKNN; GPU utilization/thermal/throughput chưa đo |
| Filesystem `/` | ext4, 915 GiB total, 103 GiB available (89% used) | Chỉ ảnh chụp dung lượng; không chứng minh endurance/quota/reserve |
| `/media/tieubaoca/HDD1` | ext4, 1.8 TiB total, 926 GiB available (47% used) | Không xác nhận là storage edge hoặc failure domain độc lập |
| Camera device | Không có `/dev/video*` tại thời điểm probe | RTSP camera/SKU/firmware/codec/session chưa được cung cấp hoặc kiểm tra |
| Network | Ethernet và Wi-Fi interfaces up; có default route | WAN/uplink throughput, latency, outage và clock correlation chưa đo |
| Lab stack | Docker CLI có; `docker compose ps` không phân giải được cấu hình vì `DASHBOARD_TOKEN` và `DEVICE_TOKENS` thiếu | Probe không khởi động hay thay đổi service; credentials không ghi vào hồ sơ |
| Repo fixtures tại probe #02 | Chưa có model/sample trong inventory ban đầu | Snapshot lịch sử; cập nhật #11 bên dưới, không suy production clearance |

Nguồn: read-only probes `uname -a`, `lscpu`, `free -h`, `lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS`, `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader`, `df -hT / /media/tieubaoca/HDD1`, `find /dev -maxdepth 1 -name 'video*' -print`, `ip -brief link`, `ip route`, `docker compose ps`, và inventory repo bằng `rg --files`. Full command/result record: [ticket #02 log](../logs/2026-10-12-ticket-02.md).

## Cập nhật software lab #11 — 2026-10-12

- Commit `e47d6cf`: manifests/attribution tại `models/yolox-tiny/`, independent goldens tại `fixtures/oracle/`; binary/photo ở ignored `data/oracle/`. Hash đầy đủ và rights scope nằm trong manifests, không dùng mutable release URL thay pin bytes.
- Python3.12.3, ORT1.20.1 CPU, NumPy1.26.4, OpenCV-headless4.10.0.84. Raw-BGR preprocessor source pin riêng với released binary và per-class postprocessor; mismatch old-tag preprocessing đã được user duyệt hiệu chỉnh.
- Pinned runtime full suite85/85 pass, no-record golden original13detections/10person, crop9/7, negative0. Đây là conformance fixtures, không đo recall/FP/capacity/field quality. [Evidence #11](../logs/2026-10-12-ticket-11.md).

## Scope, workload và ODD

| Loại | Giá trị hiện tại | Trạng thái |
|---|---|---|
| Use case | Person-down, một camera cố định và ROI lòng đường trước | Scope lab đã duyệt; chưa có site/camera để xác nhận |
| Camera/edge count | Một camera / một edge là đơn vị triển khai ban đầu | Target workload, chưa đo |
| 1080p, 10–15 analysis FPS; 1–4 camera | Khoảng workload nghiên cứu để thử | Không phải capacity hoặc acceptance đã đạt |
| Person pixel minimum, camera pose/ROI cụ thể, ánh sáng/thời tiết/occlusion bounds | `pending` | Product/operations + ML cần định nghĩa từ site và data được phép dùng |
| Quality thresholds, recall/FP denominator, sample sufficiency và review minutes/alert | `pending` | Product/ML/QA cần duyệt protocol trước khi ký G2 |
| Vehicle, PTZ/multi-plane và calibrated motion | Ngoài scope baseline | Vehicle cần calibration và G4b riêng khi được bật |
| Samples/model lab #11 | YOLOX-Tiny ONNX và Shibuya public-domain fixture đã pin SHA/size/source/runtime; user duyệt lab ngày 2026-10-12 | Exact released-weight/training-data rights, privacy/personality và site/production clearance vẫn pending; không suy từ source Apache-2.0 |
| Site owner, named acceptance signer | `pending` | Product/operations gán tên và ngày trước site acceptance |

### Đã chọn làm target, chưa phải phép đo

| ID | Preliminary target | Acceptance boundary |
|---|---|---|
| Q6 | Event ring 10 phút; pre-roll 10 giây; post-roll 20 giây; server clips 7 ngày; outage budget 24 giờ cho clip chưa ACK | Sizing inputs; bitrate, event rate, quota, time-to-full, endurance và autonomy chưa đo. Không xóa protected/unACK evidence theo outage budget |
| Q16 | P95 từ durable edge event commit tới dashboard hiển thị ≤5 giây trên LAN | Chỉ ký với clock basis/correlation, uncertainty, sample count và browser timing; không gồm temporal verification hoặc post-roll upload và không chứng minh AI quality/capacity |
| Hardware | ONNX/software decode là baseline lab; board chưa chọn | Không tuyên bố hardware decode, RKNN, target capacity hay thermal envelope đạt |
| Recovery | RPO/RTO, recorder gap budget và detection time | `pending`, phải gắn service/data scope, fault case, measurement và owner; không lấy outage budget làm RTO |

Sizing chỉ được tính sau khi thu bitrate/profile thực, event/day, pin overlap, queue/outbox, recording+upload contention và retention. Ghi missing input là `null`/`pending`; không suy capacity từ CPU/GPU model hoặc dung lượng đĩa tổng.

## Protocol tối thiểu

Trước mỗi run, pin commit/build, OS/SDK/runtime, model/config/dataset hashes, schema/rule/calibration versions; xác nhận fixture có quyền dùng, preliminary target, clock/uncertainty, workload, quota/reserve, owner và recovery method. Không chạy destructive power-cut nếu chưa xác định thiết bị lab, backup và người phục hồi.

| Case | Thao tác | Expected / evidence | Gate |
|---|---|---|---|
| Replay determinism | Cùng fixture với fixed inputs và clock | Outcomes/provenance ổn định; manifest fixture/hash và command | G1 |
| Camera/session loss | Disconnect/reconnect hoặc feed gap khi có nguồn thật | Operational fault/degraded rõ, epoch không nối sai, recorder gap/evidence partial đo được; synthetic không thay RTSP proof | G1 |
| Slow/failed storage | Inject lỗi/quota trên fixture hoặc disk lab riêng | Không ACK giả; protected evidence giữ nguyên; reserve/fault bounded và recovery trace | G1/G4a |
| WAN unavailable/resume | Cô lập endpoint trong thời gian được duyệt, sau đó phục hồi | Event/evidence/outbox còn durable, age/bytes đo được, reconcile idempotent; không xóa theo 24h target | G4a |
| Clock/latency | Ghi capture/receive/commit/render clock basis cùng sai số và sample count | Q16 chỉ pass khi tương quan đủ; nếu thiếu clock evidence thì `blocked`, không kết luận từ timestamp đơn lẻ | G1 |
| Quality/ODD | Held-out positive, hard-negative và unsupported conditions theo approved manifest | Report denominator, miss/FP, unavailable/out-of-ODD, uncertainty, coverage và review load; ngưỡng chưa duyệt thì không pass G2 | G2 |
| Power-cut/restore | Chỉ trên device cụ thể đã chọn, có snapshot/backup và recovery owner | Loss/gap theo approved RPO/RTO và recovery trace; chưa có device/signer thì `not-run/blocked` | G4a |

Mỗi case lưu `pass/fail/blocked/not-run`, expected/actual, command thật, timestamp/correlation, IDs/hashes của dữ liệu được bảo vệ, report, residual risk và reviewer. Failure matrix đầy đủ nằm tại [integration-release](../implementation-checklists/integration-release.md); case không chạy không được đánh dấu pass.

## Quyết định và việc còn thiếu

- Product/operations: gán site/use-case signer, ODD bounds và quality/review targets.
- Edge/platform: xác nhận camera/board, stream ownership, timestamp, storage mount/quota, uplink và workload thật.
- ML + Product/legal: giữ model/fixture pins lab #11; hoàn thiện released-weight/training-data/privacy/site clearance và held-out dataset trước production/quality acceptance.
- QA/operations: xác định RPO/RTO, recorder gap budget, fault scope, recovery device/owner và cách đo.

Các mục trên là gate mở, không cản synthetic/demo hoặc replay software hiện có; chúng chặn kết luận live-site, target capacity, quality sign-off và field readiness tương ứng.
