
import unittest
import pandas as pd

from investigation.tracing import find_paths


class TestTracing(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame([
            {
                "transaction_id": "TX001",
                "timestamp": "2026-10-01 08:00:00",
                "source_account": "A001",
                "target_account": "B001",
                "amount": 1000,
                "scenario": "normal",
                "is_suspicious": False,
            },
            {
                "transaction_id": "TX002",
                "timestamp": "2026-10-01 08:03:00",
                "source_account": "B001",
                "target_account": "C001",
                "amount": 900,
                "scenario": "normal",
                "is_suspicious": False,
            },
        ])
        self.df["timestamp"] = pd.to_datetime(self.df["timestamp"])

    def test_finds_direct_path(self):
        paths = find_paths(self.df, "A001", "B001", max_hops=4)

        self.assertEqual(len(paths), 1)
        self.assertEqual(
            paths[0][0]["transaction_id"],
            "TX001",
        )

    def test_finds_multi_hop_path(self):
        paths = find_paths(self.df, "A001", "C001", max_hops=4)

        self.assertEqual(len(paths), 1)
        self.assertEqual(
            [tx["transaction_id"] for tx in paths[0]],
            ["TX001", "TX002"],
        )

    def test_returns_no_path_for_reverse_direction(self):
        paths = find_paths(self.df, "C001", "A001", max_hops=4)

        self.assertEqual(len(paths), 0)

    def test_respects_max_hops(self):
        paths = find_paths(self.df, "A001", "C001", max_hops=1)

        self.assertEqual(len(paths), 0)


if __name__ == "__main__":
    unittest.main()