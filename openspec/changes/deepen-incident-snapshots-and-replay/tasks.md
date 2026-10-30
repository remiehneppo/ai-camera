# Tasks

Kế hoạch revision 1, ngày 2026-10-29. [ADR-0005](../../../docs/adr/0005-incident-snapshot-ownership.md), [ADR-0006](../../../docs/adr/0006-semantic-replay-pipeline-reuse.md) và [design.md](design.md) đã được người dùng duyệt. **Người dùng cho phép triển khai ngày 2026-10-30; checkbox chỉ hoàn thành sau kiểm chứng tương ứng.** Tạo tasks.md không phải đã chạy mã, test hoặc smoke.

## 1. Chuẩn bị seam snapshot

- [x] 1.1 Chốt inventory caller và baseline trước khi sửa exported output.
  - Phụ thuộc: phê duyệt triển khai kế hoạch này. Cỡ S; enabler cho S01/S03/S09 và R01/R02.
  - Phạm vi: ghi kết quả vào log đang có và tasks.md, không thêm runtime/config option. Dùng codegraph trước; kiểm references bằng language server nếu có khi đổi exported symbol. Liệt kê caller thực của năm process_tracks, fixture dùng _handle_incident/_handle_fall_incident/_build_event/_create_event, kể cả test_review_fixes.py, test_architecture_deepening.py, evaluator và live runner.
  - Nghiệm thu: inventory phân biệt caller facts, caller full snapshot và test semantics; xác nhận baseline CLI/function theo design §4, giữ mặc định khác nhau của từng caller; ghi giới hạn hoặc khác biệt repo phát hiện được, không dùng số event chưa duyệt làm ground truth.
  - Kiểm chứng: codegraph/reference output có file/range; đối chiếu constructor/CLI và fixture hiện hữu. Không chạy lại inference hoặc overwrite report lịch sử chỉ để lập inventory.

- [x] 1.2 Xây module snapshot theo interface đã duyệt với kiểm tra hành vi độc lập.
  - Phụ thuộc: 1.1. Cỡ S; files dự kiến: apps/edge/snapshot.py, tests/test_snapshot.py. Truy vết: S02, S04, S05, S06, S07; phần constructor của S01/S03/S09.
  - Nghiệm thu: build_incident_snapshot(facts, *, context, feature) không giữ session/state hoặc storage handle, dùng contract/Evidence policy hiện hữu; input sai bị từ chối, producer/config/rule/quality và payload/anchor được giữ đúng; snapshot không alias dữ liệu input có thể bị sửa sau đó.
  - Nghiệm thu: không sửa rule/ngưỡng, không thêm dependency/adapter, không thêm bind/rebind lifecycle hoặc ép mọi payload thành Person-down; không coi UUID/UTC minting là hàm thuần hay constructor idempotent.
  - Kiểm chứng sau khi task hoàn tất: `.venv-oracle/bin/python -m pytest -q tests/test_snapshot.py`; `.venv-oracle/bin/python -m mypy apps/edge/snapshot.py`. Smoke constructor với facts có dwell, pose và first_qualifying_observation; quan sát matching session/interval và input mutation isolation bằng assert tạm ngoài repo.

### Checkpoint A: constructor có bằng chứng, runtime chưa chuyển

Hoàn tất 1.1–1.2 trước khi đổi engine output. Các kiểm tra constructor phải đạt và runtime hiện hữu vẫn hoạt động vì chưa chuyển producer/caller. Đây chỉ là prerequisite có thể kiểm độc lập, không được gọi là hoàn tất feature hoặc phát hành một constructor không có caller cuối cùng.

## 2. Chuẩn bị clean cutover producer và pipeline

Các task 2.1–2.7 là các lát cắt có owner/file rõ, **không phải các release riêng**. Chúng cùng task 3.1–3.3 tạo một integration batch chưa phát hành: trong lúc đổi output, một số caller chưa chuyển sẽ chưa tương thích. Không tuyên bố full-suite xanh giữa batch, không thêm shim, hai kiểu output, adapter tạm hoặc catch/fallback để giấu trạng thái đó. Chỉ checkpoint B mới cho phép đánh dấu batch hoàn tất.

- [x] 2.1 Chuyển Person-down sang facts shape chung, giữ ba nhánh và anchor hiện hữu.
  - Phụ thuộc: checkpoint A. Cỡ M; files dự kiến: apps/edge/incident.py, tests/test_tracking_incident.py, tests/test_on_vehicle_flow.py, tests/test_pose_outcomes_flow.py. Truy vết: S01/S04/S06/S09.
  - Nghiệm thu: Person fall giữ onset, lying-persistent/on-vehicle giữ first_qualifying_observation và candidate lifecycle hiện hữu; pose/association, independent state/reset/cooldown và tham số process_tracks không đổi; assertions rule đọc facts, không tự dựng full snapshot trong engine.
  - Nghiệm thu: xóa test chỉ yêu cầu _handle_fall_incident_backward_compatibility khi bỏ shim; giữ kiểm tra anchor/pose/quality có hành vi tương đương qua constructor hoặc process_frame, không đổi tên test để ghim forwarding cũ.
  - Kiểm chứng sau tích hợp caller: `.venv-oracle/bin/python -m pytest -q tests/test_tracking_incident.py tests/test_on_vehicle_flow.py tests/test_pose_outcomes_flow.py`; các assertion snapshot phải qua constructor/pipeline, không re-pin private wiring.

- [x] 2.2 Chuyển vùng nguy hiểm sang facts, giữ ROI/lịch/dwell và producer riêng.
  - Phụ thuộc: checkpoint A. Cỡ S; files: apps/edge/danger_zone.py, tests/test_danger_zone_flow.py. Truy vết: S01/S03/S04/S06/S09.
  - Nghiệm thu: giữ ngưỡng/lịch/ROI/exception/track-gap và anchor alert_condition; feature config/module/factory/producer binding không đổi; engine không còn tự cấp event/message/request identity hoặc validate full snapshot.
  - Kiểm chứng sau tích hợp caller: `.venv-oracle/bin/python -m pytest -q tests/test_danger_zone_flow.py`; giữ kiểm tra config riêng, detector/rule lineage, quality thấp và multi-module linked events qua pipeline.

- [x] 2.3 Chuyển Vehicle incident sang facts, giữ động học và payload tương tác.
  - Phụ thuộc: checkpoint A. Cỡ S; files: apps/edge/vehicle_incident.py, tests/test_vehicle_incident_flow.py. Truy vết: S01/S03/S04/S06/S09.
  - Nghiệm thu: interaction_type/track_ids/detections, vehicle_motion và rule lineage không mất; giữ ngưỡng, cooldown/gap/ROI và alert_condition; bỏ full snapshot construction trong engine, không tune rule theo clip đã thấy kết quả.
  - Kiểm chứng sau tích hợp caller: `.venv-oracle/bin/python -m pytest -q tests/test_vehicle_incident_flow.py`; so facts/semantic snapshot bằng fixture hiện hữu, không dùng TP/FP suy từ tên dataset.

### Checkpoint nội bộ A1: rà soát payload trước khi ghép

Sau 2.1–2.3, integration owner đối chiếu shape facts, source anchor, lifecycle và producer context với design. Đây là kiểm tra thay đổi đang làm, **không** là bằng chứng caller cũ đã chạy được. Không publish hoặc mở release checkpoint khi evaluator/pipeline chưa chuyển.

- [x] 2.4 Chuyển Illegal parking sang facts, giữ continuity và lịch/exception.
  - Phụ thuộc: checkpoint A. Cỡ S; files: apps/edge/parking_incident.py, tests/test_parking_incident_flow.py. Truy vết: S01/S03/S04/S06/S09.
  - Nghiệm thu: giữ dwell/bbox/vehicle_label, first-frame không bịa stationarity, ROI/lịch/exception/reset/cooldown và alert_condition; không còn envelope/Evidence request trong engine output.
  - Kiểm chứng sau tích hợp caller: `.venv-oracle/bin/python -m pytest -q tests/test_parking_incident_flow.py`.

- [x] 2.5 Chuyển Crowd concentration và Suspected public disorder sang facts.
  - Phụ thuộc: checkpoint A. Cỡ S; files: apps/edge/crowd_incident.py, tests/test_crowd_incident_flow.py. Truy vết: S01/S03/S04/S06/S09.
  - Nghiệm thu: giữ crowd_count/track_ids/persistence_seconds/disorder_metrics, taxonomy/severity/confidence và independent state; giữ rule/exception/anchor, không bỏ metrics vì danh sách trường Person-down.
  - Kiểm chứng sau tích hợp caller: `.venv-oracle/bin/python -m pytest -q tests/test_crowd_incident_flow.py`; các caller trong test_review_fixes.py được chuyển ở 2.6.

- [x] 2.6 Ghép pipeline vào một seam tạo/persist snapshot và chuyển caller/fixture còn lại.
  - Phụ thuộc: 2.1–2.5. Cỡ M theo lát cắt; files chính: apps/edge/pipeline.py, tests/test_pipeline.py, tests/test_quality_odd.py, tests/test_architecture_deepening.py, tests/test_review_fixes.py. Live/synthetic/benchmark caller phát hiện ở 1.1 phải được xử lý trong integration batch nếu bị đổi contract; chỉ sửa nơi bị ảnh hưởng.
  - Nghiệm thu: pipeline dùng cùng constructor cho năm feature; context camera/session/Origin hiện tại, producer pipeline_id/version/config/rule riêng và quality scoped/fallback được giữ; snapshot hợp lệ chuyển EvidenceLifecycle trước emit, input lỗi không tạo durable intent.
  - Nghiệm thu: chuyển các FallEngine fixture ở test_pipeline.py và test_quality_odd.py sang facts đầy đủ; không bù input thiếu bằng default taxonomy/confidence/anchor trong constructor mới.
  - Nghiệm thu: bỏ branch nhận full snapshot rồi sửa lại, constructor riêng Person-down và forwarding entry point chỉ khi references đã về 0; không đổi dispatch compatibility/error propagation, không gộp temporal state, không đổi schema/transaction/retry ownership.
  - Kiểm chứng tại checkpoint B: `.venv-oracle/bin/python -m pytest -q tests/test_snapshot.py tests/test_pipeline.py tests/test_quality_odd.py tests/test_architecture_deepening.py tests/test_review_fixes.py tests/test_event_delivery.py tests/test_crash_recovery.py`; assertions camera/session/feature isolation và retry identity dùng local storage hiện hữu.

- [x] 2.7 Chuyển synthetic capacity fixture sang facts hợp lệ.
  - Phụ thuộc: 2.6. Cỡ S; file sửa dự kiến: tests/test_capacity_lab.py. Enabler cho S01/S09 và checkpoint B; không thay capacity algorithm hoặc nhận target capacity đã đạt.
  - Nghiệm thu: FallEngine fixture phát facts có payload/anchor_kind hợp lệ để outbox path vẫn thực sự được kích hoạt; không tự validate hoặc tạo snapshot ở fixture; giữ test_gap/cooldown assertions không bị ảnh hưởng.
  - Kiểm chứng tại checkpoint B: `.venv-oracle/bin/python -m pytest -q tests/test_capacity_lab.py tests/test_track_gap.py tests/test_live_pipeline.py tests/test_rtsp_pipeline.py`; các file chỉ đọc kết quả [] hoặc process_frame mà không đọc output cũ chỉ cần regression, không đổi mã để tạo diff không cần thiết.

### Checkpoint nội bộ A2: context và durable handoff

Sau 2.4–2.7, integration owner rà soát S01–S09, references của entry point sẽ xóa và input shape của evaluator. Giữ caller migration list mở cho tới hết 3.3; không chốt candidate 1 là release hoàn chỉnh khi evaluator còn đọc full snapshot cũ.

## 3. Chuyển evaluator vào runtime module

Nhóm này nối vào seam snapshot của nhóm 2 trong cùng integration batch. Không tạo bước trung gian evaluator tự ghép snapshot hoặc framework replay mới để tách release. tests/test_semantic_replay.py đã được tạo và chạy; test result nằm trong log, không suy từ tên file hoặc checkbox.

- [x] 3.1 Chuyển evaluator Vehicle incident sang PerceptionPipeline với cấu hình hiệu lực nguyên vẹn.
  - Phụ thuộc: 2.6. Cỡ S; files: tools/eval_vehicle.py, tests/test_semantic_replay.py. Truy vết: R01–R08/R10, phần vehicle của R02.
  - Nghiệm thu: CLI giữ min-speed=20/impact-decel=150, direct function giữ 8/50, max_frames=300 và tracker 0.25/0.08/0.3; không tự nhận pipeline defaults; mỗi file có session/state mới và Origin=replay, chỉ storage tạm cục bộ.
  - Nghiệm thu: bỏ detect/Track/feature orchestration riêng; summary lấy snapshot emitted/persisted; evaluator đọc pipeline.last_observation sau process_frame rồi raise RuntimeError nếu detection ngoài ok/ok_empty, không chờ process_frame tự raise vì hiện có thể trả []; không báo clean/negative pass hoặc success summary; try/finally đóng capture và dọn thư mục tạm ở đường lỗi.
  - Kiểm chứng tại checkpoint B: `.venv-oracle/bin/python -m pytest -q tests/test_semantic_replay.py tests/test_vehicle_incident_flow.py`; fixture kiểm outcome ở điểm ngưỡng và report effective config, không chỉ mock echo kwargs.

- [x] 3.2 Chuyển evaluator đa tình huống sang PerceptionPipeline.
  - Phụ thuộc: 2.6 và contract snapshot/replay dùng trong 3.1. Cỡ S; files: tools/eval_all_scenarios.py, tests/test_semantic_replay.py. Truy vết: R01–R08/R10 và toàn bộ cấu hình multi-scenario ở R02.
  - Nghiệm thu: giữ CLI max_frames=200/direct function=300, pose mặc định bật, vehicle 15/120, parking dwell=20 và crowd 5/3; không vô tình bật thêm danger-zone hay thay bộ feature đang được evaluator chọn.
  - Nghiệm thu: dùng pipeline cho detection/Track/pose/feature/snapshot, giữ sampling/time source hiện tại nhất quán với pts/time_base vi giây; giữ pose outcomes độc lập, không gọi tracker lần hai hoặc giữ state qua file khác; summary/status/error/local cleanup theo cùng contract đã duyệt, không thêm runner abstraction.
  - Kiểm chứng tại checkpoint B: `.venv-oracle/bin/python -m pytest -q tests/test_semantic_replay.py tests/test_pose_outcomes_flow.py tests/test_eval_clip.py`; đối chiếu semantic outcomes runtime/replay với cùng input/config thay UUID hoặc wall-clock giữa hai run.

- [x] 3.3 Đồng bộ evaluator clip và báo cáo phạm vi đo.
  - Phụ thuộc: 3.1–3.2. Cỡ M; files: tools/eval_clip.py, tools/eval_vehicle.py, tools/eval_all_scenarios.py, tests/test_eval_clip.py, tests/test_semantic_replay.py. Truy vết: R02/R04/R05/R07/R08/R09/R10.
  - Nghiệm thu: eval_clip giữ chỉ feature đang bật, CLI max_frames=0/pose mặc định tắt; dữ kiện summary khớp snapshot thực được emit/persist, detection lỗi không lẫn ok_empty hoặc pose failure; không đổi schema snapshot hay dựng lại event trong reporter.
  - Nghiệm thu: latency ở command có xuất latency đo quanh process_frame gồm local persistence, nêu scope và giữ đơn vị/percentile hiện hữu; không thêm phép so với số lịch sử hoặc một trường latency giả cho command chưa có phép đo. Zero events chỉ là số đầu ra, không nhận Complete evidence/quality/server-review readiness.
  - Kiểm chứng tại checkpoint B: `.venv-oracle/bin/python -m pytest -q tests/test_semantic_replay.py tests/test_eval_clip.py`; kiểm timing bằng clock điều khiển và work quan sát được, không assert thời gian wall-clock thật hoặc private call order.

### Checkpoint B: clean cutover chạy được qua tất cả caller

Chỉ integration owner kết luận checkpoint sau khi hoàn tất 2.1–2.7 và 3.1–3.3, không trong lúc sibling đang sửa shared files. Chạy focused full test modules, không chỉ một test được chọn. Nếu kiểm tra thất bại, sửa nguyên nhân trong batch; không ghim lại incidental assertion, xóa validation hoặc dùng fallback full snapshot.

Phải chứng minh S01–S09 và R01–R10 bằng outcomes; inventory references không còn caller đòi output cũ; không còn builder/forwarder/comment cũ theo design. Sau checkpoint này mới có một candidate 1+2 cutover hợp lệ để đưa đi review; không commit/push/merge nếu người dùng chưa yêu cầu trong cuộc hội thoại.

## 4. Bằng chứng chạy thật và hoàn tất

- [x] 4.1 Chạy smoke runtime hữu hạn trên fixture ngoài repo.
  - Phụ thuộc: checkpoint B. Cỡ S; chỉ dùng fixture/driver tạm ngoài repo, không thêm permanent test cho wiring. Truy vết: S03/S06/S08/S09, R01/R03/R04/R05/R06/R07/R08/R09/R10.
  - Nghiệm thu: tạo một clip synthetic 1280×720, FPS 30000/1001, hữu hạn; chạy cả ba CLI với giới hạn frame và không giao nhận mạng; quan sát rational clock/status, config hiệu lực, summary và timing scope thật. Nếu clip chỉ có zero events, kết quả đó không đủ chứng minh snapshot/anchor/persist.
  - Nghiệm thu: driver assert tạm qua pipeline thực với observation/facts synthetic có kiểm soát tạo ít nhất một event có anchor/quality/config riêng, rồi đọc local outbox để đối chiếu snapshot; chèn một detection failure và pose degradation để quan sát đường lỗi/status riêng. Không dùng customer video hoặc gửi dữ liệu ra ngoài.
  - Lệnh dự kiến, chỉ chạy sau implementation; thư mục mới tách khỏi dữ liệu cần giữ:

    ```sh
    smoke_dir=$(mktemp -d "${TMPDIR:-/tmp}/camera-replay-smoke.XXXXXX")
    ffmpeg -f lavfi -i testsrc2=size=1280x720:rate=30000/1001 \
      -t 2 -c:v mpeg4 "$smoke_dir/replay-smoke.mp4"
    .venv-oracle/bin/python tools/eval_vehicle.py \
      --video "$smoke_dir/replay-smoke.mp4" --max-frames 3
    .venv-oracle/bin/python tools/eval_all_scenarios.py \
      --videos "$smoke_dir/replay-smoke.mp4" --max-frames 3 --no-pose
    .venv-oracle/bin/python tools/eval_clip.py \
      --video "$smoke_dir/replay-smoke.mp4" --max-frames 3
    ```

  - Không tải/thay model để che thiếu prerequisite. Nếu artifact local chưa có, ghi đúng thiếu gì, hoàn tất deterministic paths có thể chạy và không báo smoke inference đã đạt. Dọn fixture/driver tạm sau khi giữ evidence cần thiết vào log; không overwrite report lịch sử.

- [x] 4.2 Chạy gates đầy đủ và ghi bằng chứng bàn giao.
  - Phụ thuộc: 4.1. Cỡ M; files tài liệu dự kiến: docs/logs/2026-10-29-architecture-deepening-review.md, docs/architecture/contracts.md phần implementation note liên quan, README.md phần evaluator bị thay đổi, tasks.md. Truy vết: toàn bộ S01–S09/R01–R10.
  - Nghiệm thu: `.venv-oracle/bin/python -m pytest -q` và `.venv-oracle/bin/python -m mypy domain/ apps/ tools/` đạt, ghi chính xác command/exit/passed/failed/skipped/warnings; nếu repo có gate mới khi thực thi thì dùng gate thực, không tạo make verify giả. Lặp cùng check ba lần cùng nguyên nhân thì dừng và báo nguyên nhân.
  - Nghiệm thu: `openspec validate deepen-incident-snapshots-and-replay --strict --json` đạt; cập nhật docs/log bằng evidence đã quan sát, phân biệt semantic replay với quality, Complete evidence, native/target capacity và transfer/review; mỗi checkbox chỉ đánh dấu sau khi hành vi tương ứng được chứng minh.
  - Kiểm chứng: đối chiếu toàn bộ scenario với design/tests thực đã chạy, không nhận test dự kiến là test tồn tại; giữ ADR-0001–0006 và schema storage không đổi. Không archive OpenSpec trước merge và không triển khai, rollback, commit hoặc phát hành ngoài lệnh người dùng.

## Traceability

Đây là ánh xạ từ đặc tả sang task, không phải test result. [Design Verification mapping](design.md#verification-mapping) giữ danh sách test hiện hữu/dự kiến và semantics cần kiểm.

| Scenario | Task sở hữu thay đổi | Checkpoint chứng minh |
|---|---|---|
| S01 | 1.2, 2.1–2.6 | B, 4.2 |
| S02 | 1.2, 2.6 | A, B |
| S03 | 1.2, 2.2–2.6 | B, 4.1 |
| S04 | 1.2, 2.1–2.5 | A, B |
| S05 | 1.2 | A, B |
| S06 | 1.2, 2.1–2.5 | A, B, 4.1 |
| S07 | 1.2, 2.6 | A, B |
| S08 | 2.6, 4.1 | B, 4.2 |
| S09 | 2.1–2.6, 4.1 | B, 4.2 |
| R01 | 3.1–3.2, 4.1 | B, 4.2 |
| R02 | 1.1, 3.1–3.3 | B, 4.2 |
| R03 | 3.1–3.2, 4.1 | B, 4.2 |
| R04 | 3.1–3.3, 4.1 | B, 4.2 |
| R05 | 3.1–3.3, 4.1 | B, 4.2 |
| R06 | 3.1–3.2, 4.1 | B, 4.2 |
| R07 | 3.1–3.3, 4.1 | B, 4.2 |
| R08 | 3.1–3.3, 4.1 | B, 4.2 |
| R09 | 3.3, 4.1 | B, 4.2 |
| R10 | 3.1–3.3, 4.1 | B, 4.2 |

## Ownership and execution constraints

- Một integration owner chịu trách nhiệm snapshot.py, pipeline.py, tests/test_snapshot.py, tests/test_semantic_replay.py và việc ghép các caller. Các lát cắt feature 2.1–2.5 có thể nghiên cứu đồng thời nhưng không chỉnh shared files cùng lúc.
- Nếu dùng agent ghi mã: mỗi agent một worktree/branch với file disjoint; owner thống nhất facts/context contract trước khi dispatch. Agent không chạy build/lint/tests/format giữa lúc các lát cắt phụ thuộc đang chỉnh; owner chạy focused/full gates sau tích hợp. Không tự tạo branch hoặc commit trong lượt lập kế hoạch này.
- Tests/test_danger_zone_flow.py có cả rule và carrier/pipeline assertions; cùng owner giữ file hoặc gửi yêu cầu chỉnh cho integration owner, không giao chồng người. Các caller phát hiện thêm ở 1.1 được chia lát cắt S/M trước khi chỉnh, vẫn nằm trong cùng integration batch; không bỏ vì ngoài danh sách dự kiến.
- Không thêm permanent test chỉ kiểm forwarding, source text, call count, wording hoặc echo kwargs. Giữ regression cho precedence, lỗi, payload, anchor, continuity, state isolation và persisted identity. Private-cache/incidental tests không được re-pin; loại khi đã có outcome coverage phù hợp.
- Không sửa threshold/ODD/rights/authorization, `.env`/secrets, dataset labels, report lịch sử hoặc ticket Execution ngoài bằng chứng của chính change. Không thêm module/store/process/adapter ngoài phạm vi để né clean cutover.
Người dùng đã duyệt kế hoạch và cho phép áp dụng change ngày 2026-10-30. Không tự commit/push, archive hoặc phát hành từ phê duyệt triển khai này.
