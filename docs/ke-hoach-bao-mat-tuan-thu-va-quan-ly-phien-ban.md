# Kế hoạch bảo mật và quản lý phiên bản: phạm vi tham chiếu

## Phạm vi đối chiếu với code `17d9a32`

Tài liệu này ghi định hướng và các mục cần thẩm định; không phải chứng nhận tuân thủ, thiết kế production đã accepted hoặc bảng chức năng đã triển khai. Các đoạn về HSM/TPM, LUKS, mTLS, VLAN/flow compiler, NVR, redaction và export hai người duyệt phải có quyết định, code và evidence riêng trước khi coi là hiện trạng CiviWatch. Những tham chiếu ADR-0012/ADR-0017 trong nội dung không thuộc tập ADR-0001–0008 của repository này; không dùng chúng để ghi đè quyết định hiện hành.

Hiện trạng kỹ thuật đã đối chiếu:

| Hạng mục | Có trong baseline | Giới hạn |
|---|---|---|
| Media control | go2rtc `1.9.15` pin digest, credential bên ngoài, local auth, kiểm origin/allowlist route và chặn chuyển tiếp credential khác origin | Smoke cô lập xác nhận HTTP 401/200, foreign-origin 403 và admin-route 404; HTTP Basic không mã hóa đường truyền |
| Dashboard | Xóa token gỡ storage và URL media/evidence, chặn refresh cũ khôi phục nội dung; query credential được bỏ khỏi thanh địa chỉ | Không suy ra token chưa từng xuất hiện ở request/proxy log trước khi trang xử lý |
| Durability và rollout | SQLite event/outbox/request intent cùng transaction; code có signed activation/LKG và canary/rollback | Pin/file I/O nằm ngoài DB transaction; chưa chứng minh power-cut, TPM/HSM hoặc target rollout production |
| Hậu kiểm hình ảnh | Feature verifier mặc định offline; remote verifier chỉ khi được chọn tường minh | Muốn gửi ảnh tới endpoint bên ngoài phải có phê duyệt dữ liệu/residency; output AI vẫn là đề xuất |

Bằng chứng và giới hạn: [remediation log](logs/2026-11-11-review-remediation.md), [hợp đồng tích hợp](architecture/contracts.md), [readiness](architecture/deployment-readiness.md). Phần căn cứ pháp lý bên dưới giữ vai trò danh mục tham chiếu cần pháp chế xác minh hiệu lực và phạm vi áp dụng trước khi sử dụng; lần đồng bộ này không xác nhận nội dung pháp lý hoặc tiêu chuẩn đã đáp ứng.

---

## I. Căn cứ Pháp lý & Tiêu chuẩn Kỹ thuật Tham chiếu (Nguồn Kiểm chứng Trực tiếp)

Mọi giải pháp kỹ thuật trong kế hoạch này đều được ánh xạ trực tiếp và truy vết tới các văn bản quy phạm pháp luật của Nhà nước Việt Nam và các tiêu chuẩn kỹ thuật quốc tế chính thức:

### 1. Văn bản Pháp lý & Quy chuẩn Việt Nam
* [Thông tư số 48/2026/TT-BCA của Bộ Công an ban hành QCVN 14:2026/BCA](https://vbpl.vn/van-ban/chi-tiet/thong-tu-48-2026-tt-bca-ban-hanh-quy-chuan-ky-thuat-quoc-gia-ve-thiet-bi-camera-giam-sat-su-dung-giao-thuc-internet-cac-yeu-cau-an-ninh-mang-co-ban--9048b740-541f-11f1-b175-1fe27ccb5c48): Quy chuẩn kỹ thuật quốc gia về an toàn thông tin mạng và an ninh thông tin đối với hệ thống camera giám sát (yêu cầu an toàn đầu ghi §2.2, mạng §2.3, lưu trữ §2.4, phần mềm VMS §2.5, thiết bị biên Edge Box §2.6).
* [QCVN 11:2026/BCA do Bộ Công an ban hành](https://tcvn.gov.vn/bo%cc%a3-cong-an-ban-hanh-qcvn-112026-bca-ve-thiet-bi-camera-giam-sat-su-dung-giao-thuc-internet/14/05/2026/): Quy chuẩn kỹ thuật quốc gia về thiết bị camera giám sát sử dụng giao thức Internet.
* [Nghị định 13/2023/NĐ-CP của Chính phủ về Bảo vệ Dữ liệu Cá nhân](https://xaydungchinhsach.chinhphu.vn/print/toan-van-nghi-dinh-13-2023-nd-cp-bao-ve-du-lieu-ca-nhan-119230516104357809.htm): Quy định bắt buộc về bảo vệ hình ảnh, khuôn mặt, biển số xe; quy định ghi âm/ghi hình tại nơi công cộng (Điều 8, Điều 18, Điều 25); đánh giá tác động xử lý dữ liệu cá nhân (DPIA).
* [Luật Bảo vệ Dữ liệu Cá nhân số 91/2025/QH15](https://chinhphu.vn): Nguyên tắc tối thiểu hóa thu thập dữ liệu; cấm chuyển dữ liệu ra nước ngoài khi chưa được phê duyệt; cơ chế lưu trữ có thời hạn và xóa dữ liệu an toàn.
* [Nghị định số 85/2016/NĐ-CP của Chính phủ về Bảo đảm An toàn Hệ thống Thông tin theo Cấp độ](https://vanban.chinhphu.vn/?pageid=27160&docid=185340): Thiết kế, triển khai và kiểm toán hệ thống camera an ninh giám sát trật tự đô thị theo tiêu chuẩn **Cấp độ 3**.
* [Quyết định số 502/QĐ-TTg của Thủ tướng Chính phủ](https://chinhphu.vn/?pageid=27160&docid=217334&classid=2): Phê duyệt Phương án kết nối, chia sẻ dữ liệu giữa các hệ thống camera giám sát an ninh, trật tự, xử lý vi phạm và điều hành giao thông với CSDL quốc gia về dân cư và Trung tâm giám sát, điều hành đô thị thông minh (IOC).
* [Quyết định ban hành Bộ tiêu chí an toàn thông tin mạng cơ bản cho camera giám sát của Bộ Thông tin và Truyền thông](https://beta.mic.gov.vn/ban-hanh-bo-tieu-chi-yeu-cau-an-toan-thong-tin-mang-co-ban-cho-camera-giam-sat-197240508125815623.htm).

### 2. Tiêu chuẩn Kỹ thuật Quốc tế & Nguồn mở
* [RFC 8446 — The Transport Layer Security (TLS) Protocol Version 1.3](https://www.rfc-editor.org/rfc/rfc8446.html): Chuẩn mã hóa kênh truyền bảo mật.
* [RFC 8032 — Edwards-Curve Digital Signature Algorithm (EdDSA - Ed25519)](https://www.rfc-editor.org/rfc/rfc8032.html): Chuẩn ký số chữ ký Ed25519 cho gói model và gói luật.
* [RFC 9457 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html): Định dạng chuẩn hóa thông báo lỗi API.
* [ONVIF Profile G Specification](https://www.onvif.org/profiles/profile-g/): Chuẩn trích xuất, phát lại và lưu trữ video phục vụ điều tra chứng cứ.
* [OASIS PKCS #11 v3.0 — Cryptographic Token Interface Standard](https://docs.oasis-open.org/pkcs11/pkcs11-base/v3.0/pkcs11-base-v3.0.html): Chuẩn giao tiếp phần cứng bảo mật HSM.
* [NIST FIPS 140-2 / FIPS 140-3 Security Requirements for Cryptographic Modules](https://csrc.nist.gov/publications/detail/fips/140-3/final): Tiêu chuẩn bảo vệ khóa trên thiết bị phần cứng bảo mật USB HSM.
* [TCG TPM 2.0 Library Specification](https://trustedcomputinggroup.org/resource/tpm-library-specification/): Chuẩn bảo vệ khóa và đo lường tính toàn vẹn phần cứng qua PCR.
* [CycloneDX v1.6 SBOM Specification](https://cyclonedx.org/specification/overview/): Chuẩn định danh thành phần phần mềm và kiểm toán chuỗi cung ứng.
* [Sigstore Cosign Specification](https://docs.sigstore.dev/cosign/overview/): Chuẩn ký và xác minh chữ ký số ảnh container.
* [Linux Unified Key Setup (LUKS2)](https://gitlab.com/cryptsetup/cryptsetup): Chuẩn mã hóa khối lưu trữ trên phân vùng Linux.
* [SPDX License List v3.23](https://spdx.org/licenses/): Danh mục chuẩn hóa giấy phép mã nguồn mở.

---

## II. Phân rã Kỹ thuật theo 5 Trụ cột Bảo mật & Quản lý Phiên bản

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   KIẾN TRÚC BẢO MẬT & QUẢN LÝ PHIÊN BẢN CHUẨN VIỆT NAM            │
├────────────────────────────────┬─────────────────────────────────────────────────┤
│ 1. AN NINH MẠNG & PHÂN VÙNG    │ Whitelist luồng F01-F36, RTSPS Pinning, mTLS,  │
│    (QCVN 14 Mục 2.3)           │ Cách ly 5 VLAN, nftables DROP, chống TOCTOU.    │
├────────────────────────────────┼─────────────────────────────────────────────────┤
│ 2. KHÓA CỨNG BIÊN (EDGE)       │ LUKS2 + TPM2 (PCR 0+7), Secure Boot, Anti-tamper│
│    (QCVN 14 Mục 2.6)           │ GPIO 298, Chặn USB/UART, Hạ tải quá nhiệt.      │
├────────────────────────────────┼─────────────────────────────────────────────────┤
│ 3. DỮ LIỆU CÁ NHÂN & CHỨNG CỨ │ Không ReID, Làm mờ (D-FINE-N), NVR 24/7 độc lập,│
│    (Luật 91/2025 & NĐ 13/2023) │ EvidenceStore chỉ ghi, Xuất 2 người duyệt AES-256│
├────────────────────────────────┼─────────────────────────────────────────────────┤
│ 4. QUẢN LÝ PHIÊN BẢN & KÝ SỐ   │ Tách khóa 2 cấp (HSM offline & USB HSM trên máy),│
│    (ADR-0012, ADR-0017)        │ Staged Rollout (Canary A/B), Cổng G1-G4.        │
├────────────────────────────────┼─────────────────────────────────────────────────┤
│ 5. CHUỖI CUNG ỨNG & KIỂM TOÁN  │ Cấm AGPL/GPL (R7), Quét Trivy 0 High/Crit,      │
│    (Nghị định 331/2026/NĐ-CP)  │ SBOM CycloneDX 1.6, Nhật ký chuỗi băm SHA-256.  │
└────────────────────────────────┴─────────────────────────────────────────────────┘
```

---

### Trụ cột 1: An ninh Mạng, Phân vùng & Bảo mật Kênh truyền (QCVN 14 Mục 2.3)

#### 1.1. Phân vùng Mạng vật lý & Logic (5 VLAN độc lập)
* **`VLAN_CAMERA` (VLAN 111–118, subnet `10.21.n.0/24`):** Bật chế độ Port Isolation / Private VLAN trên switch lớp 2. Các camera tuyệt đối không được giao tiếp ngang hàng với nhau. Camera chỉ được phép nói chuyện với Switch cụm, NVR và Hộp biên cụm.
* **`VLAN_EDGE` (VLAN 121–128, subnet `10.22.n.0/28`):** Hộp AI biên chỉ mở luồng ra tới máy chủ trung tâm (`cw-backend`), máy GPU (`cw-fleet`), và NTP trụ sở.
* **`VLAN_SERVER` (VLAN 130, subnet `10.23.0.0/24`):** NVR chính/dự phòng, Máy chủ CiviWatch, Máy GPU (vLLM, Fleet), Máy chủ thời gian NTP GPS.
* **`VLAN_MGMT` (VLAN 140, subnet `10.24.0.0/22`):** Quản trị thiết bị mạng; kết nối từ ngoài vào bắt buộc qua VPN IPsec/IKEv2 xác thực bằng chứng chỉ máy khách mTLS (không sử dụng mật khẩu).
* **`DMZ` (VLAN 160, subnet `10.26.0.0/28`):** Máy chuyển luồng MediaMTX và bộ xuất [Phương án 502](https://chinhphu.vn/?pageid=27160&docid=217334&classid=2); ngăn chặn hoàn toàn kết nối từ bên ngoài gọi ngược vào vùng camera.

#### 1.2. Danh sách trắng Luồng mạng (Zero-Trust Network Flows)
* **Nguồn sự thật duy nhất:** Toàn bộ kết nối được khai báo tập trung tại tệp dữ liệu máy đọc được (`flows.yaml`) gồm 36 luồng vật lý F01–F36 và 7 luồng nội bộ I01–I07.
* **Trình sinh cấu hình tường lửa tự động:** Sử dụng công cụ `flowgen` biên dịch trực tiếp sang quy tắc **`nftables`** (bảng `inet civiwatch`):
  ```nftables
  table inet civiwatch {
      chain input {
          type filter hook input priority filter; policy drop;
          ct state established,related accept
          iifname "lo" accept
      }
      chain forward {
          type filter hook forward priority filter; policy drop;
          ct state established,related accept
          # Chỉ cho phép các cổng container được công bố trong flows.yaml
          ct original ip daddr $SERVER_IP ct original proto-dst 8443 accept
      }
      chain output {
          type filter hook output priority filter; policy drop;
          ct state established,related accept
          oifname "lo" accept
      }
  }
  ```

#### 1.3. Mã hóa Toàn trình & Ghim Vân tay Chứng chỉ (Certificate Pinning)
* **Luồng Camera $\rightarrow$ Hộp biên / NVR (F01, F02):** Bắt buộc giao thức **RTSPS (TCP 322)** theo [RFC 8446 (TLS 1.3)](https://www.rfc-editor.org/rfc/rfc8446.html). Tuyệt đối cấm kết nối RTSP thường (TCP 554). Hộp biên và NVR ghim chặt vân tay chứng chỉ SHA-256 của từng camera (`sourceFingerprint`). Ngắt kết nối ngay lập tức nếu phát hiện lệch vân tay (ngăn chặn tấn công giả mạo luồng T03).
* **Luồng Hộp biên $\rightarrow$ Máy chủ (F07, F08, F10):** Bắt buộc giao thức **HTTPS mTLS**. Máy chủ xác thực chứng chỉ máy khách của hộp biên (`CN = EDGE-Cn`), đối chiếu trạng thái `cert_status = ACTIVE` trong cơ sở dữ liệu trước khi tiếp nhận dữ liệu.
* **Chống tấn công TOCTOU tại DMZ:** Trình truyền tải `_PinnedStream` kiểm tra và xác thực mã băm SHA-256 của chứng chỉ máy chủ đích trực tiếp trong bước bắt tay TLS của kết nối socket trước khi gửi byte dữ liệu đầu tiên.

---

### Trụ cột 2: Khóa cứng Thiết bị Biên & Cơ chế Chịu lỗi Vật lý (QCVN 14 Mục 2.6)

#### 2.1. Bảo vệ Dữ liệu Tĩnh tại Biên (Data-at-Rest Protection)
* Phân vùng dữ liệu chứa video và bộ đệm (`/data`) trên ổ cứng NVMe bắt buộc được mã hóa bằng **[LUKS2](https://gitlab.com/cryptsetup/cryptsetup)** thuật toán `aes-xts-plain64`.
* Tự động giải mã bằng chip phần cứng **[TPM 2.0](https://trustedcomputinggroup.org/resource/tpm-library-specification/)** thông qua `systemd-cryptenroll` với ràng buộc PCR `0+7` (chỉ giải mã khi firmware bo mạch và trạng thái Secure Boot chưa bị thay đổi).
* Khóa cứng Secure Boot: Nạp khóa số của tổ chức vào firmware SoC Jetson Orin NX và thực hiện quy trình đốt cầu chì vật lý một chiều (`odmfuse.sh`).

#### 2.2. Giám sát Xâm nhập Vật lý (Anti-Tamper Defense)
* **Công tắc mở vỏ hộp (Case Tamper):** Nối chân công tắc hành trình vào chân GPIO 298 của SoC. Daemon `tamper-gpio-monitor.sh` sử dụng `gpiomon` để bắt sự kiện mở nắp hộp theo thời gian thực.
* **Công tắc cửa tủ cụm (Cabinet Door):** Nối vào cổng digital input của switch công nghiệp, switch gửi SNMPv3 Trap (UDP 162) về máy chủ trung tâm.
* **Quy trình phản ứng tự động:** Khi phát hiện mở vỏ hộp ngoài khung lịch bảo trì (`maintenance_window`):
  1. Gán cờ `integrity.trusted = false` cho toàn bộ sự kiện phát sinh từ hộp đó.
  2. Gửi cảnh báo kỹ thuật `TAMPER_SUSPECTED` ưu tiên mức `HIGH` về máy chủ.
  3. Máy chủ trung tâm tự động thu hồi chứng chỉ máy khách mTLS của hộp (`cert_status = REVOKED`), ngắt toàn bộ quyền truy cập hệ thống của hộp biên.

#### 2.3. Khóa cứng Hệ điều hành & Tự bảo vệ Quá nhiệt
* Vô hiệu hóa module nạp thiết bị lưu trữ ngoài USB (`blacklist usb-storage`).
* Vô hiệu hóa cổng giao tiếp nối tiếp UART / Serial Console (`mask serial-getty@*`).
* Toàn bộ container chạy dưới quyền người dùng không đặc quyền (`non-root`, UID `10001`, GID `10001`), gỡ bỏ toàn bộ capabilities (`cap_drop: [ALL]`), kích hoạt hệ tệp chỉ đọc (`read_only: true`).
* **Bảo vệ phần cứng khi quá nhiệt:** Đọc cảm biến nhiệt độ SoC định kỳ. Khi vượt ngưỡng an toàn ($> 75^\circ\text{C}$):
  - Kích hoạt lệnh `throttle Level 1`: Giảm 50% khung hình suy luận của các camera thông thường.
  - Kích hoạt lệnh `throttle Level 2`: Dừng hoàn toàn tiến trình suy luận, giữ nguyên bộ đệm video, phát cảnh báo `EDGE_OVERHEAT` về trung tâm.

---

### Trụ cột 3: Bảo vệ Dữ liệu Cá nhân & Bằng chứng Pháp lý (Luật 91/2025/QH15 & Nghị định 13/2023/NĐ-CP)

#### 3.1. Tuân thủ Nguyên tắc R2 & Tối thiểu hóa Dữ liệu (Data Minimization)
* Tuân thủ [Điều 8 và Điều 25 Nghị định 13/2023/NĐ-CP](https://xaydungchinhsach.chinhphu.vn/print/toan-van-nghi-dinh-13-2023-nd-cp-bao-ve-du-lieu-ca-nhan-119230516104357809.htm): Video thu thập tại nơi công cộng chỉ phục vụ an toàn trật tự đô thị; nghiêm cấm sử dụng cho mục đích nhận dạng khuôn mặt, định danh cá nhân trái phép hoặc theo dõi liên camera (ReID).
* Hợp đồng sự kiện `cw.event.v1` chỉ lưu tọa độ bounding box chuẩn hóa, vector vận tốc và nhãn phân loại thô (`person`, `motorbike`, `car`, `truck`, `bus`); tuyệt đối không lưu trữ vector nhúng đặc trưng khuôn mặt (face embeddings).

#### 3.2. Dịch vụ Làm mờ Ảnh tĩnh Phục vụ Công khai (`civi-blur`)
* Dịch vụ làm mờ khuôn mặt và biển số xe chạy độc lập ngoài vùng mạng camera, xử lý ảnh tĩnh trước khi công bố ra các hệ thống dịch vụ công (CiviConnect, CiviField).
* Mô hình sử dụng: **D-FINE-N** ([giấy phép Apache-2.0](https://spdx.org/licenses/Apache-2.0.html)), chạy ở độ chính xác FP16 batch 1.
* Cơ chế xử lý: Quét toàn ảnh kết hợp lưới ô chồng lấn 2×2 / 3×3 (overlap 20%) để bắt đối tượng ở xa, nới khung biên 20%, áp dụng thuật toán Pixelate kết hợp Gaussian Blur không thể khôi phục.
* **Nguyên tắc Fail-Closed:** Tự động loại bỏ toàn bộ dữ liệu vị trí EXIF/GPS; nếu mô hình lỗi hoặc ảnh không hợp lệ, hệ thống trả mã lỗi và tuyệt đối không bao giờ trả ảnh gốc chưa làm mờ.

#### 3.3. Chuỗi Hành trình Bằng chứng Bất biến (Chain-of-Custody)
* **Đầu ghi NVR 24/7 độc lập:** Video luồng chính 4MP lưu trữ tối thiểu 30 ngày trên NVR phân vùng RAID6 (+1 ổ dự phòng nóng). Bằng chứng chính (`CLIP_NVR`) bắt buộc cắt từ NVR thông qua [ONVIF Profile G Specification](https://www.onvif.org/profiles/profile-g/) không mã hóa lại (`-c copy`), đồng bộ theo mốc thời gian tuyệt đối NTP (RTP extension `0xABAC`). Clip trên hộp biên (`CLIP_EDGE`) chỉ đóng vai trò tạm thời trong thời gian chờ NVR xử lý.
* **Kho lưu trữ `EvidenceStore`:** Hoạt động theo cơ chế ghi-một-lần (write-once), tính mã băm SHA-256 dạng luồng, đổi tên tệp nguyên tử và khóa quyền truy cập tệp chỉ đọc (`0440`). Cấm hoàn toàn thao tác ghi đè tệp.
* **Quy trình Xuất Bằng chứng Hai Người Duyệt (SEC-09):**
  - Cán bộ trực tạo yêu cầu $\rightarrow$ Cán bộ quản trị hoặc vận hành khác người yêu cầu phê duyệt (`approved_by <> requested_by`).
  - Worker kết xuất in cứng hình mờ (watermark text mã cán bộ + thời điểm UTC) lên từng khung hình bằng bộ mã hóa [Cisco OpenH264 (giấy phép BSD)](https://spdx.org/licenses/BSD-2-Clause.html).
  - Đóng gói tệp ZIP mã hóa chuẩn **WinZip AES-256** với mật khẩu một lần đọc từ kho bí mật riêng.
  - Tệp và mật khẩu được bàn giao **trao tay qua USB vật lý** kèm biên bản giao nhận có chữ ký hai bên.

#### 3.4. Nhật ký Kiểm toán Chuỗi băm Bất biến (Append-Only Audit Hash Chain)
* Mọi hành động của người dùng (đăng nhập, xem trực tiếp, phát lại, tìm kiếm, xuất clip, xác nhận sự kiện, sửa luật) được ghi nhận trong bảng `cw.audit_log`.
* Database trigger cấp PostgreSQL ngăn chặn tuyệt đối các thao tác `UPDATE`, `DELETE`, `TRUNCATE`.
* Mỗi dòng nhật ký được liên kết mật mã:
  $$\text{row\_hash} = \text{SHA-256}(\text{prev\_hash} \parallel \text{canonical\_payload})$$
* Bộ kiểm định `AuditChainDailyVerifier` tự động rà soát toàn bộ chuỗi băm mỗi ngày. Nếu phát hiện sai lệch băm, lập tức phát cảnh báo kỹ thuật `AUDIT_CHAIN_BROKEN`.
* Thời hạn lưu trữ nhật ký tối thiểu **24 tháng** theo [Nghị định số 85/2016/NĐ-CP](https://vanban.chinhphu.vn/?pageid=27160&docid=185340).

---

### Trụ cột 4: Quản lý Phiên bản, Ký số & Phát hành Cuốn chiếu (ADR-0012, ADR-0017)

#### 4.1. Kiến trúc Tách Khóa 2 Cấp (Hierarchical Key Architecture)
Khắc phục mâu thuẫn giữa yêu cầu cập nhật ngưỡng luật hằng ngày và an toàn tuyệt đối của mô hình AI:

```
┌────────────────────────────────────────────────────────┐
│ MÁY KÝ NGOẠI TUYẾN (AIR-GAPPED)                        │
│ [USB HSM Gốc 1 - Khóa Ed25519 Gốc Phát Hành]           │
└──────────────────────────┬─────────────────────────────┘
                           │ (Ký ngoại tuyến)
          ┌────────────────┴────────────────┐
          ▼                                 ▼
┌──────────────────┐              ┌───────────────────────────┐
│ GÓI MODEL        │              │ CHỨNG CHỈ ỦY QUYỀN LUẬT   │
│ cw.bundle.v1     │              │ rules-signer.cert.json    │
│ (Ed25519 Root)   │              │ (Scope: rules, hạn <=12th)│
└──────────────────┘              └─────────────┬─────────────┘
                                                │ (Giao cho máy GPU)
                                                ▼
                                  ┌───────────────────────────┐
                                  │ MÁY GPU TRỤ SỞ (cw-fleet) │
                                  │ [USB HSM 2: Ký Luật]      │
                                  │ -> Tự động ký cw.rules.v1 │
                                  └───────────────────────────┘
```

1. **Khóa Gốc Phát Hành (Release Root Key - [Ed25519](https://www.rfc-editor.org/rfc/rfc8032.html)):** Lưu trên thiết bị bảo mật phần cứng USB HSM chuẩn [FIPS 140-2 / 140-3](https://csrc.nist.gov/publications/detail/fips/140-3/final), cắm tại máy ký offline riêng biệt, cất trong két sắt an toàn. Dùng để:
   - Ký gói mô hình `cw.bundle.v1` (tệp `manifest.json.sig`).
   - Ký ảnh container qua [Sigstore Cosign](https://docs.sigstore.dev/cosign/overview/).
   - Ký chứng chỉ ủy quyền cho Khóa Ký Luật.
2. **Khóa Ký Luật (Rules Signer Key - Ed25519):** Lưu trên USB HSM thứ hai gắn trực tiếp vào máy GPU trụ sở, `cw-fleet` truy cập tự động thông qua chuẩn [OASIS PKCS #11](https://docs.oasis-open.org/pkcs11/pkcs11-base/v3.0/pkcs11-base-v3.0.html).
   - Chứng chỉ ủy quyền gắn cứng phạm vi `scope = "rules"`, thời hạn $\le 12$ tháng.
   - Hộp biên chỉ chấp nhận chữ ký này trên tệp luật YAML, từ chối tuyệt đối nếu xuất hiện trên mô hình AI hay mã thực thi.

#### 4.2. Ràng buộc Mật mã Toàn vẹn Tệp Nhãn & Báo cáo Cổng (ADR-0017)
* **Khóa chặt ánh xạ lớp đối tượng:**
  - Trường `labels_sha256` (mã băm của `labels/detector.json`) được đưa trực tiếp vào `manifest.json`, nằm dưới phạm vi bảo vệ của chữ ký số Ed25519 khóa gốc.
  - Chuẩn hóa định dạng tệp nhãn thành JSON object: `{"0": "person", "1": "bicycle", ...}`.
* **Ràng buộc Artifact với Báo cáo Cổng chất lượng:**
  - Mã băm `gate.json -> identity.model.artifact_sha256` bắt buộc phải trùng khớp tuyệt đối (sử dụng hàm so sánh hằng thời gian `constant_time_equals`) với mã băm của tệp mô hình nhị phân khi nạp artifact, khi đóng gói và khi hộp biên cài đặt.
  - Cổng chất lượng bắt buộc qua 4 chốt kiểm: **G1** (độ chính xác tương đương $\ge 98\%$), **G2** (độ chính xác thực địa), **G3** (hiệu năng 6 luồng thực tế), **G4** (ngân sách báo sai). Cấm phát hành gói có trạng thái `FAILED` hoặc `NOT_RUN`.

#### 4.3. Quy trình Phát hành Cuốn chiếu (Staged Rollout) & Tự động Rollback Khe A/B
* **Vòng đời phát hành tại `cw-fleet`:** `BUILT` $\rightarrow$ `STAGED` $\rightarrow$ `CANARY` $\rightarrow$ `ROLLING` $\rightarrow$ `DONE` (hoặc `PAUSED` / `ROLLED_BACK`).
* **Cơ chế Khe A/B trên hộp biên:**
  - Gói mới được cài đặt vào khe nhàn rỗi (khe B).
  - Hộp biên tự kiểm tra trong cửa sổ thử nghiệm `health_window_minutes` (30 phút).
  - Nếu xảy ra lỗi suy luận, FPS sụt giảm $> 20\%$, hoặc mất kết nối nhịp tim về trụ sở $\rightarrow$ Hộp biên **tự động chuyển mạch quay lại khe cũ (khe A)** và gửi cảnh báo `BUNDLE_ROLLED_BACK`.
  - Trên `cw-fleet`: nếu hộp canary báo xấu hoặc hết hạn thử nghiệm mà không đạt `HEALTHY`, toàn bộ đợt phát hành tự động chuyển sang `ROLLED_BACK`, khôi phục bản mong muốn của toàn cụm về bản an toàn `previous_version`.

---

### Trụ cột 5: Kiểm toán Chuỗi Cung ứng, Quét Lỗ hổng & Giấy phép Nguồn mở (R7)

#### 5.1. Chính sách Giấy phép Nguồn mở Nghiêm ngặt (R7 License Policy)
* Sử dụng công cụ `check_licenses.py` phân tích biểu thức bản quyền [SPDX License List](https://spdx.org/licenses/) sang dạng chuẩn tuyển (DNF) có xét thứ tự ưu tiên dấu ngoặc đơn.
* **Sản phẩm đóng gói (Shipped Scope):** Chỉ chấp nhận các giấy phép mở thương mại: [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html), [MIT](https://spdx.org/licenses/MIT.html), [BSD](https://spdx.org/licenses/BSD-3-Clause.html), [PostgreSQL](https://spdx.org/licenses/PostgreSQL.html), [LGPL liên kết động](https://spdx.org/licenses/LGPL-3.0-only.html), [MPL-2.0](https://spdx.org/licenses/MPL-2.0.html) nguyên bản.
* **Cấm tuyệt đối ở mọi nơi:** **AGPL** (cấm hoàn toàn, kể cả môi trường dev/ops) và **GPL** trong sản phẩm đóng gói (loại bỏ toàn bộ các mô hình dính AGPL/GPL như YOLO Ultralytics, YOLOv9, và các thư viện AI phi thương mại).
* Giấy phép GPL chỉ được chấp nhận đối với công cụ tự động hóa vận hành nội bộ không phân phối vào sản phẩm (như Ansible).

#### 5.2. Quét Lỗ hổng & Quản lý Danh mục Thành phần (SBOM)
* **Quét lỗ hổng tĩnh (SEC-12):** Tích hợp công cụ Aquasec Trivy quét toàn bộ hệ tệp và ảnh container trong pipeline CI/CD: bắt buộc đạt **0 lỗ hổng mức HIGH/CRITICAL**, **0 secret rò rỉ**, **0 lỗi cấu hình sai (misconfig)**.
* **Danh mục thành phần phần mềm (SBOM - SEC-13):** Tự động sinh tệp SBOM định dạng [CycloneDX v1.6 JSON](https://cyclonedx.org/specification/overview/) cho mỗi bản phát hành (sử dụng Syft), định danh toàn bộ thư viện Java, Python và mã băm SHA-256 của các tệp nguồn.
* **Ký ảnh container (SEC-14):** 100% ảnh container triển khai tại máy chủ và hộp biên được kéo từ Private Registry nội bộ theo digest băm cố định (`@sha256:...`) và phải được kiểm tra chữ ký số bằng [Sigstore Cosign](https://docs.sigstore.dev/cosign/overview/) trước khi khởi chạy.

---

## III. Ma trận Trách nhiệm & Ranh giới Thực hiện (RACI / Human Boundary)

Phân định ranh giới nghiêm ngặt giữa công việc tự động của AI Agent và thẩm quyền bắt buộc của Con người theo quy định an toàn:

| Hạng mục công việc | Quyền hạn AI Agent | Thẩm quyền Con người (Bắt buộc) |
|---|---|---|
| **Cấu hình Tường lửa & Mạng** | Viết bảng luồng `flows.yaml`, sinh cấu hình `nftables` và kịch bản kiểm tra | Phê duyệt mở cổng vật lý, cấu hình Switch thật tại hiện trường, đăng ký APN 4G với nhà mạng |
| **Khóa cứng Thiết bị Biên** | Viết script LUKS, TPM2, GPIO monitor, cấu hình Docker non-root | **Nạp khóa Secure Boot, chạy lệnh đốt cầu chì vật lý (`odmfuse.sh`)** trên bo mạch |
| **Quản lý Khóa & Ký số** | Viết kịch bản Lễ tạo khóa (`tools/ceremony`), bộ kiểm thử SoftHSM, công cụ ký | **Trực tiếp cắm USB HSM vật lý, nhập mã PIN, ký biên bản Lễ tạo khóa, cất két sắt** |
| **Mô hình AI & Dữ liệu** | Dịch model sang TensorRT/INT8, chạy bộ đo benchmark G1, tính toán sai số | **Ký biên bản nghiệm thu cổng chất lượng G1–G4, ký văn bản Đánh giá tác động dữ liệu (DPIA)** |
| **Triển khai & Vận hành** | Viết playbook Ansible, Docker compose, cấu hình giám sát, script soak test | **Chạy lệnh triển khai lên môi trường sản xuất P0**, bật tình huống cho cán bộ trực, ký biên bản |

---

## IV. Lộ trình Triển khai 4 Giai đoạn (Implementation Roadmap)

```
Giai đoạn 1: Chuẩn bị & Mật mã (Tuần 1 - 2)
  ├── 1.1 Khóa hồ sơ mạng flows.yaml & sinh nftables (Trụ cột 1)
  ├── 1.2 Tổ chức Lễ tạo khóa 2 cấp & chuẩn bị USB HSM (Trụ cột 4)
  └── 1.3 Quét kiểm toán giấy phép R7 & lỗ hổng Trivy (Trụ cột 5)

Giai đoạn 2: Khóa cứng Thiết bị Biên & Cơ sở Hạ tầng (Tuần 3 - 4)
  ├── 2.1 Cài đặt LUKS2 + TPM2 + Anti-tamper GPIO trên Jetson (Trụ cột 2)
  ├── 2.2 Thiết lập phân vùng 5 VLAN & Switch ACL (Trụ cột 1)
  └── 2.3 Đóng gói Docker non-root & Private Registry có xác thực Cosign (Trụ cột 5)

Giai đoạn 3: Tầng Dữ liệu, Chứng cứ & Giao tiếp (Tuần 5 - 6)
  ├── 3.1 Kích hoạt RTSPS ghim vân tay & mTLS nội bộ (Trụ cột 1)
  ├── 3.2 Tích hợp NVR Profile G Replay & EvidenceStore chỉ ghi (Trụ cột 3)
  └── 3.3 Kích hoạt Chuỗi băm kiểm toán audit_log & Quy trình xuất AES-256 (Trụ cột 3)

Giai đoạn 4: Quản lý Phiên bản & Diễn tập Nghiệm thu (Tuần 7 - 8)
  ├── 4.1 Triển khai cw-fleet, ký gói model & ký luật tự động (Trụ cột 4)
  ├── 4.2 Diễn tập tự động Rollback khe A/B trên hộp biên (Trụ cột 4)
  └── 4.3 Chạy kiểm định 29 bài test tự động QCVN 14:2026/BCA Phụ lục B2 (Trụ cột 1-5)
```

### Tiêu chuẩn Nghiệm thu Tổng thể (Exit Criteria)
1. **An ninh mạng ([QCVN 14:2026/BCA](https://vbpl.vn/van-ban/chi-tiet/thong-tu-48-2026-tt-bca-ban-hanh-quy-chuan-ky-thuat-quoc-gia-ve-thiet-bi-camera-giam-sat-su-dung-giao-thuc-internet-cac-yeu-cau-an-ninh-mang-co-ban--9048b740-541f-11f1-b175-1fe27ccb5c48) §2.3):** 100% kết nối vật lý được mã hóa (RTSPS/mTLS); tường lửa `nftables` chặn 100% cổng ngoài bảng luồng; quét cổng từ bên ngoài không phát hiện bất kỳ dịch vụ truyền rõ nào.
2. **Thiết bị biên (QCVN 14:2026/BCA §2.6):** Đốt cầu chì Secure Boot thành công; phân vùng NVMe mã hóa bằng TPM2 tự động mở khóa; công tắc vỏ hộp cảnh báo tức thì khi bị mở; hộp tự động rollback về khe A khi gặp bản cập nhật lỗi trong vòng 30 phút.
3. **Pháp lý & Bằng chứng ([Luật 91/2025/QH15](https://chinhphu.vn) & [Nghị định 13/2023/NĐ-CP](https://xaydungchinhsach.chinhphu.vn/print/toan-van-nghi-dinh-13-2023-nd-cp-bao-ve-du-lieu-ca-nhan-119230516104357809.htm)):** Bảng `audit_log` toàn vẹn chuỗi băm 100%; xuất clip bắt buộc 2 người duyệt và tệp xuất ra được mã hóa AES-256 kèm hình mờ; không có tính năng nhận diện khuôn mặt hay đọc biển số trái phép; báo cáo quét Trivy đạt **0 HIGH, 0 CRITICAL**.
4. **Vận hành phiên bản ([RFC 8032](https://www.rfc-editor.org/rfc/rfc8032.html) & [PKCS #11](https://docs.oasis-open.org/pkcs11/pkcs11-base/v3.0/pkcs11-base-v3.0.html)):** Tách bạch 100% giữa quy trình ký gói model ngoại tuyến (người duyệt) và quy trình ký gói luật tự động qua HSM; mọi artifact phát hành đều bị ràng buộc mật mã với mã băm `labels_sha256` và `artifact_sha256` của báo cáo cổng chất lượng.
