# Hướng dẫn triển khai Apache IoTDB & Monitoring

**Đề tài 1:** Đo lường thực nghiệm ảnh hưởng của thứ tự và kích thước dữ liệu đến chi phí ghi vào Apache IoTDB.
**Mô hình:** Chạy 1 ConfigNode và 1 DataNode trong cùng một container (chế độ standalone) bằng Docker Compose.

---

## 1. Yêu cầu hệ thống
* **OS:** Windows 11 Pro (đã bật WSL2 làm backend cho Docker).
* **RAM:** Máy host nên có từ 8GB trở lên (Container IoTDB sẽ tự chiếm khoảng 6.2GB).
* **Software:** Docker Engine & Docker Compose bản mới nhất.

---

## 2. Khởi chạy nhanh (Quickstart)

Mở terminal, đi tới thư mục chứa file `docker-compose.yml` và chạy các lệnh sau:

```bash
# 1. Tải image và khởi chạy ngầm
docker compose pull
docker compose up -d

# 2. Xem log để đảm bảo IoTDB đã chạy thành công
docker logs -f iotdb
# Đợi vài chục giây, nếu thấy dòng "Congratulations, IoTDB DataNode is set up successfully" là OK. Thoát xem log bằng Ctrl+C.
```

**Các lệnh thường dùng khác:**
* Tắt hệ thống (nhưng **giữ lại** data): `docker compose down`
* Xóa sạch hệ thống (bao gồm **xóa sạch toàn bộ data/logs**): `docker compose down -v`
* Truy cập vào CLI của IoTDB:
  ```bash
  docker exec -it iotdb /iotdb/sbin/start-cli.sh -h iotdb -u root -pw root
  ```

---

## 3. Kiến trúc & Cấu hình mạng

Để đảm bảo mọi thành viên trong nhóm đều chạy trên một môi trường giống nhau 100%, Docker Image đã được khóa cứng bằng mã SHA256 thay vì dùng tag (ví dụ: `latest`). 

**Các cổng (Ports) cần lưu ý (Chỉ mở ở `127.0.0.1`):**
* `6667`: Cổng kết nối CSDL (JDBC / Session API) để ghi/đọc data.
* `9091`: Cổng lấy Metrics của ConfigNode (cho Prometheus).
* `9092`: Cổng lấy Metrics của DataNode (cho Prometheus).
* `9090`: Giao diện web của Prometheus.
* `3000`: Giao diện web của Grafana.

**Lưu trữ dữ liệu (Volumes):**
* Thư mục cấu hình `./iotdb/conf` trên máy bạn sẽ được map trực tiếp vào container. Nếu muốn đổi cấu hình, cứ sửa file ở đây rồi chạy `docker compose up -d --force-recreate`.
* Dữ liệu thật (TsFile, WAL) và Logs được lưu trong Docker Volume. Git sẽ không quản lý những file này.

---

## 4. Giám sát hệ thống (Monitoring)

Ngay khi hệ thống chạy lên, bộ giám sát cũng đã sẵn sàng:
* **Prometheus:** `http://127.0.0.1:9090`
* **Grafana:** `http://127.0.0.1:3000` (Không cần đăng nhập, cứ thế xem).

**Mẹo quan trọng khi chạy thực nghiệm:**
Mặc định, Prometheus lấy metrics mỗi 5 giây/lần để tránh làm lag IoTDB. Khi cần chạy test ngắn và cần độ chính xác cao (lấy metrics 1 giây/lần):
1. Mở file `monitoring/prometheus/prometheus.yml`.
2. Bỏ comment (uncomment) đoạn `iotdb-datanode-highfreq` ở cuối file.
3. Chạy lệnh sau để cập nhật mà không cần restart container:
   ```powershell
   Invoke-RestMethod -Uri http://127.0.0.1:9090/-/reload -Method Post
   ```

---

## 5. Kết nối & Tương tác

Sử dụng Python (thư viện `apache-iotdb`) để kết nối và ghi dữ liệu. Code mẫu:

```python
from iotdb.Session import Session

# Connect to IoTDB
s = Session("127.0.0.1", 6667, "root", "root")
s.open(False)

print(s.get_time_zone())
# Add your insert logic here...

s.close()
```

---

## 6. Phần B — Bộ sinh tải và benchmark ghi IoTDB

Code ở `load_generator/` sinh workload có thể tái lập theo seed và ghi dữ liệu
vào IoTDB. Có thể điều chỉnh tỷ lệ OOO, độ trễ trung bình/phân bố, batch size
và số luồng đồng thời. Mỗi lần chạy đọc lại dữ liệu để xác minh số bản ghi và
giá trị đã ghi.

Cài thư viện và chạy kiểm thử:

```powershell
py -3.13 -m pip install -r load_generator\requirements.txt
py -3.13 -m unittest -v load_generator.test_workload load_generator.test_benchmark
```

Sau khi stack ở phần A đã khởi động:

```powershell
py -3.13 -m load_generator.benchmark --records 1000 --batch-size 100 --concurrency 2 --ooo-ratio 0.3 --mean-lateness-ms 5000 --distribution exponential --seed 42
```

Tham số kết nối có thể đặt qua `IOTDB_HOST`, `IOTDB_PORT`,
`IOTDB_USERNAME`, `IOTDB_PASSWORD`. Hướng dẫn chi tiết, định nghĩa OOO và
lateness, cùng định dạng output nằm trong [`load_generator/README.md`](load_generator/README.md).

---

## 7. Giải thích các cơ chế cốt lõi

Lưu ý 2 cơ chế sau của IoTDB để không hiểu nhầm các chỉ số khi test:

* **Cơ chế xả bộ nhớ (Flush):** Hệ thống xả dữ liệu từ RAM xuống đĩa mỗi 10 phút, hoặc khi vùng nhớ ghi (Write Memory) đầy khoảng 40% (~280MB). Đừng nhìn vào tổng RAM IoTDB đang dùng để đoán, hãy xem chỉ số `flush_memtable_count_total` trên Prometheus.
* **Cơ chế gộp file (Compaction):** Khi có dữ liệu lệch thời gian (Out-of-Order), hệ thống tạo ra các file `unsequence` và phải chạy gộp file (`cross-space compaction`). Hiện tượng này gây tốn CPU. Theo dõi chỉ số `compaction_task_count{name="cross"}` trên Prometheus để thấy rõ.

---

## 8. Quy ước chung cho nhóm

* **Quản lý source code:** Các bạn tạo branch riêng (VD: `feature/ten-chuc-nang`) từ nhánh `main` để làm việc. Khi xong thì tạo Pull Request.
* **Không commit các file sau:** Dữ liệu sinh ra quá lớn (`.parquet`, `.csv`), dữ liệu trong volume (`iotdb/data`, `iotdb/logs`), secrets, thư mục ảo (`venv`).
* **Quy tắc commit:** Đặt tiền tố rõ ràng. Ví dụ: `[LoadGen] Them chuc nang sinh data lanh`, `[Config] Doi port mac dinh`.