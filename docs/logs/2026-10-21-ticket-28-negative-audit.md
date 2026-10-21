# Ticket #28 — Negative audit sampler + G2 quality regression report (2026-10-21)

## Phạm vi

Lát cắt #28 gồm:

- `apps/edge/audit_sampler.py`: `NegativeAuditSampler` lấy mẫu segment no-alert trước ring expiry
  theo `SamplingPlan` (stratum + `p_h`), ghi manifest `pending_review` vào
  `<evidence_dir>/audit_samples/`.
- `tools/negative_audit_report.py`: CLI dựng report G2 có version, weighted recall + CI 95%,
  per-branch, FP/camera-hour & camera-day, review load, sample sufficiency, verdict
  `PASS/FAIL/BLOCKED` và block owner sign-off.
- `domain/quality_eval.py`: **không có trong workspace** tại thời điểm bắt đầu; đã tạo theo
  contract tối thiểu đã báo dispatcher (`SamplingPlan`/`Stratum` + `evaluate_quality_metrics`).
  Nếu agent khác cũng sở hữu file này, cần reconcile theo contract ở mục "Quyết định" bên dưới.

Không đổi event/evidence/review contract hiện hữu; không thêm dependency ngoài stdlib.

## Quyết định

1. **Sampling tất định bằng SHA-256**, key = `salt|plan_version|stratum|camera|start|end`; không
   dùng RNG toàn cục nên replay cùng ring cho cùng quyết định. `sample_id` là UUIDv5 tất định
   theo cùng key, dedupe trong process + đọc manifest sẵn có: cùng một window không thể nhân đôi
   denominator. Window có alert (`alert_count > 0`) không bao giờ thành audit sample.
2. **Alert là census, negative sample là survey**: alert không lấy `p_h` từ plan (mặc định
   weight 1, chỉ dùng `inclusion_probability` nếu record tự khai); negative sample lấy `p_h`
   từ plan theo stratum. Record khai `p_h` lệch plan → `inclusion_probability_mismatch` và BLOCKED,
   vì weight sai làm hỏng estimator.
3. **Recall = Horvitz-Thompson ratio** trên `Σw·detected / Σw·(detected+missed)`; CI 95% Wilson
   trên Kish effective sample size. Không cộng raw count giữa các stratum khác `p_h`.
4. **FP denominator = HT-estimated camera-hours** từ chính negative samples
   (`Σ duration_hours / p_h`); FP/camera-day = FP/camera-hour × 24. Raw sampled hours vẫn được báo
   cạnh estimate để thấy độ phóng đại.
5. **Alerts-only không bao giờ có recall số**: khi `negative_samples_reviewed == 0`, `recall` và
   mọi `branches[*]` bị set `estimate/ci_low/ci_high = None`, `usable=false`; verdict BLOCKED.
   Bookkeeping weight (`weighted_*_units`) vẫn giữ để audit nhưng không dùng làm recall.
6. **Verdict**: BLOCKED khi alerts-only/không có recall unit/sample không đủ/coverage gap
   (missing stratum, unplanned sample, rights chưa clear, thiếu `p_h`, alert chưa review, mismatch
   `p_h`) hoặc `ci_low < min_recall`; FAIL khi recall point < target hoặc FP/day > target;
   PASS chỉ khi đủ mẫu, đủ coverage và `ci_low >= min_recall`.
7. **Review load** tính từ `review_seconds`/`review_minutes` của cả alert và negative sample;
   per camera-day dùng observation days suy từ HT hours (rất nhỏ với fixture ngắn — đọc kèm hours).
8. Report có `schema_version`/`report_version`, hash từng input, `plan_version` + `plan_sha256`,
   protocol pins (confidence, min samples, denominator, estimator, interval method), timestamp
   override được để chạy golden.

## Bằng chứng chạy (2026-10-21)

Môi trường: `.venv-oracle` (Python 3.12), workspace `AI-Camera-OC`.

```bash
.venv-oracle/bin/python tools/negative_audit_report.py --help   # exit 0, in usage đầy đủ
PYTHONPATH=. .venv-oracle/bin/pytest tests/test_negative_audit_flow.py -q  # 47 passed, 8 subtests
PYTHONPATH=. .venv-oracle/bin/pytest tests -q                   # 519 passed, 126 subtests
```

Fixture tổng hợp `/tmp/t28` (không commit): plan 2 stratum `p_h=0.5/0.25`, 4 alert
(3 confirmed, 1 false positive), 5 negative sample (1 missed `person_fall`, 1 pending review).

| Case | Command chính | Kết quả |
|---|---|---|
| Alerts-only | `--alerts alerts.jsonl` | `BLOCKED ['alerts_only']` (không báo recall) |
| Recall dưới target | thêm `--negatives/--plan --min-samples 3` | `FAIL ['recall_below_target:0.6000 < 0.9']` |
| Thiếu mẫu theo plan | plan `min_samples=5` | `BLOCKED ['insufficient_sample', 'effective_negative_samples=4.57 < min_samples=5']` |
| CI không đạt target | 9/10 detected, n_eff 10 | `BLOCKED ['uncertainty_below_target:ci_low=0.5958 < 0.9']` |
| PASS | 60 confirmed + 30 reviewed clear | `PASS`, recall 1.0, ci_low 0.9398, FP/day 0 |
| `p_h` mismatch | record 0.9 vs plan 0.5 | `BLOCKED ['coverage_incomplete', 'inclusion_probability_mismatch:1']` |
| Sampler p=1 | `sample_window(cam, 100, 160)` | record đủ field spec; gọi lại → `None` (dedupe) |
| Sampler có alert | `alert_count=2` | `None`, không ghi manifest |
| Sampler p≈0 | stratum `p=1e-6` | `None`; `should_sample=False` |
| Segment adapter | `sample_segment(Segment)` | map `session_id` → camera, ghi record |
| Manifest dir | `--negatives evidence/audit_samples` | tự bỏ `plan.json`, report đọc được `samples.jsonl` |
| Output | `--output report.md` / `report.json` | suy format theo đuôi, ghi file, markdown đủ block |
| `--strict` | alerts-only | exit 2 (BLOCKED); PASS exit 0 |

## Chưa chạy / giới hạn

- Chưa có site/camera thật, chưa có reviewed data thật: toàn bộ số trên là fixture tổng hợp,
  **không phải nghiệm thu chất lượng** và không thay field/benchmark/hardware acceptance.
- `tests/test_negative_audit_flow.py` (47 test) được một agent khác viết song song trong cùng
  workspace, không nằm trong task book của log này; nó khóa đúng contract `blocking_gaps`,
  `sample_sufficiency`, `wilson_interval`, sampler manifest và CLI. Toàn bộ 47 test pass với
  implementation này, full suite 519 passed.
- `matching_window_seconds` chỉ được pin khi truyền `--matching-window-seconds`; chưa có giá trị
  được duyệt từ site nên report ghi warning `matching_window_not_pinned`.
- Ngưỡng `min_recall`, `max_fp_per_day`, `min_samples`, owner signer vẫn `pending` theo
  `docs/architecture/lab-profile.md`; report chỉ tạo block sign-off, không tự ký.
- Chưa tích hợp sampler vào vòng đời recorder/pipeline đang chạy (`live_pipeline`/`evidence`):
  caller phải gọi `sample_segment`/`sample_window` trước ring expiry.
- Chưa commit: các file đang ở trạng thái untracked, chờ dispatcher review/commit.
