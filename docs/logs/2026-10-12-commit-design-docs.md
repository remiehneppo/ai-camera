# Commit tài liệu thiết kế và nghiên cứu

- Người dùng yêu cầu commit các thay đổi tài liệu đã hoàn thành.
- Phạm vi: hợp đồng tích hợp, ADR, kiến trúc, checklist, tracker, báo cáo review, nghiên cứu và nhật ký của lượt cập nhật này.
- Giữ nguyên các file untracked đã có: `.codegraph/`, `AGENTS.md` và nhật ký lịch sử ngoài lượt cập nhật.
- Kiểm lại tài liệu: 104 Markdown, 698 liên kết local trong workspace, 89 task, 50 ticket, 45 failure cases; DAG ONNX/RKNN không có chu trình. `git diff --check` sạch.
- Không chạy runtime/hardware tests vì thay đổi chỉ là tài liệu. Không push; kiểm liên kết workspace chưa chứng minh checkout độc lập có đủ mọi nhật ký lịch sử.
- Chuẩn hóa CRLF thành LF trong bảng giá CSV để kiểm tra staged whitespace sạch; giữ nguyên dữ liệu giá.
