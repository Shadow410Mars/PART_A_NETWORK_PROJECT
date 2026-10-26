# Part B — Workload generator and write benchmark

This package generates a reproducible timestamp-ordered workload and writes it
to the IoTDB instance from Part A. It supports out-of-order ratio, late-arrival
distribution and mean lateness, batch size, and concurrent writer streams.

## Install and test

From the repository root, using PowerShell:

```powershell
py -3.13 -m pip install -r load_generator\requirements.txt
py -3.13 -m unittest -v load_generator.test_workload load_generator.test_benchmark
```

## Run

Start the Part A Docker Compose stack first, then run a verified smoke workload:

```powershell
py -3.13 -m load_generator.benchmark --records 1000 --batch-size 100 --concurrency 2 --ooo-ratio 0.3 --mean-lateness-ms 5000 --distribution exponential --seed 42
```

Connection defaults match the local Part A Compose configuration:

- Host: `127.0.0.1` (`IOTDB_HOST`)
- RPC port: `6667` (`IOTDB_PORT`)
- Username: `root` (`IOTDB_USERNAME`)
- Password: `root` (`IOTDB_PASSWORD`)

Override connection settings with environment variables rather than editing
source code. Do not use production credentials or expose this demo stack to an
untrusted network.

## Workload semantics

- **OOO ratio:** fraction of records after the first whose timestamp is below
  the maximum timestamp already submitted in that stream. The generator picks
  the target number of OOO positions exactly; timestamps are kept unique.
- **Lateness:** for an OOO record, the previous stream watermark minus its
  timestamp. `--mean-lateness-ms` is the target mean among OOO records only.
- **Distribution:** `exponential` (default) or `uniform`.
- **Batch size:** maximum records sent in one `insert_records_of_one_device`
  request.
- **Concurrency:** number of independent streams, sessions, and devices.
  Each stream uses seed `--seed + stream_id`.

Trace generation, schema setup, and read-back verification are outside the
timed write phase. The recorded throughput is client-side write-phase
throughput; it is not isolated disk latency or an IoTDB internal OOO cost.

## Output

The default output directory is `load_generator\output\` and is ignored by
Git. It contains:

- `raw\benchmark_runs.csv`: one row per benchmark run.
- `raw\benchmark_batches.csv`: request latency and status per batch.
- `runs\<run_id>.json`: configuration, worker outcomes, and read-back
  verification.

Use `--output-dir` to select another local output directory. Keep generated
datasets and runtime output out of source control.
