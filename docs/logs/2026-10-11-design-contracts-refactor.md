# Áp dụng review và refactor tài liệu — 2026-10-11

## Yêu cầu và phạm vi

Người dùng yêu cầu cập nhật theo review, loại bỏ quyết định lỗi thời/trùng lặp để dễ tham khảo, rồi đồng bộ nghiên cứu. Đây là authorization sửa tài liệu thiết kế/backlog; không triển khai source hoặc chạy thiết bị, không claim ticket, commit/push.

## Hành động và quyết định

- CodeGraph status đúng project trả 0 files/nodes/edges; dùng Markdown để sửa tài liệu, không rebuild index. Ponytail áp dụng như lượt review; không cần worker hoặc subagent. Memory lookup lượt review không có nội dung dự án, không dùng memory facts.
- Thêm contracts làm nguồn chuẩn cho PerceptionPipeline, full snapshots/immutable origin, pin intent/receipt/anchor, evidence dimensions, review freshness/correction, downstream eligibility, replay và gate theo target. ADR-0004 ghi chấp nhận thiết kế theo yêu cầu người dùng; không sửa ngược lịch sử ADR-0001–0003.
- MVP chọn pin khi persist event và sizing ring theo anchor-to-pin delay/recovery, không thêm candidate hold mặc định. Thiếu video báo partial/missing, không hứa khôi phục quá retention. Policy site vẫn cần operator sign-off trước pilot.
- Đồng bộ architecture/plan/readiness, checklist module, ticket acceptance và ma trận X01–X45. #31/#35 bỏ hard blocker RKNN, thêm conditional blocker #30 cho target RKNN; ONNX vẫn phải exact-target conformance/capacity.
- Tạo docs/README.md làm điểm vào. Tracker slices là nơi duy nhất giữ Status/Execution; checklist module giữ task/acceptance/evidence. Bỏ bản sao 672 dòng breakdown, graph/phase/status trùng và boilerplate DoR/Done lặp ở 18 module; thay bằng dẫn nguồn chuẩn. Giữ 89 task IDs và 50 ticket, không tick acceptance mới.
- Review report được đánh dấu đã xử lý ở mức thiết kế, có mapping F01–F10→contracts/tickets/tests; nội dung review gốc và logs lịch sử không dùng làm spec hiện hành.
- Nghiên cứu đổi PostgreSQL/MQTT ingress/native-after-profiling/ngưỡng và timeline cũ thành thiết kế hiện hành: person-down trước, native C++/Python, HTTPS/FastAPI/MongoDB, ring10 phút/pre10/post20, gate theo target. Giữ quan sát giá09–10-10 và sources/license notes theo thời điểm; không refresh quote hoặc tuyên bố clearance mới. Cập nhật README/outline/fields tương ứng.

## Kiểm chứng

- Kiểm 104 Markdown và 698 link local: đích file tồn tại; 12 code fences đóng đúng, 2 JSON samples parse được. Đây là link filesystem trong workspace, không phải kiểm mọi HTTP URL hoặc portability của checkout.
- Parse 4 YAML documents/samples (outline/fields và ví dụ architecture/readiness) thành công.
- Đủ 89/89 task IDs ở plan, module checklists và mapping 50 tickets; dependency nguồn trong từng module khớp plan, bảng blockers/conditional trong PRD khớp file ticket.
- DAG cả ONNX/RKNN không có chu trình. Ancestors của pilot #49: ONNX không chứa #29/#30, RKNN có cả hai; cả hai vẫn chứa G1/G2/capacity/rollout/power-cut/native recovery/central restore prerequisites.
- Có đúng 45 cases X01–X45 duy nhất. Không tick acceptance hoặc đổi Execution sang done.
- git diff --check sạch sau khi sửa khoảng trắng ở dòng thay đổi; diff chỉ gồm tài liệu và research YAML metadata, không source/config runtime/tests. Script kiểm ở /tmp/check_camera_docs.py.
- Không có runtime/hardware/browser/quality tests từ lượt sửa tài liệu này.

## Đầu ra

- [Mục lục hiện hành](../README.md).
- [Hợp đồng tích hợp](../architecture/contracts.md).
- [Tracker thực thi](../../.scratch/system-build-slices/PRD.md).
- [Research đã đồng bộ](../../traffic-ai-camera-research/report.md).

Các file untracked/index/AGENTS và logs đã có được giữ nguyên; không stage hoặc chỉnh Git metadata. Các script chỉnh/kiểm tạm ở /tmp không là source sản phẩm.
