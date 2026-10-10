# Aa – Hạ tầng & Triển khai Apache IoTDB

> Đề tài 1: Đo lường thực nghiệm ảnh hưởng của thứ tự và kích thước dữ liệu đến chi phí ghi vào Apache IoTDB

Phần A — Thành viên 1: Hạ tầng đơn nút (1 ConfigNode + 1 DataNode trong cùng container, chế độ *standalone*) đóng gói bằng Docker Compose, kèm cấu hình tham số bộ nhớ, WAL, flush, compaction đã kiểm tra thực tế.

---

## 1. Môi trường yêu cầu

| Yếu tố | Phiên bản đã kiểm thử |
|---|---|
| Hệ điều hành | Windows 11 Pro (WSL2 backend cho Docker) |
| Docker Engine | 29.8.2 |
| Docker Compose | v5.5.1 (plugin `docker compose`) |
| RAM host | ≥ 8 GB (container JVM tự chiếm ~6.2 GB) |
| Yêu cầu khác | WSL2 kernel 6.6.87.2+; WSL cần set default version = 2 |

---

## 2. Thông tin phiên bản & kiến trúc

| Mục | Giá trị |
|---|---|
| Image Docker (tag mặc định) | `apache/iotdb:2.0.11-standalone` (pin cố định tag, **không** dùng `latest`) |
| Chế độ triển khai | 1C1D đơn nút — ConfigNode (`nodeId=0`) + DataNode (`nodeId=1`) chạy trong cùng container |
| Build Info | `7c0de06` (thuộc nhánh 2.0.11 stable, pushed 14/09/2026, Created = `2026-09-14T07:32:19Z`) |
| TZ container | `Asia/Ho_Chi_Minh` |

### 2.1 Phân biệt pin Tag phiên bản vs pin Image Digest (Audit 3)

> ⚠ **Khoa học thực nghiệm**: Tag phiên bản (vd `2.0.11-standalone`) trên Docker Hub **có thể được maintainer push lại nội dung mới** (vd patch fix hotfix không đổi tag), nên 2 người cùng dùng `apache/iotdb:2.0.11-standalone` kéo vào 2 ngày khác nhau có thể nhận được image layer khác nhau → sai số đo lường.
>
> **Cam kết tái lập 100%**: Thay `image: tag` bằng `image: <repo>@sha256:<digest>` (hướng dẫn cụ thể ghi comment ở đầu mỗi service trong [docker-compose.yml](file:///C:/Users/HELLO/Desktop/Đồ%20án/docker-compose.yml)). Digest dưới đây đã được verify bằng `docker image inspect` trên môi trường phát triển gốc:

| Service | RepoDigests SHA256 (đã kiểm chứng) |
|---|---|
| **IoTDB 2.0.11 standalone** | `apache/iotdb@sha256:5ace0f3eceff892dd349d02288224c966f3fdeb11d08c4f575b642a110b82338` |
| Prometheus v2.54.1 | `prom/prometheus@sha256:f6639335d34a77d9d9db382b92eeb7fc00934be8eae81dbc03b31cfe90411a94` |
| Grafana OSS 11.2.0 | `grafana/grafana-oss@sha256:408afb9726de5122b00a2576763a8a57a3c86d5b0eff5305bc994ceb3eb96c3f` |

---

## 3. Các cổng tiếp xúc (chỉ bind `127.0.0.1`, **không** phơi ra mạng ngoài)

| Cổng host → container | Vai trò | Dùng cho nhóm |
|---|---|---|
| `127.0.0.1:6667` → `6667` | IoTDB RPC (JDBC / Session Native) | Nhóm B (ghi data), nhóm C/D (đọc metric JDBC) |
| `127.0.0.1:9091` → `9091` | Prometheus metrics ConfigNode | Nhóm C (Prometheus scrape CN) |
| `127.0.0.1:9092` → `9092` | Prometheus metrics DataNode | Nhóm C (Prometheus scrape DN – quan trọng hơn) |

Các cổng nội bộ sau **không** được bind ra host vì chỉ dùng trong container/network `iotdb-net`: 10710, 10720, 10730, 10740, 10750, 10760.

---

## 4. Volumes & Dữ liệu bền vững

| Tên volume (named) | Mount point trong container | Nguồn trong repo | Chịu trách nhiệm |
|---|---|---|---|
| `iotdb-data` | `/iotdb/data` | (Docker managed, **không commit** vào Git) | TsFile, WAL, metadata — dữ liệu thí nghiệm |
| `iotdb-logs` | `/iotdb/logs` | (Docker managed, **không commit**) | log GC, flush, compaction — nhóm D đọc log |
| Bind mount `./iotdb/conf` → `/iotdb/conf` (read-only `:ro`) | `/iotdb/conf` | `iotdb/conf/*` (commit vào Git) | Tham số cấu hình cho các lần dựng lại sau này |

### 4.1 Vòng đời Docker Volumes (Audit 4)

> ⚠ **Git không quản lý named volumes Docker**: `git reset`, `git checkout`, hay clone repo mới hoàn toàn **KHÔNG** tác động gì đến nội dung 4 named volumes (`iotdb-data`, `iotdb-logs`, `prometheus-data`, `grafana-data`) — chúng được Docker daemon quản lý độc lập, nằm tại mountpoint `/var/lib/docker/volumes/<name>/_data` bên trong WSL2 distro `docker-desktop-data`.
>
> Các lệnh Docker **CÓ THỂ XÓA** named volumes (luôn backup `iotdb-data` trước khi chạy nếu chứa dữ liệu thí nghiệm quý giá):
> * `docker compose down -v` — stop + xóa container/network **VÀ XÓA HẾT** 4 named volumes được định nghĩa trong [docker-compose.yml](file:///C:/Users/HELLO/Desktop/Đồ%20án/docker-compose.yml).
> * `docker volume rm iotdb-data iotdb-logs prometheus-data grafana-data` — xóa lẻ từng volume.
> * `docker volume prune` — xóa TẤT CẢ volumes không được tham chiếu bởi container nào đang chạy (NGUY HIỂM nếu có project khác trên máy).
>
> Mặc định (`docker compose down` không có `-v`) thì named volumes được giữ lại.

⚠ Mẹo backup dữ liệu TsFile trước khi dọn:
```powershell
docker run --rm -v iotdb-data:/src -v "${PWD}/backup_$(Get-Date -Format yyyyMMdd):/dst" alpine cp -a /src/. /dst/.
```

---

## 5. Khởi chạy (tái lập môi trường)

```powershell
# Bước 1: Clone repository (hoặc cd vào thư mục đã có)
cd "C:\Users\HELLO\Desktop\Đồ án"

# Bước 2: Kiểm tra docker hoạt động
docker --version          # ≥ 24.x OK
docker compose version    # ≥ v2 OK
docker info               # phải in Server Version, không lỗi kết nối

# Bước 3: Kiểm tra cấu hình Compose trước khi chạy
docker compose config     # exit=0 là hợp lệ

# Bước 4: Nền (pull image nếu thiếu) → khởi động ngầm
docker compose pull
docker compose up -d

# Bước 5: Chờ ~40–60 giây, kiểm tra log
docker logs -f iotdb 2>&1 | Select-String -Pattern "Congratulations"
# Mong đợi dòng: Congratulations, IoTDB DataNode is set up successfully.
```

**Các lệnh thường dùng tiếp theo:**

| Mục đích | Lệnh |
|---|---|
| Kiểm tra trạng thái container | `docker ps --filter name=iotdb` |
| Xem log (tail 50 dòng) | `docker logs iotdb --tail 50` |
| Đăng nhập CLI interactive | `docker exec -it iotdb /iotdb/sbin/start-cli.sh -h iotdb -u root -pw root` |
| Thoát CLI | gõ `exit` hoặc Ctrl+D |
| Dừng (giữ data) | `docker compose down` |
| Khởi động lại (giữ data) | `docker compose up -d` |
| Tải cấu hình mới (sửa `iotdb/conf/*`) | `docker compose up -d --force-recreate` |
| Reload Prometheus KHÔNG restart container (sửa prometheus.yml) | `Invoke-RestMethod http://127.0.0.1:9090/-/reload -Method Post` (Windows) / `curl -X POST http://127.0.0.1:9090/-/reload` (Linux/macOS) |

### 5.8 Disclaimer về phạm vi kiểm thử đã thực hiện (Audit 4)

Tất cả các mục trong bảng nghiệm thu phần A đều được chạy và PASS trên **workspace hiện tại** tại commit sau khi dựng xong. **Tuy nhiên, một bài kiểm thử giả lập "clone sạch hoàn toàn từ repo rỗng sang máy mới chưa từng có Docker image/volume nào" chưa được thực hiện**. Do đó:

* Các lệnh ở Section 5, 6 dựa trên bằng chứng thực tế trên workspace gốc, nhưng thành viên khi dựng trên máy mới **nên báo cáo nếu phát hiện sai khác** (đặc biệt là bước `docker compose pull` lần đầu, hoặc bước copy conf từ container mới khi người dùng chưa có sẵn thư mục `iotdb/conf/`).
* File cấu hình `iotdb/conf/` được commit vào Git (mount `:ro`), nên kết quả dựng trên máy mới dự kiến giống 100% nếu cùng digest image.

---

## 6. Tài liệu tham số quan trọng

Bảng dưới đây phân biệt 3 trạng thái theo đúng quy ước đề tài:
- ⚪ **MẶC ĐỊNH** = giá trị được set trong `iotdb-system.properties.template` (file 95KB), không xuất hiện trong file `iotdb-system.properties` 72 dòng thực tế
- 🟢 **ĐÃ CẤU HÌNH** = giá trị được chủ đích đặt trong `docker-compose.yml` hoặc `iotdb/conf/iotdb-system.properties` (có kiểm chứng trong file)
- 🔴 **RUNTIME ĐO ĐƯỢC** = giá trị thực tế đo được bằng `ps`/`docker exec` sau khi container chạy (không được suy đoán)

### 6.1 Bộ nhớ JVM

| Tham số | Đơn vị | MẶC ĐỊNH (template) | ĐÃ CẤU HÌNH | RUNTIME ĐO ĐƯỢC (máy 7.6 GB host) |
|---|---|---|---|---|
| DataNode JVM Heap (Xms=Xmx, fix) | MB | Tính tự động theo host RAM | ⚪ không set env `MEMORY_SIZE` | 🔴 **2922 MB** (`-Xms2922M -Xmx2922M`) |
| DataNode MaxDirectMemory (off-heap) | MB | Tính tự động | ⚪ mặc định | 🔴 **977 MB** |
| DataNode OFF_HEAP_MEMORY prop | MB | Tính tự động | ⚪ mặc định | 🔴 **977 MB** |
| ConfigNode JVM Heap (Xms=Xmx) | MB | Tính tự động | ⚪ mặc định | 🔴 **1752 MB** |
| ConfigNode MaxDirectMemory | MB | Tính tự động | ⚪ mặc định | 🔴 **585 MB** |
| Stack size (`-Xss`) | KB |  | ⚪ mặc định | 🔴 **512 KB** |
| **Tổng JVM 2 tiến trình (heap+off-heap)** | GB |  |  | 🔴 **≈ 6.2 GB / 7.6 GB host** |

→ Nếu muốn ép RAM cố định (để so sánh công bằng giữa các máy khác nhau khi nhóm mở rộng), thêm:
```yaml
environment:
  - MEMORY_SIZE=2G     # ví dụ ép DataNode heap cố định 2 GB (CN auto chia tỉ lệ)
```
vào service `iotdb` trong `docker-compose.yml`. **Hiện tại không làm vậy** để giữ tính trung lập lần chạy đầu tiên theo tài liệu.

### 6.2 Phân bổ bộ nhớ trong DataNode (Memory Budget Proportions)

| Tham số | MẶC ĐỊNH | Ý nghĩa |
|---|---|---|
| `datanode_memory_proportion` | `3:3:1:1:1:1` | 6 bucket tổng DN heap (write/read/schema…) |
| `storage_engine_memory_proportion` | `8:2` | Trong storage engine: write buffer vs read |
| `write_memory_proportion` | `19:1` | write mem = seq vs unseq memtable (19/20 seq, 1/20 unseq) |
| `flush_proportion` | `0.4` | Khi memory usage đạt 40% → trigger flush memtable → TsFile |
| `reject_proportion` | `0.8` | Khi đạt 80% → reject (từ chối ghi mới, backpressure) |
| `wal_buffer_queue_proportion` | `0.1` | 10% write memory dùng cho queue buffer WAL |
| `chunk_metadata_size_proportion` | `0.1` | 10% read memory cho chunk metadata cache |

→ Nhóm B+E cần đặc biệt chú ý: **`flush_proportion=0.4`** nghĩa là với 2.9GB heap DN thì khi ~1.1GB write mem được dùng, memtable bắt đầu đổ xuống disk. Nếu batch size lớn × concurrency cao gây vượt `reject_proportion=0.8` (~2.3GB) thì IoTDB sẽ từ chối ghi — đây là failure case cần ghi trong log thí nghiệm.

### 6.3 WAL (Write-Ahead Log)

| Tham số | MẶC ĐỊNH | ĐÃ CẤU HÌNH |
|---|---|---|
| `wal_mode` | `ASYNC` | ⚪ |
| `wal_async_mode_fsync_delay_in_ms` | `1000` (1s) | ⚪ |
| `wal_sync_mode_fsync_delay_in_ms` | `3` | ⚪ |
| `wal_buffer_size_in_byte` | `33554432` (32 MB) | ⚪ |
| `wal_file_size_threshold_in_byte` | `31457280` (~30 MB) | ⚪ |
| `wal_memtable_snapshot_threshold_in_byte` | `8388608` (8 MB) | ⚪ |
| `wal_dirs` | `data/datanode/wal` (trong named vol `iotdb-data`) | ⚪ |
| `WALCompressionAlgorithm` | `LZ4` | ⚪ (xuất hiện trong log runtime) |

→ Mode **WAL = ASYNC** cho throughput cao hơn nhưng rủi ro mất ~1s dữ liệu nếu crash. Chính là yếu tố khiến đo lường OOO cần kiểm tra kỹ: nếu tắt WAL (chưa làm) vs ASYNC vs SYNC thì chi phí ghi khác nhau. Để kiểm soát biến thiên, **để nguyên ASYNC mặc định trong toàn bộ ma trận thí nghiệm**.

### 6.4 Memtable & Flush

| Tham số | MẶC ĐỊNH | Ghi chú |
|---|---|---|
| `enable_timed_flush_seq_memtable` | `true` | Timer flush seq memtable |
| `seq_memtable_flush_interval_in_ms` | `600000` (10 phút) | Thời gian tối đa seq giữ trong mem |
| `seq_memtable_flush_check_interval_in_ms` | `30000` (30s) | Chu kỳ kiểm tra |
| `enable_timed_flush_unseq_memtable` | `true` | Timer flush unseq |
| `unseq_memtable_flush_interval_in_ms` | `600000` (10 phút) |  |
| `unseq_memtable_flush_check_interval_in_ms` | `30000` |  |
| `io_task_queue_size_for_flushing` | `10` | Độ dài queue I/O flush |

→ Kết hợp với `flush_proportion=0.4`, memtable có 2 nguyên nhân bị flush: (1) timer 10 phút, (2) memory threshold 40% DN heap. **Với load generator chạy liên tục, trigger (2) sẽ xảy ra thường xuyên hơn.**

### 6.5 Compaction (LSM-tree reorganize)

Đây là cơ chế LSM-tree chịu ảnh hưởng trực tiếp của dữ liệu ghi sai thứ tự → nguyên nhân chính của đề tài.

| Tham số | MẶC ĐỊNH | Ý nghĩa |
|---|---|---|
| `enable_seq_space_compaction` | `true` | Inner compaction vùng sequence |
| `enable_unseq_space_compaction` | `true` | Inner compaction vùng unsequence |
| `enable_cross_space_compaction` | `true` | Merge các file unseq vào seq (tốn kém nhất) |
| `enable_auto_repair_compaction` | `true` | Tự sửa lỗi nếu compaction crash |
| `compaction_priority` | `INNER_CROSS` | Ưu tiên inner trước, cross sau |
| `compaction_thread_count` | `10` | Tổng thread compaction |
| `sub_compaction_thread_count` | `4` | Sub-thread cho 1 task lớn |
| `compaction_schedule_interval_in_ms` | `60000` (1 phút) | Quét 1 lần/phút |
| `compaction_write_throughput_mb_per_sec` | `16` MB/s | Giới hạn tốc độ ghi compaction (tránh cạnh tranh với ingest) |
| `compaction_read_throughput_mb_per_sec` | `0` (unlimited) |  |
| `target_compaction_file_size` | `2147483648` (2 GB) | Mục tiêu file TsFile sau merge |
| `inner_compaction_total_file_size_threshold` | `10737418240` (10 GB) | Trigger inner khi tổng file quá mức |
| `inner_compaction_total_file_num_threshold` | `100` | Hoặc khi đủ 100 file |
| `max_cross_compaction_candidate_file_size` | `5368709120` (5 GB) | Giới hạn cross compaction |

→ PromQL mẫu ĐÃ XÁC MINH (Audit 1) nhóm C cần vẽ Grafana cho nhóm B+E:
  (Lưu ý quan trọng: **KHÔNG dùng `rate()` cho metric dạng GAUGE** dưới đây — chúng biểu diễn giá trị tức thời, không phải counter tích lũy. `rate()` chỉ dành cho counter có suffix `_total`.)

| Metric | Type | Label quan trọng | PromQL ví dụ | Ý nghĩa cho đề tài OOO |
|---|---|---|---|---|
| `thread_pool_active_thread_count` | GAUGE | `pool_name =~ ".*Compaction.*"` | `thread_pool_active_thread_count{pool_name="org.apache.iotdb.threadpool:type=Compaction-Worker"}` | Số thread compaction đang BẬT tức thời (tăng khi OOO cao). |
| `compaction_task_count` | GAUGE | `name ∈ {inner_seq, inner_unseq, cross, settle, insertion}` | `compaction_task_count{name="cross"}` (**CORE OOO metric**) | Số task cross-space compaction đang chạy — chỉ tăng khi có unseq file cần merge vào seq space, đây là bằng chứng trực tiếp nhất OOO gây tốn chi phí. |
| `flush_cost_seconds` | SUMMARY quantile | `stage ∈ {encoding, io, write_plan_indices,...}` | `flush_cost_seconds{quantile="0.99",stage="io"}` | Latency flush memtable→TsFile, percentile 99. |
| `jvm_memory_used_bytes` | GAUGE | `nodeType`, `area="heap"` | `sum by (nodeType) (jvm_memory_used_bytes{area="heap"})` | Heap dùng thực tế DN vs CN. **Runtime đo thực tế (Audit5) idle = DN 1,454 MiB / 2,922 MiB (49.7%), tức đã vượt flush_proportion=0.4 ở trạng thái rỗi → khi chạy load gen flush xảy ra nhanh.** |
| `wal_cost_seconds` | SUMMARY quantile | `stage ∈ {make_checkpoint,...}` | `wal_cost_seconds{quantile="0.99"}` | WAL latency p99 (replaced old metric `wal_flush_time_cost_summary` which DOES NOT EXIST). |
| `file_count` | GAUGE | `level=0..N, tsfileType ∈ {sequence, unsequence}` | `sum by (tsfileType) (file_count{nodeType="DATANODE"})` | Số lượng file seq vs unseq (tỷ lệ unseq tăng chứng minh OOO gây write amplification). |
| `flush_memtable_count_total` | COUNTER suffix `_total` | — | `rate(flush_memtable_count_total{nodeType="DATANODE"}[5m])` | Flush task throughput per second (CHO COUNTER nên dùng `rate()` là hợp lệ). |

→ **Sai sót cũ đã loại bỏ (Audit1):** `sum(rate(thread_pool_active_thread_count{name="Compaction-Worker"}[5s]))` — sai ở 2 điểm (label `pool_name` chứ không phải `name`; rate() trên gauge vô nghĩa). Metric `wal_flush_time_cost_summary` không tồn tại trên endpoint 9092 → đã thay bằng `wal_cost_seconds`.

### 6.6 Tham số đã chủ động sửa (khác mặc định)

Đây là những điểm **ĐÃ CẤU HÌNH** (🟢), không tự suy ra từ template:

| File | Khóa | Giá trị mặc định (template) | Giá trị đã set | Lý do |
|---|---|---|---|---|
| `docker-compose.yml` | `ports` bind IP | (mẫu docs `6667:6667` tức all interface) | `127.0.0.1:xxx:xxx` | Không phơi dịch vụ ra mạng ngoài |
| `docker-compose.yml` | `ulimits nofile` | (mẫu docs = 1048576 comment) | `soft=1048576 hard=1048576` | Tránh lỗi `Checking whether the ports are already occupied...` treo |
| `iotdb/conf/iotdb-system.properties` | `cn_metric_reporter_list` | *(rỗng = off)* | `PROMETHEUS` | Bật metrics cho nhóm C |
| `iotdb/conf/iotdb-system.properties` | `dn_metric_reporter_list` | *(rỗng = off)* | `PROMETHEUS` | Bật metrics DataNode (quan trọng nhất) |
| `iotdb/conf/iotdb-system.properties` | xóa dòng thừa `_=/usr/bin/env` | - | Đã xóa | Artifact sai sót khi copy `docker cp` |
| `docker-compose.yml` | volumes conf | (mẫu docs không mount conf) | `./iotdb/conf:/iotdb/conf:ro` | Reproducible cấu hình khi clone |
| `docker-compose.yml` | volumes data/logs | (mẫu docs dùng bind mount `./iotdb/data`) | **named volumes** `iotdb-data`, `iotdb-logs` | Phân quyền trên WSL2 ổn định hơn; tách biệt lifecycle với source code |
| `docker-compose.yml` | `restart` | (mẫu docs `always`) | `unless-stopped` | Hạ tầng nhẹ hơn; không tự khởi động lại khi user chủ động `stop` |

---

## 7. Kết nối IoTDB (cho nhóm B, E viết load generator / runner)

| Trường hợp | Thông số |
|---|---|
| Host (từ host Windows) | `127.0.0.1` |
| Host (từ container khác cùng network `iotdb-net`) | `iotdb` (tên service Docker, dùng cho load gen container hóa sau này) |
| Port RPC | `6667` |
| User mặc định | `root` |
| Password mặc định | `root` |
| Fetch size mặc định (JDBC) | `10000` |

Python (Session API — nhóm B ưu tiên dùng vì nhanh hơn JDBC cho ghi):
```python
# pip install apache-iotdb==1.3.0 hoặc phiên bản tương thích 2.0.x
from iotdb.Session import Session
s = Session("127.0.0.1", 6667, "root", "root")
s.open(False)
print(s.get_time_zone())
# ... insert_records / insert_records_of_one_device / insert_tablet ...
s.close()
```

Test nhanh bằng CLI 1-shot (không interactive):
```
docker exec iotdb /iotdb/sbin/start-cli.sh -h iotdb -u root -pw root -e "show databases;"
```

---

## 8. Kết quả kiểm thử Giai đoạn A1 (bằng chứng thực tế)

Thực hiện lúc container up lần đầu, recreate, sau khi `docker compose down` rồi `up -d` lại (kiểm tra persistence 3 lần):

| Kiểm thử | Kết quả | Lệnh / Bằng chứng |
|---|---|---|
| Show cluster | ✅ PASS 2 node Running | `show cluster;` → NodeID 0 (ConfigNode) + 1 (DataNode), version 2.0.11 Build 7c0de06, State=Running |
| Create database `root.sensor_test` | ✅ PASS | schema/data RF=1 |
| INSERT OOO pattern | ✅ PASS 3 rows | ts=1000 → ts=2000 → ts=**1500** (OOO: 1500 được insert SAU 2000) → 3 "Msg: executed successfully" |
| SELECT ORDER BY TIME ASC | ✅ PASS | trả về 3 dòng đã được sắp xếp tự động 1000 → 1500 → 2000 |
| Persistence sau `--force-recreate` container | ✅ PASS | select lại vẫn còn 3 dòng |
| Persistence sau `docker compose down` → `up -d` | ✅ PASS | named volumes giữ lại, select vẫn còn 3 dòng |
| Metrics endpoint CN `:9091/metrics` | ✅ PASS | curl được Prometheus text format, labels `nodeType="CONFIGNODE"` |
| Metrics endpoint DN `:9092/metrics` | ✅ PASS | ~99 dòng metric, tags `nodeType="DATANODE"` (có Flush pool, …) |
| Bind mount conf `:ro` | ✅ PASS | Container khởi động lại sau khi mount, không có permission issue |

> ⚠ **Lưu ý Khoa học thực nghiệm (Audit 4):** Bài kiểm thử OOO pattern (ts=1000 → 2000 → 1500 SAU) trên đây chỉ chứng minh **TÍNH ĐÚNG ĐẮN về logic truy vấn** (cơ sở dữ liệu trả về kết quả đúng thứ tự thời gian, dữ liệu không bị mất). Nó **KHÔNG phải là bằng chứng định lượng** rằng chi phí ghi, CPU compaction, write amplification hay số lượng file unseq đã tăng lên do OOO. Đo lường mối quan hệ *tỷ lệ OOO → chi phí ghi* là mục tiêu của **Toàn bộ đề tài (Nhóm B sinh tải × Nhóm E runner ma trận × Nhóm F phân tích)** và cần được thực hiện bằng cách chạy load gen cố định 1 tổ hợp tham số trong ≥ 5 phút, đo các PromQL Section 6.5, sau đó lặp lại với N tổ hợp khác nhau để so sánh.

→ Dữ liệu kiểm thử `root.sensor_test.d1` + `root.acceptance.devA` được **giữ lại trong named volume `iotdb-data`** như bằng chứng runtime; nhóm E có thể chạy 2 lệnh sau TRƯỚC KHI bắt đầu ma trận thí nghiệm để làm trắng dữ liệu mà không cần xóa volume:
```sql
DROP DATABASE root.sensor_test;
DROP DATABASE root.acceptance;
FLUSH;
```

---

## 9. Monitoring nền tảng (ĐÃ HOÀN THÀNH A3 — Audit 2)

3 service monitoring ĐANG CHẠY thực tế sau khi `docker compose up -d`. Truy cập trình duyệt host:

| Service | URL | Tài khoản | Tình trạng tại Audit |
|---|---|---|---|
| Prometheus UI + API | `http://127.0.0.1:9090` | anonymous (public read-only) | ✅ 3 scrape target UP (lúc Audit mặc định, không bật highfreq) |
| Grafana UI | `http://127.0.0.1:3000` | `admin/admin` (tùy chỉnh password sau login) OR **Anonymous Viewer** (chỉ xem, không cần login — đã bật `GF_AUTH_ANONYMOUS_ENABLED=true`) | ✅ Health `database=ok`; Datasource Prometheus `uid=prometheus-iotdb` (default=True) đã được auto provision |
| IoTDB ConfigNode metrics raw | `http://127.0.0.1:9091/metrics` | — | ✅ Text format Prometheus |
| IoTDB DataNode metrics raw | `http://127.0.0.1:9092/metrics` | — | ✅ Text format Prometheus |

### 9.1 Cấu hình Scrape mặc định (Audit 2 — MẶC ĐỊNH KHÔNG BẬT 1s HIGH FREQ)

Sau khi Audit, cấu hình mặc định giảm thiểu overhead monitoring lên hệ thống đang đo (quy tắc khoa học thực nghiệm: **không để measurement system ảnh hưởng measured system hơn mức cần thiết**):

| Scrape job | Tần suất | Target | Ý nghĩa |
|---|---|---|---|
| `prometheus` (self) | 15s | `localhost:9090` | Tự monitor Prometheus instance |
| `iotdb-confignode` | 15s | `iotdb:9091` | ConfigNode metrics (thay đổi ít) |
| `iotdb-datanode` | 5s | `iotdb:9092` | DataNode metrics (đủ độ phân giải cho trend 5s) |
| `iotdb-datanode-highfreq` | **COMMENTED / OPT-IN** | `iotdb:9092` | **Tùy chọn 1s cho thí nghiệm ngắn**, chỉ bật khi nhóm E chạy load gen 2-3 phút, sau đó comment lại để giảm overhead |

### 9.2 Cách bật High-Frequency 1s (khi chạy benchmark)

1. Mở file [prometheus.yml](file:///C:/Users/HELLO/Desktop/Đồ%20án/monitoring/prometheus/prometheus.yml#L29-L64), uncomment block cuối `iotdb-datanode-highfreq`
2. **KHÔNG restart container** (giữ history TSDB):
   ```powershell
   Invoke-RestMethod -Uri http://127.0.0.1:9090/-/reload -Method Post
   ```
3. Verify: `http://127.0.0.1:9090/targets` → có thêm 4 target `iotdb-datanode-highfreq` UP

### 9.3 Kiểm tra Overhead Monitoring trước ma trận chính (Bắt buộc khoa học thực nghiệm)

> ⚠ **Hiệu ứng Observer:** Việc scrape metrics mỗi 5s + 1s tiêu tốn CPU DN xử lý format Prometheus text, và network (nhỏ, trong Docker bridge). Để ĐO & GHI RÕ hiệu ứng này trước ma trận thực:

**Quy trình kiểm tra overhead monitoring (Nhóm E chạy trước khi run N tổ hợp chính):**

1. Chọn một tổ hợp tham số "medium" cố định: VD `OOO=25%, batch=1024, threads=4`
2. Chạy load gen **2 lần với EXACT SAME params + random seed**:
   * Lần #A (baseline monitoring thấp): giữ cấu hình mặc định (3 job, DN=5s) → ghi median latency / throughput
   * Lần #B (monitoring cao): uncomment highfreq 1s + reload Prom → ghi median latency / throughput
3. Tính: `overhead% = 100 * (median_lat_B - median_lat_A) / median_lat_A`
4. Nếu `overhead% > 2%`: Báo cáo trong kết quả cuối cùng, hoặc tắt highfreq khi không cần, và cấu hình giảm `dn_metric_prometheus_reporter_export_num_threads` trong iotdb-system.properties.
5. Nếu `overhead% ≤ 2%`: chấp nhận và ghi footnote trong báo cáo bàn giao (mức sai ≤ 2% là đủ tốt cho thí nghiệm ước lượng bậc 1).

### 9.4 Truy vấn mẫu ĐÃ XÁC MINH hoạt động

Tất cả các PromQL ví dụ cho đề tài OOO đã được verify thực tế trả về non-empty samples (xem Section 6.5 bảng chi tiết). **KHÔNG dùng `rate()` cho gauge thread_pool_active_thread_count / compaction_task_count / jvm_memory_used_bytes**. `rate()` chỉ hợp lệ cho counter `_total`.

---

## 10. Xử lý lỗi thường gặp

| Triệu chứng | Nguyên nhân / Khắc phục |
|---|---|
| Log khởi động dừng ở `Checking whether the ports are already occupied...` quá lâu (> 2 phút) | `nofile` quá cao khiến lsof() trong container WSL2 quá chậm. Giảm xuống `1048576` (đã làm). Nếu vẫn chậm, giảm tiếp `262144`. |
| `docker info` báo `cannot connect to the Docker daemon` | Mở Docker Desktop trước; WSL distribution `docker-desktop-data` phải chạy. |
| CLI `start-cli.sh` báo lỗi JDBC connect refused | Container chưa chạy xong. Chờ đến khi log hiện `Congratulations` rồi thử lại. |
| Khi chạy nhiều batch ghi nhận `500: Reject` | Đã chạm `reject_proportion=0.8` → Giảm concurrency / batch size, hoặc tăng `MEMORY_SIZE` nếu máy đủ RAM. |
| Khi `docker compose up` báo `bind: An attempt was made to access a socket in a way forbidden by its access permissions` | Cổng 6667/9091/9092 đang bị chiếm (chạy 2 lần chẳng hạn). Dùng `netstat -ano | findstr :6667` rồi kill PID chiếm dụng. |

---

## 11. Cấu trúc repository

```
C:\Users\HELLO\Desktop\Đồ án\
├── .gitignore                      # bỏ iotdb/data, iotdb/logs, *.pyc, venv, *.parquet, *.csv lớn…
├── docker-compose.yml              # 3 services: iotdb 2.0.11 + prometheus v2.54.1 + grafana 11.2.0
├── README.md                       # tài liệu này (Audit pass, 7 sections verified)
├── iotdb/
│   └── conf/                       # commit vào Git, mount read-only (:ro) cho container
│       ├── iotdb-system.properties             # OVERRIDE 72 dòng (metrics PROMETHEUS port 9091/9092 bật)
│       ├── iotdb-system.properties.template    # 95KB, TẤT CẢ tham số mặc định (tham chiếu group)
│       ├── datanode-env.sh                     # MEMORY_SIZE, IOTDB_ALLOW_HEAP_DUMP…
│       ├── confignode-env.sh
│       ├── iotdb-common.sh
│       ├── iotdb-cluster.properties
│       ├── logback-datanode.xml                # config log level, file appender (nhóm D đọc)
│       ├── logback-confignode.xml
│       ├── logback-backup.xml
│       ├── logback-tool.xml
│       ├── jmx.access
│       └── jmx.password
└── monitoring/                   # commit vào Git (Section 9 — A3 monitoring đã dựng xong)
    ├── prometheus/
    │   └── prometheus.yml        # 3 job mặc định + 1 opt-in highfreq (commented)
    └── grafana/
        └── provisioning/
            └── datasources/
                └── datasource.yml # Auto-provision Prometheus datasource uid=prometheus-iotdb (default=true, proxy)
```

---

## 12. Quy ước Git dành cho nhóm

- **Nhánh chính:** `main`. Mọi thành viên làm trên feature branch `A/hai-infra`, `B1/ten-loadgen`, `B2/ten-latency`, `C/ten-monitoring`, `D/ten-log-extractor`, `E/ten-experiment-runner`, `F/ten-analysis`.
- **Merge rule:** Pull request, ít nhất 1 reviewer (không tự merge vào main).
- **Không commit:** file dữ liệu thô (`.parquet`, `.csv` lớn), named volumes content, secrets, `iotdb/data/*`, `iotdb/logs/*`.
- **Commit message convention:** `[A] docker-compose: pin 2.0.11 + enable prometheus metrics`, `[B1] loadgen: add out-of-order ratio param with fixed seed`.

---

## 13. Hướng bắt đầu tích hợp cho từng nhóm

| Nhóm | Hành động đầu tiên | Lưu ý cốt lõi từ Audit |
|---|---|---|
| **B1 (Bộ sinh tải lõi OOO ratio)** | Kết nối Session API `127.0.0.1:6667` user=`root` pw=`root`. Tạo DB convention `root.exp_r<OOO>_b<batch>_t<thread>`, schema theo device × measurement design. | Seed cố định N lần lặp; PromQL verify metric `compaction_task_count{name="cross"}` > 0 khi OOO>50% để biết load gen kích hoạt cross-space compaction đúng. |
| **B2 (Load gen latency + concurrency)** | Chạy unit test khớp tỉ lệ OOO của B1 trước khi thêm delay/concurrency params. | Tuân thủ interface của B1; đo overhead của chính load gen framework trên test máy trống (Idle baseline) trước khi chạy ma trận. |
| **C+D (Giám sát & Thu thập log)** | Prometheus + Grafana ĐÃ SẴN (Section9). Mở Grafana `http://127.0.0.1:3000` admin/admin → Build dashboard dùng **7 PromQL ĐÃ VERIFY ở Section 6.5 bảng**. Nhóm D extract log: `docker cp iotdb:/iotdb/logs ./iotdb/logs_run_NNN/` | ⚠ Xem Section 6.5: **KHÔNG dùng `rate()` cho gauge thread_pool / compaction_task_count**; metric cũ `wal_flush_time_cost_summary` KHÔNG TỒN TẠI → thay bằng `wal_cost_seconds`. Regex extract log cho pattern: `cross_space_compaction`, `flush_memtable`, `Rejecting` (Section 10 troubleshooting). |
| **E (Runner & ma trận thí nghiệm)** | Đầu tiên: **Chạy quy trình Section 9.3 đo overhead monitoring 1 lần duy nhất** và ghi kết quả vào metadata tổng. Sau đó viết script: (0) DROP 2 DB test (Section 8 SQL) / (1) start load gen B1+B2 / (2) chờ end / (3) SLEEP `compaction_schedule_interval`=60s để compaction hoàn thành / (4) export Prom `query_range` step=1s + copy log volume → gộp vào folder structure theo run id. | Khi reset DB giữa các run ưu tiên `DROP DATABASE ...;` thay vì `docker compose down -v` (cách 1 không chờ IoTDB restart 40s). Khi muốn trắng hoàn toàn (lần đầu build baseline) thì mới dùng `-v`. |
| **F (Phân tích Notebook)** | Chờ nhóm E export data schema thống nhất. Template: load parquet → groupby (OOO, batch, concurrency) → Welch's t-interval / Wilcoxon signed-rank paired test cho N≥5 lặp → vẽ (a) line+band 95% CI (b) boxplot (c) heatmap batch vs OOO. | Biến trung gian giải thích cho báo cáo cuối: dùng `compaction_task_count{name="cross"}` mean và `file_count{tsfileType="unsequence"}` mean làm 2 feature dự đoán chi phí ghi, không chỉ report raw cost. |

---

Phiên bản bàn giao Aa: commit đầu tiên sau khi nghiệm thu Bước 5 & Bước 6 xong.
