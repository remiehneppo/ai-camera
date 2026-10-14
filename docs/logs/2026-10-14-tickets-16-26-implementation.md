# Implementation & Review Log — Tickets #16 & #26 (2026-10-14)

## Context & Objectives
- Triển khai hai ticket được người dùng xác nhận:
  - **Ticket #16**: Startup/shutdown giữ recorder và state đúng (Runtime lifecycle, reconcile before analytics, graceful drain, process isolation, session/epoch reset).
  - **Ticket #26**: Persistent lying khi thiếu onset (Phát hiện người nằm bền vững khi không có onset / ID switch, taxonomy `person_lying_persistent`, anchor_kind `first_qualifying_observation`, khoảng evidence request `[anchor_time - 10, anchor_time + 20]`).

## Delegation & Model Routing
- Điều phối viên phân rã thành hai task book độc lập tuân thủ R1–R6.
- Subagents được spawn với route:
  - Subagent 1: `onechain/Gemini 3.8 Flash (High)` (Ticket #26)
  - Subagent 2: `onechain/Gemini 3.8 Flash (High)` (Ticket #16)
- Cả hai subagent thực hiện theo phương pháp TDD (Red -> Green -> Refactor), tuân thủ Karpathy Guidelines.

## Code Review Findings & Remediation
- Thực hiện two-axis review (Standards & Spec):
  - **Standards**: Phát hiện tên hàm alias không phản ánh đúng domain trong `pipeline.py`, hardcode branching lặp lại, và code trùng lặp build detection history trong `incident.py`.
  - **Spec**: Phát hiện test fault injection chưa dùng real process kill, test drain thao tác vào socket nội bộ, và nguy cơ trôi `first_qualifying_time` khi có minor jitter.
- Dispatch remediation vòng 2:
  - Chuẩn hóa hàm `_handle_incident` và đọc trực tiếp `anchor_kind` và `severity` từ incident.
  - Tách helper `_format_detections` và `_create_incident` trong `incident.py`.
  - Giữ vững `first_qualifying_time` cho chuỗi lying persistence.
  - Sửa test `test_kill_or_hang_of_analytics_leaves_recorder_functional_and_status_degraded` sang inject `SIGKILL` thật vào analytics process, xác minh recorder tiếp tục hoạt động và ghi nhận trạng thái `degraded: True`.
  - Thêm test ID switch và transient speed jitter.

## Verification Evidence
- `tests.test_tracking_incident`: 24 tests passed (0.218s).
- `tests.test_edge_runtime`: 12 tests passed (5.431s).
- Integration test suite (`test_architecture_deepening`, `test_crash_recovery`, `test_review_contract`): 62 tests passed (10.737s).
- Mypy: `Success: no issues found in 5 source files`.
