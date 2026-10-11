# Hồ sơ readiness cho edge AI camera

**Cập nhật:** 2026-10-11. **Trạng thái:** mẫu thu thập/chưa nghiệm thu; không có số đo hardware trong repo được dùng để ký capacity. Tài liệu này hỗ trợ [kiến trúc](system-architecture.md), không thay đặc tả module.

## Hồ sơ cần khóa

Owner dưới đây là vai trò đề xuất; chủ dự án phải gán người cụ thể, ngày và link bằng chứng trước khi đánh dấu đạt. `TBD`, `null`, `REQUIRED` là thiếu dữ liệu, không phải giá trị nghiệm thu.

| Artifact | Nội dung bắt buộc | Owner đề xuất | Gate |
|---|---|---|---|
| Physical/facts sheet | Camera SKU/firmware; main/sub codec/profile/bitrate/FPS; concurrent sessions đã test; board/RAM/OS/kernel/SDK; storage SKU/TBW/filesystem; switch/VLAN/WAN; UPS/power/thermal enclosure | Edge/platform | Trước BOM và Slice 1 |
| Stream ADR | Upstream/reconnect/capture owner; dual/relay; timestamp mapping; bounded queue; main/sub; kill/hang test | Edge/platform | Trước nghiệm thu Slice 1 |
| Workload/retention | Camera/site, analysis FPS, pose mean/burst, event/day, ring/pre/post, pinned retention, export/delete policy | Product + edge | Trước BOM |
| Preliminary SLO | ODD, latency, evidence completeness, offline autonomy, RPO/RTO scope, AI quality và review capacity | Product + operations | Trước hardware/PoC |
| Storage plan | Mount/quota/reserve, shared physical failure domains, WAL/checkpoint/fsync budget, time-to-full, endurance/backup | Platform | Tối thiểu Slice 1; đủ trước pilot |
| Threat/privacy record | Attacker/trust boundaries, physical access, credentials; căn cứ xử lý, retention/access/transfer, legal approval tên/ngày/site | Security + pháp chế | Trước pilot có dữ liệu thật |
| Model manifest | Exact weights/hash, code/checkpoint/dataset terms, training/source lineage, conversion/runtime/pre/post versions, golden/field report, clearance | ML + pháp chế | Trước release lên site |
| Benchmark/capacity | Workload và provenance, bottlenecks, thermal 24–72h, recording/upload đồng thời, P95/P99 và headroom đã đo | Edge + ML | Trước field pilot |
| Failure/recovery matrix | Fault, expected degraded state, dữ liệu được bảo vệ, detection time/RTO, test evidence và runbook | QA + operations | Trước field pilot |
| Field acceptance | Ngày/đêm/mưa/che khuất, positives/hard negatives, negative-audit sampling/uncertainty, recall/FP và operator load | ML + product | Trước fleet |
| Central SLA/restore | Ingestion/DB/object-store failure domain, durable receipts, backup/restore/HA theo SLA | Backend + operations | Trước fleet theo SLA |

## Site profile tối thiểu

Minh họa dữ liệu cần thu thập, chưa phải schema runtime. Không đưa credential hoặc URI có password vào hồ sơ.

```yaml
site:
  id: REQUIRED
  facts_sheet_ref: REQUIRED
  physical_diagram_ref: REQUIRED
  privacy_approval_ref: REQUIRED
camera:
  id: REQUIRED
  sku_firmware: REQUIRED
  main_stream_profile_ref: REQUIRED # codec/profile/resolution/FPS/bitrate đo
  sub_stream_profile_ref: REQUIRED # hoặc explicit unsupported
  verified_concurrent_sessions: null
  stream_ownership_adr: REQUIRED
odd:
  profile_ref: REQUIRED # min person pixels, light/weather, occlusion/ROI
workload:
  camera_count_per_edge: null
  analysis_fps_per_camera: null
  pose_mean_roi_per_second: null
  pose_burst_roi_per_second: null
evidence:
  mode: REQUIRED # continuous_nvr hoặc event_ring
  pre_roll_seconds: null
  post_roll_seconds: null
  ring_hours: null
  pinned_retention_policy_ref: REQUIRED
  quota_and_reserve_ref: REQUIRED
network:
  measured_uplink_mbps: null
  expected_maximum_outage_hours: null
acceptance:
  preliminary_slo_ref: REQUIRED
  capacity_report_ref: REQUIRED
  field_acceptance_ref: REQUIRED
  approved_by: null
  approved_at: null
```

## Manifest benchmark tối thiểu

Số chưa đo là `null`; điền lý do trong `missing_measurements`. Clock basis phải cho biết capture age hay receive age. Không ký capacity từ manifest mẫu này.

```json
{
  "device_profile_hash": null,
  "camera_profiles_hash": null,
  "model_artifact_hash": null,
  "config_snapshot_hash": null,
  "dataset_manifest_hash": null,
  "duration_hours": null,
  "workload": {
    "camera_count": null,
    "analysis_fps_per_camera": null,
    "pose_mean_roi_per_second": null,
    "pose_burst_roi_per_second": null,
    "recording_and_upload_profile_ref": null
  },
  "clock_basis": null,
  "results": {
    "frame_age_p95_ms": null,
    "frame_age_p99_ms": null,
    "event_latency_p95_ms": null,
    "event_latency_p99_ms": null,
    "recorder_gap_seconds": null,
    "evidence_completeness_ratio": null,
    "fsync_p99_ms": null,
    "max_wal_bytes": null,
    "peak_outbox_bytes": null,
    "max_temperature_c": null,
    "sustained_power_watts": null,
    "resource_timeseries_ref": null,
    "event_quality_report_ref": null
  },
  "missing_measurements": ["Template only; no hardware run"],
  "accepted_capacity": null,
  "approval_ref": null
}
```

## Rủi ro và quyết định còn mở

Priority là thứ tự xử lý thiết kế, chưa phải xác suất định lượng từ vận hành. Ghi likelihood/confidence sau khi có field data; không coi mọi rủi ro dưới đây là lỗi đã xảy ra.

| Risk | Priority | Trigger / bằng chứng cần | Mitigation / quyết định |
|---|---|---|---|
| Recorder phụ thuộc analytics upstream | P0 | Kill/hang analytics tạo segment gap | Stream ADR + fault domain đúng §6.3a |
| Disk full/wear/failure | P0 | Time-to-full, write/fsync error, health/endurance | Quota/reserve/I/O budget; ghi residual physical SPOF; backup theo RPO |
| Capacity hoặc nhiệt không đạt | P0 | Frame age/pose burst/throttle trong soak | Giảm scope/camera, đổi BOM; không chỉ giảm threshold AI |
| Domain shift/ID switch/missing onset | P0 | Field regression/negative audit theo ODD | Persistent-lying path, uncertainty, dataset/acceptance theo site |
| Privacy hoặc artifact license chưa clearance | P0 | Thiếu hồ sơ owner/ngày/phạm vi/hash | Chặn production; không suy license repo thành weights license |
| Native crash làm mất analytics state | P1 trước pilot | Crash/restart hoặc RTO không đạt | Pinned SDK/soak; process isolation có điều kiện, reset epoch |
| Update compromise/rollback/clock uncertain | P0 trước pilot | Bad signature/expired/old sequence/wrong target | Trust bootstrap/rotation/revocation + signed activation tests |
| Malformed storm | P1 trước pilot | Forensic quota/counter tăng | Bounded samples/duplicate compaction; truncation fault |
| WAN hoặc central outage | P1 | Outbox age/bytes, ACK outage | Offline autonomy, reconcile; central HA theo SLA |
| Python/C++ divergence | P1 | Golden/event tolerance fail | Shared conformance kit, chặn release |
| Review overload | P1 | Alerts cần review × phút/alert | TCO gồm true/false/uncertain alerts; ký review capacity |

Không chọn sẵn ba process, shared-memory IPC, WORM compliance mode, Kubernetes hoặc HA đa site. Những lựa chọn đó cần fault test, threat model, retention và SLA; rollback phải giữ trust high-water mark và data compatibility.
