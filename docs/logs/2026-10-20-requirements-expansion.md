# Nhật ký mở rộng requirement — 2026-10-20

## Hoạt động và nguồn

- Người dùng yêu cầu `/grill-with-docs`; đã đọc skills grilling/domain-modeling và hướng dẫn docs/agents/domain.md, issue-tracker.md.
- Đã phỏng vấn theo cây quyết định Q1–Q35. Q35 xác nhận hiểu thống nhất và cho phép cập nhật tài liệu, không triển khai code.
- CodeGraph lần đầu mặc định trả index DSH; gọi lại với projectPath `/home/tieubaoca/AI/AI-Camera-OC` xác định đúng repo. Index chủ yếu source; khảo sát tài liệu bằng native read sau đó.
- Teammate requirements-reader khảo sát read-only; lead đọc kiểm chứng CONTEXT.md, ADR-0001, implementation-plan và deployment-readiness.
- Có nhiều thay đổi dở dang trong working tree trước tác vụ (bao gồm deployment-readiness và tracker); không revert, stage, commit hay ghi đè chúng.

## Quyết định đã xác nhận

### Phạm vi và thứ tự (Q1–Q9)

- 13 nhóm gốc là danh mục mục tiêu, không bắt buộc triển khai đồng loạt. Person-down đạt gate trước, tai nạn xe sau, các nhóm mới mở rộng theo giai đoạn; giữ thứ tự ADR-0001.
- Camera cố định ngoài trời đường phố/vỉa hè đô thị. Person-down đầu tiên vẫn ROI lòng đường.
- RF-DETR + ViTPose là ứng viên đánh giá bổ sung, không thay baseline đã chốt và không chứng minh độ phủ tình huống.
- AI tạo sự kiện nghi ngờ; người trực xác minh; không tự kết luận pháp lý, y tế, nguyên nhân hay trách nhiệm.
- Cho phép cấu hình vùng/lịch theo camera, không đòi AI tự suy mọi quy định.
- Person-down giữ nhánh fall có onset, persistent lying thiếu onset và person on stationary vehicle với ưu tiên riêng, không suppress tự động.
- Tai nạn: nghi ngờ sự cố đường bộ có xe tham gia, gồm xe–xe, xe–người và xe tự ngã/lật/đâm vật cố định. Trạng thái tĩnh thiếu diễn biến chỉ là dấu hiệu nguy hiểm/chưa rõ, không tự kết luận va chạm.

### Danh mục và nhãn (Q10–Q26)

Người dùng yêu cầu chốt định nghĩa requirement cả 13 nhóm trong buổi này, không chỉ ghi danh mục nháp. Các giá trị số và nghiệm thu thực địa vẫn pending theo Q30–Q33.

1. Cháy/khói: tách nghi ngờ lửa và nghi ngờ khói; một dấu hiệu đủ để xét cảnh báo, có thể liên kết sự kiện. Hơi nước/bụi/phản xạ/đèn pha là hard negatives.
2. Ngập: nước đạt vùng/mốc cảnh báo cấu hình và duy trì đủ lâu; không hứa đo độ sâu centimet/khả năng xe vượt qua. Phân biệt đường ướt/vũng nhỏ/phản chiếu.
3. Đổ trộm rác: tách nghi ngờ hành vi bỏ/đổ rác có diễn biến và rác xuất hiện/tồn lưu thiếu diễn biến trong vùng không được phép; không gán người đi ngang là thủ phạm.
4. Lấn chiếm vỉa hè: xe, hàng hóa/quầy/bàn ghế và vật cản chiếm vùng cần thông thoáng đủ lâu, có ngoại lệ theo site; người đi qua không phải chiếm dụng.
5. Đỗ sai chỗ: xe đứng yên quá thời gian theo vùng/lịch không được phép; phân biệt đèn đỏ, ùn tắc/chờ theo luồng; thiếu quan sát là chưa rõ. Không thêm ANPR/chủ xe.
6. Tụ tập: hai lớp tập trung đông người (số lượng/mật độ/thời gian) và nghi ngờ gây rối có hành vi xô đẩy/đánh nhau, đập phá, ném vật vào người/tài sản hoặc cùng chiếm/chặn luồng giao thông. Đông người/chạy/vung tay riêng lẻ không đủ kết luận gây rối. Ngoại lệ điểm chờ/hàng đợi/sự kiện hợp lệ.
7. Ẩu đả: nghi ngờ tương tác bạo lực ít nhất hai người dựa trên chuỗi hành động. Thể thao/đùa/ôm/hỗ trợ người ngã là hard negatives; không xác định người tấn công/vũ khí.
8. Tai nạn như trên.
9. Người ngã/person-down như trên.
10. Vào vùng nguy hiểm: người vào ROI theo lịch, không xác định danh tính/quyền truy cập; người được phép vẫn có thể cần cảnh báo an toàn. Chưa mở phạm vi phương tiện.
11. Vật bỏ quên: tách người đặt rồi rời xa và vật tồn lưu chưa rõ người liên quan; có ngoại lệ hàng hóa/vật cố định hợp lệ. Không suy chủ sở hữu/ý định/tính nguy hiểm.
12. Cây đổ: cây/cành lớn đã đổ vào vùng, có hoặc thiếu diễn biến bắt đầu; không dự báo cây sắp đổ/nghiêng. Kích thước tối thiểu pending.
13. Đèn đường hỏng: quan sát đèn không sáng trong lịch dự kiến bật sau khoảng chuyển tiếp; nguyên nhân cần người trực xác minh. Chưa thêm sáng yếu/nhấp nháy/chẩn đoán điện.

Bổ sung nhánh riêng nghi ngờ tác động phá hoại tài sản: đập/đá/phá kéo hoặc ném vật vào tài sản; không khẳng định thiệt hại/giá trị/ý định. Hard negatives sửa chữa/dọn dẹp/thao tác bình thường. Không ép nhánh này vào ẩu đả. Chưa thêm tự gây hại độc lập; vùng nguy hiểm/person-down xử lý biểu hiện tương ứng.

Nhiều nhãn có thể liên kết một diễn biến, chống lặp từng nhóm; không bắt buộc tự hợp nhất chính xác liên camera hoặc xóa nhãn khác.

### Vận hành và cấu hình (Q27–Q34)

- Mục tiêu ngày/đêm/mưa trong giới hạn đã kiểm thử theo từng nhóm. Điều kiện chưa kiểm thử không coi đã hỗ trợ; thiếu hình ảnh là unknown/degraded, không negative.
- Dashboard trước, người trực xác minh; chưa SMS/Zalo/cuộc gọi/tự điều phối cứu hộ.
- Mặc định khẩn: lửa/khói, person-down, tai nạn, ẩu đả, người vào vùng nguy hiểm. Cao: ngập, cây đổ, gây rối, phá hoại, vật nghi bỏ quên. Thường: rác, chiếm dụng, đỗ sai, tập trung đông người đơn thuần, đèn không sáng. Có thể cấu hình theo site/bối cảnh; không đồng nhất severity với confidence.
- Module register độc lập, logic/state/config theo module × camera; chia sẻ perception tương thích, không mặc định process riêng hay inference trùng. Thêm module không chứng minh đủ tài nguyên bật đồng thời.
- Config bật/tắt, ROI/lịch, ngưỡng và ngoại lệ riêng. Module bật mà thiếu/sai config bắt buộc báo lỗi rõ theo fail-fast baseline, không silent skip.
- Giá trị số chưa có ghi pending, phê duyệt trước nghiệm thu; không tự bịa ngưỡng chung.
- Quality gate riêng từng nhóm: positives/hard negatives, bỏ sót, báo nhầm theo camera/giờ, latency từ diễn biến đủ điều kiện đến cảnh báo, tải review; số mục tiêu pending theo site/workload.
- Orin NX là dòng ứng viên đã chọn (không Xavier NX); RAM/SKU/checkpoint/SDK và số camera/FPS/capacity chưa chốt. Benchmark trên actual SKU toàn hệ thống gồm ghi clip/upload; không lấy inference riêng làm capacity. Thay engine phải conformance và event regression.
- Evidence cố định raw clip 10 giây trước/20 giây sau mốc điều kiện đủ tạo cảnh báo. Lưu nguồn gốc, thời gian, mốc bắt đầu quan sát/thời gian duy trì/vùng/config. Đánh dấu đầy đủ/thiếu clip theo hợp đồng hiện hành.
- Chấp nhận clip chỉ bao phủ một phần sự kiện kéo dài: không chứng minh toàn bộ thời gian tồn tại hoặc bảo đảm xem được lúc bắt đầu. Lịch sử quan sát không thay video; nếu onset ngoài clip phải thể hiện rõ. Không tự thêm nhiều clip hay NVR dài ngày.

## Hiệu chỉnh đã xác nhận Q36 — mốc evidence

Sau Q35, teammate phát hiện contracts §3 hiện lấy onset cho fall và first qualifying observation cho persistence, khác Q34 lấy mốc đủ điều kiện cảnh báo. Lead đọc kiểm chứng và hỏi lại, không tự đổi baseline. Người dùng Q36 xác nhận:

- Giữ anchor person-down baseline theo contracts §3: onset estimate hoặc first qualifying observation; không dịch anchor theo trigger muộn.
- Các nhóm mới dùng mốc đủ điều kiện cảnh báo. Cả hai policy giữ clip 10 giây trước/20 giây sau; ghi rõ policy theo loại và provenance.
- Q36 hiệu chỉnh phần khái quát anchor của Q32/Q34 và các đoạn tổng kết bên trên. Giới hạn clip với sự kiện kéo dài, metadata không thay video, tính bất biến request và completeness theo requested interval vẫn giữ.
- Cho phép đồng bộ phần bổ sung policy nhóm mới trong contracts, không thay bảng baseline hoặc sửa runtime trong tác vụ docs.

## Kế hoạch tài liệu và kiểm tra

- Luồng nghiệp vụ: tạo đặc tả danh mục, đồng bộ CONTEXT/architecture/plan/mục lục; giữ các nội dung baseline không bị thay đổi.
- Luồng công nghệ: cập nhật ứng viên model/hardware và readiness/lab đối chiếu, không tuyên bố capability đã đạt.
- Lead review định nghĩa, pending, evidence và references; kiểm tra diff không chạm code/không xóa thay đổi có sẵn.
- Chưa có benchmark, huấn luyện hoặc kiểm thử runtime trong tác vụ docs này.

## Kết quả thực thi và review

- task-1 requirements-reader: khảo sát baseline read-only, hoàn tất.
- task-2 scenario-docs: tạo `docs/requirements/urban-safety-scenarios.md`; đồng bộ CONTEXT, docs README, architecture, implementation plan và contracts (scope được mở để bổ sung Q36). Đủ US01–US14: 13 nhóm gốc + nhánh phá hoại riêng.
- task-3 technology-docs: tạo `docs/requirements/technology-candidates.md`; cập nhật readiness và lab-profile; giữ baseline và bảo toàn nội dung readiness có sẵn trước tác vụ.
- Lead đọc đặc tả, candidate và diff tài liệu; yêu cầu cả hai teammate đồng bộ Q36, không chấp nhận mâu thuẫn anchor còn pending sau khi người dùng đã quyết định.
- Self-check teammate: scenario 88/88 local link targets; technology 22/22; git diff --check pass. Teammate technology kiểm chứng nội dung readiness trước tác vụ được bảo toàn.
- Lead chạy kiểm tra độc lập bằng python3: **110 local link targets tồn tại**, **14 hàng definition/params/priority + 14 hàng hard-negative/gate**, Q36 và pending hiện diện. Kiểm bằng git HEAD: bảng/request anchor baseline và toàn bộ contracts từ §3.1 trở đi **không đổi**. `git diff --check` pass.
- Lệnh validator lần đầu dùng `python` không có trên host; chạy lại bằng `python3` thành công. Không ghi nhận lần lỗi command là kiểm tra pass.
- Link check chỉ xác minh target path, không xác minh fragments. Không chạy runtime suite hoặc benchmark vì thay đổi trong phạm vi docs.
- Review chấp nhận giao tài liệu; chưa chấp nhận runtime capability, quality, target capacity, model rights hay field deployment. Các ngưỡng/site/workload/SKU/checkpoint và người phê duyệt vẫn cần hoàn thiện theo gates trong đặc tả.
- Không sửa code, đóng ticket triển khai, thay ADR accepted, stage hoặc commit trong tác vụ này; các code/tracker/report changes trước tác vụ không thuộc delivery.
