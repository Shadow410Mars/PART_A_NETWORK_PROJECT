
import argparse
import csv
import json
import math
import os
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from iotdb.Session import Session
from iotdb.utils.IoTDBConstants import TSDataType

from .workload import generate_trace, measure_trace


HOST = os.environ.get("IOTDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("IOTDB_PORT", "6667"))
USERNAME = os.environ.get("IOTDB_USERNAME", "root")
PASSWORD = os.environ.get("IOTDB_PASSWORD", "root")
DATABASE = "root.iotdb_bench"

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"

RUN_FIELDS = [
    "run_id", "device", "seed", "records_submitted",
    "records_verified", "batch_size", "batch_count",
    "target_ooo_ratio", "actual_ooo_ratio",
    "mean_lateness_ooo_records_ms", "write_elapsed_seconds",
    "throughput_records_per_sec", "status",
]

BATCH_FIELDS = [
    "run_id", "batch_index", "records_submitted",
    "write_latency_ms", "status", "error",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--records", type=int, default=1000,
                   help="Total records across all workers")
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--ooo-ratio", type=float, default=0.30)
    p.add_argument("--mean-lateness-ms", type=float, default=5000)
    p.add_argument("--distribution",
                   choices=["uniform", "exponential"],
                   default="exponential")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timestamp-step-ms", type=int, default=1000)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for run metadata and CSV output.",
    )
    p.add_argument(
        "--run-id",
        help="Optional 32-character hexadecimal run identifier",
    )
    p.add_argument(
        "--experiment-group",
        help="Optional controlled-experiment condition label",
    )
    args = p.parse_args()

    if args.records < 2:
        p.error("--records must be >= 2")
    if args.batch_size < 1:
        p.error("--batch-size must be >= 1")
    if not 1 <= args.concurrency <= args.records // 2:
        p.error("--concurrency must be >= 1 and each worker needs >= 2 records")
    if not math.isfinite(args.ooo_ratio) or not 0 <= args.ooo_ratio <= 1:
        p.error("--ooo-ratio must be between 0 and 1")
    if not math.isfinite(args.mean_lateness_ms) or args.mean_lateness_ms <= 0:
        p.error("--mean-lateness-ms must be positive and finite")
    if args.timestamp_step_ms < 1:
        p.error("--timestamp-step-ms must be >= 1")
    if args.run_id is not None and (
        len(args.run_id) != 32
        or any(char not in "0123456789abcdefABCDEF" for char in args.run_id)
    ):
        p.error("--run-id must be 32 hexadecimal characters")
    return args


def append_csv(path, fields, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerows(rows)


def split_records(total, workers):
    q, r = divmod(total, workers)
    return [q + (i < r) for i in range(workers)]


def create_schema(session, device):
    # Schema setup is intentionally outside the timed write phase.
    session.execute_non_query_statement(
        f"CREATE TIMESERIES {device}.temperature "
        "WITH DATATYPE=FLOAT, ENCODING=PLAIN, COMPRESSOR=SNAPPY"
    )
    session.execute_non_query_statement(
        f"CREATE TIMESERIES {device}.humidity "
        "WITH DATATYPE=FLOAT, ENCODING=PLAIN, COMPRESSOR=SNAPPY"
    )


def build_insert_batch(records):
    """Build the row-oriented shape expected by insert_records_of_one_device."""
    timestamps = [record.timestamp_ms for record in records]
    measurements = [["temperature", "humidity"] for _ in records]
    data_types = [
        [TSDataType.FLOAT, TSDataType.FLOAT] for _ in records
    ]
    values = [
        [
            25.0 + record.sequence * 0.01,
            60.0 + record.sequence * 0.01,
        ]
        for record in records
    ]
    return timestamps, measurements, data_types, values


def prepare_stream(args, run_id, stream_id, record_count):
    seed = args.seed + stream_id
    trace = generate_trace(
        record_count=record_count,
        ooo_ratio=args.ooo_ratio,
        seed=seed,
        timestamp_step_ms=args.timestamp_step_ms,
        mean_lateness_ms=args.mean_lateness_ms,
        lateness_distribution=args.distribution,
    )
    device = (
        f"{DATABASE}.run_{run_id}_stream_{stream_id:03d}"
    )
    return {
        "stream_id": stream_id,
        "seed": seed,
        "device": device,
        "trace": trace,
        "metrics": measure_trace(trace),
    }


def writer(stream, args, ready, start_event, abort_event):
    """One worker owns one session and one device."""
    session = None
    batches = []
    submitted = 0
    error = None

    try:
        session = Session(HOST, PORT, USERNAME, PASSWORD)
        session.open(False)
        create_schema(session, stream["device"])
    except Exception as exc:
        error = f"setup: {type(exc).__name__}: {exc}"
        ready.put((stream["stream_id"], error))
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
        return {
            "stream_id": stream["stream_id"],
            "submitted": 0,
            "batches": [],
            "status": "ERROR",
            "error": error,
        }

    ready.put((stream["stream_id"], None))
    start_event.wait()

    try:
        if abort_event.is_set():
            return {
                "stream_id": stream["stream_id"],
                "submitted": 0,
                "batches": [],
                "status": "ERROR",
                "error": "Run aborted because another worker failed setup",
            }

        for offset in range(0, len(stream["trace"]), args.batch_size):
            records = stream["trace"][offset:offset + args.batch_size]
            timestamps, measurements, data_types, values = (
                build_insert_batch(records)
            )

            batch_start = time.perf_counter()
            batch_status = "PASS"
            batch_error = ""
            try:
                session.insert_records_of_one_device(
                    stream["device"],
                    timestamps,
                    measurements,
                    data_types,
                    values,
                )
                submitted += len(records)
            except Exception as exc:
                batch_status = "ERROR"
                batch_error = f"{type(exc).__name__}: {exc}"
                error = batch_error
            latency_ms = (time.perf_counter() - batch_start) * 1000

            batches.append({
                "records_submitted": len(records),
                "write_latency_ms": f"{latency_ms:.6f}",
                "status": batch_status,
                "error": batch_error,
            })

            if batch_status == "ERROR":
                break

        return {
            "stream_id": stream["stream_id"],
            "submitted": submitted,
            "batches": batches,
            "status": "PASS" if error is None else "ERROR",
            "error": error,
        }
    except Exception as exc:
        return {
            "stream_id": stream["stream_id"],
            "submitted": submitted,
            "batches": batches,
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


def verify_stream(stream):
    session = Session(HOST, PORT, USERNAME, PASSWORD)
    session.open(False)
    try:
        result = session.execute_query_statement(
            f"SELECT temperature, humidity FROM {stream['device']}"
        )
        observed = {}
        while result.has_next():
            row = result.next()
            fields = row.get_fields()
            observed[row.get_timestamp()] = (
                (
                    fields[0].get_object_value(fields[0].get_data_type())
                    if fields[0] else None
                ),
                (
                    fields[1].get_object_value(fields[1].get_data_type())
                    if fields[1] else None
                ),
            )

        verified = 0
        problems = []
        for record in stream["trace"]:
            expected = (
                25.0 + record.sequence * 0.01,
                60.0 + record.sequence * 0.01,
            )
            actual = observed.get(record.timestamp_ms)
            if actual is None:
                problems.append(f"missing timestamp {record.timestamp_ms}")
                continue

            if all(
                value is not None
                and math.isclose(
                    float(value), target, rel_tol=0, abs_tol=1e-4
                )
                for value, target in zip(actual, expected)
            ):
                verified += 1
            else:
                problems.append(
                    f"value mismatch at {record.timestamp_ms}"
                )

        extras = set(observed) - {
            r.timestamp_ms for r in stream["trace"]
        }
        if extras:
            problems.append(f"{len(extras)} unexpected timestamps")

        return verified, problems
    finally:
        session.close()


def main():
    args = parse_args()
    raw_dir = args.output_dir / "raw"
    runs_dir = args.output_dir / "runs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id or uuid.uuid4().hex
    counts = split_records(args.records, args.concurrency)

    # Generate every trace before timing begins.
    streams = [
        prepare_stream(args, run_id, i, count)
        for i, count in enumerate(counts)
    ]

    print(f"RUN_ID: {run_id}")
    print(f"RECORDS: {args.records}")
    print(f"BATCH_SIZE: {args.batch_size}")
    print(f"CONCURRENCY: {args.concurrency}")
    print("Preparing sessions and schemas outside timed phase...")

    ready = queue.Queue()
    start_event = threading.Event()
    abort_event = threading.Event()
    results = []

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(writer, s, args, ready, start_event, abort_event)
            for s in streams
        ]

        # Wait until every worker reports whether its setup succeeded.
        readiness = [ready.get() for _ in streams]
        setup_errors = [item for item in readiness if item[1] is not None]

        if setup_errors:
            abort_event.set()
        write_start_utc = utc_now()
        write_start = time.perf_counter()
        start_event.set()

        for future in futures:
            results.append(future.result())

        write_elapsed = time.perf_counter() - write_start
        write_end_utc = utc_now()

    submitted = sum(r["submitted"] for r in results)
    batch_rows = []
    for result in results:
        for batch in result["batches"]:
            batch_rows.append(batch)

    verification = []
    if not setup_errors:
        for stream in streams:
            try:
                count, problems = verify_stream(stream)
                verification.append({
                    "stream_id": stream["stream_id"],
                    "verified": count,
                    "problems": problems,
                })
            except Exception as exc:
                verification.append({
                    "stream_id": stream["stream_id"],
                    "verified": 0,
                    "problems": [f"{type(exc).__name__}: {exc}"],
                })

    verified = sum(v["verified"] for v in verification)
    batch_count = len(batch_rows)
    actual_ooo = (
        sum(s["metrics"]["late_record_count"] for s in streams)
        / sum(len(s["trace"]) - 1 for s in streams)
    )
    late_streams = [
        s for s in streams if s["metrics"]["late_record_count"] > 0
    ]
    late_count = sum(
        s["metrics"]["late_record_count"] for s in late_streams
    )
    mean_lateness = (
        sum(
            s["metrics"]["mean_lateness_ooo_records_ms"]
            * s["metrics"]["late_record_count"]
            for s in late_streams
        ) / late_count
        if late_count else None
    )

    problems = [
        problem
        for item in verification
        for problem in item["problems"]
    ]
    status = (
        "PASS"
        if not setup_errors
        and all(r["status"] == "PASS" for r in results)
        and submitted == args.records
        and verified == args.records
        and not problems
        else "ERROR"
    )

    run_row = {
        "run_id": run_id,
        "device": ";".join(s["device"] for s in streams),
        "seed": args.seed,
        "records_submitted": submitted,
        "records_verified": verified,
        "batch_size": args.batch_size,
        "batch_count": batch_count,
        "target_ooo_ratio": args.ooo_ratio,
        "actual_ooo_ratio": actual_ooo,
        "mean_lateness_ooo_records_ms": mean_lateness,
        "write_elapsed_seconds": f"{write_elapsed:.6f}",
        "throughput_records_per_sec": (
            f"{submitted / write_elapsed:.3f}"
            if write_elapsed > 0 else ""
        ),
        "status": status,
    }

    append_csv(
        raw_dir / "benchmark_runs.csv", RUN_FIELDS, [run_row]
    )

    # Keep the legacy batch CSV schema; batch_index is unique per run.
    for index, batch in enumerate(batch_rows):
        batch["run_id"] = run_id
        batch["batch_index"] = index
    append_csv(
        raw_dir / "benchmark_batches.csv", BATCH_FIELDS, batch_rows
    )

    metadata = {
        "generator_version": 2,
        "run_id": run_id,
        "experiment_group": args.experiment_group,
        "host": HOST,
        "port": PORT,
        "database": DATABASE,
        "records_target_total": args.records,
        "records_submitted": submitted,
        "records_verified": verified,
        "batch_size": args.batch_size,
        "concurrency": args.concurrency,
        "seed_base": args.seed,
        "stream_seeds": [s["seed"] for s in streams],
        "target_ooo_ratio": args.ooo_ratio,
        "actual_ooo_ratio": actual_ooo,
        "mean_lateness_target_ms_when_ooo": args.mean_lateness_ms,
        "mean_lateness_ooo_records_ms": mean_lateness,
        "lateness_distribution": args.distribution,
        "write_start_utc": write_start_utc,
        "write_end_utc": write_end_utc,
        "write_elapsed_seconds": write_elapsed,
        "throughput_records_per_sec": (
            submitted / write_elapsed if write_elapsed > 0 else None
        ),
        "timing_scope": (
            "Client-side wall-clock write phase; trace generation, "
            "schema setup, and verification excluded. Not physical disk latency."
        ),
        "streams": [
            {
                "stream_id": s["stream_id"],
                "device": s["device"],
                "seed": s["seed"],
                "records": len(s["trace"]),
                **s["metrics"],
            }
            for s in streams
        ],
        "workers": [
            {k: v for k, v in r.items() if k != "batches"}
            for r in results
        ],
        "verification": verification,
        "verification_problems": problems[:50],
        "setup_errors": setup_errors,
        "status": status,
    }

    metadata_path = runs_dir / f"{run_id}.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"WRITE_SECONDS: {write_elapsed:.6f}")
    print(f"SUBMITTED: {submitted}/{args.records}")
    print(f"VERIFIED: {verified}/{args.records}")
    print(f"THROUGHPUT: {submitted / write_elapsed:.3f} records/s")
    print(f"STATUS: {status}")
    print(f"METADATA: {metadata_path}")
    for stream_id, error in setup_errors:
        print(f"ERROR: stream {stream_id} {error}", flush=True)
    for worker in results:
        if worker["error"]:
            print(
                f"ERROR: stream {worker['stream_id']} {worker['error']}",
                flush=True,
            )
    for problem in problems:
        print(f"ERROR: verification {problem}", flush=True)

    raise SystemExit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
