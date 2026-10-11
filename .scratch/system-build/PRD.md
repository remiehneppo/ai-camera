# PRD — Bộ công việc triển khai AI Camera giao thông

Status: needs-triage
Execution: not-started
Owner: Chủ dự án cần gán người phụ trách từng module.
Updated: 2026-10-11

## Mục tiêu và phạm vi

Chuyển thiết kế hiện hành thành checklist có thể claim, implement và kiểm chứng: 18 module M00–M17, đủ 89 task từ plan. Luồng đầu tiên là person-down một camera cố định/ROI lòng đường; G1 chỉ chứng minh vertical slice với event fixture, chất lượng person-down ở G2. Vehicle là nhánh sau có gate riêng.

Bản PRD này tham chiếu scope đã có, không tạo yêu cầu sản phẩm hoặc quyết định accepted mới. Q1–Q19, ba ADR và readiness hiện hành vẫn là nguồn chuẩn. Không có implementation, benchmark hoặc gate pass mới từ việc viết checklist.

## Tài liệu và issue chính thức

- [Mục lục, ownership và dependency map](../../docs/implementation-checklists/README.md).
- [Phân tích kiến trúc và SOLID](../../docs/implementation-checklists/architecture-analysis.md).
- [37 ca kiểm lỗi và release gates](../../docs/implementation-checklists/integration-release.md).
- [Plan nguồn](../../docs/architecture/implementation-plan.md).
- Issue/checklist module nằm trong `issues/01-m00-...md` đến `issues/18-m17-...md`; danh sách có link tại mục lục. Mỗi task giữ ID nguồn, không tạo một bản checklist trùng để tránh tick lệch.

## Acceptance của bộ tài liệu

- Có file riêng cho mọi module, ownership/path/contract/prerequisites và các bước implement cụ thể.
- Đủ 89 task IDs duy nhất từ backlog, mỗi task có bước, acceptance và evidence record.
- Có failure matrix xuyên module, Definition of Ready/Done và gate sign-off phân biệt planned/implemented/tested/accepted.
- Links và task references hợp lệ; không chỉnh source/config/tests, không tick các công việc chưa thực hiện.

## Comments

- 2026-10-11: Materialize backlog/checklist theo yêu cầu phân tích/lập kế hoạch; mọi issue needs-triage và not-started, chưa claim.
