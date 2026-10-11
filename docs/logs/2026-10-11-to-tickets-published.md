# Nhật ký publish tracer-bullet tickets — 2026-10-11

## Authorization và phạm vi

Người dùng trả lời “đồng ý” với breakdown 50 ticket đã trình bày theo skill to-tickets. Thực hiện bước 5 publish vào local Markdown tracker theo cấu hình repo; không hỏi lại approval và không bắt đầu implementation.

## Hành động và quyết định

- Đọc canonical breakdown/CONTEXT/ADRs và quy ước tracker/triage. Không khám phá source mới hoặc gọi CodeGraph vì bước này chỉ xuất kế hoạch đã khảo sát/duyệt; không reindex. Không subagent/local worker.
- Tạo `.scratch/system-build-slices/PRD.md` làm mục lục/frontier/traceability và 50 file riêng dưới `issues/`, số 01–50 theo dependency order.
- Mỗi ticket có title, What to build, Blocked by với số/title/link thật tới ticket prerequisite, Status/Execution, acceptance, task mapping và Comments. Không đưa source-code paths hoặc code snippets vào implementation instructions.
- Giữ nguyên titles/behaviors/acceptance/blocking edges của breakdown đã duyệt. Task mapping bao phủ 89 task nguồn; một task chia nhiều mốc không tự thêm blocking edge.
- 42 ready-for-agent; #15/#29/#42 needs-info với camera/target/downstream protocol còn thiếu; #37/#46/#48/#49/#50 ready-for-human cho power-cut/survey/acceptance/field work. Các điều kiện ngoài ghi cụ thể theo quy ước draft đã duyệt.
- Notification #42 và vehicle #46–#48 có activation gates riêng; không chặn person-down nếu disabled. ready-for-agent không có nghĩa đã xong prerequisites. Frontier ban đầu: #01/#02.
- Đổi review artifact từ draft-awaiting-user-review sang approved-published và thêm link tracker trong mục lục checklist. Parent PRD/issues `.scratch/system-build/` không sửa/đóng; so hashes trước/sau publication xác nhận nội dung giữ nguyên.
- Không claim/implement/test runtime, không sửa source/config/tests, không stage/commit/push. Giữ nguyên untracked và worktree changes từ các lượt trước.

## Kiểm chứng và giới hạn

- PASS: 50 ticket files riêng, approved title/behavior/criteria/blocking edges giữ nguyên, 89 source task IDs đầy đủ.
- PASS: blocker links hợp lệ, graph acyclic và blockers-first, frontier #01/#02; 54 Markdown files của tracker/index/review artifact kiểm local links/tables/whitespace/fences và acceptance unchecked.
- Git diff --check đạt; file untracked được đọc/kiểm trực tiếp. Parent tracker hashes không đổi; source plan không bị chỉnh thêm trong lần publish này.
- Publication là backlog, không chứng minh implementation/hardware/field gates đã đạt. Các external prerequisites, named owners và sign-off vẫn được xử lý tại ticket/gate tương ứng.

## Commit theo yêu cầu tiếp theo

- Người dùng yêu cầu commit thay đổi. Phạm vi: implementation plan cập nhật, docs/implementation-checklists, hai tracker system-build/system-build-slices và ba logs mới về checklist/draft/publication.
- Giữ ngoài commit AGENTS.md, .codegraph, research và các historical/module-plan logs untracked đã có trước nhiệm vụ checklist. Không dùng git add toàn workspace, không push.
- Trước staging: kiểm lại 18 module/89 task/checklist và 50 tickets/blocking DAG/links/criteria: PASS. Staged index ban đầu trống.
- Chỉ thay Markdown; không chạy runtime/hardware tests và không suy publication thành gate đạt. Commit message Conventional Commits theo caveman-commit: docs: add checklists and implementation tickets.
