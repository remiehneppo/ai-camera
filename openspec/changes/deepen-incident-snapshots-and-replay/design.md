# Design

Trạng thái: thiết kế revision 1 được duyệt ngày 2026-10-29; kế hoạch và triển khai được cho phép ngày 2026-10-30. Python reference đã triển khai và kiểm chứng theo [log](../../../docs/logs/2026-10-29-architecture-deepening-review.md#implementation-authorized--2026-10-30); không phải nghiệm thu native/target hoặc chất lượng model. [Proposal](proposal.md), ADR-0005/0006 accepted và [tasks.md](tasks.md) ghi phạm vi/tiến độ.

## Context

Đã thống nhất tập trung snapshot, chuyển toàn bộ caller không shim, replay qua cùng runtime module, interface stateless, cấu hình hiệu lực theo caller, fail-fast detection failure và timing quanh process_frame gồm persist cục bộ. Phê duyệt thiết kế không cho phép tự triển khai; không đổi các giới hạn ngoài scope.

Codegraph xác nhận bốn full-snapshot builders và một đường Person-down riêng; hai evaluator có orchestration trực tiếp, còn eval_clip dùng pipeline. EventOutbox tiếp tục validate tại seam storage; mục tiêu không phải ép số lần gọi validator bằng test wiring.

Thuật ngữ theo [CONTEXT](../../../CONTEXT.md): Suspected incident, Alert feature pipeline, Evidence, Origin, Unknown observation và Track. SnapshotFacts/SnapshotContext/FeatureContext dưới đây là tên kiểu kỹ thuật cho dữ liệu hiện hữu, không phải khái niệm nghiệp vụ mới.

## Goals / Non-Goals

**Goals:** một nơi gắn full snapshot/context, payload không mất dữ kiện, caller/test qua cùng interface, và replay không lặp lại stage nội bộ.

**Non-Goals:** thay rule/ngưỡng, schema wire/storage, datastore, policy Evidence, cơ chế review hoặc native lifecycle. Không thêm adapter registry, class hierarchy theo feature, process, retry/timeout mới hoặc framework replay.

## Decisions

### 1. So sánh interface snapshot

Ba thiết kế read-only độc lập khảo sát cùng source và scope. Chỉ chọn hình dạng interface, không lấy nguyên ví dụ implementation của các phương án.

| Phương án | Depth và leverage | Locality và seam | Tradeoff / đề xuất |
|---|---|---|---|
| Hàm không giữ context | Một entry point dựng snapshot và giữ invariants cho năm feature | Kiểm snapshot không cần chạy detector/recorder; context truyền tại thời điểm phát | Khuyến nghị; dùng nhóm facts/context/feature thay hàng chục tham số rời |
| Session context + feature binding | Caller truyền ít context lặp | Phải bind/rebind khi session/config/model đổi; quality vẫn cần theo frame | Không chọn mặc định; thêm vòng đời và nguy cơ stale context |
| Chỉ hàm private trong PerceptionPipeline | process_frame thuận tiện cho runtime/replay | Luật snapshot vẫn lẫn với điều phối và storage setup khi kiểm riêng | Giữ pipeline làm caller chính, không đặt toàn bộ test snapshot sau pipeline |

Deletion test: xóa các builders trùng và bước sửa full snapshot rồi giữ các nghĩa vụ tại một implementation. Không chỉ chuyển metadata assembly sang caller khác. Dependency category của module snapshot là in-process; không cần adapter. Replay dùng detector/local-storage adapters đã có; không dựng hypothetical seam mới.

### 2. Interface snapshot đã duyệt

Implementation: apps/edge/snapshot.py. Một entry point: `build_incident_snapshot(facts, *, context, feature) -> dict[str, Any]`. Không có bind/reset/close hay storage handle trong interface này.

Ba nhóm input:

- `SnapshotFacts`: hai khóa `anchor_kind` và `payload`. Payload chứa taxonomy/severity/confidence/anchor_time/detection_time cùng các trường tình huống hiện hữu. Anchor kind dùng enum đang có trong evidence contract, không rút thành chỉ onset và alert_condition.
- `SnapshotContext`: identity camera/device/session và Origin hiện tại, detector/pose provenance và artifact hash, calibration, quality đã đánh giá cùng capability scope nếu có. Không nhận credential, token hoặc RGB buffer; không cache context giữa hai lượt gọi.
- `FeatureContext`: producer pipeline_id/pipeline_version, config_version và rule_lineage được caller lấy từ feature đang hoạt động. Module/factory tiếp tục xuất hiện trong payload khi schema payload hiện hữu có chúng; không tự thêm vào mọi tình huống.

Caller chính là PerceptionPipeline; caller tạo fixture snapshot riêng cũng dùng entry point này. Feature module chỉ tạo facts; evaluator sau chuyển đổi dùng process_frame thay vì tự gọi snapshot constructor trên một đường quyết định khác.

Ví dụ cách dùng interface đã triển khai:

```python
facts_list = engine.process_tracks(tracks, timestamp=source_time)
for facts in facts_list:
    snapshot = build_incident_snapshot(
        facts,
        context=current_snapshot_context,
        feature=active_feature_context,
    )
    evidence.persist(snapshot)
```

Invariants của interface:

1. Module tự cấp event_id/message_id/request_id và UTC produced_at/event_time cho revision mới, giữ schema/revision policy hiện hữu. Hàm không giữ state và không I/O, nhưng không thuần toán học: UUID/UTC mới có thể khác giữa hai lần gọi.
2. Context camera/session/Origin lấy từ lượt xử lý hiện tại. Producer pipeline_id/version giữ binding hiện hữu của từng feature; không dùng pipeline_id chung đè identity riêng của bốn feature. Person-down giữ producer context pipeline hiện tại.
3. Config/rule lineage lấy từ FeatureContext, không cho payload override. Giữ các rule roles thực, kể cả vehicle_motion; ghép provenance detector/pose theo semantics hiện hành, không bịa model/version mới.
4. Quality vẫn được tính bằng assess_capability_quality/quality pipeline hiện hữu trước seam. Module snapshot gắn kết quả scoped hoặc fallback, đồng bộ root quality_state với payload quality; không suy normal hay ODD supported từ việc chưa có policy.
5. Facts chỉ có shape khai báo. Từ chối full snapshot hoặc quality/evidence_requests/capability_scope do facts cung cấp; đây là lỗi caller chưa chuyển, không âm thầm bỏ trường. Payload nghiệp vụ còn lại giữ nguyên, không allowlist chỉ theo Person-down.
6. Giữ lifecycle hiện có theo tình huống: khi chuyển facts Person-down phải giữ candidate như output cũ; không thêm candidate cho mọi feature. Không đổi severity/confidence hay default taxonomy để che input thiếu.
7. Tạo Evidence request bằng make_evidence_request hiện hữu từ payload.anchor_time và anchor_kind. Không suy anchor từ taxonomy, không thay bằng detection_time. Giữ [-10,+20], policy version, matching session và first_qualifying_observation.
8. Tạo cấu trúc snapshot mới, không sửa/alias nested dữ liệu facts/context có thể bị caller thay đổi; không sao chép ảnh hoặc Track history ngoài dữ kiện đã giới hạn vào payload.
9. ValueError cho cấu trúc facts/context hoặc anchor sai; EventValidationError hiện hữu cho snapshot vi phạm contract. Không thêm hệ phân cấp exception; lỗi phải đến caller trước EvidenceLifecycle.persist.
10. Hàm tạo revision mới, không idempotent theo facts. Retry phải dùng snapshot/request đã persist; không gọi constructor lại để tái tạo identity. EventOutbox giữ validation và ràng buộc uniqueness hiện hữu.

### 3. Thay đổi caller và test surface

Giữ tên/interface tham số process_tracks hiện hữu và cơ chế dispatch tương thích; chỉ đổi output facts. Không chuẩn hóa tham số engine hoặc bỏ cơ chế truyền exception trong cùng change nếu không cần cho cutover.

Phạm vi caller đã xác nhận bằng codegraph và kiểm chứng khi triển khai:

- Feature producers: incident.py, danger_zone.py, vehicle_incident.py, parking_incident.py, crowd_incident.py.
- Runtime: pipeline.py dùng một đường construction; live_pipeline.py tiếp tục process_frame/incident config hiện hữu. Kiểm cả synthetic fixture consumers nếu dùng snapshot builder cũ; không tự đổi luồng synthetic đang có khác scope.
- Evaluator: eval_all_scenarios.py, eval_vehicle.py và eval_clip.py. run_benchmark.py cần kiểm caller/measurement nhưng không đổi bài benchmark baseline/full hoặc số liệu lịch sử nếu không bị cutover ảnh hưởng.
- Test/fixture: test_danger_zone_flow.py, test_vehicle_incident_flow.py, test_parking_incident_flow.py, test_crowd_incident_flow.py, test_tracking_incident.py, test_pose_outcomes_flow.py, test_on_vehicle_flow.py, test_quality_odd.py, test_pipeline.py và test_eval_clip.py. Không coi danh sách này thay cho references khi đổi exported output.

The interface is the test surface: test rule trên facts, test snapshot qua constructor, test emitted/persisted semantics qua process_frame. Không re-pin private helper/cache identity/call counts hoặc câu chữ incidental. Giữ các assertion lỗi/anchor/quality/lineage có hành vi người dùng; chỉ loại test implementation khi đã có kiểm tra outcome tương ứng.

### 4. Baseline replay và phạm vi chức năng

Giữ giá trị hiệu lực hiện tại theo từng command/caller, truyền tường minh tracker và feature module vào PerceptionPipeline. Bảng là baseline mã hiện tại đã duyệt để bảo toàn khi chuyển đổi, không phải policy site hoặc ngưỡng nghiệm thu chất lượng.

| Caller hiện tại | max_frames mặc định | Vehicle min_moving_speed | impact_deceleration | Pose mặc định |
|---|---:|---:|---:|---|
| eval_all_scenarios CLI | 200 | 15 | 120 | Bật |
| evaluate_video trực tiếp | 300 | 15 | 120 | Bật |
| eval_vehicle CLI | 300 | 20 | 150 | Không cấu hình pose |
| evaluate_clip của eval_vehicle trực tiếp | 300 | 8 | 50 | Không cấu hình pose |
| eval_clip CLI | 0 | Không bật vehicle riêng | Không bật vehicle riêng | Tắt |

Nguồn baseline: tools/eval_all_scenarios.py:44–86,240–288; tools/eval_vehicle.py:25–45,121–160; tools/eval_clip.py:50–82,141–153. Các CLI hiện dùng sample_fps=10. Tracker hai evaluator trực tiếp dùng high/low/match=0.25/0.08/0.3, khác pipeline defaults 0.5/0.1/0.2; phải truyền tracker hiện hữu thay vì nhận defaults mới.

Parking max_dwell=20, crowd min_count=5/min_duration=3 và các tham số Person-down chỉ định trong evaluator đa kịch bản phải giữ. Các tham số không override vẫn theo constructor hiện hữu và phải được phản ánh trong cấu hình hiệu lực của báo cáo; không sao chép toàn bộ default thành một nguồn cấu hình mới.

Kiểm kê implementation xác nhận pose queue/batch hiệu lực của evaluator đa tình huống cũ là 30/30 trong PoseManager; scheduler riêng budget 8 chỉ chọn candidate, không phải budget xử lý. Khi ghép pipeline, giữ scheduler của manager thay vì ghi đè bằng scheduler chọn candidate. Regression chín người đủ điều kiện giữ chín pose outcomes; đây là bảo toàn baseline thực, không phải tăng budget mới.

Mỗi file replay có pipeline/session riêng, không giữ temporal state qua hai video. Pipeline dùng cùng frame/status path; caller không gọi detect/update/pose thêm lần nữa. Clock tiếp tục dùng time_base vi giây nhất quán của PerceptionExecution cho đường timestamp tổng hợp hiện tại; đây không phải khẳng định lấy PTS gốc container. Không đổi cơ chế giải mã/time source trong refactor này.

### 5. Detection failure, báo cáo và timing đã duyệt

- Detector status ngoài ok/ok_empty: để pipeline ghi observation và xử lý gap, sau đó evaluator raise RuntimeError và CLI trả lỗi; không xuất summary thành công cho clip/lượt chạy đó. Lỗi trước frame đầu cũng không có success report. Không tạo retry/continue mode mới.
- Pose skipped/failed giữ pose status riêng, không mặc định dừng lượt chạy nếu detection hợp lệ. Không giữ legacy loop mà chỉ đổi cách in failure.
- Báo cáo dùng snapshot emitted/persisted và last_observation, thêm cấu hình hiệu lực và định danh phạm vi timing. Giữ các trường summary hiện hữu có nghĩa tương ứng; thay nhãn clean bằng mô tả zero events, không thêm nhãn TP/FP khi chưa có review.
- Timing quanh process_frame từ trước gọi đến sau trả về, gồm local persistence; loại decode/conversion/sampling/model startup, summary và network. Giữ đơn vị ms và cách tính percentile hiện hữu; thêm phạm vi vào latency_ms hoặc trường mô tả kề nó để consumer phân biệt số cũ. Không coi số mới là benchmark so sánh với report lịch sử.
- Dùng try/finally cho capture và context manager thư mục tạm. Không gọi close tưởng tượng: EventOutbox hiện mở connection theo thao tác, FileRecorder không có close interface chung; dọn tài nguyên thật đã mở, không thêm no-op lifecycle.

Các lựa chọn baseline bảo toàn, fail-fast và timing đã được người dùng duyệt ngày 2026-10-29. Không có mục tiêu latency/FPS mới hoặc held-out acceptance target.

## Risks / Trade-offs

### Tám điểm kiểm soát thiết kế

1. Volume: hiện có năm feature factories và hai direct evaluator loops; chưa có số event/rps hiện trường hoặc dự báo hai năm. Giả định phạm vi này giữ workload/config đang có, không tăng số camera/feature hay thêm buffer toàn video; không suy capacity từ cấu trúc.
2. Ownership/atomicity: constructor không storage; EvidenceLifecycle/EventOutbox giữ transaction event+outbox+request intent trước pin. Không có transaction mới giữa DB và recorder, không đổi MongoDB downstream semantics.
3. Concurrency: giữ processing RLock theo pipeline, stateless constructor không shared mutable session; uniqueness SQLite, EvidenceLifecycle lock và recorder commit/receipt guards giữ nguyên. Không thêm worker, cache context hoặc shared builder state.
4. Failure: không có outbound network trong evaluator mới. Invalid facts/validation lỗi trước persist; pin/FS/SQLite errors theo lifecycle hiện hữu và propagate nếu hiện đang propagate. Không tăng retry/timeout hoặc dọn dữ liệu ngoài thư mục lượt chạy.
5. Idempotency: identity event/revision/message/request của revision đã persist giữ nguyên qua retry/recovery. Constructor chỉ gọi cho sự kiện mới; TTL/unACK policy và canonical hash giữ nguyên.
6. Compatibility: schema version/storage/canonicalization giữ nguyên. Interface facts là clean cutover, cập nhật caller/fixture cùng release; không shim. Producer identity từng feature và pipeline semantics không được âm thầm đồng nhất.
7. Isolation: không đổi RBAC/tenant/site authorization hoặc server RLS. S09 kiểm camera/session/feature context, không giả là bằng chứng RLS. Giữ các gate quyền hiện hữu; không thêm PostgreSQL hoặc test auth giả để phục vụ refactor snapshot.
8. Rollout/rollback: [tasks.md](tasks.md) xác định kế hoạch chi tiết; hoàn tất seam snapshot trước khi nối replay vào seam đó, và chỉ phát hành khi đã cập nhật trọn caller. Không migration; rollback build/config đồng bộ về revision trước và đọc nguyên snapshot/schema cũ, không sửa history hoặc tái cấp identity. Không triển khai hay rollback thật trong lượt lập kế hoạch này.

### Bằng chứng và giới hạn

Không dùng event counts chưa duyệt làm ground truth, không tune collision rule và không đổi ODD CCTV cố định 720p–1080p. Temporary outbox/recorder chỉ kiểm metadata/handoff; không có raw coverage thì không nhận Complete evidence. Full native lifecycle, real camera/target capacity và transfer/server/review nằm ngoài change.

## Verification mapping

Các test dưới đây đã tồn tại và được chạy trong focused/full gates; kết quả chính xác nằm trong log triển khai. Dùng fixtures synthetic có kiểm soát và local storage thật cho semantics. Số scenario: 9 snapshot, 10 replay; không coi mapping hoặc validator là test result.

Test dùng unittest.TestCase và subTest theo convention hiện hữu. Các nodeid file::Class::method dưới đây chạy được; focused commands trong tasks.md chọn toàn file để bao phủ cả sibling regressions.

| Scenario | Kiểm tra tự động đã thực thi |
|---|---|
| S01 | `tests/test_snapshot.py::TestIncidentSnapshotConstruction::test_all_feature_facts_construct_valid_snapshots` và năm feature flow modules |
| S02 | `tests/test_snapshot.py::TestIncidentSnapshotConstruction::test_snapshot_envelope_in_facts_is_rejected_before_persist` |
| S03 | `tests/test_pipeline.py::TestPipelineRuntime::test_scoped_and_fallback_quality_distinct_with_feature_identity_across_session_resets`; `tests/test_danger_zone_flow.py::TestMultiModuleCarrierPipelineE2E::test_registry_loaded_named_module_with_distinct_config_version` và `test_real_detector_provenance_propagation` |
| S04 | `tests/test_snapshot.py::TestIncidentSnapshotConstruction::test_scenario_payload_fields_and_lifecycle_are_preserved` |
| S05 | `tests/test_snapshot.py::TestIncidentSnapshotConstruction::test_snapshot_does_not_alias_mutable_input` |
| S06 | `tests/test_snapshot.py::TestIncidentSnapshotConstruction::test_source_anchor_kind_and_interval_are_preserved` |
| S07 | `tests/test_pipeline.py::TestPipelineRuntime::test_invalid_facts_raise_value_error_before_event_or_outbox_persistence`; `tests/test_snapshot.py::TestIncidentSnapshotConstruction::test_invalid_input_is_rejected_by_constructor` |
| S08 | `tests/test_event_delivery.py::EdgeOutboxTests::test_retry_keeps_the_same_snapshot_and_message_identity` và tests/test_crash_recovery.py |
| S09 | `tests/test_snapshot.py::TestIncidentSnapshotConstruction::test_camera_session_reset_preserves_feature_isolation`; scoped/reset pipeline test ở S03 và gap/cooldown regressions |
| R01 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r01_replay_and_runtime_have_matching_semantic_outcomes` |
| R02 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r02_command_and_function_effective_policies_are_preserved`; `test_multi_scenario_keeps_effective_pose_processing_budget` |
| R03 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r03_fractional_fps_replay_keeps_valid_observation_time` |
| R04 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r04_detection_failure_is_not_successful_evaluation`; `test_explicit_missing_video_returns_cli_failure` |
| R05 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r05_empty_detection_and_pose_failure_remain_distinct` |
| R06 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r06_replay_origin_is_local_only` |
| R07 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r07_reported_events_match_persisted_snapshots` |
| R08 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r08_zero_events_do_not_claim_review_or_coverage` |
| R09 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r09_latency_measures_pipeline_work_not_decode` |
| R10 | `tests/test_semantic_replay.py::SemanticReplayTests::test_r10_replay_releases_resources_on_failure_and_completion` |

Sau implementation, chạy focused modules bị đổi rồi `.venv-oracle/bin/python -m pytest -q` và `.venv-oracle/bin/python -m mypy domain/ apps/ tools/`; ghi rõ passed/failed/skipped. Repo hiện không có make verify hoặc Makefile; không tạo runner mới chỉ cho tài liệu này. Không có build/lint gate riêng được xác định từ AGENTS.md; không suy một command giả.

Smoke sau implementation: tạo clip synthetic hữu hạn có FPS phân số bằng ffmpeg ngoài repo, chạy ba evaluator ở cấu hình tương ứng, quan sát status/output/persisted anchors và lỗi detection có kiểm soát. Một clip CCTV được phép dùng có thể bổ sung smoke, nhưng không thay test deterministic hoặc quality labels. Không ghi đè báo cáo lịch sử hay kết quả dataset mặc định.

## Diagram sources

- [H01 snapshot ownership](../../../docs/adr/diagrams/H01-incident-snapshot-ownership.drawio): facts và context vào module snapshot, rồi lifecycle persist intent trước pin.
- [H02 semantic replay reuse](../../../docs/adr/diagrams/H02-semantic-replay-reuse.drawio): caller đọc/sample, pipeline xử lý bằng module hiện hữu, không có giao nhận mạng.

Các hình mô tả thiết kế đã duyệt; bằng chứng implementation tách riêng trong log, không suy runtime conformance từ hình. Hình không mô tả full native lifecycle hoặc raw Evidence coverage.

## Approval checkpoint

Người dùng đã duyệt stateless snapshot construction interface, cấu hình replay giữ giá trị hiệu lực hiện hữu theo caller, fail-fast detection failure và latency quanh process_frame gồm persist cục bộ. Ngày 2026-10-30, người dùng duyệt [tasks.md](tasks.md) và cho phép triển khai. Không đánh dấu task implementation hoàn thành từ việc tạo tài liệu hoặc validator trả thành công.
