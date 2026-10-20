# Nhật ký /to-tickets — 2026-10-20

## Yêu cầu và quyết định

Người dùng yêu cầu tạo ticket phục vụ implement requirement mở rộng, ưu tiên cập nhật ticket cũ thay vì chỉ tạo mới. Skill /to-tickets yêu cầu vertical slices, blocking edges và duyệt trước publish; tracker local Markdown, triage theo docs/agents.

- T1: duyệt toàn bộ phạm vi requirement, chỉ soạn/publish backlog, không thực thi.
- T2: mở rộng tracker `.scratch/system-build-slices`, giữ issue IDs/evidence; không sửa PRD cha. Index đối chiếu riêng.
- T3: duyệt cập nhật **12 issue cũ** (#03,#07,#21,#28,#31,#34,#44,#46,#47,#48,#49,#50), tạo **16 issue #53–#68**. #57 vùng nguy hiểm là carrier vertical cho phần module/anchor dùng chung; #58–#68 phụ thuộc #57 và độc lập nhau.
- Giữ lịch sử done #04/#14/#17/#22/#24; #29/#30 vẫn là nhánh RKNN, không repurpose Orin.
- #53 follow-up pose outcomes; #54 RF-DETR và #55 ViTPose riêng, không hard dependency lẫn nhau; #56 actual Orin baseline conformance, capacity dùng #31.
- Phân biệt hard dependency, conditional target/backend dependency và activation/site/rights/threshold/quality gates. Không đưa toàn bộ catalog thành blocker person-down hoặc mặc định mọi module cần model mới/Orin/calibration.
- Giữ Q36: person-down onset/first qualifying; nhóm mới alert-condition anchor; cả hai clip10/20, metadata không thay video.

## Hoạt động

- Đã đọc triage labels, PRD và immediate target issues; CodeGraph context với projectPath tuyệt đối đúng repo; teammate ticket-audit khảo sát read-only 52 issues hiện có và requirement.
- Audit chỉ ra PRD snapshot #04 stale và #52 thiếu trong bảng; một số legacy Status ready-for-review ngoài canonical roles. Không tự sửa parent hoặc đổi lịch sử/triage ngoài scope.
- Snapshot trước publish: PRD SHA256 `64442c7f63956770036ca181e4d49ec8f7bb52e25528c04134b553e743bf2528`; git diff PRD SHA256 `c40b17ff6b66102ed213a83acb9c4b924fd7eb10cb9687dd0dccb19819abdc69`. PRD đã có thay đổi của người dùng trước tác vụ, không được ghi đè.
- Giao task-4 existing-tickets sửa đúng 12 issue cũ; task-5 new-tickets tạo16 mới/index. Scopes file tách biệt dù cùng thư mục issues. Lead kiểm tra sau self-check.

## Kiểm tra và bàn giao

- task-4 existing-tickets hoàn tất: sửa đúng12 issue cũ, thêm27 acceptance criteria unchecked và audit comment; không sửa file ngoài scope. Self-check82 local issue links và history preservation đạt.
- task-5 new-tickets hoàn tất: tạo đúng16 issue #53–68 và `requirements-expansion-index.md`; self-check193 local link targets, US01–US14 coverage, canonical triage và dependencies đạt. Lead review yêu cầu sửa traceability template53–57 và diễn đạt63/index28; teammate đã sửa và kiểm lại.
- Lead đọc key tickets #31/#44/#47/#53/#54/#55/#57/#63 và index. Kiểm độc lập bằng python3: 68 issue IDs liên tục, approved hard edges chính xác, hard DAG68nodes và union hard+conditional DAG đều acyclic;209 link targets trong28issue được tác vụ chạm tồn tại (không kiểm fragments).
- Tất cả16new Execution not-started, không checkbox checked. #53 ready-for-agent chỉ integration/fixtures lab specified; #54–68 needs-info với input/owner/điều kiện chuyển ready, không giả định model/data/site đã sẵn sàng.
- Lead kiểm snapshot12 old issues: SHA hợp lệ, Status/Execution/Owner/checkedcriteria/oldcomments/evidence-handoff giữ nguyên. Bảy issue giữ nguyên04/14/17/22/24/29/30 khớp SHA trước tác vụ byte-for-byte.
- Parent PRD SHA256 vẫn `64442c7f63956770036ca181e4d49ec8f7bb52e25528c04134b553e743bf2528`, không thay đổi so trước publish; các thay đổi user trước đó được bảo toàn.
- `git diff --check` đạt. Không implementation, benchmark, runtime/hardware tests, stage/commit hay đóng ticket nào trong tác vụ backlog. Review chấp nhận publish backlog, không xác nhận năng lực nhận diện/target capacity.

## Commit/push theo yêu cầu người dùng

Người dùng yêu cầu commit và push sau bàn giao. Phạm vi commit chỉ gồm requirement/docs và ticket của hai tác vụ ngày2026-10-20; không gom code, PRD hoặc thay đổi dở dang trước đó. Với deployment-readiness có diff hỗn hợp, chỉ stage section ứng viên mới, giữ section SQLite/upload2026-10-17 ngoài commit. Kiểm staged diff/whitespace trước commit; kết quả commit/push báo trực tiếp sau khi Git xác nhận.

## Bàn giao

Mở `.scratch/system-build-slices/requirements-expansion-index.md` để xem mapping cập nhật/cũ/mới, hard DAG, conditional/activation gates và input còn thiếu. Tiến độ/claim chỉ ghi vào từng issue nguồn, không ở index hoặc snapshot PRD. Frontier mới có #53 theo blockers14/22/24; các candidate/module khác cần cung cấp đầu vào được nêu trước khi giao implementation đầy đủ.
