
import unittest
import pandas as pd

from app.backend.core.risk_rules import (
    find_multiple_incoming,
    find_rapid_outgoing,
    find_high_value_transfers,
    find_case_overlap
)


class TestRiskRules(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame([
            {
                "transaction_id": "TX001",
                "timestamp": "2026-10-01 10:00:00",
                "source_account": "A001",
                "target_account": "B001",
                "amount": 1000,
            },
            {
                "transaction_id": "TX002",
                "timestamp": "2026-10-01 10:10:00",
                "source_account": "A002",
                "target_account": "B001",
                "amount": 800,
            },
            {
                "transaction_id": "TX003",
                "timestamp": "2026-10-01 10:20:00",
                "source_account": "A003",
                "target_account": "B001",
                "amount": 600,
            },
            {
                "transaction_id": "TX004",
                "timestamp": "2026-10-01 10:04:00",
                "source_account": "B001",
                "target_account": "C001",
                "amount": 900,
            },
            {
                "transaction_id": "TX005",
                "timestamp": "2026-10-01 09:50:00",
                "source_account": "B001",
                "target_account": "D001",
                "amount": 200,
            },
        ])

        self.df["timestamp"] = pd.to_datetime(self.df["timestamp"])

    def test_multiple_incoming_detects_ten_senders(self):
        df = pd.DataFrame([
            {
                "transaction_id": f"TX{i:03d}",
                "timestamp": "2026-10-01 10:00:00",
                "source_account": f"A{i:03d}",
                "target_account": "B001",
                "amount": 1000,
            }
            for i in range(1, 11)
        ])

        result = find_multiple_incoming(df)
        row = result[result["account_id"] == "B001"]

        self.assertEqual(len(row), 1)
        self.assertEqual(int(row.iloc[0]["evidence"]), 10)

    def test_multiple_incoming_ignores_nine_senders(self):
        df = pd.DataFrame([
            {
                "transaction_id": f"TX{i:03d}",
                "timestamp": "2026-10-01 10:00:00",
                "source_account": f"A{i:03d}",
                "target_account": "B001",
                "amount": 1000,
            }
            for i in range(1, 10)
        ])

        result = find_multiple_incoming(df)
        self.assertTrue(result.empty)

    def test_rapid_outgoing_detects_transfer_within_five_minutes(self):
        result = find_rapid_outgoing(self.df)

        if result.empty:
            self.fail("ควรพบรายการ Rapid Outgoing ภายใน 5 นาที")

        match = result[
            (result["incoming_transaction_id"] == "TX001")
            & (result["outgoing_transaction_id"] == "TX004")
        ]

        self.assertEqual(len(match), 1)
        self.assertAlmostEqual(float(match.iloc[0]["evidence"]), 4)

    def test_rapid_outgoing_ignores_transfer_before_incoming(self):
        result = find_rapid_outgoing(self.df)

        if result.empty:
            return

        match = result[
            (result["incoming_transaction_id"] == "TX001")
            & (result["outgoing_transaction_id"] == "TX005")
        ]

        self.assertEqual(len(match), 0)

    def test_rapid_outgoing_ignores_transfer_after_five_minutes(self):
        df = self.df.copy()
        df.loc[
            df["transaction_id"] == "TX004", "timestamp"
        ] = pd.Timestamp("2026-10-01 10:06:00")

        result = find_rapid_outgoing(df)

        if result.empty:
            return

        match = result[
            (result["incoming_transaction_id"] == "TX001")
            & (result["outgoing_transaction_id"] == "TX004")
        ]

        self.assertEqual(len(match), 0)

    def test_rapid_outgoing_includes_exactly_five_minutes(self):
        df = self.df.copy()
        df.loc[
            df["transaction_id"] == "TX004", "timestamp"
        ] = pd.Timestamp("2026-10-01 10:05:00")

        result = find_rapid_outgoing(df)

        if result.empty:
            self.fail("ควรพบรายการ Rapid Outgoing ที่เวลา 5 นาที")

        match = result[
            (result["incoming_transaction_id"] == "TX001")
            & (result["outgoing_transaction_id"] == "TX004")
        ]

        self.assertEqual(len(match), 1)
        self.assertAlmostEqual(float(match.iloc[0]["evidence"]), 5)

    def test_high_value_ignores_49999(self):
        df = pd.DataFrame([{
            "transaction_id": "TX101",
            "source_account": "A001",
            "target_account": "B001",
            "timestamp": "2026-10-01 10:00:00",
            "amount": 49999,
        }])

        result = find_high_value_transfers(df)
        self.assertEqual(len(result), 0)

    def test_high_value_detects_exactly_50000(self):
        df = pd.DataFrame([{
            "transaction_id": "TX102",
            "source_account": "A001",
            "target_account": "B001",
            "timestamp": "2026-10-01 10:00:00",
            "amount": 50000,
        }])

        result = find_high_value_transfers(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result.iloc[0]["rule"],
            "high_value_transfer",
        )

    def test_high_value_detects_above_50000(self):
        df = pd.DataFrame([{
            "transaction_id": "TX103",
            "source_account": "A001",
            "target_account": "B001",
            "timestamp": "2026-10-01 10:00:00",
            "amount": 50001,
        }])

        result = find_high_value_transfers(df)
        self.assertEqual(len(result), 1)

    def test_detects_account_in_multiple_cases(self):
        df = pd.DataFrame({
            "case_id": ["CASE001", "CASE002", "CASE001"],
            "account_id": ["B782", "B782", "A001"],
        })

        result = find_case_overlap(df)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["account_id"], "B782")
        self.assertEqual(result.iloc[0]["evidence"], 2)

    def test_ignores_account_in_one_case(self):
        df = pd.DataFrame({
            "case_id": ["CASE001", "CASE001"],
            "account_id": ["A001", "A001"],
        })

        result = find_case_overlap(df)

        self.assertTrue(result.empty)

    def test_removes_duplicate_case_account_pairs(self):
        df = pd.DataFrame({
            "case_id": ["CASE001", "CASE001", "CASE002"],
            "account_id": ["B782", "B782", "B782"],
        })

        result = find_case_overlap(df)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["evidence"], 2)


if __name__ == "__main__":
    unittest.main()
