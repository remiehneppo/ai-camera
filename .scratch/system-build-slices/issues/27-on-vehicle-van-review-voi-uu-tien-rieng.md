# 27: On-vehicle vẫn review với ưu tiên riêng

Status: ready-for-agent
Execution: done (software lab)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; claimed & completed (software lab).

**What to build:** Người ngả trên xe đã stationary/upright tạo event review ưu tiên thấp; xe đổ/ngã cạnh xe có danger override.

**Blocked by:** [#26: Persistent lying khi thiếu onset](26-persistent-lying-khi-thieu-onset.md).

## Acceptance criteria

- [x] Association có uncertainty/history, không suppress vì bbox overlap hoặc kết luận ngủ/bất tỉnh.
- [x] Lab không notification khẩn; product protocol chưa ký vẫn lưu/review event, chưa bật hazard scope ngoài yêu cầu.

## Traceability

Task nguồn: I03, I04, UI03.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

- **Edge Perception & Incident Engine (`apps/edge/incident.py`, `apps/edge/pipeline.py`):**
  - Nhận diện phương tiện 2 bánh (`motorcycle`, `bicycle`) và theo dõi lịch sử trạng thái: `is_stationary`, `is_upright` (aspect_ratio < 1.15), `is_fallen` (aspect_ratio >= 1.2 hoặc đổi độ nghiêng nhanh).
  - Yêu cầu xe phải đứng yên và đứng thẳng từ trước khi người bắt đầu ngả/nằm (>= 1.0s hoặc 2 frame ổn định).
  - Khi người nằm trên xe đỗ đứng thẳng từ trước: phát `taxonomy="person_on_stationary_vehicle"`, `severity="low"`, `anchor_kind="first_qualifying_observation"`, anchor_time = first qualifying time.
  - **Danger Overrides:**
    1. Người có pha falling onset (hạ thấp nhanh / va chạm) qua xe đứng yên → giữ nguyên `person_fall` với `severity="critical"`.
    2. Xe bị đổ/nghiêng (`is_fallen`) hoặc đổ sau khi người nằm → override về `person_lying_persistent` với `severity="high"`.
    3. Xe đến sau hoặc đang di chuyển → không gắn `person_on_stationary_vehicle`, giữ `person_lying_persistent` (`severity="high"`).
    4. Observation gap / clock jump: xóa continuity xe và người, không demote sai.
- **Server Review Queue & Dataset Export (`apps/server/store.py`, `main.py`, `dataset.py`, `static/index.html`):**
  - Hàm `review_priority_for`: `person_on_stationary_vehicle` hoặc severity "low" gán priority `"low"`; high/critical gán `"urgent"`; còn lại `"standard"`.
  - API `/v1/events` hỗ trợ query filter `?severity=low` và `?taxonomy=person_on_stationary_vehicle`.
  - Outbox lab giữ `eligibility="ineligible"` (không gửi notification khẩn).
  - Dashboard web hiển thị badge xám `On-vehicle (Low priority)` và thông tin review priority riêng.
  - API `/v1/dataset/export` xuất trọn vẹn lineage, review decision, taxonomy và review priority.
- **Test suite:**
  - `tests/test_on_vehicle_flow.py`: 6/6 tests passed (6 subtests).
  - `tests/test_review_priority.py`: 6/6 tests passed.
  - `tests/test_tracking_incident.py`: 36/36 tests passed (gồm 6 tests on-vehicle mới).
  - Toàn bộ test suite: 471 passed, 118 subtests passed (100% xanh).

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
- 2026-10-21: Hoàn tất triển khai Ticket #27 trong software lab qua dispatch subagents (Edge + Server + QA Integration). Khắc phục triệt để gap continuity cho vehicle states. Toàn bộ 471 unit & integration tests đạt xanh 100%.
