"""
Apache IoTDB benchmark workload generator - D4 prototype, version 2.

Chạy kiểm thử:
    python -m unittest -v load_generator.test_workload

Sinh và kiểm tra trace thử nghiệm:
    python -c "from load_generator import generate_trace, measure_trace; print(measure_trace(generate_trace(10000,0.3,seed=42,mean_lateness_ms=5000)))"

Chú ý:
    - Chưa ghi dữ liệu vào IoTDB.
    - mean_lateness_ms là trung bình mục tiêu CỦA RIÊNG các bản ghi OOO.
    - mean_lateness_all_records_ms bao gồm cả bản ghi đúng thứ tự,
      có lateness bằng 0.
"""

import math
import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Record:
    sequence: int
    timestamp_ms: int
    lateness_ms: int


def sample_lateness(rng, distribution, mean_lateness_ms):
    """Lấy mẫu lateness dương, tính bằng millisecond."""
    if distribution == "uniform":
        upper = max(1, round(2 * mean_lateness_ms))
        return rng.randint(1, upper)

    if distribution == "exponential":
        return max(1, round(rng.expovariate(1.0 / mean_lateness_ms)))

    raise ValueError(
        "distribution must be 'uniform' or 'exponential'"
    )


def generate_trace(
    record_count,
    ooo_ratio,
    seed,
    timestamp_step_ms=1000,
    mean_lateness_ms=5000.0,
    lateness_distribution="exponential",
    base_timestamp_ms=1_700_000_000_000,
):
    """
    Sinh trace theo thứ tự bản ghi đến.

    Định nghĩa OOO:
        Một bản ghi OOO có timestamp nhỏ hơn watermark trước đó,
        tức max(timestamp của các bản ghi đã đến trước nó).

    Định nghĩa lateness:
        watermark_trước_đó - timestamp_hiện_tại, nếu kết quả dương;
        ngược lại bằng 0.

    mean_lateness_ms:
        Trung bình mục tiêu có điều kiện trên các bản ghi OOO,
        không phải trung bình trên toàn bộ trace.
    """
    if not isinstance(record_count, int) or record_count < 2:
        raise ValueError("record_count must be an integer >= 2")

    if not math.isfinite(ooo_ratio) or not 0.0 <= ooo_ratio <= 1.0:
        raise ValueError("ooo_ratio must be between 0 and 1")

    if not isinstance(timestamp_step_ms, int) or timestamp_step_ms < 1:
        raise ValueError("timestamp_step_ms must be an integer >= 1")

    if (
        not math.isfinite(mean_lateness_ms)
        or mean_lateness_ms <= 0
    ):
        raise ValueError("mean_lateness_ms must be positive and finite")

    if lateness_distribution not in {"uniform", "exponential"}:
        raise ValueError(
            "lateness_distribution must be 'uniform' or 'exponential'"
        )

    if not isinstance(base_timestamp_ms, int):
        raise ValueError("base_timestamp_ms must be an integer")

    rng = random.Random(seed)

    # Chọn chính xác số vị trí OOO mục tiêu trong các vị trí sau bản ghi đầu.
    target_late_count = round(ooo_ratio * (record_count - 1))
    late_positions = set(
        rng.sample(range(1, record_count), target_late_count)
    )

    # Timestamp nền giống một mốc thời gian epoch tính bằng millisecond.
    # Các bản ghi đúng thứ tự tiến thêm timestamp_step_ms.
    watermark = base_timestamp_ms
    trace = [
        Record(
            sequence=0,
            timestamp_ms=watermark,
            lateness_ms=0,
        )
    ]
    used_timestamps = {watermark}

    for sequence in range(1, record_count):
        if sequence not in late_positions:
            # Bản ghi đúng thứ tự: timestamp mới vượt watermark.
            timestamp = watermark + timestamp_step_ms
        else:
            # Bản ghi OOO: timestamp nằm trước watermark hiện tại.
            lateness = sample_lateness(
                rng,
                lateness_distribution,
                mean_lateness_ms,
            )
            timestamp = watermark - lateness

            # Timestamp phải duy nhất. Nếu trùng, tăng lateness 1 ms
            # cho đến khi tìm được timestamp chưa sử dụng.
            # Việc này có thể làm lateness thực tế lệch nhẹ khỏi mẫu ban đầu.
            while timestamp in used_timestamps:
                lateness += 1
                timestamp = watermark - lateness

        if timestamp in used_timestamps:
            raise RuntimeError("Duplicate timestamp generated")

        actual_lateness = max(0, watermark - timestamp)

        trace.append(
            Record(
                sequence=sequence,
                timestamp_ms=timestamp,
                lateness_ms=actual_lateness,
            )
        )
        used_timestamps.add(timestamp)

        # Chỉ cập nhật watermark khi timestamp mới vượt cực đại trước đó.
        watermark = max(watermark, timestamp)

    return trace

def generate_multi_stream_traces(
    stream_count,
    record_count_per_stream,
    ooo_ratio,
    seed,
    timestamp_step_ms=1000,
    mean_lateness_ms=5000.0,
    lateness_distribution="exponential",
):
    """
    Tạo trace riêng cho từng edge stream.

    Mỗi stream có:
    - chuỗi sequence riêng;
    - watermark riêng;
    - OOO ratio mục tiêu riêng;
    - seed riêng, xác định từ seed gốc và stream_id.

    Kết quả:
        {
            0: [Record, Record, ...],
            1: [Record, Record, ...],
            ...
        }

    Hàm này chỉ sinh dữ liệu; chưa thực hiện I/O hay concurrency.
    """
    if not isinstance(stream_count, int) or stream_count < 1:
        raise ValueError("stream_count must be an integer >= 1")

    traces = {}

    for stream_id in range(stream_count):
        stream_seed = seed + stream_id

        traces[stream_id] = generate_trace(
            record_count=record_count_per_stream,
            ooo_ratio=ooo_ratio,
            seed=stream_seed,
            timestamp_step_ms=timestamp_step_ms,
            mean_lateness_ms=mean_lateness_ms,
            lateness_distribution=lateness_distribution,
        )

    return traces


def measure_multi_stream_traces(traces):
    """
    Tổng hợp metrics mà vẫn giữ ranh giới watermark giữa các stream.

    Không gộp timestamp của các stream để tính OOO:
    mỗi stream có tiến trình thời gian riêng.
    """
    if not traces:
        raise ValueError("traces must not be empty")

    per_stream = {
        stream_id: measure_trace(trace)
        for stream_id, trace in traces.items()
    }

    total_records = sum(
        metrics["record_count"]
        for metrics in per_stream.values()
    )
    total_positions_after_first = sum(
        metrics["record_count"] - 1
        for metrics in per_stream.values()
    )
    total_late_records = sum(
        metrics["late_record_count"]
        for metrics in per_stream.values()
    )

    all_lateness_sum = sum(
        metrics["mean_lateness_all_records_ms"]
        * metrics["record_count"]
        for metrics in per_stream.values()
    )

    total_ooo_lateness_sum = sum(
        (metrics["mean_lateness_ooo_records_ms"] or 0)
        * metrics["late_record_count"]
        for metrics in per_stream.values()
    )

    return {
        "stream_count": len(per_stream),
        "total_records": total_records,
        "actual_ooo_ratio": (
            total_late_records / total_positions_after_first
            if total_positions_after_first else 0.0
        ),
        "mean_lateness_all_records_ms": (
            all_lateness_sum / total_records
        ),
        "mean_lateness_ooo_records_ms": (
            total_ooo_lateness_sum / total_late_records
            if total_late_records else None
        ),
        "per_stream": per_stream,
    }

def percentile(values, p):
    """Percentile theo nearest-rank, với p nằm trong (0, 1]."""
    if not values:
        return None

    ordered = sorted(values)
    index = max(0, math.ceil(p * len(ordered)) - 1)
    return ordered[index]


def measure_trace(trace):
    """Tính lại OOO và lateness từ timestamp thực tế theo thứ tự đến."""
    if not trace:
        raise ValueError("trace must not be empty")

    seen_max = trace[0].timestamp_ms
    all_lateness = [0]
    ooo_lateness = []
    late_count = 0

    for record in trace[1:]:
        lateness = max(0, seen_max - record.timestamp_ms)
        all_lateness.append(lateness)

        if lateness > 0:
            late_count += 1
            ooo_lateness.append(lateness)

        seen_max = max(seen_max, record.timestamp_ms)

    return {
        "record_count": len(trace),
        "late_record_count": late_count,
        "actual_ooo_ratio": late_count / (len(trace) - 1),
        "mean_lateness_all_records_ms": (
            sum(all_lateness) / len(all_lateness)
        ),
        "mean_lateness_ooo_records_ms": (
            sum(ooo_lateness) / len(ooo_lateness)
            if ooo_lateness else None
        ),
        "max_lateness_ms": max(all_lateness),
        "p95_lateness_all_records_ms": percentile(all_lateness, 0.95),
        "p95_lateness_ooo_records_ms": percentile(ooo_lateness, 0.95),
        "timestamps_unique": (
            len({record.timestamp_ms for record in trace}) == len(trace)
        ),
    }


def build_metadata(
    trace,
    target_ooo_ratio,
    seed,
    mean_lateness_ms,
    lateness_distribution,
    timestamp_step_ms,
):
    """Lưu tham số mục tiêu riêng với số đo thực tế."""
    return {
        "generator_version": 2,
        "seed": seed,
        "target_ooo_ratio": target_ooo_ratio,
        "mean_lateness_target_ms_when_ooo": mean_lateness_ms,
        "lateness_distribution": lateness_distribution,
        "timestamp_step_ms": timestamp_step_ms,
        **measure_trace(trace),
    }


def record_to_dict(record):
    return asdict(record)