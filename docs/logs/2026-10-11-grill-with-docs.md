# Làm rõ kế hoạch triển khai — grill-with-docs

## Phạm vi

Làm rõ kế hoạch từng module và toàn hệ thống theo yêu cầu người dùng. Chỉ ghi tài liệu; chưa được yêu cầu triển khai runtime.

## Căn cứ và hành động

- Đọc skill grill-with-docs, grilling và domain-modeling; môi trường không có Skill tool, áp dụng hướng dẫn từ SKILL.md trực tiếp.
- Đọc CONTEXT.md, quy ước docs/agents, implementation-plan.md, system-architecture.md, deployment-readiness.md và log module implementation hiện có.
- CodeGraph context không trả symbol; files trả “No files indexed”. Không suy ra trạng thái implementation từ index trống, không tự rebuild index. Chỉ đọc các tài liệu đã được dẫn chiếu.
- Git status cho thấy nhiều tài liệu và thư mục hiện có là untracked; giữ nguyên, không stage/commit/push.
- Shell sandbox lỗi bwrap loopback; dùng escalation để đọc tài liệu và git status. Đây là giới hạn môi trường.
- Plan hiện có ghi 89 task và Q1–Q3 pending; không coi đề xuất cũ là người dùng đã chấp thuận.

## Cây quyết định và vòng 1 — chờ trả lời

1. Hardware/development path: xác nhận hướng replay trên máy phát triển trước; hardware đích phải được kiểm chứng trước G1. Nhánh sau: inventory/probe → stream ownership/main-sub → decoder/SDK và capacity.
2. Storage scope: event ring + giữ clip sự kiện hay continuous NVR. Nhánh sau: pre/post, retention, outage, quota/reserve và BOM.
3. Server lab: một server nội bộ cho ingestion/evidence/review. Nhánh sau: môi trường triển khai/API/storage lab; production topology và SLA chốt riêng trước pilot.
4. Native staging: thống nhất tracker C++ ở P1, pose native ở P2 và RKNN ở P3 như implementation-plan; kiến trúc §14 hiện xếp ByteTrack C++ + pose vào Slice 3. Nhánh sau: cập nhật tài liệu kiến trúc và contracts/bàn giao theo quyết định đã xác nhận.

Các lựa chọn trên đều pending. Vòng tiếp theo cần bao phủ ODD, mục tiêu nghiệm thu, workflow review, contracts/failure semantics, ownership và triển khai từng module theo prerequisites đã chốt. Không tự đặt ngưỡng sản phẩm hoặc tạo ADR accepted khi chưa có quyết định.

## Kết quả vòng 1 — người dùng xác nhận

- Q1: chưa chốt board; inference ONNX để test luồng trên x86, Raspberry Pi hoặc board khác có runtime hỗ trợ; RKNN tối ưu sau. Thay yêu cầu hardware decode/board đích bắt buộc ở G1 bằng software baseline + buffer fixtures; kiểm chứng hardware thật trước target capacity/pilot.
- Q2: event ring + giữ clip sự kiện, không thêm NVR nhiều ngày.
- Q3: một server lab nội bộ; production topology vẫn mở.
- Q4: tracker C++ P1, native pose P2, RKNN P3 khi chọn target. Người dùng yêu cầu tương thích đầu vào/đầu ra để dễ thay engine.
- Cập nhật implementation-plan, bảng slices/FrameBuffer gate của system-architecture và deployment-readiness. Hợp đồng semantic thống nhất frame/ROI, transform/time/correlation và detection/pose/status; adapter giữ chi tiết tensor/vendor. Đây là mô tả contract cần triển khai, chưa phải code hoặc kết quả parity.
- Không tạo glossary thứ hai hoặc ADR cho lựa chọn engine baseline dễ thay thế. Stream topology, storage budget và production ADR còn thiếu đầu vào.

## Frontier vòng 2 — đề xuất, chưa xác nhận

- Q5: scope/ODD lab đầu tiên — một camera cố định, person-down trong ROI lòng đường; xe là nhánh sau, điều kiện khó đưa vào evaluation và báo unknown ngoài ODD.
- Q6: giá trị thử nghiệm evidence — pre/post 10/20 giây, ring 10 phút, server clip 7 ngày; edge giữ clip chưa ACK với budget outage 24 giờ, xử lý quota khi vượt budget cần chốt tiếp. Đây là đề xuất lab, chưa tính capacity/BOM.
- Q7: workflow lab — một vai trò reviewer, danh sách/detail/playback + confirmed/false_positive/resolved; event hiện trước clip, chưa gửi notification ngoài dashboard.
- Q8: thay engine qua config lúc startup/restart analytics, recorder tiếp tục; mỗi engine dùng manifest và conformance report. Chưa cần hot-swap mỗi frame.

## Kết quả vòng 2 — người dùng xác nhận

- Q5: yêu cầu tách tính năng cảnh báo thành pipeline riêng, register thêm khi có tính năng mới. Không suy câu trả lời này thành xác nhận ODD/một camera cố định hoặc danh sách tính năng ban đầu.
- Q6: đồng ý các target evidence lab; bổ sung placeholder mở rộng event delivery cho Kafka, RabbitMQ, WebSocket. Ghi port/contract dự kiến, không thêm broker/no-op implementation. Chưa rõ integration edge→server hay server→downstream.
- Q7: đồng ý review lab theo đề xuất.
- Q8: đồng ý đổi engine bằng config + restart analytics, recorder độc lập.
- Cập nhật plan/readiness, mô tả pipeline ở architecture và thuật ngữ Alert feature pipeline trong CONTEXT.md. Registry dùng allowlist; phạm vi chia sẻ perception và isolation còn pending.

## Frontier vòng 3 — chờ trả lời

- Q9: pipeline tách logic/state/config, chia sẻ source/perception khi tương thích hay process độc lập mỗi tính năng?
- Q10: điểm Kafka/RabbitMQ/WebSocket ở server downstream, edge delivery, hay cần cả hai?
- Q11: tính năng đầu tiên và ODD lab — person-down trước, một camera cố định/ROI lòng đường?
- Q12: khi quota cạn — ưu tiên evidence đã pin/chưa ACK, dọn ring/clip được phép, báo degraded và partial/failed khi không giữ được clip mới; không xóa im lặng hoặc drop metadata như video frame?

## Kết quả vòng 3 — người dùng xác nhận

- Q9: pipeline độc lập logic/state/config, dùng chung source/perception khi tương thích; chỉ tách process khi cần isolation.
- Q10: publisher tương lai nằm phía server downstream sau durable commit; edge giữ HTTPS.
- Q11: person-down trước, một camera cố định/ROI lòng đường; vehicle làm sau.
- Q12: bảo vệ pinned/unACK evidence; dọn dữ liệu được phép; thiếu storage thì degraded/partial/failed, metadata/outbox reserve riêng. Ghi rõ reserve hữu hạn, commit fail không ACK.
- Đồng bộ implementation-plan, system-architecture và readiness; thêm ADR-0001 về pipeline boundary và ADR-0002 về server downstream delivery. Chưa triển khai broker hoặc source.

## Frontier vòng 4 — đề xuất, chưa xác nhận

- Q13: thiếu capability hoặc pipeline exception: đánh dấu pipeline unavailable/degraded với lý do, giữ pipeline khác và recorder; shared source/native failure ảnh hưởng dependent pipelines, không chuyển thành negative hoặc âm thầm đổi engine.
- Q14: lab stack: FastAPI/Python server, PostgreSQL, filesystem evidence dưới storage adapter; React/TypeScript dashboard. Object store adapter chỉ thêm khi cần production; DB/object-store ACK/reconciliation semantics vẫn giữ.
- Q15: packaging: Docker Compose cho server lab/DB/dashboard; edge build native + Python riêng, service manager/watchdog, replay CLI dùng cùng composition; không bắt buộc container trên mọi board.
- Q16: acceptance lab: đề xuất event→dashboard P95 ≤5 giây từ durable edge commit trên LAN; chấm evidence đủ pre/post khi source/ring có dữ liệu, partial khi gap; G1 không ký recall/FPS. Chất lượng/ODD target và RPO/RTO target hardware cần baseline P0/P2 trước khi chốt pilot.

## Kết quả vòng 4 — người dùng xác nhận và sửa đề xuất

- Q13: enabled mà config thiếu/sai phải panic ngay; disabled có thể unavailable. Đã sửa startup policy thành fail-fast, không silent skip; reject bad activation giữ last-known-good, recorder độc lập. Runtime errors sau start vẫn cần chốt riêng.
- Q14: FastAPI/Python + MongoDB; không coi đây là xác nhận React/TypeScript hoặc filesystem evidence. Đổi tham chiếu PostgreSQL hiện hành sang MongoDB, giữ unique revision/conditional review và transaction outbox. Thêm ADR-0003; kiểm tra MongoDB transaction requirements/write concern theo official docs.
- Q15: đồng ý Compose server/DB/dashboard và native/Python edge/service manager/replay chung composition.
- Q16: đồng ý target LAN event commit→dashboard P95 ≤5 giây, tách temporal verification/evidence finalize và chưa ký recall/FPS. Ghi clock correlation vào acceptance.

## Frontier vòng 5 — chờ trả lời

- Q17: runtime pipeline errors sau startup thành công: fault/degraded rõ, bounded retry/restart/reset state, pipeline độc lập và recorder tiếp tục; shared native crash có thể restart toàn analytics, không silent fallback.
- Q18: MongoDB lab một-member replica set để phục vụ transaction, không phải HA; production topology chốt riêng. Cần smoke test commit/retry trên exact version.
- Q19: React/TypeScript dashboard và evidence filesystem qua storage adapter cho lab, object store sau nếu cần. Hai lựa chọn này chưa được xác nhận ở Q14.

## Kết quả vòng 5 — người dùng xác nhận và thu gọn UI

- Q17: đồng ý runtime fault policy, bounded retry/reset và shared analytics restart khi native crash; giữ config startup fail-fast.
- Q18: đồng ý MongoDB replica set một member + persistent volume/transaction tests cho lab; không phải HA.
- Q19: chỉ làm giao diện dev demo đơn giản để test trực quan, đội giao diện riêng ghép UI sau. Không coi đây là xác nhận React/TypeScript. Chọn HTML/JS nhỏ do FastAPI phục vụ qua public API, không frontend app/container riêng; UI03/UI04 là scope bàn giao đội UI ở phase sau.
- Filesystem evidence lab giữ là lựa chọn triển khai tạm, có thể đảo ngược và chưa phải production storage accepted; không hỏi lại một quyết định reversible không cần thiết.
- Đồng bộ plan, kiến trúc và ADR backend. Giữ APIs/schemas/fixtures/auth/error/revision contracts làm bàn giao, không để UI demo sở hữu business transitions.
- Tổng hợp Q1–Q19 và chuyển facts/hardware/ODD/quality/production decisions sang task/gate có owner. Chờ người dùng xác nhận shared understanding trước triển khai; không tự claim issues hoặc viết runtime.

## Giới hạn kiểm chứng sau vòng 5

Kiểm tra trực tiếp 7 Markdown files đã sửa/tạo: bảng Q1–Q19 đủ và đúng thứ tự, ADR links tồn tại, fences cân bằng, whitespace đạt. Đã sửa các câu pending runtime/topology/UI lỗi thời ở tài liệu hiện hành; log lịch sử giữ nguyên nội dung từng vòng.

## Yêu cầu commit

Người dùng yêu cầu commit thay đổi. Phạm vi: CONTEXT.md, ba tài liệu architecture/readiness/implementation-plan, ba ADR, log phỏng vấn này và ba quy ước docs/agents được plan dẫn chiếu. Giữ ngoài commit AGENTS.md, .codegraph/, traffic-ai-camera-research/ và các log lịch sử untracked có sẵn. Dùng commit message `docs: clarify module implementation plan`; không push. Chỉ kiểm tra tài liệu/staged diff, không chạy runtime tests cho thay đổi Markdown.

Chưa chạy runtime, hardware probe, benchmark hoặc field test. Giữ CONTEXT.md làm glossary theo quy ước repo, đã thêm thuật ngữ pipeline tính năng cảnh báo. Hai ADR ghi quyết định đã xác nhận, không chứng minh implementation. Chỉ thay Markdown, không stage/commit/push.
