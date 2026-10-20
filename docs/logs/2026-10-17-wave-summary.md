# Tổng hợp đợt triển khai 2026-10-17

Phạm vi: 5 luồng subagent theo khuyến nghị bước tiếp theo. Lead review sau khi nhận kết quả. Không đóng gate G1–G5.

| Luồng | Việc | Kết quả | Log |
|---|---|---|---|
| A | Đồng bộ tracker (#08,#09,#13,#15–#18,#22,#24,#26) | 188 passed; #15 hạ partial; #16–#18,#22,#24,#26 done (software lab) | [tracker-sync](2026-10-17-tracker-sync.md) |
| B | Cảnh báo SQLite chưa vá + HTTP 413 ở uploader | 4 test mới pass; SQLite 3.45.1 chưa xác minh backport | [sqlite-upload](2026-10-17-sqlite-upload.md) |
| C | #04 `re_review_reasons` | Code thêm, 8 test HTTP mới chưa xác nhận xanh (Mongo lỗi) | [ticket-04](2026-10-17-ticket-04.md) |
| D | #21 quality/ODD tri-state tới event/detail | 19 passed; thiếu native, camera-moved, API với Mongo thật | [ticket-21](2026-10-17-ticket-21.md) |
| E | #23 track gap/clock jump | 9 test mới pass; thiếu report ID-switch theo ODD, pose qua gap | [ticket-23](2026-10-17-ticket-23.md) |

Lead kiểm lại: `test_track_gap, test_quality_odd, test_edge_uploader, test_edge_doctor, test_pipeline` → 53 passed. `git stash list` rỗng.

## Vấn đề mở
- Mongo lab: container `ai-camera-oc-mongo-1` restart nhiều lần, container `mongodb` khác giữ cổng 27017. Chặn test server/Mongo (review, dataset_lineage, crash_recovery server, rtsp e2e). Chưa sửa Docker.
- Chưa có baseline sạch để kết luận các test fail Mongo không do thay đổi mới; cần chạy lại sau khi sửa Mongo.
- Ngưỡng `max_observation_gap=1.0s` chưa chỉnh theo FPS (3 FPS: rớt ≥3 frame liên tiếp thì reset).
- Một số luồng dùng `git stash` tạm trong cây chung; đã pop, không mất file.
- Tracker: #15 `needs-info` (PRD) vs `ready-for-review` (ticket) còn lệch; #04, #21, #23 chưa cập nhật Execution (giữ partial).
