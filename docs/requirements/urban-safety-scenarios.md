# Requirement tình huống an toàn đô thị

**Ngày xác nhận:** 2026-10-20, Q35 và làm rõ anchor Q36. **Trạng thái:** requirement nghiệp vụ đã xác nhận; không phải capability đã triển khai hoặc nghiệm thu. Nguồn quyết định: [phỏng vấn Q1–Q36](../logs/2026-10-20-requirements-expansion.md). Tài liệu này là nguồn chuẩn cho định nghĩa tình huống, tham số cần chốt và giới hạn quan sát; [contracts](../architecture/contracts.md) giữ hợp đồng tích hợp, [plan](../architecture/implementation-plan.md) giữ phân kỳ, [readiness](../architecture/deployment-readiness.md) giữ bằng chứng/gate triển khai.

## 1. Phạm vi và nguyên tắc chung

- Danh mục gồm 13 nhóm gốc và nhánh phá hoại riêng, không yêu cầu triển khai đồng loạt. Giữ [ADR-0001](../adr/0001-feature-pipeline-boundaries.md): person-down đạt gate trước, tai nạn có xe sau; các nhóm còn lại mở theo giai đoạn với gate riêng, chưa hứa thứ tự hoặc lịch.
- Camera cố định ngoài trời, đường phố/vỉa hè đô thị; baseline person-down đầu tiên vẫn một camera/ROI lòng đường. PTZ, góc nhìn hoặc miền hiện trường khác không tự được hỗ trợ.
- AI tạo **sự kiện nghi ngờ**, dashboard chuyển người trực xác minh. Không kết luận pháp lý, y tế, nguyên nhân, trách nhiệm, ý định hoặc danh tính. Chưa có SMS/Zalo/cuộc gọi hay tự điều phối cứu hộ; không thêm ANPR/chủ xe, tự gây hại độc lập hoặc nhận diện quyền truy cập.
- Mục tiêu ngày/đêm/mưa chỉ được coi hỗ trợ trong ODD đã kiểm thử **theo từng nhóm**. Che khuất, thiếu hình ảnh, mất continuity hoặc điều kiện chưa kiểm thử phải là unknown/degraded/unsupported phù hợp, không phải negative.
- Mỗi module đăng ký độc lập; logic/state/config theo **module × camera** (và phiên quan sát). Bật/tắt, ROI, lịch, ngưỡng và ngoại lệ riêng. Chia sẻ source/detector/tracker/pose khi tương thích; không mặc định process riêng hay decode/inference trùng. Thêm module không chứng minh đủ tài nguyên để bật tất cả đồng thời.
- Module enabled thiếu/sai config bắt buộc phải fail-fast với lỗi rõ theo baseline; không silent skip. Module disabled được biểu diễn rõ. Không dùng degraded runtime để bỏ qua validation startup.
- Một diễn biến có thể mang nhiều nhãn được liên kết; chống lặp từng nhóm, không ép hợp nhất liên camera chính xác hoặc xóa nhãn khác. Đông người, gây rối, ẩu đả và phá hoại không phải từ đồng nghĩa.

## 2. Danh mục requirement và tham số

Các ID dưới đây là ID requirement tài liệu, **không** là enum/schema API hoặc ticket triển khai. Mọi ngưỡng số chưa ghi giá trị đều **pending theo site**, cần owner phê duyệt trước nghiệm thu, không dùng chung một ngưỡng cho mọi nhóm. Cột ưu tiên là mặc định Q29, có thể cấu hình theo site/bối cảnh; severity không phải confidence.

| ID / nhóm | Điều kiện và nhánh phải phân biệt | Tham số/config cần có; giá trị pending nếu chưa chốt | Ưu tiên mặc định |
|---|---|---|---|
| US01 — Cháy/khói | Tách nghi ngờ lửa và nghi ngờ khói; một dấu hiệu đủ để xét cảnh báo, có thể liên kết hai sự kiện; không bắt buộc đồng thời lửa và khói | ROI, ngưỡng quan sát/duy trì từng dấu hiệu, ngoại lệ nguồn khói/lửa hợp lệ theo site | Khẩn |
| US02 — Ngập | Nước đạt vùng/mốc cảnh báo cấu hình và duy trì đủ lâu; không hứa đo độ sâu centimet hoặc khả năng xe vượt qua | ROI/mốc cảnh báo, thời gian duy trì, điều kiện quan sát mặt đường, ngoại lệ | Cao |
| US03 — Đổ trộm rác | Tách nghi ngờ hành vi bỏ/đổ rác có diễn biến và rác xuất hiện/tồn lưu thiếu diễn biến trong vùng không được phép; không gán người đi ngang là thủ phạm | Vùng/lịch không cho phép, đối tượng rác, thời gian tồn lưu, ngoại lệ thu gom/site | Thường |
| US04 — Lấn chiếm vỉa hè | Xe, hàng hóa/quầy/bàn ghế hoặc vật cản chiếm vùng cần thông thoáng đủ lâu; áp dụng ngoại lệ site; người đi qua không là chiếm dụng | ROI cần thông thoáng, loại vật/xe, thời gian chiếm dụng, lịch và ngoại lệ hợp lệ | Thường |
| US05 — Đỗ sai chỗ | Xe đứng yên quá thời gian trong vùng/lịch không được phép; phân biệt chờ theo luồng/đèn đỏ/ùn tắc; thiếu quan sát là chưa rõ | ROI, lịch hạn chế, thời gian đứng yên, tolerance chuyển động, ngoại lệ luồng/chờ | Thường |
| US06 — Tụ tập/gây rối | Hai lớp: tập trung đông người theo số lượng/mật độ/thời gian; nghi ngờ gây rối có xô đẩy/đánh nhau, đập phá, ném vật vào người/tài sản hoặc cùng chiếm/chặn luồng giao thông. Đông người/chạy/vung tay riêng lẻ không đủ kết luận gây rối | ROI/lịch, số lượng/mật độ/thời gian, chuỗi hành vi gây rối, vùng luồng, ngoại lệ điểm chờ/hàng đợi/sự kiện hợp lệ | Thường với đông người; Cao với gây rối |
| US07 — Ẩu đả | Nghi ngờ tương tác bạo lực ít nhất hai người dựa trên chuỗi hành động; không xác định người tấn công hoặc vũ khí | ROI/lịch, khoảng quan sát chuỗi tương tác, ngưỡng bằng chứng, ngoại lệ hoạt động hợp lệ | Khẩn |
| US08 — Tai nạn có xe | Nghi ngờ sự cố đường bộ có xe tham gia: xe–xe, xe–người, xe tự ngã/lật/đâm vật cố định. Trạng thái tĩnh thiếu diễn biến chỉ là dấu hiệu nguy hiểm/chưa rõ, không tự kết luận va chạm | ROI đường bộ, loại tương tác, history/continuity, ngưỡng temporal/geometry nếu dùng; không suy tai nạn chỉ từ overlap/TTC | Khẩn |
| US09 — Person-down | Giữ ba nhánh: fall có onset; persistent lying thiếu onset; person on stationary vehicle có ưu tiên riêng, không suppress tự động. Không chẩn đoán ngủ/bất tỉnh/đột quỵ | ROI lòng đường baseline, onset/history, thời gian persistence, association xe đứng yên/đứng thẳng từ trước, ưu tiên và danger overrides từng nhánh | Khẩn cho person-down; on-vehicle có ưu tiên review riêng theo policy baseline |
| US10 — Vào vùng nguy hiểm | Người vào ROI theo lịch; không xác định danh tính/quyền truy cập. Người được phép vẫn có thể cần cảnh báo an toàn; chưa mở phương tiện | ROI nguy hiểm, lịch, điều kiện vào vùng/duy trì và ngoại lệ an toàn theo site | Khẩn |
| US11 — Vật bỏ quên | Tách người đặt rồi rời xa và vật tồn lưu chưa rõ người liên quan; không suy chủ sở hữu, ý định hoặc tính nguy hiểm | ROI/lịch, loại/kích thước vật, khoảng cách rời xa, thời gian tồn lưu, ngoại lệ hàng hóa/vật cố định hợp lệ | Cao |
| US12 — Cây đổ | Cây/cành lớn đã đổ vào vùng, có hoặc thiếu diễn biến bắt đầu; không dự báo cây sắp đổ/nghiêng | ROI, kích thước tối thiểu cây/cành, điều kiện tồn tại/quan sát; các giá trị pending | Cao |
| US13 — Đèn đường hỏng | Quan sát đèn không sáng trong lịch dự kiến bật sau khoảng chuyển tiếp; người trực xác minh nguyên nhân. Chưa thêm sáng yếu/nhấp nháy/chẩn đoán điện | Vùng/đèn cần quan sát, lịch bật, khoảng chuyển tiếp, thời gian xác nhận không sáng, điều kiện nhìn thấy đèn | Thường |
| US14 — Nhánh phá hoại tài sản | Nghi ngờ đập/đá/phá kéo hoặc ném vật vào tài sản; độc lập với ẩu đả, có thể liên kết gây rối. Không khẳng định thiệt hại/giá trị/ý định | ROI/tài sản quan sát, chuỗi hành động và thời gian/ngưỡng bằng chứng, ngoại lệ sửa chữa/dọn dẹp | Cao |

## 3. Hard negatives và gate từng nhóm

Mỗi dòng phải có positives của **từng nhánh**, hard negatives và tình huống unknown/thiếu quan sát trong tập đánh giá có version. Các ví dụ dưới đây là coverage tối thiểu cần kiểm thử, không phải rule tự động suppress khi chưa có bằng chứng. Gate chung ở §5 áp dụng cho mọi dòng; chưa có nhóm nào được nghiệm thu chỉ nhờ danh mục này.

| ID | Hard negatives / ranh giới phải kiểm thử | Gate riêng cần chứng minh |
|---|---|---|
| US01 | Hơi nước, bụi, phản xạ, đèn pha; nguồn hợp lệ theo site | Đánh giá lửa/khói riêng và khi cùng xuất hiện; không cần cả hai mới cảnh báo |
| US02 | Đường ướt, vũng nhỏ, phản chiếu | Phân biệt nước đạt/không đạt mốc, persistence và mốc không nhìn rõ |
| US03 | Thu gom hợp lệ, vật/rác có sẵn, người đi ngang | Hành vi có diễn biến khác tồn lưu thiếu onset; không gán tác nhân khi thiếu liên kết |
| US04 | Người đi qua, hàng hóa/xe hợp lệ theo ngoại lệ | Vùng cần thông thoáng, thời lượng và ngoại lệ đúng camera/lịch |
| US05 | Đèn đỏ, ùn tắc, xe chờ theo luồng, dừng ngắn hợp lệ | Đủ history mới xét vượt thời gian; mất quan sát không thành vi phạm |
| US06 | Điểm chờ, hàng đợi, sự kiện hợp lệ; chạy/vung tay riêng lẻ | Tách đông người và gây rối; hành vi/chặn luồng phải đủ bằng chứng |
| US07 | Thể thao, đùa, ôm, hỗ trợ người ngã | Chuỗi tương tác ít nhất hai người; action mơ hồ không thành bạo lực chắc chắn |
| US08 | Near-miss, overlap do phối cảnh, dừng đèn đỏ/kẹt xe; xe tĩnh thiếu diễn biến | Có xe trong mọi nhánh; tách dấu hiệu tĩnh/chưa rõ khỏi nghi va chạm, gate độc lập person-down |
| US09 | Ngồi/cúi/nhặt đồ; ngả trên xe đứng yên, hỗ trợ người ngã | Fast/slow fall, thiếu onset, occlusion/đổi track/gap, xe đổ/ngã cạnh xe; không suppress on-vehicle |
| US10 | Người ngoài ROI, ngoài lịch; trường hợp được phép vẫn có rủi ro | Crossing/ROI/lịch đúng; không dựa vào danh tính hoặc quyền truy cập; chưa claim phương tiện |
| US11 | Hàng hóa/vật cố định hợp lệ; người đứng gần vật có sẵn | Phân biệt đặt rồi rời xa và tồn lưu không rõ người; không suy sở hữu/nguy hiểm |
| US12 | Cây đứng/nghiêng, bóng cây, cành nhỏ ngoài phạm vi | Cây/cành lớn đã đổ trong ROI, có/thiếu onset; kích thước tối thiểu được ký |
| US13 | Ban ngày/ngoài lịch bật, khoảng chuyển tiếp, đèn bị che/khuất | Đủ khả năng nhìn thấy và đủ thời gian; không suy lỗi điện từ ảnh tối |
| US14 | Sửa chữa, dọn dẹp, thao tác bình thường | Có chuỗi tác động vào tài sản; không ép thành ẩu đả hoặc kết luận thiệt hại |

## 4. Evidence và sự kiện kéo dài

- Theo Q34/Q36, mọi policy giữ raw clip cố định **10 giây trước/20 giây sau anchor theo loại sự kiện**, trên thời gian nguồn. **Person-down giữ nguyên baseline:** fall dùng onset estimate có provenance; persistent lying/on-vehicle thiếu onset dùng first qualifying observation của chuỗi persistence theo contracts §3. **Các nhóm mới dùng mốc đủ điều kiện tạo cảnh báo** (alert-condition anchor), phụ thuộc rule/ROI/lịch/ngưỡng đã phê duyệt. Không dùng thời điểm dashboard nhận hoặc người trực review.
- Lưu provenance, camera/phiên, thời gian, mốc bắt đầu quan sát, thời gian duy trì, vùng/config và lý do thiếu quan sát. Phân biệt mốc bắt đầu quan sát, onset có bằng chứng, mốc đủ điều kiện và thời điểm gửi/nhận cảnh báo; không gán onset khi chỉ thấy tồn lưu.
- Complete/partial/missing và actual ranges/gaps tuân theo hợp đồng evidence. **Complete clip không có nghĩa full episode**: một vật tồn lưu lâu hoặc ngập kéo dài có thể chỉ được nhìn thấy một đoạn trong clip. Nếu onset ngoài clip hoặc không quan sát được, phải thể hiện rõ.
- Metadata duration/lịch sử quan sát không thay video, không chứng minh toàn bộ thời gian tồn tại và không bảo đảm xem được lúc bắt đầu. Không tự thêm nhiều clip, kéo dài clip hoặc NVR nhiều ngày.
- **Policy theo loại đã xác nhận Q36:** [contracts §3](../architecture/contracts.md#3-evidence-request-anchor-và-pin-receipt) giữ bảng baseline person-down và bổ sung policy nhóm mới; không coi onset/first qualifying observation là alert-condition anchor. Đây là làm rõ requirement, không đổi code hoặc interval/request đã ACK. Trước triển khai nhóm mới phải có policy version, fixtures và regression, giữ lineage evidence đã có.

## 5. Quality, hiệu năng và điều kiện mở module

Trước nghiệm thu **mỗi nhóm tại mỗi profile site/workload** phải có:

1. Định nghĩa positives theo từng nhánh, hard negatives, unknown/unsupported; ODD ngày/đêm/mưa, pixel-on-target, góc nhìn/che khuất và lịch/ROI có version, owner ký.
2. Báo cáo bỏ sót, báo nhầm theo camera/giờ, latency từ **diễn biến đủ điều kiện** đến cảnh báo và tải review; các mục tiêu số **pending theo site/workload**. Không đánh đồng latency này với target lab commit→dashboard đã chốt trong plan.
3. Kiểm tra config enabled invalid fail-fast, isolation state/config module × camera, reset khi mất continuity, dedup trong nhóm và nhiều nhãn liên kết mà không mất nhãn/audit.
4. Chứng minh raw clip/ranges/completeness trung thực, cả sự kiện dài/onset ngoài clip, mất nguồn và evidence chưa đủ; metadata đến trước clip không được giả complete.
5. Benchmark **toàn hệ thống** trên actual SKU: perception, rule evaluation, recorder/ghi clip, upload, concurrency, storage và nhiệt; không lấy inference riêng làm capacity hoặc suy module độc lập là tài nguyên vô hạn.

Orin NX là dòng ứng viên được chọn, không phải Xavier NX; RAM/SKU, checkpoint/SDK, số camera/FPS/capacity chưa chốt. RF-DETR + ViTPose là ứng viên đánh giá bổ sung, không thay baseline hoặc tự chứng minh coverage. Xem [ứng viên công nghệ](technology-candidates.md); mọi đổi engine phải qua conformance và event regression.

## 6. Pending và bàn giao

| Việc còn mở | Owner/gate cần xử lý | Không được suy thành |
|---|---|---|
| Ngưỡng thời gian, mật độ/số lượng, kích thước, khoảng cách, ROI/lịch/ngoại lệ từng nhóm | Product/operations + Domain/ML, trước quality acceptance của nhóm | Một threshold chung hoặc số mặc định đã được duyệt |
| Priority theo site và policy riêng on-vehicle/ambiguous, danger overrides | Product/operations trước pilot; giữ không suppress baseline | Severity bằng confidence; tự bỏ hàng review |
| ODD/positives/hard negatives và mục tiêu bỏ sót, FP/camera/giờ, latency, review load | QA/ML + operations ký theo site/workload | Ngày/đêm/mưa mọi điều kiện đều được hỗ trợ |
| Triển khai policy/version/fixtures và hồi quy evidence cho nhóm mới theo Q36; baseline person-down giữ nguyên | Domain + Edge + Backend, trước mở nhóm mới | Onset = mốc đủ điều kiện; tài liệu đã làm runtime đổi |
| Actual Orin NX SKU/RAM, camera/FPS đồng thời, storage/thermal/SDK và checkpoint clearance | Edge/ML + QA, target conformance/capacity/readiness | Tên board/model là benchmark hoặc production clearance |
| Thứ tự mở nhóm sau person-down/tai nạn và workload tổ hợp module | Product + kỹ thuật, sau gate từng nhóm/tổ hợp | Phải bật cả danh mục đồng thời |

Việc soạn requirement không đóng ticket, không tạo ADR accepted mới, không ghi nhận benchmark/huấn luyện/kiểm thử runtime hoặc field acceptance. Nhật ký hoạt động và quyết định chung do lead duy trì tại nguồn phỏng vấn nêu đầu tài liệu.
