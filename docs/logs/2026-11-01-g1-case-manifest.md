# Ma trận Kiểm lỗi Tích hợp G1 (Case Manifest G1)

Ngày: 2026-11-01
Git HEAD: `5060908ab513dad78b367d0fbda584a115466f49`
Phạm vi: Vertical slice lab G1 (Ticket #03, #15, #19). Lưu ý: Ticket #19 **chưa** đánh dấu done.

---

## Bảng Kết Quả Case X01–X19, X27, X31, X38–X43

| Case | Bằng chứng | Trạng thái | Lệnh / Kết quả |
|---|---|---|---|
| **X01** | Semantic replay cùng fixed inputs/sampling, virtual clock/watermark | `executed-pass` | `pytest tests/test_semantic_replay.py` $\rightarrow$ 6 passed |
| **X02** | Clock jump, RTSP disconnect/reconnect, session/epoch reset | `partial` (automated pass, physical cable pull pending operator) | `pytest tests/test_live_pipeline.py -k test_session_id_invariant_across_disconnect_fallback_and_reconnect` $\rightarrow$ passed; live run: `status.jsonl` có `core_epoch=1` |
| **X03** | NV12/stride khác width, crop/letterbox C02/N03/N04 | `not-run: native core absent` | Chưa triển khai module C++ native giải mã ảnh trực tiếp |
| **X04** | Enabled config sai fail-fast, factory ID lạ, untunable threshold, secrets masked | `executed-pass` | `pytest tests/test_run_edge_startup.py tests/test_module_config_doctor.py` $\rightarrow$ 21 passed; tests startup sai config exit nonzero, live startup hợp lệ `status=ok` |
| **X05** | Poll blocking, stop/cancel/reopen N01/O02 | `not-run: native core absent` | Chưa triển khai native C++ worker bindings |
| **X06** | Slow detector/consumer queue bound O01/O02 | `executed-pass` | `pytest tests/test_capacity_lab.py tests/test_live_pipeline.py` $\rightarrow$ passed |
| **X07** | Kill/hang analytics rồi khởi động lại khi recorder đang ghi | `partial` (dual-session validated, manual kill pending operator) | ADR-0007 nghiệm thu dual-session độc lập; `data/benchmark/rtsp-probe-20261101.json` k=2 passed; recorder ghi 4 segments (1.97MB stream-copy) độc lập với analytics |
| **X08** | Kill recorder/relay, reconnect và đổi codec | `partial` (automated reconnect pass, physical camera disconnect pending operator) | `pytest tests/test_live_pipeline.py -k test_reconnect_increments_core_epoch_exactly_once_no_double_increment` $\rightarrow$ passed; 4 segments `h264` stream-copy recorded |
| **X09** | Race pin vs cleanup; hai event overlap; duplicate pin/release | `executed-pass` | `pytest tests/test_evidence_lifecycle.py tests/test_recorder.py` $\rightarrow$ passed |
| **X10** | Crash sau pending, lúc temp write, sau rename, trước/sau DB finalize | `executed-pass` | `pytest tests/test_crash_recovery.py` $\rightarrow$ passed |
| **X11** | Trigger lúc boot chưa đủ ring; trigger khi đủ ring; source gap giữa pre/post | `executed-pass` | `pytest tests/test_evidence_lifecycle.py` $\rightarrow$ passed |
| **X12** | Crash giữa journal/outbox writes, inject transaction error | `executed-pass` | `pytest tests/test_event_delivery.py` $\rightarrow$ passed |
| **X13** | Server commit thành công rồi drop response; retry duplicate hash | `executed-pass` | `pytest tests/test_event_delivery.py` $\rightarrow$ passed |
| **X14** | Mongo replica set persistent, revision/current/outbox atomic | `executed-pass` | Server live ingestion trên Mongo replica set `192.168.96.2:27017` `rs0` $\rightarrow$ verify kết nối và transaction atomic |
| **X15** | Ngắt upload ở chunk/finalize, gửi lại cùng evidence, sai hash/size | `executed-pass` | `pytest tests/test_edge_uploader.py tests/test_server_evidence.py` $\rightarrow$ passed |
| **X16** | Device/site A thử upload/read/download/review dữ liệu B | `executed-pass` | `pytest tests/test_review_api.py` $\rightarrow$ passed |
| **X17** | Hai reviewer submit cùng version; AI revision tới giữa review | `executed-pass` | `pytest tests/test_review_api.py` $\rightarrow$ passed |
| **X18** | Browser list $\rightarrow$ detail $\rightarrow$ play $\rightarrow$ review; API chậm/401/403/500 | `partial` | Firefox đã kiểm tra xác thực sai/đúng và list render với dashboard đã commit (3/3 events); chưa kiểm tra toàn hành trình detail/play/review và các lỗi API còn lại |
| **X19** | Đo trễ edge commit $\rightarrow$ browser DOM render (P95 $\le 5$s) | `partial` | Report loopback ban đầu: 50/50, P95 **2.325s**, dùng UI chưa commit; smoke dashboard đã commit: 3/3, P95 **1.189s** (`data/benchmark/g1-x19-committed-ui-20261102.json`); chưa đo 50 mẫu trên LAN |
| **X27** | Disk 95%/100%, quota/reserve hết, eligible cleanup | `executed-pass` | `pytest tests/test_quota.py` $\rightarrow$ passed |
| **X31** | Synthetic/replay initial event + revisions/retry | `executed-pass` | `pytest tests/test_event_delivery.py` $\rightarrow$ passed |
| **X38** | Crash event commit trước pin, recorder ACK trước edge receipt | `executed-pass` | `pytest tests/test_evidence_lifecycle.py` $\rightarrow$ passed |
| **X39** | Onset0/trigger15, lying thiếu onset, anchor revised | `executed-pass` | `pytest tests/test_snapshot.py` $\rightarrow$ passed |
| **X40** | Finalized partial upload $\rightarrow$ retry $\rightarrow$ ACK | `executed-pass` | `pytest tests/test_evidence_lifecycle.py tests/test_edge_uploader.py` $\rightarrow$ passed |
| **X41** | Snapshot3 $\rightarrow$ 1 $\rightarrow$ 2, origin immutable | `executed-pass` | `pytest tests/test_snapshot.py` $\rightarrow$ passed |
| **X42** | False positive rồi severity/clip complete mới | `executed-pass` | `pytest tests/test_review_api.py` $\rightarrow$ passed |
| **X43** | Cùng consumer oracle/native, per-stage statuses N05/P03 | `partial` (Python reference pass; native part `not-run: native core absent`) | Python pipeline pass qua `tests/test_danger_zone_flow.py`; native core chưa triển khai |
