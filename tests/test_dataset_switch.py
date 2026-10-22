"""Tests for canonical dataset integrity, chronological ordering, and configuration.

The project operates on a single canonical dataset architecture:
- data/transactions.csv (105 transactions)
- data/accounts.csv (102 accounts)
- data/case_accounts.csv (preserved)
- data/alerts.json (canonical alert store)

Run: python -m unittest tests/test_dataset_switch.py -v
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch
import pandas as pd

from app.backend.db.config import (
    DATASET_ENV,
    DEFAULT_DATASET,
    dataset_name,
    get_transactions_path,
    get_accounts_path,
    get_alerts_path,
)
from app.backend import engine


class TestCanonicalDataset(unittest.TestCase):
    """Test canonical dataset configuration, row counts, references, and sorting."""

    def test_canonical_paths_resolution(self) -> None:
        """Paths resolve to canonical files in data/ regardless of environment settings."""
        tx_path = get_transactions_path()
        acc_path = get_accounts_path()
        alerts_path = get_alerts_path()

        self.assertEqual(tx_path.name, "transactions.csv")
        self.assertEqual(acc_path.name, "accounts.csv")
        self.assertEqual(alerts_path.name, "alerts.json")
        self.assertTrue(tx_path.exists())
        self.assertTrue(acc_path.exists())
        self.assertTrue(alerts_path.exists())

    def test_backward_compatible_dataset_name(self) -> None:
        """dataset_name() returns 'canonical' without requiring MULETRACE_DATASET."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DATASET_ENV, None)
            self.assertEqual(dataset_name(), DEFAULT_DATASET)
            self.assertEqual(dataset_name(), "canonical")

        # Backward compatibility if MULETRACE_DATASET is set in shell/environment
        with patch.dict(os.environ, {DATASET_ENV: "demo"}):
            self.assertEqual(dataset_name(), "canonical")
            self.assertEqual(get_transactions_path().name, "transactions.csv")

    def test_canonical_dataset_counts_and_referential_integrity(self) -> None:
        """Canonical dataset contains exactly 105 transactions and 102 accounts."""
        df_tx = engine.load_transactions()
        df_acc = engine.load_accounts()
        df_cases = engine.load_case_accounts()

        self.assertEqual(len(df_tx), 105)
        self.assertEqual(len(df_acc), 102)

        # Unique IDs
        self.assertEqual(df_tx["transaction_id"].nunique(), 105)
        self.assertEqual(df_acc["account_id"].nunique(), 102)

        # All transaction accounts must exist in accounts
        tx_accounts = set(df_tx["source_account"]).union(set(df_tx["target_account"]))
        known_accounts = set(df_acc["account_id"])
        self.assertTrue(tx_accounts.issubset(known_accounts))

        # All case accounts must exist in accounts
        case_accounts = set(df_cases["account_id"])
        self.assertTrue(case_accounts.issubset(known_accounts))

    def test_chronological_sorting_guarantee(self) -> None:
        """Transactions must be strictly sorted by timestamp and transaction_id."""
        df = engine.load_transactions()

        # Timestamps must be non-decreasing
        timestamps = df["timestamp"].tolist()
        for i in range(len(timestamps) - 1):
            self.assertLessEqual(
                timestamps[i],
                timestamps[i + 1],
                f"Timestamps out of order at index {i}: {timestamps[i]} > {timestamps[i+1]}"
            )

        # Verify raw CSV out-of-order records (e.g. TX0053, TX0065 with 2026-09-20)
        # are sorted to the front rather than remaining in row-index order.
        first_rows = df.head(2)
        first_ids = set(first_rows["transaction_id"].tolist())
        self.assertIn("TX0053", first_ids)
        self.assertIn("TX0065", first_ids)

    def test_health_check_reports_canonical_dataset(self) -> None:
        """health_check() confirms dataset is canonical and files are accessible."""
        health = engine.health_check()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["dataset"], "canonical")
        self.assertTrue(health["transactions_file_exists"])
        self.assertTrue(health["case_accounts_file_exists"])


if __name__ == "__main__":
    unittest.main()
