# Requirement tình huống an toàn đô thị

**Cập nhật:** 2026-10-30 · **Trạng thái:** Đặc tả nghiệp vụ chuẩn cho 14 nhóm tình huống an toàn đô thị (`US01` → `US14`). Hiện tại **5 nhóm trọng tâm (`US05`, `US06`, `US08`, `US09`, `US10`) đã được triển khai đầy đủ trên bản tham chiếu phần mềm Edge**; 9 nhóm còn lại giữ ở trạng thái đặc tả danh mục chờ dữ liệu/mô hình chuyên biệt. Chưa có nhóm nào được ký nghiệm thu hiện trường (`G2/G5`).

Tài liệu liên quan: [Từ điển domain (`CONTEXT.md`)](../../CONTEXT.md) · [Hợp đồng tích hợp](../architecture/contracts.md) · [Kế hoạch triển khai](../architecture/implementation-plan.md) · [Ứng viên công nghệ](technology-candidates.md) · [Tracker mở rộng](../../.scratch/system-build-slices/requirements-expansion-index.md).

---

## 1. Phạm vi và nguyên tắc nghiệp vụ chung

- **Triển khai phân kỳ theo ranh giới module độc lập ([ADR-0001](../adr/0001-feature-pipeline-boundaries.md)):** Danh mục 14 nhóm tình huống không triển khai hay bật đồng loạt. `US09 (Person-down)` trên một camera cố định / ROI lòng đường là luồng chuẩn đầu tiên; từng module mở rộng có cấu hình, state theo `module × camera × session` và cổng nghiệm thu riêng (`G4b`).
- **Ràng buộc ODD cố định:** Chỉ áp dụng cho camera CCTV gắn cố định ngoài trời quan sát lòng đường/vỉa hè đô thị ở độ phân giải **720p–1080p**. Camera hành trình (dashcam), PTZ quay quét liên tục hoặc luồng `< 720p` nằm ngoài phạm vi hỗ trợ.
- **Sự kiện nghi ngờ phục vụ con người xác minh:** Hệ thống AI chỉ phát **sự kiện nghi ngờ (`Suspected incident`)** kèm clip bằng chứng để người trực trên Dashboard xác minh. Hệ thống không kết luận pháp lý, tình trạng y tế, lỗi chủ quan, ý định hay danh tính cá nhân; không tích hợp nhận diện biển số/chủ xe (ANPR) và không tự động gửi cảnh báo ra kênh ngoài Dashboard khi chưa mở cổng giao thức riêng ([ADR-0002](../adr/0002-server-downstream-event-publishing.md)).
- **Trung thực trước điều kiện thiếu quan sát:** Mọi điều kiện che khuất, mờ nhòe, đóng băng khung hình, đứt quãng track hoặc ánh sáng/thời tiết ngoài miền đã kiểm thử phải trả trạng thái `unknown` / `degraded` / `unsupported` trung thực, không suy diễn thành âm tính an toàn hay dương tính giả.
- **Fail-fast cấu hình & Liên kết đa nhãn:** Module được bật (`enabled=True`) nhưng thiếu hoặc sai cấu hình ROI/lịch/hiệu chuẩn bắt buộc phải từ chối khởi động rõ ràng (`fail-fast`), không âm thầm bỏ qua. Cùng một diễn biến thực tế có thể phát sinh sự kiện độc lập từ nhiều module (ví dụ va chạm xe kèm người ngã); mỗi module tự chống lặp trong phạm vi của mình mà không xóa nhãn hay lịch sử audit của module khác.

---

## 2. Danh mục 14 nhóm tình huống, tham số và trạng thái thực thi

Các mã `US01–US14` là mã định danh nghiệp vụ trong tài liệu; cột **Thực thi hiện tại** ánh xạ trực tiếp sang module và taxonomy trong mã nguồn:

| ID / Nhóm | Điều kiện nghiệp vụ và các nhánh phải phân biệt | Tham số cấu hình bắt buộc *(ngưỡng site thực tế cần ký trước pilot)* | Ưu tiên mặc định | Thực thi hiện tại (Software Lab) |
|---|---|---|---|---|
| **US01 — Cháy / khói** | Tách nghi ngờ lửa và nghi ngờ khói; một dấu hiệu đủ xét cảnh báo, có thể liên kết hai sự kiện | ROI, thời gian duy trì từng dấu hiệu, ngoại lệ nguồn khói/lửa hợp lệ tại site | Khẩn | Backlog (`#58`) — chờ model/dữ liệu lửa-khói |
| **US02 — Ngập nước** | Nước đạt mốc/vùng cảnh báo đã cấu hình và duy trì đủ lâu; không cam kết đo độ sâu theo cm | ROI/mốc chuẩn trên mặt đường, thời gian duy trì, điều kiện quan sát rõ mặt đường | Cao | Backlog (`#59`) — chờ mốc chuẩn & dữ liệu ngập |
| **US03 — Đổ trộm rác** | Tách hành vi bỏ/đổ rác có diễn biến với rác tồn lưu thiếu diễn biến; không gán người đi ngang là thủ phạm | Vùng/lịch cấm, lớp đối tượng rác, thời gian tồn lưu, lịch thu gom hợp lệ | Thường | Backlog (`#60`) — chờ taxonomy vật thể rác |
| **US04 — Lấn chiếm vỉa hè** | Xe, quầy hàng, bàn ghế hoặc vật cản chiếm vùng vỉa hè cần thông thoáng vượt thời gian cho phép | ROI vỉa hè, loại vật/xe, thời gian chiếm dụng, lịch và ngoại lệ được phép | Thường | Backlog (`#61`) — chờ lớp vật cản & lịch site |
| **US05 — Đỗ xe sai quy định** | Xe cơ giới/hai bánh đứng yên vượt ngưỡng thời gian trong vùng và khung giờ cấm; phân biệt dừng chờ đèn đỏ/ùn tắc | ROI cấm đỗ, `ScheduleWindow`, `dwell_seconds`, dung sai dao động hộp giới hạn, ngoại lệ tắc đường | Thường | **Đã cài đặt:** `apps/edge/parking_incident.py` (`illegal_parking`, `#62`) |
| **US06 — Tụ tập / gây rối** | Hai mức: (1) tập trung đông người vượt số lượng/mật độ/thời gian (`crowd_concentration`); (2) nghi ngờ gây rối khi cụm không gian cục bộ có đa tác nhân phân tán vận tốc hướng ra ngoài (`suspected_disorder`). Không báo gây rối chỉ vì 1 người chạy/tập thể dục giữa đám đông đứng yên | ROI/lịch, ngưỡng số người, bán kính gom cụm theo tỷ lệ chiều cao người, số tác nhân chuyển động nhanh tối thiểu, thời gian duy trì | Thường (đông người) / Cao (gây rối) | **Đã cài đặt:** `apps/edge/crowd_incident.py` (`crowd_concentration`, `suspected_disorder`, `#63`) |
| **US07 — Ẩu đả** | Nghi ngờ tương tác bạo lực trực tiếp giữa ít nhất hai người theo chuỗi hành động; không suy đoán vũ khí hay kẻ chủ mưu | ROI/lịch, cửa sổ thời gian tương tác gần, ngưỡng bằng chứng động tác | Khẩn | Backlog (`#64`) — chờ mô hình tương tác hành vi |
| **US08 — Tai nạn có xe** | Sự cố đường bộ có phương tiện: va chạm/giảm tốc đột ngột hoặc dừng bất thường trong làn xe chạy; phân biệt trạng thái tĩnh thiếu diễn biến | Hiệu chuẩn hình học (`GeometryCalibration`), vùng làn đường, ngưỡng giảm tốc/vận tốc/thời gian dừng, lịch sử track liên tục | Khẩn | **Đã cài đặt:** `apps/edge/vehicle_incident.py` (`vehicle_accident`, `stopped_vehicle_in_lane`, `#45–#47`) |
| **US09 — Person-down** | Ba nhánh rõ ràng: (1) `person_fall` có diễn biến hạ thấp (onset); (2) `person_lying_persistent` nằm bền vững thiếu onset; (3) `person_on_stationary_vehicle` có ưu tiên review riêng, không tự động ẩn | ROI lòng đường, ngưỡng tỷ lệ khung/pose keypoints, thời gian nằm bền vững, kiểm tra gắn kết với xe đứng yên từ trước | Khẩn *(riêng on-vehicle xếp ưu tiên thấp hơn để review riêng)* | **Đã cài đặt:** `apps/edge/incident.py` + `pose.py` (`#14, #24–#27, #53`) |
| **US10 — Vào vùng nguy hiểm** | Người xâm nhập vào đa giác ROI nguy hiểm trong khung giờ hiệu lực; cảnh báo an toàn không phụ thuộc danh tính | Đa giác ROI nguy hiểm, `ScheduleWindow`, điểm neo chân hộp người, thời gian duy trì/cooldown | Khẩn | **Đã cài đặt:** `apps/edge/danger_zone.py` (`danger_zone_intrusion`, `#57`) |
| **US11 — Vật bỏ quên** | Tách hành vi người đặt vật rồi rời xa với vật lạ tồn lưu không rõ người liên quan; không suy đoán chất nổ/chủ sở hữu | ROI/lịch, kích thước vật, khoảng cách tách rời người–vật, thời gian tồn lưu | Cao | Backlog (`#65`) — chờ bám vết vật tĩnh nhỏ |
| **US12 — Cây đổ** | Cây hoặc cành lớn đã ngã đổ chắn vào vùng quan sát (có hoặc thiếu onset); không dự báo cây sắp đổ | ROI lòng đường/vỉa hè, kích thước tối thiểu, thời gian xác nhận | Cao | Backlog (`#66`) — chờ detector vật cản cây đổ |
| **US13 — Đèn đường hỏng** | Đèn chiếu sáng không sáng trong khung giờ quy định bật sau khoảng trễ chuyển tiếp, khi tầm nhìn tới đèn đảm bảo | Tọa độ vùng đèn trên ảnh, lịch bật tắt, thời gian chuyển tiếp, điều kiện tầm nhìn | Thường | Backlog (`#67`) — chờ cấu hình điểm đèn & lịch |
| **US14 — Phá hoại tài sản** | Nghi ngờ hành vi đập, đá, kéo đổ hoặc ném vật vào tài sản công cộng; độc lập với ẩu đả giữa người (`US07`) | ROI tài sản cần bảo vệ, chuỗi tương tác người–tài sản, ngoại lệ công nhân bảo trì/vệ sinh | Cao | Backlog (`#68`) — chờ dữ liệu hành vi tương tác |

---

## 3. Hard Negatives và Ranh giới Kiểm thử Bắt buộc theo từng nhóm

Mỗi nhóm trước khi mở nghiệm thu `G2` phải có bộ kiểm thử gồm cả mẫu dương tính theo từng nhánh, mẫu âm tính khó (hard negatives) và mẫu thiếu quan sát (`unknown`):

| ID | Hard negatives bắt buộc không được báo động sai | Điều kiện vượt cổng riêng của nhóm |
|---|---|---|
| **US01** | Hơi nước, bụi đường, ánh đèn pha quét ban đêm, nguồn khói sinh hoạt được phép | Kiểm định tách biệt nhánh lửa, nhánh khói và trường hợp xuất hiện đồng thời |
| **US02** | Mặt đường ướt sau mưa, vũng nước nông phản chiếu ánh đèn | Phân biệt rõ mực nước chạm mốc cấu hình với mặt đường ướt hoặc mất tầm nhìn |
| **US03** | Nhân viên thu gom rác đúng lịch, rác đã nằm sẵn khi người đi bộ bước ngang qua | Không gán trách nhiệm cho người đi ngang khi thiếu chuỗi hành vi bỏ rác |
| **US04** | Người đi bộ dừng ngắn, xe/hàng hóa trong khung giờ hoặc khu vực ngoại lệ hợp lệ | Áp dụng chính xác đa giác vỉa hè, thời lượng chiếm dụng và lịch ngoại lệ |
| **US05** | Dòng xe dừng chờ đèn đỏ, ùn tắc dây chuyền, xe dừng trả khách ngắn dưới ngưỡng | Phải có lịch sử track liên tục trong ROI và trong khung giờ hiệu lực mới phát cảnh báo |
| **US06** | Bến xe buýt, hàng chờ hợp lệ, một người chạy bộ/tập thể dục bên cạnh nhóm người đứng yên | Tách bạch `crowd_concentration` với `suspected_disorder`; nhánh gây rối bắt buộc kiểm chứng phân tán đa tác nhân cục bộ |
| **US07** | Tập thể dục, đùa giỡn nhẹ, khoác vai hoặc người dân cúi xuống đỡ người bị ngã | Đòi hỏi chuỗi tương tác đối kháng giữa tối thiểu hai track người |
| **US08** | Hai xe đi sượt qua nhau do góc phối cảnh 2D, dừng đèn đỏ, hộp xe nhảy nhãn sang người | Yêu cầu hiệu chuẩn hình học hợp lệ và bám vết nhất quán theo nhóm lớp phương tiện |
| **US09** | Người cúi buộc dây giày/nhặt đồ rồi đứng dậy, tài xế nằm nghỉ trên yên xe máy đỗ tĩnh | Xử lý đúng cả ngã nhanh, ngã từ từ, nằm sẵn thiếu onset và phân loại riêng `person_on_stationary_vehicle` |
| **US10** | Người đi sát mép ngoài đa giác ROI, hoặc đi vào vùng khi ngoài khung giờ trực | Kiểm tra điểm neo hộp người với đa giác ROI và `ScheduleWindow` chính xác |
| **US11** | Thùng hàng/biển báo cố định hợp lệ, hành khách đứng sát hành lý của mình | Phân biệt rõ sự kiện tách rời người–vật với vật tĩnh có sẵn |
| **US12** | Bóng râm cành cây rung theo gió, cành lá nhỏ không gây cản trở | Xác nhận vật cản kích thước lớn nằm cố định trong vùng đường/vỉa hè |
| **US13** | Ban ngày, giai đoạn chạng vạng chuyển tiếp lịch bật đèn, ống kính bị che khuất nguồn đèn | Không suy diễn lỗi điện chỉ từ độ sáng trung bình toàn ảnh |
| **US14** | Công nhân sửa chữa hạ tầng, nhân viên vệ sinh thao tác bình thường trên tài sản | Có chuỗi tác động bất thường trực tiếp lên vùng tài sản mục tiêu |

---

## 4. Chính sách Evidence và Sự kiện kéo dài (`contracts.md §3`)

1. **Cửa sổ clip cố định `[-10s, +20s]` quanh mốc neo (`evidence_anchor_time`):**
   - **`US09 (Person-down)`:** Nhánh `person_fall` lấy mốc ước lượng bắt đầu ngã (`evidence_anchor_kind = "onset"`); hai nhánh thiếu onset (`person_lying_persistent`, `person_on_stationary_vehicle`) lấy quan sát đủ điều kiện đầu tiên của chuỗi hiện tại (`evidence_anchor_kind = "first_qualifying_observation"`).
   - **Tất cả các nhóm cảnh báo theo điều kiện (`US05`, `US06`, `US08`, `US10`, và các nhóm mở rộng sau này):** Lấy mốc thời gian nguồn tại thời điểm thỏa mãn điều kiện phát cảnh báo (`evidence_anchor_kind = "alert_condition"`). Tuyệt đối không dùng thời điểm Server nhận gói tin hay thời điểm người trực mở xem làm mốc cắt video.
2. **Giới hạn ngữ nghĩa của clip `complete`:** Với các sự kiện kéo dài nhiều phút hoặc nhiều giờ (như đỗ xe lâu, ngập nước, vật tồn lưu), `completeness = "complete"` chỉ xác nhận clip đã bao phủ đủ 30 giây `[-10s, +20s]` quanh mốc neo đã yêu cầu, **không** có nghĩa clip chứa toàn bộ vòng đời từ lúc bắt đầu đến lúc kết thúc sự việc. Hệ thống lưu kèm thời điểm bắt đầu quan sát và thời lượng duy trì trong metadata kèm provenance rõ ràng.

---

## 5. Điều kiện nghiệm thu trước khi bật từng nhóm tại hiện trường (`G2` / `G4b`)

Một nhóm tình huống chỉ được chuyển từ trạng thái chạy thử phần mềm (software lab) sang bật chính thức tại site khi hoàn tất đủ 5 điều kiện:
1. Có bộ dữ liệu CCTV cố định 720p–1080p độc lập gồm mẫu dương tính từng nhánh, hard negatives và điều kiện ngày/đêm/mưa mục tiêu đã được chủ bài toán ký duyệt phạm vi ODD.
2. Có báo cáo đo định lượng tỷ lệ bỏ sót, số báo động giả/camera-ngày, độ trễ từ lúc đủ điều kiện đến lúc phát cảnh báo và tổng số phút review phát sinh cho ca trực.
3. Vượt đầy đủ bài kiểm tra fail-fast cấu hình, cô lập trạng thái `module × camera × session`, chống lặp trong nhóm và giữ nguyên đa nhãn liên nhóm ([ADR-0005](../adr/0005-incident-snapshot-ownership.md)).
4. Chứng minh tính trung thực của `evidence_anchor_kind`, dải thời gian thực tế (`actual_ranges`) và trạng thái `complete`/`partial`/`missing` khi đứt luồng hoặc sự kiện kéo dài.
5. Vượt bài đo tải toàn hệ thống (`G3`) trên đúng SKU phần cứng đích với đúng tổ hợp các module dự kiến bật đồng thời.
