# Phân rã công việc còn lại và wave kế tiếp — 2026-10-24

Ghi chú quyết định + phân rã theo yêu cầu "phân rã công việc và tiếp tục implement". Nguồn tiến độ là
Status/Execution trong từng file issue (không phải snapshot PRD/index); commit/evidence ghi trong log này
và comment của issue được tác động.

## 1. Xuất phát điểm (đã kiểm, không suy đoán)

- HEAD `340b5f2` (docs: sync README with tickets #27, #28, #33, and 526 tests), working tree clean.
- `.venv-oracle/bin/python -m pytest -q`: **526 passed, 126 subtests passed, 232 warnings** trong 133.14s.
- Tracker: 68 issue trong `.scratch/system-build-slices/issues`. Đếm Execution đọc trực tiếp từ file:
  **21 done · 6 partial · 2 blocked · 39 not-started**.

## 2. Hard dependency graph (trích từ dòng `**Blocked by:**` của từng issue)

Chỉ các node còn mở, giữ nguyên số ticket:

```
#03(blocked) -> #10 -> #12 -> #13
#03          -> #34 -> #35 -> #39, #45
#03          -> #57 -> #58..#68
#06(partial) -> #10, #51, #52(blocked)
#07(partial) -> #47
#08,#18      -> #32 -> #36
#15(partial) -> #19
#28,#18      -> #31 -> #38 -> #39
#32,#34,#33  -> #45
```

## 3. Frontier hiện tại

**A. Sẵn sàng, chỉ cần software (không chờ external input):**

| Ticket | Blockers | Ghi chú |
|---|---|---|
| #32 Retained evidence truy hồi có authorization | #08 done, #18 done | Vertical slice server+edge, mở #36/#45 |
| #40 Synthetic probe báo operational fault riêng | #17 done, #05 done | Edge health + notification guard |
| #41 Malformed storm không ăn hết state reserve | #18 done, #05 done | Server ingest hardening |
| #43 Central retention + backup/restore proof | #08 done, #33 done | Retention policy + restore proof |
| #44 UI sản phẩm cho review/annotation | #04, #20, #27 done | Cần UI thật, không demo |
| #47 Vehicle motion + suspected-incident flow | #14 done, #07 partial | Trục phát hành G4b; nhánh metric geometry cần #46 |

**B. Bị chặn bởi một node blocked duy nhất — #03** (fan-out lớn nhất):

`#03` Execution = `blocked`: phần server/edge config + doctor lab đã có, nhưng acceptance gốc đòi
*full PerceptionPipeline/factory* và capability RKNN/RTSP chưa nghiệm thu. Toàn bộ #10/#12/#13,
#34/#35/#39/#45 và #57/#58–#68 nằm sau node này.

**C. Chờ người/hardware (không phải việc agent):** #37 (power-cut), #46 (calibration geometry),
#48/#49/#50 (nghiệm thu G4b/G4a/G5).

**D. needs-info / needs-triage (thiếu đầu vào, không được đóng bằng mock):** #29, #42, #52, #54–#56.

## 4. Thứ tự wave đề xuất

| Wave | Nội dung | Mở khoá |
|---|---|---|
| **0 (này)** | #03 delta: contract config module × camera + fail-fast + registry độc lập | #10, #34, #57 (phần config/seam) |
| 1 | #32 retained-evidence retrieval có authorization | #36, #45 |
| 2 | #41 malformed storm, #40 synthetic probe, #43 retention/backup proof | #49 prerequisites |
| 3 | #34 signed activation giữ LKG → #35 canary/rollback → #39 provisioning/watchdog | #49 |
| 4 | #47 vehicle motion + suspected incident (track G4b), #44 UI review | #48, #49 |
| 5 | #19 → #49 → #50 (nghiệm thu, có người ký) | — |

Nguyên tắc: mỗi wave là một slice dọc có test + evidence thật; không đánh dấu pass cho phần chỉ chạy unit/mock.

## 5. Wave 0 — phạm vi slice được chọn cho lượt này

Chọn **#03 delta requirement (2026-10-20)**, không chọn acceptance gốc:

- Trong scope: cấu hình độc lập **module × camera** gồm enabled/disabled, ROI, lịch, ngưỡng, ngoại lệ;
  enabled thiếu/sai trường bắt buộc **fail-fast với lỗi có ngữ cảnh**, không lộ secrets, không silent skip;
  disabled có reason/capability rõ; module đăng ký độc lập giữ state/config **theo camera/session**,
  activation tại boundary với desired/observed version.
- Ngoài scope (giữ nguyên trạng thái blocked): full `PerceptionPipeline` port + factory/artifact manifest,
  capability RKNN/RTSP. Không tạo factory/artifact giả để đóng ticket.

## 6. Quyết định & giả định (ghi lại thay vì hỏi lại)

1. **Mở wave ở #03 chứ không phải #32** vì #03 là bottleneck duy nhất chặn 3 nhánh lớn; #32 vẫn nằm nguyên
   ở wave 1. *Đảo quyết định nếu* bạn muốn ưu tiên luồng người dùng thấy được (#32) trước — khi đó #03 giữ blocked.
2. **#03 giữ Execution = `partial`**, không `done`: slice delta xong, acceptance gốc còn mở. #34/#57 được phép
   dùng seam config này nhưng không được coi #03 đã nghiệm thu toàn bộ.
3. **#07/#21 partial** chỉ được coi là đủ cho phần *config/seam* của #57; policy alert-condition-anchor (Q36) cho
   nhóm mới vẫn là việc của #57, không suy ra từ person-down.
4. **Không sửa** #29/#42/#52/#54–#56: thiếu đầu vào external hoặc needs-triage.

## 7. Kết quả lượt này

**Đã làm (wave 0, #03 delta slice):**

| Hạng mục | Nội dung |
|---|---|
| `domain/alert_module_config.py` | Contract thuần: `AlertModuleDefinition`, `CameraModuleConfig` (enabled/disabled + reason, ROI normalised, lịch, ngưỡng do definition khai báo, ngoại lệ), `parse_camera_module_config` fail-fast có context và không echo giá trị, `AlertModuleRegistry` (stage/activate/state/reset_session/capabilities) |
| `apps/edge/doctor.py` | `--module-config` (lặp được), `load_module_registry`, `module_capabilities`; `preflight` thêm `capabilities.modules`, exit 1 khi config enabled sai |
| `tests/test_alert_module_config.py` | 21 test: fail-fast theo field, chống leak secret, ROI/lịch/ngưỡng, stage≠activate, reject version cũ giữ LKG, reset session theo camera, capability report |
| `tests/test_module_config_doctor.py` | 6 test: document hợp lệ/sai, malformed, secret không vào report, CLI exit 1, backward-compatible `not_configured` |

**Bằng chứng chạy thật (2026-10-24):**

- `.venv-oracle/bin/python -m pytest tests/test_alert_module_config.py tests/test_module_config_doctor.py -q` → `27 passed`.
- `.venv-oracle/bin/python -m pytest tests/test_edge_doctor.py tests/test_edge_config.py -q` → `12 passed, 13 subtests passed`.
- `.venv-oracle/bin/python -m pytest -q` → `553 passed, 126 subtests passed` trong 123.16s (baseline 526 → +27).
- `mypy domain/alert_module_config.py apps/edge/doctor.py` → 2 lỗi cũ ở `doctor.py:32` (`_SQLITE_FIXED.get` typing), 0 lỗi mới.

**Trạng thái tracker sau lượt này:** #03 `Execution: blocked → partial` (delta slice xong; acceptance gốc + full port/factory
vẫn mở). Các nhánh #10/#34/#57 được phép đi tiếp trên seam config này nhưng không được coi #03 đã nghiệm thu.

**Việc kế tiếp (wave 1):** #32 retained-evidence retrieval có authorization → mở #36, #45. Sau đó wave 2 (#41, #40, #43).

## 8. Tệp thay đổi

- `domain/alert_module_config.py` (mới), `apps/edge/doctor.py`, `tests/test_alert_module_config.py` (mới),
  `tests/test_module_config_doctor.py` (mới), `README.md`, `.scratch/system-build-slices/issues/03-*.md`, log này.
