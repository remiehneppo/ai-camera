# Nhật ký chuyển checklist thành tracer-bullet tickets — 2026-10-11

## Yêu cầu và căn cứ

Người dùng gọi `$to-tickets` và cung cấp skill. Đã đọc file `/home/tieubaoca/.agents/skills/to-tickets/SKILL.md`, quy ước local Markdown tracker/triage và mục lục checklist. Dùng kiến trúc/glossary/ADR/89 task trong ngữ cảnh đã khảo sát; không cần khám phá source lại. CodeGraph lần khảo sát trước có 0 indexed source, không có source runtime được phân tích để prefactor.

## Hành động và quyết định

- Tạo bản review `docs/implementation-checklists/ticket-breakdown-draft.md`: 50 slices có title, blocking edges, behaviour, source-task mapping và acceptance dự kiến.
- Bao phủ đủ 89 task nguồn; một task có thể tách baseline/integration/hardening. Task references không tự là hard prerequisite.
- Chia vertical flows: event→durable server→demo; event→pin→clip; upload→playback; review→versioned state; observations→incident→review. Tooling/facts/conformance/fault/hardware là deliverables verifiable, không thêm UI không cần thiết.
- Không có ticket scaffold/prefactor tổng quát vì chưa có runtime cần refactor. Không ép phụ thuộc toàn module; bỏ dependency track-gap vào feedback khi chỉ cần dataset samples đã có.
- Tách G4a readiness với field G5 để không gom lab sign-off và pilot dài hạn thành một ticket; vehicle/calibration chỉ mở sau G2 và không chặn person-down khi disabled.
- Ticket hardware/clearance/policy/UI owner/sign-off có external prerequisites. Khi publish cần triage đúng ready-for-human/needs-info nếu còn đầu vào cụ thể thiếu, không giả AFK-ready cho toàn bộ roadmap.
- Giữ nguyên 18 module checklist/PRD hiện có; chưa xuất ticket mới vào tracker, chưa đổi trạng thái hoặc đóng/sửa parent issues. Không source/config/tests/stage/commit/push, không subagent/local worker.

## Điểm chờ theo skill

Bước 4 yêu cầu: “Iterate until the user approves the breakdown.” Vì vậy trình bày numbered breakdown để người dùng duyệt độ nhỏ/lớn, blocking edges và merge/split trước bước 5 publish. Đây là yêu cầu explicit của skill vừa được người dùng gọi, không phải hạn chế quyền ghi Markdown hoặc approval review từ môi trường.

## Kiểm chứng

- Draft đủ 50 ticket IDs duy nhất, blocking edges chỉ trỏ ticket có số nhỏ hơn; graph acyclic, dependency order hợp lệ.
- Source-task mapping bao phủ đúng 89 task của plan, không thêm task ID lạ; liên kết local và Markdown fences/whitespace được kiểm.
- Đây là draft awaiting user review, chưa có ticket được claim/implement/test hoặc gate nghiệm thu mới.
