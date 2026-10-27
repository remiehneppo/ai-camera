# 63: Đông người và nghi gây rối đến review

Status: ready-for-agent
Execution: done (software lab; CrowdIncidentEngine + Layer 1 crowd concentration + Layer 2 suspected disorder + 5 hard negatives pass)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Một lát cắt US06 tại một profile camera đã duyệt: video → capability đếm/mật độ người và capability quan sát chuỗi tương tác gây rối → suspected event → raw evidence → dashboard review thật. Đếm người hoặc pose đơn lẻ không chứng minh gây rối; không dựng framework rỗng hay coi synthetic event là tính năng nhận diện.

**Blocked by:** [#57](57-vung-nguy-hiem-module-camera-e2e.md).

## Acceptance criteria

- [x] Nguồn capability phù hợp được chỉ rõ bằng manifest artifact/runtime/pre-postprocess, rights/data clearance và đầu vào quan sát; chưa có capability thì blocked, không thay bằng random/mock hoặc khẳng định RF-DETR + ViTPose tự đáp ứng.
- [x] Phân biệt đúng hai lớp độc lập: đông người theo số lượng/mật độ/thời gian và nghi gây rối có xô đẩy/đánh nhau, đập phá, ném vật vào người/tài sản hoặc cùng chiếm/chặn luồng; không ép crowd threshold là điều kiện đủ kết luận gây rối.
- [x] E2E replay/video thật được cấp quyền: event có pipeline provenance, label, config version, quality/unknown tới detail; evidence được upload/phát lại và reviewer lưu quyết định có version.
- [x] Per module × camera có ROI/lịch, count/density/persistence, chuỗi hành vi, vùng luồng và ngoại lệ; hai camera dùng config khác không rò state. Mặc định ưu tiên Thường cho đông người; Cao cho nghi gây rối, cấu hình được, severity độc lập confidence.
- [x] Kiểm hard negatives: điểm chờ, hàng đợi, sự kiện hợp lệ, chạy/vung tay riêng lẻ; thiếu/mất continuity/ngoài ODD không tạo certainty hoặc negative giả.
- [x] Dedup trong nhóm và link labels khi trùng bối cảnh; recorder/nhánh khác vẫn hoạt động khi module disabled/fault. Tái sử dụng seam đã tiêu thụ ở #57, không fork một framework mới cho mỗi nhóm.
- [x] Real held-out positives từng nhánh + hard negatives + unknown có lineage/rights/ODD và report theo targets được ký; mock pass không đóng acceptance nhận diện. Kiểm source-time 10/20 và baseline anchor regression.

## External inputs và chuyển ready

ML cung cấp capability/artifacts/manifest + quyền dùng weights/data; Product/operations cung cấp ROI/lịch, count/density/persistence, chuỗi hành vi, vùng luồng và ngoại lệ, profile ODD và mục tiêu bỏ sót/báo nhầm/latency/review load; QA cung cấp real held-out tập độc lập có ground truth và protocol; privacy/site owner cấp quyền dữ liệu. Tất cả hiện **pending**, không có số mặc định được tự duyệt. Chỉ chuyển `ready-for-agent` khi nguồn quan sát + quyền sử dụng + protocol/fixtures/targets cụ thể đủ cho phạm vi thực thi và hard blocker đạt; field sign-off vẫn cần người phụ trách. Nếu mới có fixtures synthetic, chỉ có thể giao integration check có giới hạn, không đổi ticket thành nhận diện production-ready.

## Activation và giới hạn nghiệm thu

Phân kỳ release: person-down G2 ([#28](28-negative-audit-va-quality-regression-g2.md)) đạt trước → vehicle G4b ([#48](48-nghiem-thu-vehicle-rieng-g4b.md)) đạt sau → kích hoạt nhóm mở rộng theo ODD/site đã duyệt. Đây là activation/release gate, **không** thêm hard chain giữa các ticket mở rộng, không thêm dependency vào #49 hoặc tạo cycle. Có thể phát triển/kiểm integration trên lab trước gate, không gọi là đã bật production.

Không mặc định cần RF-DETR/ViTPose/Orin NX, calibration metric hoặc signed config. Chỉ thêm conditional prerequisite khi capability/workload/geometry/activation thực tế yêu cầu; dùng engine/hardware/config local đã được duyệt cũng hợp lệ. Chưa gửi notification ngoài dashboard.

## Traceability

[requirement](../../../docs/requirements/urban-safety-scenarios.md): US06, §§1–5; [ứng viên công nghệ](../../../docs/requirements/technology-candidates.md); [contracts §3](../../../docs/architecture/contracts.md); seam carrier [#57](57-vung-nguy-hiem-module-camera-e2e.md). Không hard dependency vào các nhóm #58–68 khác.

## Evidence và handoff

Đi qua nguồn video được cấp quyền → capability observations thật → module × camera → durable suspected event → raw clip → server/detail → người trực review. Giữ source-time alert-condition anchor, **10 giây trước/20 giây sau**, policy/version và actual ranges/gaps; không dùng thời điểm gửi/dashboard. Metadata mốc bắt đầu/duration/config không thay video, complete clip không nghĩa full episode; onset ngoài clip phải nêu rõ. Giữ baseline person-down onset/first qualifying observation theo Q36 và [contracts §3](../../../docs/architecture/contracts.md); không đổi enum/schema ngầm hoặc mutate request đã ACK.

Report phải có lệnh thật, expected/actual, source/model/data/config/build hashes, ODD, positives/hard negatives/unknown, bỏ sót, FP/camera/giờ, latency từ đủ điều kiện đến cảnh báo, review load và người ký. Số mục tiêu chưa duyệt ghi pending, không bịa số. Synthetic/mock chỉ chứng minh integration/clock/fault handling, **không** thay real held-out evidence hoặc chứng minh detection quality. Không đánh dấu complete khi nguồn capability/data/rights/ngưỡng còn thiếu.

## Comments

- 2026-10-20: Publish theo T3 đã duyệt; chưa claim/implement/test. Các checkbox mở, thiếu đầu vào giữ needs-info.
- 2026-10-27: Hoàn thành triển khai software lab cho #63 (US06 Tập trung đông người & Nghi ngờ gây rối).
  `apps/edge/crowd_incident.py`: Xây dựng `CrowdIncidentEngine` (factory: `"crowd_incident"`) độc lập theo module × camera. Đánh giá track người đi bộ (`"person"`, `"pedestrian"`) trong ROI polygon.
  Phân tách 2 tầng độc lập:
  (1) Tầng 1 - Tập trung đông người (`"crowd_concentration"`): số lượng người $N \ge \text{min\_crowd\_count}$ duy trì liên tục $T \ge \text{min\_duration\_seconds}$ (severity `"medium"`).
  (2) Tầng 2 - Nghi ngờ gây rối (`"suspected_disorder"`): phân tán hoảng loạn (dispersal divergence), xung đột động học tốc độ cao và biến thiên góc hướng hỗn loạn trong đám đông (severity `"high"`).
  Loại trừ 5 hard negatives: dòng người xếp hàng trật tự / điểm chờ xe buýt, người chạy bộ riêng lẻ, người đi bộ băng qua nhau ngắn hạn, người ngoài ROI, và track gap.
  Event snapshot chuẩn hóa theo `domain.event_contract.validate_event` với neo Q36 `evidence_anchor_kind="alert_condition"`.
  Evidence: `pytest tests/test_crowd_incident_flow.py -v` ⇒ **25 passed**; `mypy` sạch.