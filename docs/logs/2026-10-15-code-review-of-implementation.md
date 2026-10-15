# 2026-10-15 — Code review thay đổi triển khai P0/P1/P2 (so với HEAD 882d843)

Phạm vi: `git diff HEAD -- apps compose.yaml README.md` (17 file apps, working tree chưa commit). Suite: 398 passed.
Công cụ: 2 reviewer song song (Standards, Spec) trên onechain/GPT 6 Luna + `ocr delegate rule` (open-code-review, không cần LLM).
`ocr review` (cần LLM) KHÔNG chạy được: `ocr auth status` = chưa đăng nhập, chưa cấu hình provider.

## Standards (đã kiểm chứng)
- Dead code: `apps/edge/send_synthetic.py:88` gán `clock` nhưng không dùng (xác nhận bằng grep). Nhẹ.
- `apps/edge/recorder.py:76,186-188`: `_pin_locks` không bao giờ xóa entry => tăng theo số pin. Nhẹ, rò rỉ chậm.
- `apps/server/store.py:77-81`: `except Exception` quá rộng khi giải mã cursor (nhưng đã chuyển thành ValueError). Phán đoán, không chặn.
- `apps/edge/incident.py:12-15`: polygon < 3 điểm trả True (không lọc) — chính sách ngầm, chưa có hợp đồng ROI. Phán đoán.
- Deadlock callback recorder<->runner: reviewer không tìm thấy đường deadlock (callback gọi ngoài lock ở rtsp_recorder.py:103-109,137-139). Chưa có test đa luồng.

## Spec
- `apps/edge/incident.py:225-232`: khi reset sau 2 frame chuyển động, `first_qualifying_time = ts` lấy chính frame chuyển động, nên anchor/persistence tính từ frame CUỐI đang chuyển động, không phải frame đứng yên đầu tiên (issue #26, contracts §3: first qualifying observation). Lệch ~1 frame (0,1s); test dùng delta 0,15 nên không bắt được. Mức: trung bình-nhẹ. Sửa: đặt `None` khi reset.
- ODD (`pipeline.py` evaluate_odd): ngưỡng hard-coded; issue #21 đòi policy theo site/version. Không chặn.
- `roi_polygon`: chỉ qua constructor, chưa qua activation boundary (contracts §1). Không chặn.
- Trần upload 100 MiB: không mâu thuẫn hợp đồng nào, nhưng là hành vi mới. Chờ chủ dự án quyết.
- Reviewer nêu rủi ro "fallback tạo evidence giả": dispatcher đọc `live_pipeline.py:261-283` — runner KHÔNG đọc fallback khi có rtsp_url (chỉ recorder ghi fallback), nên chưa thấy đường sinh event từ fallback. Chưa kiểm chứng đầy đủ; ghi nhận là rủi ro thấp.
- Pose terminal outcome: không mất/trùng; `poll_terminal_outcomes` chỉ còn test gọi.
- `oracle_detector.py`: không đổi so với HEAD.

## open-code-review (ocr review) — chạy sau khi người dùng cấu hình provider
Provider oc / Gemini 3.8 Flash (High), 19 file, 11 phát hiện, 26m55s. Raw: `docs/logs/2026-10-15-ocr-review-raw.json`.
Dispatcher đã đọc mã để kiểm chứng. Ký hiệu: XÁC NHẬN / ĐÚNG-NHẸ / SAI-KHÔNG CHẮC.

| # | Vị trí | Kết luận | Ghi chú |
|---|---|---|---|
| 6 | evidence.py:138-150 | XÁC NHẬN, hồi quy do implementer | Bản HEAD kiểm tra quota TRƯỚC `_pin`. Bản mới `_pin` rồi mới kiểm tra, khi từ chối thì đánh dấu failed và `continue`, pin released=0 bị bỏ lại vĩnh viễn, đúng thứ cần P1-02 tránh. |
| 9 | live_pipeline.py:495-498 | XÁC NHẬN | `_ensure_capture` gọi `handle_disconnect("rtsp_open_failed")` rồi `_read_next_frame` gọi `handle_disconnect("rtsp_unavailable")` lần hai: đếm đôi disconnect/drop. |
| 11 | rtsp.py:89-90 | XÁC NHẬN | `attempts` không chặn trên, `backoff_factor ** attempts` tràn OverflowError ở ~1024 lần, làm sập vòng reconnect trong sự cố dài (chính thứ P0-03 cần chịu được). |
| 1 | live_pipeline.py:341-343 | XÁC NHẬN | Callback gọi `reconnect()` khi giữ `self._lock`; reconnect làm probe + open capture (I/O chặn nhiều giây) nên chặn `step()`/`stop()`. |
| 2 | tracker.py:105-111 | XÁC NHẬN | `Track.update` cứng `>= 2`, bỏ qua `activate_after` cấu hình (tracker.py:266 chỉ nâng được lên, không giữ tentative khi >2). |
| 7 | incident.py:122-142 | XÁC NHẬN | `observed_ids` không lọc ROI nên track ngoài ROI không bị dọn state; vào lại ROI dùng state cũ. |
| 10 | live_pipeline.py:583-599 | ĐÚNG-NHẸ | Thoát sớm khi `_is_running` False có thể bỏ sót join `_reconnect_thread`. |
| 8 | send_synthetic.py:88 | XÁC NHẬN (trùng reviewer Standards) | Dead code. |
| 3,4,5 | run_edge.py, run_server.py | Chưa kiểm chứng | File này không thuộc 6 nhóm triển khai và đã có sẵn trong working tree của người dùng (untracked); ngoài phạm vi thay đổi của dispatcher. Chỉ ghi nhận. |

## Vòng sửa (dispatcher tự sửa theo yêu cầu "tự fix tất cả"), TDD: test đỏ trước, rồi sửa
Full suite sau sửa: 409 passed (trước: 398; +11 test mới).

| Mục | Sửa | Test mới |
|---|---|---|
| #6 evidence.py | Kiểm tra quota TRƯỚC `_pin`; khi từ chối thì `release_pin` pin đã có | test_reconcile_quota_rejection_* (2) |
| #11 rtsp.py | Bắt OverflowError và dừng đếm `attempts` khi đã chạm trần | test_long_outage_*, test_reset_restarts_* |
| #9 live_pipeline | `_read_next_frame` chỉ ghi disconnect nếu `_ensure_capture` chưa ghi | test_failed_rtsp_open_counts_exactly_one_disconnect_per_read |
| #1 live_pipeline | `_on_recorder_source_change` gọi `reconnect()` NGOÀI `self._lock` | test_recorder_rtsp_callback_does_not_hold_runner_lock_* |
| #10 live_pipeline | `stop()` không thoát sớm khi `_reconnect_thread` còn sống | test_stop_joins_reconnect_thread_* |
| #2 tracker | `Track.update` không tự nâng active khi do ByteTracker quản (`activate_after`) | test_activate_after_is_respected_beyond_two_hits |
| #7 incident | `_in_roi`; track ngoài ROI coi như không quan sát nên state bị dọn | test_out_of_roi_track_state_is_dropped_* |
| Anchor persistent | Reset => `first_qualifying_time = None`, anchor = frame đứng yên đầu tiên (2.1 thay vì 2.0) | test_persistent_lying_anchor_is_first_stationary_observation |
| _pin_locks | Xóa entry sau release, chỉ khi không ai giữ khóa | test_release_pin_drops_its_per_pin_lock_entry |
| send_synthetic | Bỏ biến `clock` thừa | (không đổi hành vi) |
| #3,#4,#5 run_edge/run_server | Chuyển khởi tạo + `signal.signal` vào `__main__`; bỏ `import sys`; run_server trả exit code của uvicorn | kiểm bằng import từ worker thread, không tạo `data/` |

Ghi chú: run_edge.py/run_server.py vốn untracked, nằm ngoài phạm vi triển khai; sửa theo yêu cầu "fix tất cả".
Chưa sửa (chờ quyết định chủ dự án): trần upload 100 MiB; quy ước parity detector (P2-09/P2-10 đã hoàn tác).

## ocr review vòng 2 (sau sửa): 11 -> 2 phát hiện, 16m37s
Raw: `docs/logs/2026-10-15-ocr-review-raw-round2.json`. Không còn phát hiện nào thuộc nhóm đã sửa.
- run_edge.py:46-50 (thấp) — XÁC NHẬN: sau khi SIGINT đã có handler, `except KeyboardInterrupt` không thể xảy ra. Đã sửa: vòng `while not stop_event.wait(1.0)`, bỏ `import time`.
- store.py:130-133 (trung bình) — BÁC BỎ: ocr cho rằng `except AutoReconnect` bỏ lọt `ServerSelectionTimeoutError`. Kiểm bằng pymongo cài đặt: `ServerSelectionTimeoutError` và `NetworkTimeout` đều là lớp con của `AutoReconnect` (MRO: SSTE -> AutoReconnect -> ConnectionFailure). Không đổi mã.
Full suite cuối: xem kết quả chạy ngay trước mục này.
