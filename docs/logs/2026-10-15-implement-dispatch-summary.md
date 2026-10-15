# 2026-10-15 — Điều phối triển khai P0/P1/P2 từ full-flow review

Nguồn: `docs/logs/2026-10-15-full-flow-code-review.md`. Route subagent: n9router/ag/gemini-3.8-flash-high.
Log chi tiết từng nhóm: `2026-10-15-impl-{incident-pipeline,pose,rtsp-live,storage,server-outbox,tracker-detector}.md`.

## Kết quả nghiệm thu (dispatcher tự chạy lại test, đọc diff)
| Nhóm | Mục | Kết quả |
|---|---|---|
| incident/pipeline | P0-01, P0-02, P1-09 (pipeline), P1-10, P1-11, P1-13 | Đạt |
| pose | P0-04, P2-08 | Đạt |
| RTSP/live | P0-03, P1-04, P1-07, P1-08, P1-09 (live), mục frame xám | Đạt sau 1 lần giao lại (lỗi lineage session_id) |
| recorder/quota/evidence | P1-02, P1-03, P2-01, P2-02, P2-03 | Đạt |
| server/outbox | P1-01, P1-05, P1-06, P2-05, P2-06, P2-07 | Đạt; P2-04 bỏ theo YAGNI |
| tracker | P1-12 | Đạt; 5 test cũ trong test_tracking_incident.py được cập nhật theo chu kỳ tentative 2 frame (anchor_time lệch +0.1s là hệ quả có chủ đích) |

Full suite: `PYTHONPATH=. .venv-oracle/bin/pytest tests -q` → 409 passed (398 sau triển khai + 11 test của vòng sửa sau code-review).

## Quyết định
- HOÀN TÁC P2-09 (NMS bỏ +1) và P2-10 (scale_x/scale_y riêng) trong `oracle_detector.py`: `test_nms_uses_original_coordinate_inclusive_pixels_and_per_class` và `tools/oracle_conformance.py` định nghĩa quy ước inclusive-pixel và scale chung làm parity contract với oracle (#12). Đổi quy ước phải cập nhật `golden-v1.json` cùng lúc, cần quyết định của chủ dự án.
- P2-04 (tách interface store) bỏ qua theo YAGNI.

## Chờ quyết định
1. `MAX_EVIDENCE_BYTES = 100 MiB` (apps/server/main.py:34) là hành vi mới, không có trong spec. Clip bitrate cao có thể bị 413. Chưa xác minh EdgeUploader xử lý 413 thế nào.
2. Có đổi quy ước parity detector (P2-09/P2-10) hay không.

## Giới hạn nghiệm thu
- Race giữa finalize_pin / _prune / release_pin chỉ kiểm bằng đọc mã, chưa có test đa luồng thực tế.
- Reconnect RTSP chỉ kiểm bằng mock/fake capture và clock, chưa có camera thật.
- Đã chạy code-review (2 reviewer + `ocr review` 2 vòng, 11 -> 2 phát hiện, 1 bác bỏ): xem `2026-10-15-code-review-of-implementation.md`. Đã commit trên nhánh master.
