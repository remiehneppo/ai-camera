# PRD — Bộ công việc triển khai hệ thống CiviWatch (`civi-watch`)

Document role: phạm vi và acceptance theo module; tiến độ ở tracker slices.
Owner: Chủ dự án cần gán người phụ trách từng module.
Updated: 2026-11-09 (Đồng bộ Kiến trúc CiviWatch v2 — ADR-0008)

[Tracker thực thi duy nhất](../system-build-slices/PRD.md). Không claim/đóng module như ticket; giữ task IDs và evidence để đối chiếu.

## Mục tiêu và phạm vi

Chuyển thiết kế hiện hành thành checklist có thể claim, implement và kiểm chứng: 18 module M00–M17, đủ 89 task từ plan cùng 14 nhóm kịch bản an toàn đô thị (`US01`–`US14`) theo [ADR-0008](../../docs/adr/0008-civiwatch-v2-hybrid-vlm-architecture.md). Luồng đầu tiên là person-down một camera cố định/ROI lòng đường; G1 chỉ chứng minh vertical slice với event fixture, chất lượng person-down ở G2. Toàn bộ 14 nhóm kịch bản đã có implementation trên Edge trong software lab (`domain/urban_scenarios.py`, `apps/edge/urban_safety_engine.py`, `apps/edge/vlm_verifier.py`). Vehicle và các nhóm mở rộng có gate nghiệm thu thực địa riêng.

Bản PRD này tham chiếu scope đã có, không tạo yêu cầu sản phẩm hoặc quyết định accepted mới. Q1–Q19, các ADR accepted và readiness hiện hành vẫn là nguồn chuẩn. Không có implementation, benchmark hoặc gate pass mới từ việc viết checklist.

## Tài liệu và issue chính thức

- [Mục lục, ownership và dependency map](../../docs/implementation-checklists/README.md).
- [Phân tích kiến trúc và SOLID](../../docs/implementation-checklists/architecture-analysis.md).
- [45 ca kiểm lỗi và release gates](../../docs/implementation-checklists/integration-release.md).
- [Plan nguồn](../../docs/architecture/implementation-plan.md).
- Issue/checklist module nằm trong `issues/01-m00-...md` đến `issues/18-m17-...md`; danh sách có link tại mục lục. Mỗi task giữ ID nguồn, không tạo một bản checklist trùng để tránh tick lệch.

## Acceptance của bộ tài liệu

- Có file riêng cho mọi module, ownership/path/contract/prerequisites và các bước implement cụ thể.
- Đủ 89 task IDs duy nhất từ backlog, mỗi task có bước, acceptance và evidence record.
- Có failure matrix xuyên module, Definition of Ready/Done và gate sign-off phân biệt planned/implemented/tested/accepted.
- Links và task references hợp lệ; không chỉnh source/config/tests, không tick các công việc chưa thực hiện.

## Comments

- 2026-10-11: Materialize backlog/checklist theo yêu cầu phân tích/lập kế hoạch; mọi issue needs-triage và not-started, chưa claim.
