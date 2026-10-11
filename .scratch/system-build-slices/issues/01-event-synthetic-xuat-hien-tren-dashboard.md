# 01: Event synthetic xuất hiện trên dashboard

Status: ready-for-agent
Execution: done
Owner: Codex agent (Edge / Backend / dev demo)

**What to build:** Gửi một event synthetic từ edge lab, lưu event cùng delivery intent bền vững, server commit rồi hiển thị metadata trên demo.

**Blocked by:** None (can start immediately).

## Acceptance criteria

- [x] Mongo replica set lab có persistent volume và readiness transaction; device auth/schema limits có ngay trong luồng đầu.
- [x] SQLite event/outbox và Mongo revision/current/downstream intent atomic; receipt chỉ sau commit; synthetic không notification.

- [x] Event revision là full snapshot; origin live/replay/synthetic bất biến và độc lập taxonomy; event/outbox/pin intent atomic khi có yêu cầu evidence.

Chuẩn semantic: [Hợp đồng tích hợp](../../../docs/architecture/contracts.md).

## Traceability

Task nguồn: C01, C03, B01, J01, S01, UI01.

Task IDs là mapping phạm vi baseline/integration/hardening; Blocked by là dependency chung; Conditional blockers áp dụng theo target đã chọn. Không phải hoàn thành toàn module nguồn trước khi làm lát cắt này.

## Evidence và handoff

Khi hoàn tất, ghi command/fixture thật, expected/actual, commit/config/model/data/platform versions, report và phần chưa chạy. Thay shared contract phải kiểm producer/consumer, clocks/status/provenance/reset, auth/validation và release/bounds theo phạm vi. Unit/mock pass không thay hardware/browser/fault/field acceptance.

## Comments

- 2026-10-11: Người dùng đã duyệt breakdown 50 ticket; publish vào local Markdown tracker. Chưa claim/implement/test, các acceptance vẫn mở.

- 2026-10-11: Đồng bộ contract sau review; acceptance bổ sung chưa chạy, Execution vẫn not-started.

- 2026-10-12: Claim implementation scope `domain/event_contract.py`, `apps/edge/`, `apps/server/`, `infra/`, `tests/`, and Compose/dependency files for the synthetic event vertical slice. CodeGraph index is empty; implementation follows the accepted docs and adds the first runtime files.

- 2026-10-12: First MongoDB 8.0.32 container could not start on the host's Linux 6.19 kernel (SERVER-121912); Compose now pins MongoDB 7.0.43 and uses a fresh version-specific volume for the lab replica set.

- 2026-10-12: Done. `python3 -m unittest discover -s tests -v` passed 10 tests. Compose MongoDB 7.0.43 startup and transaction-readiness probe passed; API health and dashboard HTML returned 200; edge synthetic delivery returned a durable receipt; invalid dashboard token returned 401, authenticated device mismatch 403, oversized request 413, duplicate revision returned the identical receipt, changed content and origin changes returned 409, and revisions 3→1 left current at 3. Local database after smoke checks: 4 immutable revisions, 3 current events, 4 synthetic/replay ineligible decisions, 0 eligible intents. Browser visual testing and hardware/power-cut gates were not run. See [implementation log](../../../docs/logs/2026-10-12-ticket-01.md).

- Evidence pin intent was not requested by this synthetic fixture; pin/capture behavior remains in ticket #07 and was not claimed by #01.
