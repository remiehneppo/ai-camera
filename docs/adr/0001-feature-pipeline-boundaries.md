---
status: accepted
---

# Pipeline tính năng độc lập, chia sẻ perception tương thích

Ngày 2026-10-11, người dùng xác nhận mỗi tính năng cảnh báo có pipeline register riêng với logic/state/config độc lập theo camera/session, dùng chung source/detector/tracker/pose khi tương thích để tránh lặp decode/inference. Registry dùng allowlisted factories và event contract chung có pipeline provenance; process riêng chỉ thêm khi cần cô lập lỗi/tài nguyên, vì tách logic không mặc nhiên bảo vệ khỏi native crash hay shared-resource overload.

Person-down cho một camera cố định/ROI lòng đường làm trước; pipeline vehicle là nhánh sau. Input/output semantic ổn định qua các engine, adapter giữ tensor/pre-postprocess riêng; thay engine vẫn phải qua conformance và event regression.
