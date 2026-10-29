# Truy vết sửa review, đánh giá dataset và điều kiện nhãn đối chứng

**Ngày ghi bổ sung:** 2026-10-29. **Phạm vi:** tài liệu truy vết T0; không sửa mã nguồn, gắn nhãn video hoặc thay đổi ngưỡng phát hiện trong lượt này.

## 1. Nguồn bằng chứng và giới hạn

Log này bổ sung các hành động và quyết định còn thiếu sau [log #57 ngày 2026-10-28](2026-10-28-ticket-57-danger-zone-carrier-e2e.md). Kết quả lệnh dưới đây lấy từ transcript thực thi trước đó; lượt ghi tài liệu này không chạy lại test hay suy luận. Đã đối chiếu lịch sử commit và JSON kết quả hiện có tại `data/benchmark/multi_scenario_eval_results.json`.

JSON kết quả và video nằm trong `data/` cục bộ, không kèm commit tài liệu này. JSON không phải nhãn đối chứng, không lưu đầy đủ bằng chứng phát lại bất biến như hash của mọi đầu vào, môi trường thực thi và nhãn đã duyệt. Các số đo dưới đây mô tả lượt chạy thăm dò, không phải nghiệm thu chất lượng hoặc capacity trên thiết bị biên.

## 2. Các commit và hành động đã thực hiện

| Commit | Nội dung và quyết định |
|---|---|
| `f44a442` | Sửa factory để khởi tạo cả năm module qua registry; bổ sung tham số lineage cho `IncidentEngine` và bài kiểm tra khởi động/xử lý frame. Ticket #57 giữ `partial`, chưa có held-out video được duyệt. |
| `b66e78c` | Sửa các finding review: giữ `config_version` riêng khi reset session; truyền chất lượng pipeline cho sự kiện đa module khi thiếu policy riêng; cache ROI pixel theo danh tính polygon và kích thước frame; điều phối theo chữ ký thay cho thử lại khi gặp `TypeError`; thêm kiểm tra tâm bbox cho ROI person-down. |
| `b60d5db` | Sửa `tools/eval_all_scenarios.py` và `tools/eval_vehicle.py`: tạo PTS vi giây và `event_time` từ cùng time base hữu tỉ; ném `RuntimeError` nếu detector trả trạng thái ngoài `ok`/`ok_empty`. |

Cache ROI theo danh tính đối tượng không chứng minh hỗ trợ sửa polygon tại chỗ; cache chữ ký không chứng minh hỗ trợ thay phương thức engine sau lần gọi đầu. Không có benchmark đối chứng chứng minh mức tăng hiệu năng của cache.

## 3. Kiểm chứng đã chạy trước khi ghi log

Các lệnh dùng `.venv-oracle/bin/python`; số liệu gắn với từng mốc commit, không thay thế nhau.

| Mốc | Lệnh | Kết quả đã quan sát |
|---|---|---|
| `f44a442` | `.venv-oracle/bin/python -m pytest tests/test_danger_zone_flow.py -v` | 16 passed, 0.65 s |
| `f44a442` | `.venv-oracle/bin/python -m pytest -q` | 860 passed, 360 warnings, 126 subtests passed, 142.62 s |
| `b66e78c` | `.venv-oracle/bin/python -m pytest tests/test_danger_zone_flow.py -v` | 21 passed, 0.86 s |
| `b66e78c` | `.venv-oracle/bin/python -m mypy domain/ apps/ tools/ tests/test_danger_zone_flow.py` | Không có lỗi trong 71 source files |
| `b66e78c` | `.venv-oracle/bin/python -m pytest -q` | 865 passed, 360 warnings, 126 subtests passed, 143.21 s |
| Lượt dataset trước sửa timestamp | `.venv-oracle/bin/python -m pytest tests/test_oracle_conformance.py -v` | 8 passed, 3 warnings, 2.02 s |
| Lượt dataset trước sửa timestamp | `.venv-oracle/bin/python -m pytest tests/test_dataset_lineage.py -v` | 7 passed, 29 warnings, 3.41 s |
| `b60d5db` | `.venv-oracle/bin/python -m mypy tools/eval_all_scenarios.py tools/eval_vehicle.py` | Không có lỗi trong 2 source files |

Hai lỗi ở lần chạy đầu của năm test review mới: thiếu `timestamp` khi tạo `Track` và tracker chưa active ở frame đầu. Sau khi sửa fixture, lượt chạy lại cho kết quả 21 passed. Lượt sửa evaluator từng gặp `IndentationError` do mất dòng `for d in dets`; đã khôi phục vòng lặp trước khi chạy dataset thành công và commit.

**Giới hạn kiểm chứng:** kết quả 865 tests thuộc mốc sửa review, không phải full-suite sau `b60d5db`. Sau sửa evaluator đã chạy mypy và video thật, nhưng chưa chạy lại full-suite hay bổ sung test hồi quy riêng cho FPS phân số/trạng thái detector lỗi.

## 4. Lỗi timestamp và các lượt chạy lại

Video intersection có FPS `29.97002997002997`. Evaluator cũ tính `event_time = round(frame_idx / native_fps, 4)` nhưng khai báo `pts = frame_idx`, `time_base = "1/30"`. `OracleDetector` yêu cầu `event_time == float(pts * Fraction(time_base))`; frame không thỏa điều kiện trả `failed`. Evaluator cũ đọc danh sách detections rỗng mà không kiểm tra trạng thái, nên báo cáo intersection 8 detections, P50 0.14 ms và 0 events không chứng minh được negative pass.

Evaluator mới dùng `pts = round((frame_idx / native_fps) * 1_000_000)`, `time_base = "1/1000000"` và `event_time = float(pts * Fraction(time_base))`. Đây là thời gian tổng hợp nhất quán, lượng tử hóa tới vi giây; không phải bằng chứng đã lấy PTS gốc của container.

Đã chạy lại riêng intersection:

```sh
.venv-oracle/bin/python tools/eval_all_scenarios.py --videos data/benchmark/intersection_traffic_1080p.mp4 --max-frames 60
.venv-oracle/bin/python tools/eval_vehicle.py --video data/benchmark/intersection_traffic_1080p.mp4 --max-frames 60
```

Lượt đa kịch bản: 60 frames, 565 detections, 6 pose outcomes, 13 events, P50/P95 33.16/44.09 ms. Lượt vehicle riêng: 60 frames, 565 detections, 12 events. Hai công cụ có cấu hình ngưỡng khác nhau; không dùng số events để kết luận công cụ nào chính xác hơn.

Lượt chạy lại 14 clip với `--max-frames 100`, `--sample-fps` mặc định 10 và pose bật:

```sh
.venv-oracle/bin/python tools/eval_all_scenarios.py \
  --videos data/benchmark/traffic_cctv_hd/000001.mp4 data/benchmark/traffic_cctv_hd/000002.mp4 \
  data/benchmark/traffic_cctv_hd/000003.mp4 data/benchmark/traffic_cctv_hd/000004.mp4 \
  data/benchmark/traffic_cctv_hd/000005.mp4 data/benchmark/traffic_cctv_hd/000006.mp4 \
  data/benchmark/traffic_cctv_hd/000007.mp4 data/benchmark/traffic_cctv_hd/000008.mp4 \
  data/benchmark/traffic_cctv_hd/000009.mp4 data/benchmark/traffic_cctv_hd/000010.mp4 \
  data/benchmark/urfd/fall-01-cam0.mp4 data/benchmark/urfd/adl-01-cam0.mp4 \
  data/benchmark/shibuya_crossing_1080p.mp4 data/benchmark/intersection_traffic_1080p.mp4 \
  --max-frames 100 --json-out data/benchmark/multi_scenario_eval_results.json
```

| Clip | Frames đã phân tích | Detections | Pose outcomes | P50/P95 (ms) | Events chưa duyệt |
|---|---:|---:|---:|---:|---:|
| CCTV `000001` | 50 | 111 | 0 | 31.07 / 31.56 | 3 |
| CCTV `000002` | 50 | 105 | 0 | 22.68 / 25.08 | 1 |
| CCTV `000003` | 50 | 228 | 0 | 23.02 / 26.24 | 6 |
| CCTV `000004` | 50 | 105 | 0 | 22.60 / 27.16 | 1 |
| CCTV `000005` | 50 | 132 | 0 | 21.63 / 24.54 | 3 |
| CCTV `000006` | 50 | 84 | 0 | 22.55 / 24.90 | 0 |
| CCTV `000007` | 50 | 171 | 1 | 22.39 / 23.51 | 2 |
| CCTV `000008` | 50 | 68 | 0 | 22.56 / 25.88 | 2 |
| CCTV `000009` | 50 | 199 | 0 | 22.00 / 30.95 | 6 |
| CCTV `000010` | 50 | 30 | 0 | 22.17 / 30.72 | 0 |
| URFD `fall-01-cam0` | 54 | 235 | 34 | 26.00 / 50.41 | 0 |
| URFD `adl-01-cam0` | 50 | 138 | 28 | 23.67 / 31.07 | 0 |
| Shibuya | 100 | 420 | 80 | 37.26 / 55.89 | 1 |
| Intersection | 100 | 981 | 15 | 32.51 / 43.44 | 16 |

Lượt chạy hoàn tất mà không kích hoạt kiểm tra fail-fast của detector. JSON hiện tại không có bộ đếm trạng thái từng frame; không suy thêm số liệu ngoài kết quả và hành vi fail-fast đã ghi nhận. Các công cụ này đánh giá bốn engine hiện hữu, không chứng minh dataset E2E của module `danger_zone` hay luồng evidence/server/review.

JSON intersection phân loại 16 đề xuất thành **13 `vehicle_vehicle`, 2 `vehicle_rollover_or_barrier`, 1 `vehicle_pedestrian`**. Phân loại 11 + 5 trong trả lời trước là sai.

Lượt benchmark riêng trước đó dùng `.venv-oracle/bin/python tools/run_benchmark.py --max-frames 60`: Shibuya baseline/full đạt 17.00/14.14 FPS; intersection đạt 17.93/14.20 FPS. Công cụ đã ghi đè báo cáo mặc định ngày 2026-10-21; đã khôi phục tài liệu lịch sử, không coi nó là báo cáo lượt chạy mới. Kết quả JSON benchmark cục bộ vẫn là đầu ra thăm dò; không so trực tiếp FPS/latency với evaluator có đường xử lý và cách lấy mẫu khác.

## 5. Đính chính các kết luận trước đó

- Rút kết luận intersection là “0 false positives” hoặc “negative pass”. Số 0 cũ bị ảnh hưởng bởi lỗi timestamp; 16 events sau sửa vẫn chưa có người duyệt TP/FP.
- Rút kết luận CCTV `000006` và `000010` là “negative pass sạch”. Không phát sinh event chỉ là quan sát đầu ra, không xác nhận clip âm tính hay loại trừ bỏ sót.
- Rút các nhãn “positive”, “tai nạn thật”, “phát hiện chính xác” gán cho những clip CCTV còn lại chỉ từ tên nguồn và số event. Manifest có metadata nguồn/ODD/hash, không có annotation va chạm.
- Chưa xác nhận event Shibuya là gây rối thật. Đầu ra `suspected_disorder` là đề xuất chờ review.
- URFD có độ phân giải 640×240 và bối cảnh trong nhà, ngoài ODD CCTV giao thông hiện hành. Không có alert không chứng minh hệ thống chủ động chặn ngoài ODD hoặc phát hiện ngã đạt yêu cầu.
- Chưa có nhãn/bằng chứng video đã duyệt để kết luận toàn bộ intersection là dừng đèn đỏ, hoặc xác nhận cơ chế gây ra từng event. Phối cảnh, giảm tốc, nhiễu bbox và đổi track là giả thuyết cần đối chiếu, không phải nguyên nhân đã chứng minh.

## 6. Quyết định: nhãn đối chứng trước, chưa tune rule

Chưa triển khai bộ lọc cùng hướng, loại bỏ nhánh va chạm hoặc mục tiêu ép 16 xuống 0. Không tự đóng dấu toàn bộ intersection là negative.

Bước tiếp theo cần người duyệt annotation độc lập cho cả khoảng có alert và khoảng không có alert: thời gian/loại tương tác, phương tiện liên quan, trường hợp không rõ, người duyệt và phiên bản nhãn gắn với hash video. Bao phủ cả va chạm thẳng đuôi xe; không coi hai xe cùng hướng là ngoại lệ an toàn mặc định.

Sau khi kiểm tra nhãn và nguồn trùng lặp, đóng băng split theo nhóm camera/nguồn để tránh rò rỉ. Các clip đã xem kết quả hiện tại không còn là tập chưa từng quan sát cho quyết định tuning. Tỷ lệ 60/40 từng đề xuất chưa được áp dụng và không đảm bảo đủ mẫu theo loại va chạm; cần bổ sung dữ liệu độc lập nếu không đủ nhóm.

So sánh baseline và candidate trên cùng nhãn/split bằng recall theo loại va chạm, số FP trên thời lượng camera đã duyệt, cảnh báo trùng và độ trễ. Chốt ngưỡng nghiệm thu trước khi tuning; chưa chốt mục tiêu giảm FP 90% hoặc recall không giảm từ lượt chạy này. Công cụ `negative_audit_report.py` cần dữ liệu review và kế hoạch lấy mẫu đúng hợp đồng, không nhận event counts thô thay nhãn.

**Còn mở:** annotation đã duyệt, tập held-out độc lập, kiểm chứng va chạm thẳng đuôi, test hồi quy evaluator, nghiệm thu video vùng nguy hiểm #57 và chạy camera/phần cứng thực tế. Lượt này chỉ bổ sung tài liệu, không thay đổi trạng thái gate của các ticket.
