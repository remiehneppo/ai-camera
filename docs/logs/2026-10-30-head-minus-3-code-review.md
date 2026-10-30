# Code review chuyên sâu 3 commit gần nhất (`316203e..5060908`) — 2026-10-30

## Phạm vi và quyết định

- Yêu cầu người dùng: review chuyên sâu 3 commit gần nhất (`code-review`, chế độ read-only đối với mã nguồn; chỉ ghi log truy vết theo `AGENTS.md`).
- Base: `758bc952bce6a1490f0293023860944ad14e7ee1`.
- Head: `5060908ab513dad78b367d0fbda584a115466f49`.
- Các commit trong phạm vi:
  1. `316203e` (`refactor(edge): centralize incident snapshot ownership and semantic replay`, T3 — ADR-0005 & ADR-0006, 41 files, `+3512/-1019`).
  2. `daf746a` (`fix(edge): gate cross-class track association and spatial disorder clusters`, T1, 5 files, `+277/-24`).
  3. `5060908` (`docs: sync architecture, glossary, test metrics, and pre-camera replay log`, T0/docs, 6 files, `+167/-10`).
- Verdict: **Request changes** (`Critical: 0, High: 2, Medium: 5, Low: 2, Nit: 1`).

## Hành động kiểm chứng

1. Khởi tạo chỉ mục cục bộ `codegraph init -y` theo `rule://oc-codegraph` (144 files, 4,378 nodes, 11,817 edges) và truy vấn đồ thị phụ thuộc cho `build_incident_snapshot`, `PerceptionPipeline.process_frame`, 5 feature engines, `ByteTracker` và 3 replay evaluators.
2. Phân tách diff lớn qua 3 subagent `reviewer` song song (`SnapshotSeamReviewer`, `ReplayAndDocsReviewer`, `TrackerAndDisorderReviewer`), sau đó tự đối chiếu lại toàn bộ mã nguồn/spec/ADR và chạy script tái hiện độc lập cho mọi finding mức `High`.
3. Chạy kiểm tra tĩnh và bộ test cho toàn bộ 16 test files chịu ảnh hưởng:
   - `/home/tieubaoca/AI/AI-Camera-OC/.venv-oracle/bin/python -m mypy domain/ apps/ tools/` -> `Success: no issues found in 72 source files`.
   - `/home/tieubaoca/AI/AI-Camera-OC/.venv-oracle/bin/python -m pytest -q` trên 16 test modules bị ảnh hưởng.
4. Tái hiện thực nghiệm (in-memory, không sửa mã nguồn) 2 lỗi `High`:
   - Đổi `pipeline.config_version` từ `"pipeline-v1"` sang `"pipeline-v2"` trên `PerceptionPipeline` dùng `IncidentEngine` mặc định: snapshot phát ra vẫn giữ `"pipeline-v1"`.
   - Đưa chuỗi detection `"bicycle"` (frame đầu) rồi 11 frame `"motorcycle"` (`score=0.85`) qua `ByteTracker` + `ParkingIncidentEngine`: `track.label` kẹt vĩnh viễn ở `"bicycle"`, phát `0` sự kiện đỗ xe sai quy định; tương tự `"pedestrian"` -> `"person"` làm `IncidentEngine` và `PoseScheduler` bỏ qua 100% track.

## Tóm tắt kết quả chính

- **High (2)**:
  1. `apps/edge/tracker.py:104-122,184-191,233-237`: `_coarse_label_group` gộp IoU trong nhóm thô nhưng `Track.update()` không bao giờ cập nhật `self.label`, gây false negative 100% khi nhãn frame đầu là `"bicycle"` (sau đó là `"motorcycle"` -> bị `ParkingIncidentEngine` loại) hoặc `"pedestrian"` (sau đó là `"person"` -> bị `IncidentEngine` và `PoseScheduler` loại).
  2. `apps/edge/pipeline.py:432-433,530-531,667` & `apps/edge/incident.py:131`: `PerceptionPipeline.__init__` ghi đè `engine.config_version = self.config_version` lên `IncidentEngine` mặc định (`""`), khiến các lần đổi `pipeline.config_version` về sau không cập nhật lại và luôn đóng dấu `config_version` cũ vào snapshot (vi phạm S03/S09).
- **Medium (5)**:
  1. `.gitignore:8` (`5060908`): thêm `.codegraph/` vào `.gitignore` nhưng chưa `git rm --cached -r .codegraph/` cho `.codegraph/.gitignore` và `.codegraph/config.json` đã track từ `26d08d7`.
  2. `apps/edge/crowd_incident.py:133,364,376-389,419-433,574-589`: ngưỡng cứng `v_radial >= 15.0`, `mean_speed >= 25.0`, `max_dist >= 120.0` ghi đè tham số cấu hình/phụ thuộc độ phân giải; `_find_disorder_cluster` trả sớm ở cụm đầu tiên và dùng một `_last_disorder_alert_time` toàn cục làm che khuất cụm gây rối thứ hai trong cùng ROI.
  3. `apps/edge/tracker.py:236,309,318-329`: `d.get("label", "unknown")` biến `{"label": None}` thành `"None"` lệch với `"unknown"`; track nhiễu ở trạng thái `lost` có thể hồi sinh chồng lên track `active` khác nhóm nhãn tại cùng bbox.
  4. `docs/adr/diagrams/H01-incident-snapshot-ownership.drawio:7` & `H02-semantic-replay-reuse.drawio:8`: legend còn ghi `"Approved design; not implemented"` và cạnh `e5` của `H02` nối thẳng `features -> Snapshot + EvidenceLifecycle` thay vì đi qua `PerceptionPipeline`.
  5. `316203e` gộp 2 ADR T3 trong một commit 41 files (`+3512/-1019`), để lại các thuộc tính envelope mồ côi trên 5 feature engines và import biến private `domain.event_contract._FIELDS` tại `apps/edge/snapshot.py:16`.
- **Low / Nit (3)**: gọi lặp `assess_capability_quality` theo số sự kiện trong cùng frame (`apps/edge/pipeline.py:640-653`); comment ODD cũ trong `tools/eval_all_scenarios.py:274-287` và thiếu liên kết chuyển tiếp tới bản sửa `fall_0005` trong `docs/logs/2026-10-30-pre-camera-dataset-replay.md:55,72`; hàm chết `_evaluate_disorder` (`apps/edge/crowd_incident.py:435-442`), truy cập trực tiếp `engine.pipeline_id` (`pipeline.py:665-666`) và cách tính timestamp float ở `tools/eval_clip.py:199`.

## Triển khai sửa toàn bộ finding (`fix all`) — 2026-10-30

1. **Bầu chọn nhãn cửa sổ trượt trong nhóm nhãn thô & chuẩn hóa nhãn (`apps/edge/tracker.py`, `apps/edge/incident.py`, `apps/edge/pose.py`, `apps/edge/parking_incident.py`, `apps/edge/vehicle_incident.py`, `apps/edge/danger_zone.py`, `apps/edge/crowd_incident.py`)**:
   - Lưu `label` đã chuẩn hóa (`_normalize_label`: gom cả `None`, `""` và thiếu khóa về `"unknown"`) trên `TrackObservation`; `Track.update(..., label=...)` cập nhật `self.label` theo tổng confidence trong cửa sổ lịch sử 5 giây (ưu tiên giữ nhãn hiện tại khi hòa điểm 1-1 để chống nháy đơn frame, tự chuyển sang nhãn ổn định khi tích lũy vượt trội).
   - Thu hồi (`mark_removed`) các track `lost` bị track `active` thuộc nhóm nhãn không tương thích đè khít (`IoU >= 0.85`).
   - Đồng bộ `IncidentEngine` và `PoseScheduler` chấp nhận cả `"person"` và `"pedestrian"`; đồng bộ `state.label` ở 4 engine còn lại khi track cập nhật nhãn.
2. **Giữ động `config_version` của `PerceptionPipeline` & tối ưu vòng phát snapshot (`apps/edge/pipeline.py`, `domain/event_contract.py`, `apps/edge/snapshot.py`)**:
   - Xóa các đoạn gán đè `engine.config_version` (cùng các trường envelope mồ côi) trong `PerceptionPipeline.__init__` và `_process_frame` để engine không khai báo `config_version` riêng luôn phản ánh `self.config_version` mới nhất sau khi xoay cấu hình.
   - Đưa phép tính `assess_capability_quality` và `feature` ra ngoài vòng `for facts in incidents:` (chỉ tính 1 lần/engine/frame khi có sự kiện) và dùng `getattr` fallback cho `pipeline_id`/`pipeline_version`.
   - Export hằng public `ENVELOPE_FIELDS` từ `domain/event_contract.py` thay cho import private `_FIELDS` tại `apps/edge/snapshot.py`.
3. **Đa cụm gây rối không che khuất nhau, ngưỡng phụ tỷ lệ theo cấu hình & xóa hàm chết (`apps/edge/crowd_incident.py`)**:
   - Tỷ lệ hóa bán kính sàn liên kết cụm theo `frame_dimensions` (và tọa độ chuẩn hóa `[0, 1]`), tỷ lệ hóa các ngưỡng phụ `min_actor_radial`, `mean_speed`, `min_surge_acc` theo tham số constructor.
   - Đổi `_find_disorder_cluster` sang `_find_disorder_clusters` trả tất cả cụm đạt ngưỡng trong cùng frame, quản lý cooldown theo từng track trong cụm (`_track_disorder_alert_time`), và xóa phương thức chết `_evaluate_disorder`.
4. **Đồng bộ Git index `.codegraph/`, sơ đồ `.drawio`, evaluators và tài liệu**:
   - Chạy `git rm --cached -r .codegraph/` để gỡ `.codegraph/.gitignore` và `.codegraph/config.json` khỏi Git index (giữ chỉ mục cục bộ trên đĩa được `.gitignore` bảo vệ).
   - Cập nhật tên trang, legend trạng thái accepted/Python reference và luồng cạnh `PerceptionPipeline -> Snapshot + EvidenceLifecycle` trên `H01-incident-snapshot-ownership.drawio` và `H02-semantic-replay-reuse.drawio` (xác nhận qua `drawio` MCP `list_pages`).
   - Đồng bộ PTS hữu tỉ `Fraction("1/1000000")` tại `tools/eval_clip.py`, sửa comment ODD diagnostic-only tại `tools/eval_all_scenarios.py`, thêm liên kết chuyển tiếp sang bản sửa `fall_0005` trong `docs/logs/2026-10-30-pre-camera-dataset-replay.md`, và đồng bộ tổng số test `896` tại `README.md`, `docs/README.md`.

### Bằng chứng kiểm chứng sau sửa đổi

- `/home/tieubaoca/AI/AI-Camera-OC/.venv-oracle/bin/python -m mypy domain/ apps/ tools/` -> `Success: no issues found in 72 source files`.
- Focused suite (16 files): `/home/tieubaoca/AI/AI-Camera-OC/.venv-oracle/bin/python -m pytest -q tests/test_snapshot.py tests/test_pipeline.py tests/test_quality_odd.py tests/test_semantic_replay.py tests/test_eval_clip.py tests/test_danger_zone_flow.py tests/test_vehicle_incident_flow.py tests/test_parking_incident_flow.py tests/test_crowd_incident_flow.py tests/test_on_vehicle_flow.py tests/test_tracking_incident.py tests/test_pose_outcomes_flow.py tests/test_track_gap.py tests/test_capacity_lab.py tests/test_review_fixes.py tests/test_tracker_lifecycle.py` -> `251 passed, 68 subtests passed, 0 failed, 0 skipped (14.10s)`.
- Full suite toàn repo: `/home/tieubaoca/AI/AI-Camera-OC/.venv-oracle/bin/python -m pytest -q` -> `877 passed, 19 skipped, 178 subtests passed, 0 failed (120.69s)` (19 test skip do worktree `scylla/` không chứa thư mục cục bộ `data/oracle/`; tổng số test toàn repo là 896).
- Live ONNX smoke (`yolox_tiny.onnx` thật trên `fall_0005.mp4` full 231 sampled frames và `fall_0001.mp4` full 224 sampled frames qua `evaluate_video` + `evaluate_clip` 30 frames): `0` detector failures, `fall_0005` giữ `0` `suspected_disorder`, `fall_0001` phát đúng `person_lying_persistent: 1`.
