# Spec Delta

## Purpose

Replay kiểm chứng đường chạy Alert feature pipeline bằng cùng module runtime và cấu hình tường minh; kết quả phân biệt quan sát hợp lệ, lỗi quan sát và Suspected incident. Phạm vi và thiết kế đã duyệt; đặc tả không chứng nhận chất lượng model, Complete evidence hoặc target hardware.

## ADDED Requirements

### Requirement: Replay uses the shared execution path with explicit effective policy

Caller replay SHALL dùng cùng Alert feature pipeline interface cho observation, Track, pose, quyết định tình huống và snapshot. Caller SHALL chỉ giữ đọc video/sampling/cấu hình/tổng hợp; MUST không duy trì đường orchestration feature độc lập thứ hai. Cấu hình hiệu lực SHALL được xác định và báo cáo theo từng command hoặc caller, không tự thay bằng runtime defaults.

#### Scenario: R01 Matched replay and runtime inputs have matched semantic outcomes
- **WHEN** replay và caller runtime thử cùng sequence observation, sampling và cấu hình model/feature/quality/pose
- **THEN** taxonomy, anchors, payload tình huống, status và snapshot persistence outcomes tương ứng giống nhau; identity mới và wall-clock giữa hai lượt chạy không phải tiêu chí so bằng

#### Scenario: R02 Existing command and function policies are not silently unified
- **WHEN** chuyển command hoặc caller hàm có ngưỡng tracker/feature, giới hạn frame hoặc pose policy khác nhau
- **THEN** từng caller giữ cấu hình hiệu lực đã khai báo của mình và báo cáo cấu hình đó; việc dùng chung module không tự chọn một bộ default chung

### Requirement: Source clock and sampling retain observation semantics

Replay SHALL dùng source-time nhất quán với pts/time_base của observation. Sampling theo kế hoạch SHALL không tự biến thành missing observation; một frame được nhận xử lý SHALL không tạo hai Track updates vì evaluator gọi lại stage nội bộ.

#### Scenario: R03 Fractional frame rate preserves rational observation time
- **WHEN** video có FPS phân số 30000/1001 được lấy mẫu theo kế hoạch cố định
- **THEN** frame được nhận xử lý có event_time bằng float(pts * Fraction(time_base)), không trở thành detection failed vì evaluator làm tròn FPS/time không nhất quán

### Requirement: Invalid detection observation cannot be reported as successful evaluation

Detection failed/missing/stale/skipped SHALL giữ status và continuity semantics của runtime; evaluator MUST kết thúc lỗi thay vì công bố lượt chạy thành công hoặc negative. Pose outcomes SHALL giữ status riêng; detection ok không xóa pose failure và pose skipped/failed không tự bị đổi thành detection failure.

#### Scenario: R04 Detection failure ends the run after preserving observation status
- **WHEN** một frame được xử lý trả detection status ngoài ok/ok_empty
- **THEN** pipeline giữ status/gap semantics hiện hữu và evaluator báo lỗi cùng frame/reason có sẵn, không phát báo cáo thành công hoặc dùng phần không quan sát được làm negative

#### Scenario: R05 Valid empty observation and pose degradation remain distinguishable
- **WHEN** detection trả ok_empty, hoặc detection ok đi cùng pose skipped/failed
- **THEN** evaluator giữ từng status tương ứng, không coi ok_empty là lỗi và không biến pose failure thành quan sát không có đối tượng

### Requirement: Replay origin and local-only side effects remain explicit

Replay SHALL giữ Origin=replay trong observation/snapshot và chỉ dùng storage tạm cục bộ trong phạm vi evaluator. Replay MUST NOT gửi event/media hoặc notification qua mạng trong lượt chạy này.

#### Scenario: R06 Replay cannot acquire live identity or network delivery
- **WHEN** evaluator xử lý video tạo Suspected incident
- **THEN** observation/snapshot giữ Origin=replay, context session đúng và event chỉ được persist cục bộ; không tạo giao nhận mạng hoặc notification

### Requirement: Reports describe observed snapshots without acceptance inference

Báo cáo SHALL tổng hợp observation và snapshot pipeline đã phát/persist, không tái dựng snapshot từ facts hoặc đếm lại bằng một đường quyết định riêng. Không có event SHALL chỉ được mô tả là zero events; MUST không suy negative pass hoặc Complete evidence từ số đó.

#### Scenario: R07 Reported events correspond to persisted snapshots
- **WHEN** lượt replay có một hoặc nhiều snapshot được emit/persist
- **THEN** báo cáo phản ánh taxonomy/anchor/payload và identity của các snapshot đó, Evidence request khớp session; không thêm event từ một đường xử lý khác

#### Scenario: R08 Zero events do not imply a reviewed negative or complete Evidence
- **WHEN** lượt replay không phát event hoặc không có footage coverage cho một Evidence request
- **THEN** báo cáo không gắn clean/negative pass, không nhận Complete evidence và không nhận server/review hoặc quality gate đã đạt

### Requirement: Timing scope and resource cleanup are observable

Latency SHALL đo quanh xử lý frame của pipeline, bao gồm snapshot construction và local persistence; SHALL loại decode/sampling/model startup/giao nhận mạng khỏi phép đo này và nêu phạm vi trong báo cáo. Caller SHALL đóng video/storage và dọn dữ liệu tạm khi kết thúc bình thường hoặc khi lỗi.

#### Scenario: R09 Report identifies the new timing scope
- **WHEN** evaluator xuất latency cho các frame đã xử lý
- **THEN** báo cáo nêu phạm vi xử lý pipeline có local persistence và không trình bày số đó như cùng phạm vi với latency evaluator cũ hoặc target capacity

#### Scenario: R10 Error and normal exits release replay resources
- **WHEN** lượt chạy hoàn tất, lỗi mở video, lỗi inference hoặc lỗi persist làm lượt chạy kết thúc
- **THEN** tài nguyên đã mở được đóng, dữ liệu tạm của lượt chạy được dọn và lỗi không bị đổi thành báo cáo thành công
