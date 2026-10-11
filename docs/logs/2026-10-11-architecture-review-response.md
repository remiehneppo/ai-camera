# Đối chiếu review kiến trúc — 2026-10-11

## Phạm vi và hành động

- Người dùng yêu cầu đánh giá review được dán trong hội thoại và cập nhật tài liệu. Chỉ sửa Markdown, không triển khai source/config/tests.
- Gọi CodeGraph status/files cho đúng project: index có 0 files/nodes, không dùng nó làm bằng chứng implementation. Đọc tài liệu Markdown trực tiếp; không index lại hoặc sửa `.codegraph/`.
- Đọc kiến trúc, log review cũ, quy ước docs và nghiên cứu liên quan. Local routing toggle không bật, nên không gọi `lma`. Không dùng subagent.
- Kiểm chứng nguồn bên ngoài bằng trang hãng/spec/cơ quan nhà nước. Các citation opaque trong review (`filecite`, `turn...`) không dùng được như nguồn của repo.
- Cập nhật `system-architecture.md`; thêm `deployment-readiness.md` và log này. Giữ lịch sử log cũ, cập nhật quyết định hiện hành trong tài liệu chính.

## Chấp nhận / làm rõ

| Nhận định | Đối chiếu và thay đổi |
|---|---|
| Giữ edge-first, semantic ports, domain/Python và native hot path | Đồng ý; không có lý do rewrite/microservices. Journal không tự là event sourcing |
| RTSP ownership mơ hồ | Đúng: §2 recorder riêng nhưng §7.2 vẽ demux chung chưa có owner. Thêm §6.3a, sửa pipeline; ADR dual/relay phải có camera test |
| Storage SPOF và contention | Đúng; thêm classes/quota/reserve/I/O budget và residual physical risk (§9.1a) |
| Thiếu số đo capacity | Đúng, tài liệu vốn là reference design. Thêm facts sheet/benchmark manifest và phân kỳ SLO; không gán FPS/TOPS giả |
| Native SDK segfault giết analytics | Đúng và đã có process-isolation option. Cụ thể hóa trigger/RTO/epoch/timeout/IPC conformance; giữ in-process ban đầu |
| Malformed persistence vô hạn | Đúng về risk. Thay invariant bằng bounded forensic sample/duplicate counters/quota/truncation fault; không compact incident hợp lệ |
| Server dedup/outbox | Dedup đã có, thiếu constraint/conflicting-payload semantics và transaction notification outbox. Bổ sung; không hứa exactly-once notification |
| Graceful degradation | Policies đã rải rác; tập trung thứ tự, hysteresis, recovery và capability visibility |
| Supply chain/privacy phải operationalize | Đã có device trust, signed bundle, SBOM/provenance. Bổ sung trust/time/rollback semantics, hồ sơ owner/phê duyệt và nâng baseline identity/provenance lên trước field pilot |
| Conformance kit | Golden parity đã có; hợp nhất test vectors/preprocess/tracker/event provenance thay test riêng mỗi backend |
| Config explosion | Immutable snapshot/version đã có (§6.1); readiness tham chiếu hash/snapshot, không thêm hệ config mới hoặc nhồi config vào event |

## Điều chỉnh / không nhận nguyên văn

| Nhận định của review | Kết luận |
|---|---|
| Ba fault domains là topology production mặc định | Chưa đủ bằng chứng. Tách recorder bắt buộc; perception process riêng có điều kiện. Một upstream/relay cũng là SPOF nguồn chung, không luôn tốt hơn dual sessions |
| Một upstream = một session/camera | Chỉ đúng cho cùng stream profile. Record main + analyze sub có thể cần hai upstream profiles; dual sessions không luôn gấp đôi tổng bitrate camera |
| RPO=0 nhờ WAL/FULL hoặc finalized file | Cần điều kiện storage/flush/media còn lành. Không chống disk/site loss; bổ sung durability boundary |
| Tách storage class/partition loại bỏ SPOF | Chỉ hạn chế quota/fill; cùng disk/controller/power vẫn chung failure domain |
| Forensic compaction bảo đảm không mất fact | Không thể hứa dưới unique-payload flood, quota đầy hoặc media lỗi. Phải báo truncation/degraded; counter cũng cần persistence budget |
| IPC migration chỉ đổi factory + shared-memory ring | Semantic API có thể giữ nhưng failure/restart semantics thay đổi. ObservationBatch không có pixels thì socket bounded thường đủ; shared memory chưa cần |
| Rollback về legacy signed manifest | Có thể mở lại rollback attack; không chọn bypass verification. Operational rollback dùng authorization sequence mới trỏ artifact cũ được phép |
| Signed YAML fields đủ như TUF | Không đủ: cần canonical signed bytes, trusted roles/keys/bootstrap, durable high-water mark, trusted time/expiry và recovery policy. Không tự nhận TUF compliance |
| Evidence completeness tính cả partial | Sửa SLI cũ: partial có lý do vẫn không phải complete |
| Trừ trực tiếp PTS/capture khỏi processing time | Chỉ hợp lệ sau clock mapping; thêm uncertainty và receive-age fallback |
| False alerts formula là toàn bộ human review | Chỉ là chi phí false-positive; tổng review còn true/uncertain/escalation |
| Effort S/M/L và likelihood cố định | Thiếu team/workload/field data; không đưa estimate thành cam kết. Risk register ghi priority và trigger thay xác suất giả |
| Copy systemd snippet/WORM thành default | Không copy: watchdog cần app heartbeat, device access/runtime phải test; immutable/WORM theo threat/legal policy và retention/delete compatibility |
| “Security/legal/supply chain mới policy” | Chỉ đúng về mức chưa implement, không đúng nếu hiểu là thiếu design: §6.18/9.3 đã có lifecycle, provenance, canary/replay và privacy gate |

## Nguồn kiểm chứng và giới hạn

- [Raspberry Pi processors / BCM2712](https://www.raspberrypi.com/documentation/computers/processors.html): HEVC hardware decode, codec khác software; CPU percentages trong tài liệu hãng là tham khảo, không thay workload benchmark.
- [NVIDIA Orin Nano encoding](https://docs.nvidia.com/jetson/archives/r36.5/DeveloperGuide/SD/Multimedia/SoftwareEncodeInOrinNano.html): Orin Nano thiếu NVENC; không suy sang Jetson Nano hoặc mọi Jetson SKU.
- [SQLite WAL](https://www.sqlite.org/wal.html), [PRAGMA](https://www.sqlite.org/pragma.html), [sync limitations](https://www.sqlite.org/howtocorrupt.html): WAL/FULL sync commit, NORMAL có thể mất commit sau power loss; storage vẫn phải thực hiện đúng sync.
- [TUF specification](https://theupdateframework.github.io/specification/): trust roles, version/expiry/rollback semantics; [SLSA 1.2](https://slsa.dev/spec/v1.2/): approved specification, có Source Track. Chưa đánh giá project đạt level nào.
- [Luật 91/2025/QH15](https://vanban.chinhphu.vn/?classid=1&docid=214590&pageid=27160&typegroup=), [Điều 32/hiệu lực](https://xaydungchinhsach.chinhphu.vn/quy-dinh-bao-ve-du-lieu-ca-nhan-thu-duoc-tu-hoat-dong-ghi-am-ghi-hinh-tai-noi-cong-cong-119250730154729554.htm), [Nghị định 356/2025/NĐ-CP](https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-356-2025-nd-cp-468371.htm), [Luật 116/2025/QH15](https://congbao.chinhphu.vn/van-ban/luat-so-116-2025-qh15-468678/61574.htm): mốc hiệu lực trong review được nguồn chính thức xác nhận. Xác nhận tồn tại/hiệu lực không thay legal clearance cho site.
- [MMPose issue #3273](https://github.com/open-mmlab/mmpose/issues/3273): câu hỏi cho hai exact checkpoints, không phải kết luận pháp lý hay blanket restriction.

## Kiểm tra và việc còn mở

- Kiểm tra local Markdown links, fenced YAML/JSON samples và cấu trúc bảng; kiểm tra các đoạn SLO/roadmap/security/stream liên quan để tránh quyết định trái nhau.
- Chưa có hardware benchmark, fault injection, soak, field acceptance hoặc legal approval mới. ADR stream ownership còn mở có chủ đích; không tạo ADR accepted thiếu facts sheet.
- Không commit/push. Các tài liệu đã untracked từ trước; không stage hoặc thay đổi `.git`/các file nghiên cứu/AGENTS.md.

## Commit theo yêu cầu tiếp theo

- Người dùng yêu cầu commit. Repo chưa có commit; phạm vi commit đầu tiên chỉ gồm tài liệu kiến trúc hiện hành, deployment readiness và log này. Các file nghiên cứu/hướng dẫn/index đã untracked từ trước giữ ngoài commit; do đó link tới nghiên cứu cần các file local hiện có, chưa đủ trong checkout chỉ từ commit này.
- Kiểm tra lại staged whitespace và danh sách file trước commit; không push.
