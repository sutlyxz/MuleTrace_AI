"""Tests for Risk Detection Rules against the Dynamic Simulation Dataset.

Verifies:
1. Rule 1 (Multiple Incoming): Flagged on mule account (5 senders within 10 min).
2. Rule 2 (Rapid Outgoing): Flagged on mule account (incoming then outgoing within 120s).
3. Rule 3 (High-Value Transfer):
   - Historical Baseline Anomaly: Flagged on baseline account (>= 3x median over 5 prior transfers).
   - Fixed Threshold Fallback: Flagged on fallback account (>= 50,000 fallback threshold).
4. Normal transactions do not trigger any false positives.
5. Multi-hop Money Tracing (AI Tool):
   - Confirms multi-hop is NOT a risk detection rule.
   - Confirms the AI money tracing tool can trace the logical path: Smurf -> Mule -> Relay -> Dest.
6. Multi-seed Validation Suite:
   - Evaluates at least 20 different seeds (25 seeds tested) for strict compliance with all constraints.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.backend.core.risk_rules import (
    find_high_value_transfers,
    find_multiple_incoming,
    find_rapid_outgoing,
)
from app.backend.core.tracing import find_paths
from app.backend.simulation.dataset import (
    TOTAL_BATCH_SIZE,
    generate_simulation_batch,
    validate_simulation_batch,
)


class TestSimulationRules(unittest.TestCase):
    """Test suite validating that dynamic simulation data triggers exactly the intended rules."""

    def setUp(self) -> None:
        self.seed = 42
        self.events = generate_simulation_batch(seed=self.seed)
        self.df = pd.DataFrame(self.events)
        self.df["timestamp"] = pd.to_datetime(self.df["timestamp"])
        self.df["amount"] = pd.to_numeric(self.df["amount"])
        self.baseline_acc = self.events[0]["source_account"]
        self.mule_acc = self.events[14]["target_account"]
        self.fallback_acc = self.events[19]["source_account"]

    def test_rule_1_multiple_incoming(self) -> None:
        """Verify Rule 1: Mule receives >= 5 incoming transfers from multiple accounts within 10m."""
        result_df = find_multiple_incoming(self.df, min_senders=2, min_transactions=5, window_minutes=10)
        self.assertFalse(result_df.empty, "Multiple incoming rule should have flagged at least one account")

        flagged_accounts = result_df["account_id"].tolist()
        self.assertIn(self.mule_acc, flagged_accounts)
        self.assertEqual(len(flagged_accounts), 1, "Only mule account should be flagged for multiple incoming")

        mule_row = result_df[result_df["account_id"] == self.mule_acc].iloc[0]
        self.assertGreaterEqual(int(mule_row["evidence"]), 5, "Evidence should reflect >= 5 distinct senders")
        self.assertIn("Received 5 incoming transactions", mule_row["reason"])

    def test_rule_2_rapid_outgoing(self) -> None:
        """Verify Rule 2: Mule transfers funds out within 2 minutes of receiving funds."""
        result_df = find_rapid_outgoing(self.df, window_minutes=2)
        self.assertFalse(result_df.empty, "Rapid outgoing rule should have flagged at least one account")

        flagged_accounts = result_df["account_id"].tolist()
        self.assertIn(self.mule_acc, flagged_accounts)
        self.assertEqual(len(flagged_accounts), 1, "Only mule account should be flagged for rapid outgoing")

        mule_row = result_df[result_df["account_id"] == self.mule_acc].iloc[0]
        self.assertLessEqual(float(mule_row["evidence"]), 2.0)
        self.assertIn("followed by outgoing", mule_row["reason"])

    def test_rule_3_high_value_historical_baseline_anomaly(self) -> None:
        """Verify Rule 3 Anomaly: Baseline account transfers >= 3x median when history >= 5."""
        result_df = find_high_value_transfers(self.df, threshold=50000, min_history=5, multiplier=3.0)
        self.assertFalse(result_df.empty)

        anomaly_rows = result_df[result_df["detection_type"] == "historical_baseline_anomaly"]
        self.assertEqual(len(anomaly_rows), 1)

        row = anomaly_rows.iloc[0]
        self.assertEqual(row["account_id"], self.baseline_acc)
        self.assertEqual(row["history_count"], 5)
        self.assertGreaterEqual(row["evidence"], row["threshold"])

    def test_rule_3_high_value_fixed_threshold_fallback(self) -> None:
        """Verify Rule 3 Fallback: Fallback account transfers >= 50,000 THB when history < 5."""
        result_df = find_high_value_transfers(self.df, threshold=50000, min_history=5, multiplier=3.0)
        fallback_rows = result_df[result_df["detection_type"] == "fixed_threshold_fallback"]
        self.assertEqual(len(fallback_rows), 1)

        row = fallback_rows.iloc[0]
        self.assertEqual(row["account_id"], self.fallback_acc)
        self.assertGreaterEqual(row["evidence"], 50000.0)
        self.assertLess(row["history_count"], 5)
        self.assertEqual(row["threshold"], 50000.0)

    def test_normal_transactions_do_not_trigger_false_positives(self) -> None:
        """Verify that routine normal accounts do not trigger any of the 3 rules."""
        m_df = find_multiple_incoming(self.df)
        r_df = find_rapid_outgoing(self.df)
        h_df = find_high_value_transfers(self.df)

        all_flagged = set(m_df["account_id"]) | set(r_df["account_id"]) | set(h_df["account_id"])
        expected_flagged = {self.mule_acc, self.baseline_acc, self.fallback_acc}
        self.assertEqual(all_flagged, expected_flagged)

    def test_multi_hop_is_tool_not_rule_and_path_exists(self) -> None:
        """Verify Multi-hop path exists for AI tool investigation without generating alerts."""
        # 1. Multi-hop does NOT generate any alert in the risk engine
        m_df = find_multiple_incoming(self.df)
        r_df = find_rapid_outgoing(self.df)
        h_df = find_high_value_transfers(self.df)

        all_rules = list(m_df["rule"]) + list(r_df["rule"]) + list(h_df["rule"])
        self.assertNotIn("multi_hop", all_rules)
        self.assertNotIn("money_trail", all_rules)

        # 2. But the AI path-finding tool CAN trace the connected trail:
        # e.g. smurf -> mule -> relay -> dest
        last_smurf = self.events[14]["source_account"]
        dest = self.events[17]["target_account"]
        paths = find_paths(self.df, start_account=last_smurf, end_account=dest, max_hops=4)
        self.assertIsNotNone(paths)
        self.assertGreater(len(paths), 0, f"AI tool should successfully discover money trail {last_smurf} -> {dest}")

    def test_twenty_different_seeds_validation_suite(self) -> None:
        """Verify across 25 different seeds that every batch satisfies all 11 prompt constraints."""
        seeds_to_test = [1, 7, 13, 21, 42, 55, 77, 99, 123, 200, 314, 456, 500, 618, 700, 777, 888, 999, 1024, 1337, 2026, 3000, 4040, 5050, 9999]
        self.assertGreaterEqual(len(seeds_to_test), 20)

        accounts_csv = Path(__file__).resolve().parent.parent / "app" / "data" / "accounts.csv"
        df_acc = pd.read_csv(accounts_csv)
        valid_accounts = set(df_acc["account_id"].astype(str))

        for seed in seeds_to_test:
            with self.subTest(seed=seed):
                events = generate_simulation_batch(seed=seed)

                # 1. Exactly 20 transactions
                self.assertEqual(len(events), 20, f"Seed {seed}: Expected exactly 20 transactions")

                # 2. Valid canonical schema and accounts
                is_valid, err = validate_simulation_batch(events)
                self.assertTrue(is_valid, f"Seed {seed}: Schema validation failed: {err}")

                for ev in events:
                    self.assertIn(ev["source_account"], valid_accounts, f"Seed {seed}: Invalid source account")
                    self.assertIn(ev["target_account"], valid_accounts, f"Seed {seed}: Invalid target account")

                # 3. Unique IDs
                tx_ids = [ev["transaction_id"] for ev in events]
                self.assertEqual(len(tx_ids), len(set(tx_ids)), f"Seed {seed}: Duplicate tx IDs")
                evt_ids = [ev["event_id"] for ev in events]
                self.assertEqual(len(evt_ids), len(set(evt_ids)), f"Seed {seed}: Duplicate event IDs")

                # 4. Chronologically valid timestamps
                ts_list = [datetime.strptime(ev["timestamp"], "%Y-%m-%d %H:%M:%S") for ev in events]
                for i in range(1, len(ts_list)):
                    self.assertLessEqual(ts_list[i - 1], ts_list[i], f"Seed {seed}: Out-of-order timestamp at {i}")

                # Build DataFrame for risk evaluation
                df_run = pd.DataFrame(events)
                df_run["timestamp"] = pd.to_datetime(df_run["timestamp"])
                df_run["amount"] = pd.to_numeric(df_run["amount"])

                # 5. Multiple Incoming detection (exactly 1 detection on mule account)
                m_df = find_multiple_incoming(df_run)
                self.assertEqual(len(m_df), 1, f"Seed {seed}: Expected 1 Multiple Incoming detection, got {len(m_df)}")
                mule_acc = m_df.iloc[0]["account_id"]

                # 6. Rapid Outgoing detection (exactly 1 detection on mule account)
                r_df = find_rapid_outgoing(df_run)
                self.assertEqual(len(r_df), 1, f"Seed {seed}: Expected 1 Rapid Outgoing detection, got {len(r_df)}")
                self.assertEqual(r_df.iloc[0]["account_id"], mule_acc, f"Seed {seed}: Rapid outgoing account mismatch")

                # 7. High-Value Median detection
                h_df = find_high_value_transfers(df_run)
                h_median = h_df[h_df["detection_type"] == "historical_baseline_anomaly"]
                self.assertEqual(len(h_median), 1, f"Seed {seed}: Expected 1 Median anomaly detection, got {len(h_median)}")

                # 8. High-Value Fallback detection
                h_fallback = h_df[h_df["detection_type"] == "fixed_threshold_fallback"]
                self.assertEqual(len(h_fallback), 1, f"Seed {seed}: Expected 1 Fallback detection, got {len(h_fallback)}")

                # 9. No unintended normal-traffic alerts
                baseline_acc = h_median.iloc[0]["account_id"]
                fallback_acc = h_fallback.iloc[0]["account_id"]
                all_flagged = set(m_df["account_id"]) | set(r_df["account_id"]) | set(h_df["account_id"])
                expected_flagged = {mule_acc, baseline_acc, fallback_acc}
                self.assertEqual(all_flagged, expected_flagged, f"Seed {seed}: Unexpected flagged accounts: {all_flagged - expected_flagged}")

                # 10. Multi-hop path compatibility with AI Tool
                smurf_last = events[14]["source_account"]
                dest = events[17]["target_account"]
                paths = find_paths(df_run, start_account=smurf_last, end_account=dest, max_hops=4)
                self.assertIsNotNone(paths, f"Seed {seed}: Paths is None")
                self.assertGreater(len(paths), 0, f"Seed {seed}: Expected multi-hop path {smurf_last} -> {dest}")

                # 11. Deterministic reproduction with same seed and base timestamp
                base_dt = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)
                batch_rep1 = generate_simulation_batch(seed=seed, base_time=base_dt)
                batch_rep2 = generate_simulation_batch(seed=seed, base_time=base_dt)
                for ev1, ev2 in zip(batch_rep1, batch_rep2):
                    self.assertEqual(ev1["source_account"], ev2["source_account"])
                    self.assertEqual(ev1["target_account"], ev2["target_account"])
                    self.assertEqual(ev1["amount"], ev2["amount"])
                    self.assertEqual(ev1["timestamp"], ev2["timestamp"])
                    self.assertEqual(ev1["scenario"], ev2["scenario"])
                    self.assertEqual(ev1["is_suspicious"], ev2["is_suspicious"])


if __name__ == "__main__":
    unittest.main()
