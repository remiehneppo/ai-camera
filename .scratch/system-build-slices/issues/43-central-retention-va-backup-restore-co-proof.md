# 43: Central retention và backup/restore có proof

Status: ready-for-agent
Execution: done (software lab; central retention manager + backup/restore reconciliation proof pass)
Owner: Gán theo ownership Edge/Domain/ML/Backend/UI/QA trong checklist đã duyệt; chưa claim.

**What to build:** Retention/delete/export đúng policy rồi restore Mongo metadata và evidence vào môi trường tách biệt.

**Blocked by:** [#08: Upload evidence và phát lại trên detail](08-upload-evidence-va-phat-lai-tren-detail.md); [#33: Device lifecycle và site access được enforce](33-device-lifecycle-va-site-access-duoc-enforce.md).

## Acceptance criteria

- [x] Restore/reconcile pending/missing/corrupt/orphan/hash/scope và immutable receipts; DB/file không transaction chung.
- [x] Production topology/storage/HA/SLA có decision owner; report RPO/RTO, Mongo one-member lab không coi HA.

## Traceability

Task nguồn: E03, E02.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.
- 2026-10-27: Hoàn thành implementation và reconciliation proof trong software lab.
  `domain/retention_contract.py`: Định nghĩa central retention policy (7 ngày mặc định, bảo vệ clip có retrieval
  đang mở, legal hold/pinned, và unreviewed high/critical severity), RBAC và audit record cho central delete/export;
  hàm chuyển trạng thái manifest sang `expired` nhưng bảo tồn 100% receipt gốc (`sha256`, `size_bytes`,
  requested/actual ranges); logic phân loại reconciliation (`verified`, `pending`, `missing`, `corrupt`, `orphan`).
  `apps/server/retention.py`: `CentralRetentionManager` thực hiện sweep/delete/export an toàn mà không giả định
  transaction chung giữa Mongo và đĩa; `create_backup_bundle` snapshot toàn bộ 9 metadata collections + clips
  vào bundle cách ly kèm SHA-256 manifest; `restore_and_reconcile` tái dựng metadata và đối soát từng file, đo
  RPO/RTO thực tế và gắn disclaimer bắt buộc `ha_disclaimer: "lab_single_replica_not_production_ha"`.
  Evidence: `pytest tests/test_central_retention_backup.py -q` ⇒ **4 passed**;
  `mypy domain/retention_contract.py apps/server/retention.py tests/test_central_retention_backup.py` sạch.