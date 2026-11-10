# 2026-11-09 — Refactor Tài liệu & Tracker Ticket đồng bộ Kiến trúc CiviWatch v2

## Hoạt động
1. Khảo sát và đối chiếu toàn bộ hệ thống tài liệu trong `docs/` (`architecture/`, `adr/`, `requirements/`, `implementation-checklists/`) và các ticket tracker trong `.scratch/system-build/` & `.scratch/system-build-slices/`.
2. Tạo mới **ADR-0008** (`docs/adr/0008-civiwatch-v2-hybrid-vlm-architecture.md`) chuẩn hóa toàn bộ các quyết định kỹ thuật của kiến trúc CiviWatch v2:
   - Hard Rebrand 100% sang CiviWatch (`civi-watch`, `civi_watch`, `/tmp/civi-watch-evidence`, CiviWatch Operations Center).
   - Tầng 1: Zero-Plumbing Media Engine (`infra/go2rtc.yaml`, `apps/edge/media_engine.py`).
   - Tầng 2: Vectorized YOLOX Postprocessing (`apps/edge/oracle_detector.py`), Batched RTMPose (`apps/edge/pose.py`), Ground-Plane Homography ($3\times 3$) (`apps/edge/homography.py`).
   - Tầng 3: Hybrid VLM Temporal Storyboard Verifier (`apps/edge/vlm_verifier.py`) & Phủ trọn 14 nhóm kịch bản an toàn đô thị (`US01`–`US14`) qua `domain/urban_scenarios.py` và `apps/edge/urban_safety_engine.py`.
   - Tầng 4: CiviWatch Operations Center (`apps/server/static/index.html`) hỗ trợ lọc và hiển thị thông tin hậu kiểm `vlm_verification`.
3. Cập nhật và đồng bộ các tài liệu kiến trúc chuẩn:
   - `docs/README.md`: Cập nhật trạng thái CiviWatch v2, 918 tests pass, 14/14 nhóm an toàn đô thị, liên kết ADR-0008.
   - `docs/architecture/system-architecture.md`: Đồng bộ danh mục 14 kịch bản, bảng quyết định kiến trúc, Homography, VLM Verifier.
   - `docs/architecture/contracts.md`: Bổ sung cấu trúc `payload.vlm_verification` vào hợp đồng Snapshot Event §2 và neo `alert_condition` §3.
   - `docs/architecture/implementation-plan.md`, `lab-profile.md`, `deployment-readiness.md`: Đồng bộ thương hiệu CiviWatch, test pass count, ODD camera cố định HD–2MP.
   - `docs/requirements/urban-safety-scenarios.md` & `technology-candidates.md`: Khẳng định baseline CiviWatch v2 đã có implementation cho cả 14 kịch bản trên Edge software lab.
4. Cập nhật các tracker và ticket thực thi trong `.scratch/`:
   - `.scratch/system-build/PRD.md` & `.scratch/system-build-slices/PRD.md`: Đồng bộ sang CiviWatch v2, cập nhật tiến độ (30 done, 20 partial, 918 tests pass).
   - `.scratch/system-build-slices/requirements-expansion-index.md`: Cập nhật tiến độ hoàn thành software-lab cho các ticket mở rộng #58–#68.
   - Các ticket #46, #58, #59, #60, #61, #64, #65, #66, #67, #68: Cập nhật `Execution: partial (software lab)`, đánh dấu các tiêu chí kỹ thuật đã implement và ghi nhận evidence vào Comments.
   - `.scratch/system-build/issues/10-m09-incident-pipelines.md` & `18-m17-geometry-vehicle.md`: Cập nhật ownership mã nguồn thực tế.

## Kết quả kiểm chứng
- `pytest tests/test_civiwatch_v2.py`: 9/9 passed.
- Toàn bộ repo `pytest`: 918 passed, 0 failures.
- `mypy domain/ apps/ tools/`: Success, 0 errors trên 79 files.
