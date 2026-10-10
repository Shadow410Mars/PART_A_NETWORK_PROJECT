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
| Image Docker | `apache/iotdb:2.0.11-standalone` (pin cố định, **không** dùng `latest`) |
| Chế độ triển khai | 1C1D đơn nút — ConfigNode (`nodeId=0`) + DataNode (`nodeId=1`) chạy trong cùng container |
| Build Info | `7c0de06` (thuộc nhánh 2.0.11 stable, cập nhật 14/9/2026 trên Docker Hub) |
| TZ container | `Asia/Ho_Chi_Minh` |

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

⚠ `docker compose down` *không* xóa named volumes. Để xóa data THỦ CÔNG (chỉ khi nhóm E muốn dọn DB giữa các lần chạy):
```
docker compose down -v      # ⚠ xóa cả iotdb-data + iotdb-logs, chỉ dùng khi ý thức rõ
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

→ Core metric nhóm C cần vẽ Grafana cho nhóm B+E:
- `compaction_running_task_count`, `flush_total_task_count`, `unseq_file_num` (số file unsequence tạo ra chính là kết quả trực tiếp của ghi sai thứ tự — càng nhiều OOO càng tăng giá trị này).

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

→ Dữ liệu kiểm thử `root.sensor_test.d1` được **giữ lại trong repo** như bằng chứng runtime; nhóm E có thể `DROP DATABASE root.sensor_test;` trước khi chạy ma trận thí nghiệm.

---

## 9. Monitoring nền tảng (tiền A3)

| Mục | Trạng thái | Hướng dẫn nhóm C |
|---|---|---|
| IoTDB Prometheus metrics endpoint (2 cổng 9091, 9092) | ✅ ĐÃ BẬT & xác minh curl được | Thêm 2 `scrape_configs` với `targets: ["iotdb:9091","iotdb:9092"]` (nếu Prometheus chạy trong cùng `iotdb-net` Docker network) hoặc `targets: ["host.docker.internal:9091", "host.docker.internal:9092"]` (nếu chạy ngoài) |
| Container Prometheus | ❌ CHƯA TẠO | Thành viên 4 làm, có thể extend `docker-compose.yml` thêm service `prometheus` với file `./prometheus/prometheus.yml` |
| Container Grafana | ❌ CHƯA TẠO | Thành viên 4 làm, datasource = Prometheus, dashboard mẫu đề xuất theo đề tài: ingest rate (records/s), e2e write latency (p50/p95/p99), flush task count & duration, compaction task count (seq inner vs unseq inner vs cross), seq vs unseq file count, CPU/RAM/disk IO container (metric `container_*` nếu có cAdvisor) |
| File cấu hình Prometheus mẫu | BLOCKER chưa tạo | Nhóm C cần tạo: folder `./prometheus/prometheus.yml` + Docker volume mount, sau đó expose `:9090` |

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
├── .gitignore                      # bỏ iotdb/data, iotdb/logs, *.pyc, venv, *.parquet…
├── docker-compose.yml              # IoTDB 2.0.11 standalone single-node
├── README.md                       # tài liệu này
└── iotdb/
    └── conf/                       # commit vào Git, mount read-only cho container
        ├── iotdb-system.properties             # 72 dòng, OVERRIDE (chứa các giá trị khác mặc định + metrics bật)
        ├── iotdb-system.properties.template    # 95KB, TẤT CẢ tham số mặc định (tham chiếu)
        ├── datanode-env.sh                     # MEMORY_SIZE, IOTDB_ALLOW_HEAP_DUMP…
        ├── confignode-env.sh
        ├── iotdb-common.sh
        ├── iotdb-cluster.properties
        ├── logback-datanode.xml                # config log level, file appender
        ├── logback-confignode.xml
        ├── logback-backup.xml
        ├── logback-tool.xml
        ├── jmx.access
        └── jmx.password
```

---

## 12. Quy ước Git dành cho nhóm

- **Nhánh chính:** `main`. Mọi thành viên làm trên feature branch `A/hai-infra`, `B1/ten-loadgen`, `B2/ten-latency`, `C/ten-monitoring`, `D/ten-log-extractor`, `E/ten-experiment-runner`, `F/ten-analysis`.
- **Merge rule:** Pull request, ít nhất 1 reviewer (không tự merge vào main).
- **Không commit:** file dữ liệu thô (`.parquet`, `.csv` lớn), named volumes content, secrets, `iotdb/data/*`, `iotdb/logs/*`.
- **Commit message convention:** `[A] docker-compose: pin 2.0.11 + enable prometheus metrics`, `[B1] loadgen: add out-of-order ratio param with fixed seed`.

---

## 13. Hướng bắt đầu tích hợp cho từng nhóm

| Nhóm | Hành động đầu tiên | Lưu ý |
|---|---|---|
| **B1 (Bộ sinh tải lõi)** | Kết nối Session API 127.0.0.1:6667 root/root. Tạo database `root.experiment`, tạo schema theo device × measurement design. | Seed cố định; cần test riêng 0% và 100% OOO cho thành viên 3 viết unit test khớp tỉ lệ thực tế. |
| **B2 (Mở rộng load gen)** | Chạy unit test khớp với tỉ lệ OOO B1 trước khi thêm delay/concurrency. | Tuân thủ thiết kế interface chung của B1. |
| **C+D (Giám sát & Thu thập)** | Thêm service Prometheus + Grafana vào `docker-compose.yml`. Cấu hình scrape 2 target. Đọc log file từ named vol `iotdb-logs` hoặc `docker logs iotdb > run001.log` | Dashboard metric DN cột trên metrics port 9092. Đặc biệt vẽ `unseq_file_count` theo thời gian (core metric đề tài). |
| **E (Runner & ma trận)** | Viết script Python `run_experiment.py` tự hóa (1) `docker exec -i iotdb drop DB` / (2) chạy load gen / (3) stop load gen / (4) chờ compaction ổn định (đợi compaction_running=0) / (5) collect metrics + logs → lưu parquet theo schema thống nhất. | Luôn reset DB giữa các run (hoặc xóa volume `-v` rồi tạo lại nếu muốn sạch hoàn toàn, nhưng phải chờ IoTDB khởi động lại ~40s). |
| **F (Phân tích)** | Đợi nhóm E export parquet schema thống nhất. Chuẩn bị notebook template: load parquet → group by (ooo_ratio, batch_size, threads) → t-interval 95% → line/heatmap/box plots. | Đọc metric compaction count + flush duration làm biến trung gian giải thích vì sao cost tăng theo OOO%. |

---

Phiên bản bàn giao Aa: commit đầu tiên sau khi nghiệm thu Bước 5 & Bước 6 xong.
