
import unittest
from pathlib import Path
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

    def test_multiple_incoming_negative_four_transactions(self):
        """Negative case (N041 scenario): 4 incoming transactions is below threshold of 5."""
        df = pd.DataFrame([
            {
                "transaction_id": f"TX{i:03d}",
                "timestamp": f"2026-10-01 10:0{i*2}:00",
                "source_account": f"A{i:03d}",
                "target_account": "B001",
                "amount": 1000,
            }
            for i in range(1, 5)
        ])
        result = find_multiple_incoming(df)
        self.assertTrue(result.empty)

    def test_multiple_incoming_negative_spread_twelve_minutes(self):
        """Negative case (N042 scenario): 5 transactions spread across 12 minutes exceeds 10m window."""
        df = pd.DataFrame([
            {
                "transaction_id": f"TX{i:03d}",
                "timestamp": ts,
                "source_account": f"A{i:03d}",
                "target_account": "B001",
                "amount": 1000,
            }
            for i, ts in enumerate([
                "2026-10-01 10:00:00",
                "2026-10-01 10:03:00",
                "2026-10-01 10:06:00",
                "2026-10-01 10:09:00",
                "2026-10-01 10:12:00",
            ], start=1)
        ])
        result = find_multiple_incoming(df)
        self.assertTrue(result.empty)

    def test_multiple_incoming_negative_single_sender(self):
        """Negative case (N043 scenario): 5 transactions from 1 sender fails >= 2 senders requirement."""
        df = pd.DataFrame([
            {
                "transaction_id": f"TX{i:03d}",
                "timestamp": f"2026-10-01 10:0{i}:00",
                "source_account": "A001",
                "target_account": "B001",
                "amount": 1000,
            }
            for i in range(1, 6)
        ])
        result = find_multiple_incoming(df)
        self.assertTrue(result.empty)

    def test_multiple_incoming_exact_ten_minute_boundary(self):
        """Positive case (B902 scenario): Exactly 5 transactions over exactly 10 minutes (inclusive)."""
        df = pd.DataFrame([
            {
                "transaction_id": f"TX{i:03d}",
                "timestamp": ts,
                "source_account": f"A{i:03d}",
                "target_account": "B902",
                "amount": 1000,
            }
            for i, ts in enumerate([
                "2026-10-01 10:00:00",
                "2026-10-01 10:02:00",
                "2026-10-01 10:04:00",
                "2026-10-01 10:07:00",
                "2026-10-01 10:10:00",
            ], start=1)
        ])
        result = find_multiple_incoming(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["account_id"], "B902")
        self.assertEqual(result.iloc[0]["transaction_ids"], "TX001, TX002, TX003, TX004, TX005")

    def test_multiple_incoming_demo_scenarios(self):
        """Verify all required canonical dataset scenarios (B782, B902, N041, N042, N043, SHOP01)."""
        tx_path = Path(__file__).resolve().parent.parent / "app" / "data" / "transactions.csv"
        df = pd.read_csv(tx_path)
        findings = find_multiple_incoming(df)
        flagged_accounts = set(findings["account_id"].tolist())

        # Positives
        self.assertIn("B782", flagged_accounts, "B782 must be detected (10 incoming in 9 min)")
        self.assertIn("B902", flagged_accounts, "B902 must be detected (5 incoming in 10 min)")
        self.assertIn("SHOP01", flagged_accounts, "SHOP01 must be detected (legitimate-business probe)")

        # Negatives
        self.assertNotIn("N041", flagged_accounts, "N041 has only 4 transactions")
        self.assertNotIn("N042", flagged_accounts, "N042 transactions span 12 minutes")
        self.assertNotIn("N043", flagged_accounts, "N043 has only 1 distinct sender")

        # B782 evidence check
        b782_row = findings[findings["account_id"] == "B782"].iloc[0]
        self.assertEqual(int(b782_row["evidence"]), 10)
        self.assertIn("TX0030", b782_row["transaction_ids"])
        self.assertIn("TX0039", b782_row["transaction_ids"])
        self.assertNotIn("TX0045", b782_row["transaction_ids"], "TX0045 occurs hours later and must not merge")

    def test_multiple_incoming_shuffled_rows_deterministic(self):
        """Findings and transaction ID ordering must be completely deterministic regardless of input row order."""
        tx_path = Path(__file__).resolve().parent.parent / "app" / "data" / "transactions.csv"
        df = pd.read_csv(tx_path)
        res1 = find_multiple_incoming(df)
        res2 = find_multiple_incoming(df.sample(frac=1, random_state=12345))
        self.assertTrue(res1.equals(res2))

    def test_multiple_incoming_no_duplicate_overlapping_windows(self):
        """Avoid duplicate findings from overlapping windows within a single burst."""
        # 8 incoming transactions in 7 minutes for account B001
        df = pd.DataFrame([
            {
                "transaction_id": f"TX{i:03d}",
                "timestamp": f"2026-10-01 10:0{i}:00",
                "source_account": f"A{i:03d}",
                "target_account": "B001",
                "amount": 1000,
            }
            for i in range(1, 9)
        ])
        result = find_multiple_incoming(df)
        self.assertEqual(len(result), 1, "Should produce exactly 1 finding, not multiple overlapping alerts")
        self.assertEqual(len(result.iloc[0]["transaction_ids"].split(", ")), 8)

    def test_multiple_incoming_separate_bursts_not_merged(self):
        """Two separate bursts > 10 minutes apart must produce 2 distinct findings, not be merged."""
        burst1 = [
            {
                "transaction_id": f"TX0{i:02d}",
                "timestamp": f"2026-10-01 10:0{i}:00",
                "source_account": f"A0{i:02d}",
                "target_account": "B001",
                "amount": 1000,
            }
            for i in range(1, 6)  # 10:01 to 10:05
        ]
        burst2 = [
            {
                "transaction_id": f"TX1{i:02d}",
                "timestamp": f"2026-10-01 11:0{i}:00",
                "source_account": f"A1{i:02d}",
                "target_account": "B001",
                "amount": 1000,
            }
            for i in range(1, 6)  # 11:01 to 11:05 (1 hour later)
        ]
        df = pd.DataFrame(burst1 + burst2)
        result = find_multiple_incoming(df)
        self.assertEqual(len(result), 2, "Separate bursts must produce 2 findings")
        ids1 = result.iloc[0]["transaction_ids"].split(", ")
        ids2 = result.iloc[1]["transaction_ids"].split(", ")
        self.assertEqual(ids1, ["TX001", "TX002", "TX003", "TX004", "TX005"])
        self.assertEqual(ids2, ["TX101", "TX102", "TX103", "TX104", "TX105"])

    def test_rapid_outgoing_detects_transfer_within_two_minutes(self):
        df = self.df.copy()
        df.loc[
            df["transaction_id"] == "TX004", "timestamp"
        ] = pd.Timestamp("2026-10-01 10:01:30")

        result = find_rapid_outgoing(df)
        match = result[
            (result["incoming_transaction_id"] == "TX001")
            & (result["outgoing_transaction_id"] == "TX004")
        ]

        self.assertEqual(len(match), 1)
        self.assertAlmostEqual(float(match.iloc[0]["evidence"]), 1.5)

    def test_rapid_outgoing_ignores_transfer_before_incoming(self):
        result = find_rapid_outgoing(self.df)
        match = result[
            (result["incoming_transaction_id"] == "TX001")
            & (result["outgoing_transaction_id"] == "TX005")
        ]
        self.assertEqual(len(match), 0)

    def test_rapid_outgoing_ignores_transfer_after_two_minutes(self):
        df = self.df.copy()
        df.loc[
            df["transaction_id"] == "TX004", "timestamp"
        ] = pd.Timestamp("2026-10-01 10:03:00")

        result = find_rapid_outgoing(df)
        match = result[
            (result["incoming_transaction_id"] == "TX001")
            & (result["outgoing_transaction_id"] == "TX004")
        ]
        self.assertEqual(len(match), 0)

    def test_rapid_outgoing_includes_exactly_two_minutes(self):
        df = self.df.copy()
        df.loc[
            df["transaction_id"] == "TX004", "timestamp"
        ] = pd.Timestamp("2026-10-01 10:02:00")

        result = find_rapid_outgoing(df)
        match = result[
            (result["incoming_transaction_id"] == "TX001")
            & (result["outgoing_transaction_id"] == "TX004")
        ]

        self.assertEqual(len(match), 1)
        self.assertAlmostEqual(float(match.iloc[0]["evidence"]), 2.0)

    def test_rapid_outgoing_demo_scenarios(self):
        """Verify B777 (2m), B778 (1m), B900 (2m), B901 (2m) are positive; N044 (3m) is negative."""
        tx_path = Path(__file__).resolve().parent.parent / "app" / "data" / "transactions.csv"
        df = pd.read_csv(tx_path)
        findings = find_rapid_outgoing(df)

        flagged_accounts = set(findings["account_id"].tolist())
        self.assertIn("B777", flagged_accounts)
        self.assertIn("B778", flagged_accounts)
        self.assertIn("B900", flagged_accounts)
        self.assertIn("B901", flagged_accounts)
        self.assertNotIn("N044", flagged_accounts)

        # Verify evidence timing values
        b777_row = findings[findings["account_id"] == "B777"].iloc[0]
        self.assertEqual(b777_row["incoming_transaction_id"], "TX0046")
        self.assertEqual(b777_row["outgoing_transaction_id"], "TX0047")
        self.assertAlmostEqual(float(b777_row["evidence"]), 2.0)

        b778_row = findings[findings["account_id"] == "B778"].iloc[0]
        self.assertEqual(b778_row["incoming_transaction_id"], "TX0048")
        self.assertEqual(b778_row["outgoing_transaction_id"], "TX0049")
        self.assertAlmostEqual(float(b778_row["evidence"]), 1.0)

        b900_row = findings[findings["account_id"] == "B900"].iloc[0]
        self.assertEqual(b900_row["incoming_transaction_id"], "TX0051")
        self.assertEqual(b900_row["outgoing_transaction_id"], "TX0052")
        self.assertAlmostEqual(float(b900_row["evidence"]), 2.0)

        b901_row = findings[findings["account_id"] == "B901"].iloc[0]
        self.assertEqual(b901_row["incoming_transaction_id"], "TX0092")
        self.assertEqual(b901_row["outgoing_transaction_id"], "TX0093")
        self.assertAlmostEqual(float(b901_row["evidence"]), 2.0)

    def test_rapid_outgoing_shuffled_rows_deterministic(self):
        """Findings must be identical when input CSV rows are shuffled."""
        tx_path = Path(__file__).resolve().parent.parent / "app" / "data" / "transactions.csv"
        df = pd.read_csv(tx_path)
        res1 = find_rapid_outgoing(df)
        res2 = find_rapid_outgoing(df.sample(frac=1, random_state=42))
        self.assertTrue(res1.equals(res2))

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

    def test_high_value_historical_baseline_anomaly(self):
        """Flag when amount >= 3.0x historical median with >= 5 prior transactions."""
        history = [
            {
                "transaction_id": f"TX{i:03d}",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": f"2026-10-01 10:0{i}:00",
                "amount": 1000,
            }
            for i in range(1, 6)  # 5 transactions, median = 1000
        ]
        current = [{
            "transaction_id": "TX006",
            "source_account": "A001",
            "target_account": "B001",
            "timestamp": "2026-10-01 10:06:00",
            "amount": 3000,  # exactly 3.0x median
        }]
        df = pd.DataFrame(history + current)
        result = find_high_value_transfers(df)
        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["transaction_ids"], "TX006")
        self.assertEqual(row["detection_type"], "historical_baseline_anomaly")
        self.assertEqual(row["history_count"], 5)
        self.assertAlmostEqual(row["baseline_median"], 1000.0)

    def test_high_value_normal_baseline_ignored(self):
        """Do not flag when amount < 3.0x historical median."""
        history = [
            {
                "transaction_id": f"TX{i:03d}",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": f"2026-10-01 10:0{i}:00",
                "amount": 1000,
            }
            for i in range(1, 6)  # 5 transactions, median = 1000
        ]
        current = [{
            "transaction_id": "TX006",
            "source_account": "A001",
            "target_account": "B001",
            "timestamp": "2026-10-01 10:06:00",
            "amount": 2999,  # less than 3.0x median
        }]
        df = pd.DataFrame(history + current)
        result = find_high_value_transfers(df)
        self.assertEqual(len(result), 0)

    def test_high_value_four_prior_transactions_uses_fallback(self):
        """With 4 prior transactions (< 5), fallback 50,000 threshold applies."""
        history = [
            {
                "transaction_id": f"TX{i:03d}",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": f"2026-10-01 10:0{i}:00",
                "amount": 1000,
            }
            for i in range(1, 5)  # only 4 transactions
        ]
        current = [{
            "transaction_id": "TX005",
            "source_account": "A001",
            "target_account": "B001",
            "timestamp": "2026-10-01 10:05:00",
            "amount": 10000,  # 10x median, but history < 5 and amount < 50000 fallback
        }]
        df = pd.DataFrame(history + current)
        result = find_high_value_transfers(df)
        self.assertEqual(len(result), 0, "Should use fixed fallback threshold when history < 5")

    def test_high_value_same_timestamp_and_no_future_leakage(self):
        """Historical baseline must be strictly earlier: exclude same-timestamp and future transactions."""
        rows = [
            {
                "transaction_id": "TX001",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": "2026-10-01 10:00:00",
                "amount": 1000,
            },
            {
                "transaction_id": "TX002",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": "2026-10-01 10:01:00",
                "amount": 1000,
            },
            {
                "transaction_id": "TX003",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": "2026-10-01 10:01:00",  # same timestamp as TX002
                "amount": 1000,
            },
            {
                "transaction_id": "TX004",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": "2026-10-01 10:02:00",
                "amount": 1000,
            },
            {
                "transaction_id": "TX005",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": "2026-10-01 10:03:00",
                "amount": 1000,
            },
            {
                "transaction_id": "TX006",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": "2026-10-01 10:04:00",
                "amount": 1000,
            },
            {
                "transaction_id": "TX007",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": "2026-10-01 10:05:00",
                "amount": 3000,  # evaluation target
            },
            {
                "transaction_id": "TX008",
                "source_account": "A001",
                "target_account": "B001",
                "timestamp": "2026-10-01 10:06:00",  # future transaction with enormous amount
                "amount": 500000,
            },
        ]
        df = pd.DataFrame(rows)
        result = find_high_value_transfers(df)

        # TX007 should be evaluated with 6 prior transactions (TX001..TX006)
        tx007_match = result[result["transaction_ids"] == "TX007"]
        self.assertEqual(len(tx007_match), 1)
        self.assertEqual(tx007_match.iloc[0]["history_count"], 6)
        # If TX008 leaked into TX007's baseline, median would be altered
        self.assertAlmostEqual(tx007_match.iloc[0]["baseline_median"], 1000.0)

    def test_high_value_demo_scenarios(self):
        """Verify A001 (TX0045 anomaly), N040 (TX0077 normal baseline), and B782 (TX0041/42 fallback)."""
        tx_path = Path(__file__).resolve().parent.parent / "app" / "data" / "transactions.csv"
        df = pd.read_csv(tx_path)
        findings = find_high_value_transfers(df)

        tx_ids = set(findings["transaction_ids"].tolist())
        # A001 TX0045 must be flagged as historical baseline anomaly
        self.assertIn("TX0045", tx_ids)
        tx0045_row = findings[findings["transaction_ids"] == "TX0045"].iloc[0]
        self.assertEqual(tx0045_row["account_id"], "A001")
        self.assertEqual(tx0045_row["detection_type"], "historical_baseline_anomaly")
        self.assertGreaterEqual(tx0045_row["history_count"], 12)
        self.assertEqual(tx0045_row["evidence"], 180000.0)

        # N040 TX0077 must NOT be flagged (normal 2,800 baseline)
        self.assertNotIn("TX0077", tx_ids)

        # B782 TX0041 and TX0042 must be flagged as fallback alerts
        self.assertIn("TX0041", tx_ids)
        self.assertIn("TX0042", tx_ids)
        tx0041_row = findings[findings["transaction_ids"] == "TX0041"].iloc[0]
        tx0042_row = findings[findings["transaction_ids"] == "TX0042"].iloc[0]
        self.assertEqual(tx0041_row["detection_type"], "fixed_threshold_fallback")
        self.assertEqual(tx0042_row["detection_type"], "fixed_threshold_fallback")
        self.assertEqual(tx0041_row["evidence"], 90000.0)
        self.assertEqual(tx0042_row["evidence"], 65000.0)

    def test_high_value_shuffled_rows_deterministic(self):
        """Findings must be identical when input CSV rows are shuffled."""
        tx_path = Path(__file__).resolve().parent.parent / "app" / "data" / "transactions.csv"
        df = pd.read_csv(tx_path)
        res1 = find_high_value_transfers(df)
        res2 = find_high_value_transfers(df.sample(frac=1, random_state=42))
        self.assertTrue(res1.equals(res2))

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