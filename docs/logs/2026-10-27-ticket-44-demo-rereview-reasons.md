# Ticket #44 — Dev-demo hiển thị lý do re-review — 2026-10-27

## Bối cảnh và quyết định
- Đọc tracker #44: `ready-for-agent`, `not-started`; dependencies #04/#20/#27 đã ghi `done` trong software lab.
- Yêu cầu implement #44 rộng hơn UI hiện có: sản phẩm queue/annotation, label correction/version/conflict/audit, operator workload và keyboard/responsive/accessibility review.
- Repo chỉ có `apps/server/static/index.html`; checklist phân biệt UI sản phẩm (`apps/dashboard/` hoặc repo UI được thống nhất) với static dev demo, và ghi demo không thay sign-off UI sản phẩm.
- Người dùng chọn rõ dev-demo-only API-backed slice, không đánh dấu ticket done; xác nhận seam: render `needs_re_review` và `re_review_reasons` từ API hiện có, không thêm taxonomy correction hoặc API mới.
- CodeGraph MCP namespace không khả dụng trong session (`tool_activate` trả unknown paged namespace); đã khảo sát trực tiếp files. Beads workspace cũng không có (`bd prime`/`bd where`).

## Thay đổi
- `apps/server/static/index.html`: khi `review.needs_re_review` bật, hiển thị lý do từ `review.re_review_reasons`; nếu field thiếu/không phải array/empty, hiển thị fallback trung tính. Nội dung đi qua `textContent` helper hiện có, không parse HTML.
- Không đổi tracker Status/Execution, không claim hoàn thành #44. Phần sản phẩm, correction/annotation semantics, UI accessibility/operator acceptance vẫn mở.

## Kiểm chứng
- `.venv-oracle/bin/python -m pytest tests/test_review_api.py -q` → 8 passed.
- `.venv-oracle/bin/python -m pytest -q` → 823 passed, 360 warnings, 126 subtests passed (142.38s).
- Python HTMLParser parse thành công; trích script kiểm bằng `node --check` → exit 0.
- `git diff --check` → pass (no whitespace errors).

## Giới hạn
- Chưa chạy browser/manual smoke; không có UI test harness trong repo. HTTP test kiểm persistence reason ở API, không kiểm browser render.
- Đây chỉ là demo slice để hỗ trợ review re-review state; không đáp ứng toàn bộ acceptance #44.
