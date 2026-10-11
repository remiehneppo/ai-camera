# Nhật ký phân tích kiến trúc và xây checklist — 2026-10-11

## Yêu cầu và phạm vi

Người dùng yêu cầu phân tích kiến trúc/kế hoạch/từng module và tạo checklist hoàn chỉnh, tách biệt, có bước tiến hành, SOLID, theo dõi và kiểm lỗi. Lần này chỉ tạo/cập nhật Markdown kế hoạch/tracker; không implement source/config/tests, không claim issue, không stage/commit/push.

## Căn cứ và hành động

- Đọc Ponytail SKILL.md và hướng dẫn repo về CodeGraph, tracker, triage/domain; dùng scope nhỏ nhất đủ bao phủ yêu cầu tài liệu.
- Quick memory lookup không có hit liên quan AI-Camera-OC; không dùng facts từ memory.
- Gọi CodeGraph context/status/files đúng project: database tồn tại, 0 files/nodes/edges; không báo not-initialized, không reindex hoặc sửa `.codegraph/`. Dùng native reads/search cho tài liệu Markdown, không dùng index trống kết luận mọi file local đều không có source.
- Đọc CONTEXT.md, kiến trúc, implementation plan, readiness, ba ADR accepted và log review/plan gần nhất. Git tracked inventory là tài liệu; plan ghi chưa triển khai runtime. Không có runtime/hardware proof mới.
- Local routing toggle không bật, không chạy lma. Exploration trực tiếp; không gọi subagent hoặc gửi thông báo ra ngoài.
- Ghi nhận git status trước thay đổi để giữ nguyên AGENTS.md, index, research và các historical logs untracked có sẵn.
- Tạo docs/implementation-checklists: mục lục/ownership/dependency/tracking, phân tích kiến trúc/SOLID/gaps, 37 ca tích hợp và gate G0–G5.
- Tạo `.scratch/system-build/PRD.md` và 18 issue/checklist theo convention `issues/<NN>-<slug>.md`. Mỗi task trong 89 task gốc có ba bước cụ thể + acceptance + evidence; mọi checkbox mở, status needs-triage, execution not-started, owner mới ở mức vai trò.
- Thêm điểm vào checklist ở implementation-plan.md; sửa tham chiếu catalog/conversion từ M13/M16 thành M15/M16 đúng module Model Registry, không đổi accepted decisions.

## Quyết định khi viết checklist

- Giữ nguồn chuẩn là kiến trúc/plan/ADR hiện hành; phân biệt thiết kế, implementation, test pass và signed acceptance. Không tạo target/capacity/effort/production approval giả.
- Checklist module là issue tracker canonical, docs index chỉ link; không tạo hai bản checkbox cho cùng task. Checklist tích hợp là acceptance E2E khác module steps.
- B04 local activation có thể implement trước T02; remote signed rollout vẫn cần T02/T04. QL03 P2 báo camera-moved, geometry validity contract ở P4. O04/A05 cùng benchmark integration sau A03.
- Recorder source/pin contract chốt F04/C03 → R01 → V04; upstream của recorder không nằm trong analytics. Synthetic fixture mở G1, không coi là quality person-down G2.
- Downstream durable intent baseline tại S01, notification guard baseline; worker/provider ở W02 theo protocol, disabled không giả delivered, lab dashboard-only.
- Data engine cần lấy mẫu no-event trước ring expiry với storage/privacy budget để negative audit khả thi. UI demo/backend và đội UI sản phẩm tách ownership/handoff; G1 browser demo không thay production UI acceptance.

## Kiểm chứng

- Kiểm tĩnh 24 Markdown files trong phạm vi (23 file mới + implementation plan cập nhật): local links, table column counts, fenced blocks, trailing whitespace, task coverage/dependency references, step IDs và trạng thái unchecked: đạt.
- Đủ 18 module, 89 task nguồn duy nhất, 661 module checkboxes, 54 kiểm lỗi riêng theo module, 37 case tích hợp X01–X37; mỗi task có .01/.02/.03/.AC/.EV đúng một lần. Rà nội dung backend/ownership/dependencies và thêm link case tích hợp trong từng module.
- Git diff --check đạt; kiểm tra file mới trực tiếp vì diff mặc định không bao gồm untracked. Tracker .scratch/system-build không bị Git ignore. Git status chỉ có implementation-plan.md thay đổi ở tracked files, cùng các Markdown mới và untracked cũ giữ nguyên.
- Chưa chạy runtime/unit/integration/hardware/soak/browser hoặc field test trong lần này. Chưa ký capacity/quality/SLO/clearance; chưa stage/commit/push. CodeGraph vẫn chưa có indexed source.
