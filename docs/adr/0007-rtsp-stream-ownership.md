---
status: proposed
---

# Quyền sở hữu luồng RTSP camera (RTSP Stream Ownership)

Ngày: 2026-11-01. Phân loại: T3. Trạng thái: proposed.

## Context

Hệ thống edge AI cần đồng thời hai chức năng trên cùng camera RTSP:
1. Ghi hình vòng lặp liên tục (`RtspRingRecorder`, sử dụng ffmpeg stream-copy vào file container mkv).
2. Phân tích thị giác máy tính theo thời gian thực (`cv2.VideoCapture` trong `LivePerceptionRunner`).

Vấn đề kiến trúc: camera IP có thể chịu được bao nhiêu phiên RTSP đồng thời từ cùng một thiết bị edge mà không bị drop packet, nghẽn băng thông hoặc suy giảm chất lượng luồng video? Nếu camera không hỗ trợ đa phiên đồng thời, edge buộc phải thiết kế một tiến trình relay/demux nội bộ (recorder sở hữu luồng và chuyển tiếp cho analytics qua Unix domain socket hoặc loopback pipe).

Nguồn: [Ticket #15 / #19](../../.scratch/system-build-slices/issues/15-rtsp-ring-recorder.md), [Hợp đồng tích hợp §3](../architecture/contracts.md#3-stream-session-và-time-uncertainty), [Kết quả probe phiên RTSP](../../data/benchmark/rtsp-probe-20261101.json).

## Dữ kiện đo lường (Measurement Evidence)

Phép đo tự động được thực hiện ngày 2026-11-01 bằng `tools/rtsp_session_probe.py` trên camera lab thật (định dạng H.264, độ phân giải 1920x1080 @ 15.0 fps, thời lượng 20.0s mỗi phiên):

- **Mức k=1 (đơn phiên)**: 1 phiên, packets thực tế = 301 / expected = 300 (100.3%), exit_code = 0, stderr = rỗng, `ok: true`.
- **Mức k=2 (song phiên - dual-session)**: 2 phiên đồng thời:
  - Phiên 1: packets = 301 / expected = 300, exit_code = 0, `ok: true`.
  - Phiên 2: packets = 301 / expected = 300, exit_code = 0, `ok: true`.
  Tỷ lệ nhận gói tin ≥ 95% trên cả hai phiên, không xảy ra drop frame hay xung đột RTSP socket.
- **Mức k=3 (tam phiên - headroom cho viewer/live stream server)**: 3 phiên đồng thời:
  - Cả 3 phiên đều đạt packets = 301 / expected = 300, exit_code = 0, `ok: true`.
  (Kết quả k=3 chỉ mang tính chất thông tin tham khảo về dư địa tải của camera).

## Decision

Căn cứ quy tắc quyết định đã định trước, do mọi phiên ở mức `k=2` đều đạt `ok: true`:

**Chọn mô hình dual-session (song phiên upstream độc lập):**
1. `RtspRingRecorder` (ffmpeg stream-copy) và `LivePerceptionRunner` (`cv2.VideoCapture` cho analytics) mỗi bên mở một phiên TCP/RTSP độc lập trực tiếp lên camera upstream.
2. Analytics không nhận dữ liệu từ recorder và ngược lại; hai luồng hoàn toàn độc lập về mặt I/O process, không có phụ thuộc chặn (non-blocking decouple).
3. Ánh xạ thời gian giữa hai phiên tuân thủ nghiêm ngặt Hợp đồng tích hợp §3: chỉ sử dụng source event-time (wall-clock timestamp) kèm cận sai số bất định thời gian (`time_uncertainty`), tuyệt đối không join frame ID giữa hai phiên.
4. Mức `k=3` đạt `ok: true` xác nhận hệ thống có đủ dư địa để tích hợp thêm luồng phụ (ví dụ viewer trực tiếp trên dashboard hoặc media relay) khi cần thiết trong tương lai mà không ảnh hưởng tới recording hay analytics.

## Alternatives considered

### 1. Recorder-owned Relay (Proxy cục bộ trên edge)

Recorder nhận một luồng duy nhất từ camera, sau đó relay ra Unix socket hoặc local RTSP/HTTP server để analytics đọc lại.
- *Ưu điểm*: Chỉ chiếm 1 phiên trên camera.
- *Nhược điểm*: Thêm độ trễ decode/muxing, phức tạp hóa quản lý tiến trình, nếu relay crash thì cả recording lẫn analytics cùng sập (single point of failure). Chỉ bắt buộc khi camera không chịu nổi `k=2`. Vì camera lab đã kiểm chứng tốt ở `k=2` và `k=3`, không chọn giải pháp này.

### 2. Analytics-owned Stream-sharing

Analytics đọc frame từ camera rồi tự nén lại để ghi đĩa.
- *Nhược điểm*: Tiêu tốn CPU/GPU cho re-encoding, phá vỡ tính toàn vẹn của bằng chứng hình ảnh (không thể stream-copy nguyên bản H.264 bitstream). Bị loại bỏ hoàn toàn.

## Consequences

- Hệ thống tiếp tục duy trì kiến trúc hai phiên độc lập đang có (`LivePerceptionRunner` + `RtspRingRecorder`), không phát sinh nợ kỹ thuật hoặc tiến trình trung gian.
- Ticket #15 không bị chặn bởi yêu cầu relay, cho phép tiến hành nghiệm thu live trên camera thật (bước 8).
- Không rò rỉ thông tin xác thực camera (URL được che giấu theo chuẩn redact, chỉ lưu log đo lường).
