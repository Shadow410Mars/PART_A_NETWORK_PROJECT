import unittest

from iotdb.utils.IoTDBConstants import TSDataType

from .benchmark import build_insert_batch, split_records
from .workload import generate_trace


class BenchmarkTests(unittest.TestCase):
    def test_records_are_split_without_loss_or_imbalance(self):
        counts = split_records(10, 3)
        self.assertEqual(counts, [4, 3, 3])
        self.assertEqual(sum(counts), 10)

    def test_batch_uses_row_oriented_iotdb_payload(self):
        records = generate_trace(
            record_count=4,
            ooo_ratio=0.5,
            seed=42,
        )

        timestamps, measurements, data_types, values = (
            build_insert_batch(records)
        )

        self.assertEqual(timestamps, [record.timestamp_ms for record in records])
        self.assertEqual(len(measurements), len(records))
        self.assertEqual(len(data_types), len(records))
        self.assertEqual(len(values), len(records))
        self.assertTrue(
            all(row == ["temperature", "humidity"] for row in measurements)
        )
        self.assertTrue(
            all(
                row == [TSDataType.FLOAT, TSDataType.FLOAT]
                for row in data_types
            )
        )

    def test_values_are_deterministic_from_record_sequence(self):
        records = generate_trace(
            record_count=3,
            ooo_ratio=0.0,
            seed=7,
        )

        _, _, _, values = build_insert_batch(records)

        self.assertEqual(
            values,
            [
                [
                    25.0 + record.sequence * 0.01,
                    60.0 + record.sequence * 0.01,
                ]
                for record in records
            ],
        )


if __name__ == "__main__":
    unittest.main()
