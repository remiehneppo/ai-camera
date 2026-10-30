# Bộ checklist kiểm soát kiến trúc, tích hợp và release gates

**Cập nhật:** 2026-10-30 · **Nguồn theo dõi tiến độ duy nhất:** [Tracker slices (`.scratch/system-build-slices/PRD.md`)](../../.scratch/system-build-slices/PRD.md) và [Index mở rộng (`#53–#68`)](../../.scratch/system-build-slices/requirements-expansion-index.md).

Bộ tài liệu trong thư mục này cung cấp tiêu chí review kiến trúc, ma trận 45 kịch bản kiểm lỗi xuyên module (`X01–X45`) và bảng điều kiện ký vượt các cổng nghiệm thu (`G0–G5`):
- [Hướng dẫn review ranh giới SOLID & hợp đồng tích hợp](architecture-analysis.md)
- [Checklist tích hợp, ma trận lỗi `X01–X45` và release gates `G0–G5`](integration-release.md)
- [Kiến trúc hệ thống](../architecture/system-architecture.md) · [Hợp đồng tích hợp](../architecture/contracts.md) · [Kế hoạch triển khai](../architecture/implementation-plan.md) · [Deployment readiness](../architecture/deployment-readiness.md)

---

## 1. Quy tắc sử dụng Checklist và Tracker

1. **Không nhân đôi trạng thái thực thi:** Mọi trạng thái `Status`, `Execution`, `Blocked by` và nhật ký lệnh chạy thuộc về từng ticket trong `.scratch/system-build-slices/issues/`. Các tệp trong `docs/implementation-checklists/` giữ tiêu chí kiểm định bất biến, không dùng làm bảng đếm phần trăm hoàn thành thứ hai.
2. **Phân biệt rõ 3 mức hoàn thành:** (a) Đã cài đặt mã nguồn trong software lab → (b) Đã vượt bộ kiểm thử tự động (`896` tests + `mypy` 72 files) → (c) Đã ký nghiệm thu cổng phần cứng/thực địa (`G1–G5`). Tuyệt đối không dùng trạng thái pass của unit test trên máy x86 để tích chọn các mục yêu cầu RTSP thật, phần cứng nhúng đích hoặc dữ liệu thực địa.
3. **Mọi thay đổi hợp đồng dùng chung** phải kiểm tra xuyên suốt từ `domain/*_contract.py` → producer tại `apps/edge/` → consumer tại `apps/server/` và `tools/eval_*.py` → bộ test hợp đồng tương ứng.

---

## 2. Ánh xạ Phân hệ Kiến trúc sang Mã nguồn Thực tế và Cổng Nghiệm thu

| Phân hệ kiến trúc | Thành phần mã nguồn thực tế | Các Ticket chính | Kịch bản lỗi & Gate trọng tâm |
|---|---|---|---|
| **Hợp đồng Domain & Conformance** | `domain/*_contract.py`, `fixtures/oracle/`, `tools/oracle_conformance.py` | `#01, #04, #05, #11` | `X01, X03, X41` · **G0** (đạt lab) / **G3** (target) |
| **Bootstrap, Doctor & Signed Config** | `apps/edge/doctor.py`, `apps/edge/config_store.py`, `apps/edge/canary.py`, `domain/alert_module_config.py` | `#03, #34, #35` | `X04, X33` · **G0/G1** (local) / **G4a** (signed rollout) |
| **Nguồn Video & Luồng Live RTSP** | `apps/edge/live_pipeline.py`, `apps/server/live_stream.py` | `#06, #10, #15, #51, #52` | `X01, X02, X07` · **G1** (đang mở chờ camera thật) |
| **Perception, Tracking, Pose & ODD Quality** | `apps/edge/oracle_detector.py`, `tracker.py`, `pose.py`, `quality.py`, `pipeline.py` | `#11–#14, #21–#24, #53` | `X05, X06, X20–X24, X43` · **G1/G2** |
| **5 Alert Feature Pipelines & Snapshot Seam** | `apps/edge/snapshot.py` ([ADR-0005](../adr/0005-incident-snapshot-ownership.md)), `incident.py`, `danger_zone.py`, `vehicle_incident.py`, `parking_incident.py`, `crowd_incident.py` | `#14, #25–#27, #46, #47, #57, #62, #63` | `X21, X23, X36, X39` · **G2** (`person_down`) / **G4b** (mở rộng) |
| **Recorder Ring, Pin & Crash Recovery** | `apps/edge/recorder.py`, `apps/edge/evidence.py`, `apps/edge/quota.py` | `#06, #07, #09, #18, #51` | `X07–X12, X38–X40` · **G1/G4a** |
| **Outbox SQLite WAL, Upload & WAN Autonomy** | `apps/edge/outbox.py`, `apps/edge/uploader.py` | `#05, #08, #09, #36` | `X13–X16, X29` · **G1/G4a** |
| **Backend Ingestion, Evidence, Review & Retrieval** | `apps/server/main.py`, `store.py`, `evidence.py`, `retrieval.py`, `storm_guard.py` | `#01, #04, #08, #20, #27, #32, #41–#43` | `X17–X19, X32, X35, X40–X42, X45` · **G1/G4a** |
| **Giám sát Sức khỏe & Synthetic Probe** | `apps/edge/health.py`, `apps/edge/probe.py` | `#16, #17, #40` | `X27, X31, X34` · **G1/G4a** |
| **Semantic Replay, Benchmark & Negative Audit** | `tools/eval_clip.py`, `eval_vehicle.py`, `eval_all_scenarios.py` ([ADR-0006](../adr/0006-semantic-replay-pipeline-reuse.md)), `run_benchmark.py`, `negative_audit_report.py` | `#28, #31` | `X01, X24–X26, X44` · **G2/G3** |
