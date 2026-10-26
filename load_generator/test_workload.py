import unittest

from .workload import (
    build_metadata,
    generate_multi_stream_traces,
    generate_trace,
    measure_multi_stream_traces,
    measure_trace,
)


class WorkloadTests(unittest.TestCase):
    def test_seed_reproducibility(self):
        args = {
            "record_count": 100,
            "ooo_ratio": 0.30,
            "seed": 42,
        }
        self.assertEqual(
            generate_trace(**args),
            generate_trace(**args),
        )

    def test_zero_ooo(self):
        metrics = measure_trace(generate_trace(100, 0.0, seed=42))
        self.assertEqual(metrics["late_record_count"], 0)
        self.assertEqual(metrics["actual_ooo_ratio"], 0.0)
        self.assertIsNone(metrics["mean_lateness_ooo_records_ms"])

    def test_full_ooo(self):
        metrics = measure_trace(generate_trace(100, 1.0, seed=42))
        self.assertEqual(metrics["late_record_count"], 99)
        self.assertEqual(metrics["actual_ooo_ratio"], 1.0)

    def test_target_ratio_and_unique_timestamps(self):
        metrics = measure_trace(
            generate_trace(1000, 0.25, seed=2026)
        )
        self.assertEqual(metrics["late_record_count"], round(0.25 * 999))
        self.assertTrue(metrics["timestamps_unique"])

    def test_exponential_conditional_mean_is_reasonable(self):
        metrics = measure_trace(generate_trace(
            10000,
            0.30,
            seed=42,
            mean_lateness_ms=5000,
            lateness_distribution="exponential",
        ))
        self.assertAlmostEqual(
            metrics["mean_lateness_ooo_records_ms"],
            5000,
            delta=600,
        )

    def test_all_record_mean_includes_in_order_records(self):
        metrics = measure_trace(generate_trace(
            10000,
            0.30,
            seed=42,
            mean_lateness_ms=5000,
        ))
        self.assertLess(
            metrics["mean_lateness_all_records_ms"],
            metrics["mean_lateness_ooo_records_ms"],
        )

    def test_invalid_ratio(self):
        with self.assertRaises(ValueError):
            generate_trace(100, 1.5, seed=42)

    def test_invalid_distribution(self):
        with self.assertRaises(ValueError):
            generate_trace(
                100,
                0.2,
                seed=42,
                lateness_distribution="normal",
            )

    def test_invalid_mean_lateness(self):
        with self.assertRaises(ValueError):
            generate_trace(100, 0.2, seed=42, mean_lateness_ms=0)

    def test_uniform_reproducibility(self):
        args = {
            "record_count": 200,
            "ooo_ratio": 0.4,
            "seed": 7,
            "lateness_distribution": "uniform",
        }
        self.assertEqual(generate_trace(**args), generate_trace(**args))

    def test_metadata_distinguishes_target_and_measurement(self):
        metadata = build_metadata(
            trace=generate_trace(100, 0.2, seed=99),
            target_ooo_ratio=0.2,
            seed=99,
            mean_lateness_ms=5000,
            lateness_distribution="exponential",
            timestamp_step_ms=1000,
        )
        self.assertEqual(metadata["seed"], 99)
        self.assertIn("target_ooo_ratio", metadata)
        self.assertIn("actual_ooo_ratio", metadata)
        self.assertIn("mean_lateness_target_ms_when_ooo", metadata)
        self.assertIn("mean_lateness_ooo_records_ms", metadata)
        self.assertIn("mean_lateness_all_records_ms", metadata)

    def test_multi_stream_reproducibility(self):
        args = {
            "stream_count": 3,
            "record_count_per_stream": 100,
            "ooo_ratio": 0.30,
            "seed": 42,
        }
        self.assertEqual(
            generate_multi_stream_traces(**args),
            generate_multi_stream_traces(**args),
        )

    def test_multi_stream_metrics(self):
        traces = generate_multi_stream_traces(
            stream_count=4,
            record_count_per_stream=1000,
            ooo_ratio=0.20,
            seed=42,
        )
        metrics = measure_multi_stream_traces(traces)
        self.assertEqual(metrics["stream_count"], 4)
        self.assertEqual(metrics["total_records"], 4000)
        self.assertAlmostEqual(metrics["actual_ooo_ratio"], 0.20, delta=0.002)
        self.assertEqual(len(metrics["per_stream"]), 4)


if __name__ == "__main__":
    unittest.main()
