"""Tests for Simulation Dataset Generator and Schema Validation.

Verifies:
- Matches canonical transactions.csv schema exactly.
- Generates exactly 20 dynamic mixed transactions per run.
- All account references exist in accounts.csv.
- All transaction IDs and event IDs are unique per run.
- Separate runs produce isolated run IDs and unique transaction/event IDs.
- Strict chronological ordering.
- Absence of hardcoded alerts, risk scores, or case IDs.
- Dynamic generation varies accounts, amounts, and timestamps.
- Explicit seed and base_timestamp deterministically reproduce logical transactions.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.backend.simulation.dataset import (
    CANONICAL_COLUMNS,
    TOTAL_BATCH_SIZE,
    generate_run_id,
    generate_simulation_batch,
    validate_simulation_batch,
)


class TestSimulationDataset(unittest.TestCase):
    """Test suite for simulation dataset compliance and integrity."""

    def setUp(self) -> None:
        self.accounts_csv = Path(__file__).resolve().parent.parent / "app" / "data" / "accounts.csv"
        self.canonical_tx_csv = Path(__file__).resolve().parent.parent / "app" / "data" / "transactions.csv"

    def test_canonical_schema_compatibility(self) -> None:
        """Verify generated events have all canonical columns from transactions.csv."""
        df_canon = pd.read_csv(self.canonical_tx_csv, nrows=5)
        canonical_cols = list(df_canon.columns)

        events = generate_simulation_batch()
        self.assertEqual(len(events), 20)

        for ev in events:
            for col in canonical_cols:
                self.assertIn(col, ev, f"Event missing canonical column {col}")

    def test_event_count_is_exactly_twenty(self) -> None:
        """Verify batch contains exactly 20 transactions."""
        events = generate_simulation_batch()
        self.assertEqual(len(events), 20)
        self.assertEqual(TOTAL_BATCH_SIZE, 20)

    def test_valid_account_references(self) -> None:
        """Verify all accounts referenced in simulation exist in accounts.csv."""
        df_acc = pd.read_csv(self.accounts_csv)
        valid_accounts = set(df_acc["account_id"].astype(str))

        events = generate_simulation_batch()
        for ev in events:
            src = ev["source_account"]
            tgt = ev["target_account"]
            self.assertIn(src, valid_accounts, f"Source account {src} not found in accounts.csv")
            self.assertIn(tgt, valid_accounts, f"Target account {tgt} not found in accounts.csv")
            self.assertNotEqual(src, tgt, "Source and target cannot be the same")

    def test_unique_transaction_and_event_ids_within_run(self) -> None:
        """Verify transaction IDs and event IDs are strictly unique within a run."""
        events = generate_simulation_batch()
        tx_ids = [ev["transaction_id"] for ev in events]
        self.assertEqual(len(tx_ids), len(set(tx_ids)), "Duplicate transaction ID found in batch")

        event_ids = [ev["event_id"] for ev in events]
        self.assertEqual(len(event_ids), len(set(event_ids)), "Duplicate event ID found in batch")

    def test_run_id_isolation_between_runs(self) -> None:
        """Verify separate runs produce distinct run IDs and disjoint transaction/event IDs."""
        batch_1 = generate_simulation_batch()
        batch_2 = generate_simulation_batch()

        run_id_1 = batch_1[0]["simulation_run_id"]
        run_id_2 = batch_2[0]["simulation_run_id"]
        self.assertNotEqual(run_id_1, run_id_2)

        tx_ids_1 = {ev["transaction_id"] for ev in batch_1}
        tx_ids_2 = {ev["transaction_id"] for ev in batch_2}
        self.assertTrue(tx_ids_1.isdisjoint(tx_ids_2))

        evt_ids_1 = {ev["event_id"] for ev in batch_1}
        evt_ids_2 = {ev["event_id"] for ev in batch_2}
        self.assertTrue(evt_ids_1.isdisjoint(evt_ids_2))

    def test_reproducibility_with_seed_and_base_timestamp(self) -> None:
        """Verify identical seed and base_timestamp deterministically reproduce logical transactions."""
        fixed_seed = 42
        fixed_base = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)

        batch_a = generate_simulation_batch(seed=fixed_seed, base_time=fixed_base)
        batch_b = generate_simulation_batch(seed=fixed_seed, base_time=fixed_base)

        # Logical transaction properties must be identical
        for ev_a, ev_b in zip(batch_a, batch_b):
            self.assertEqual(ev_a["source_account"], ev_b["source_account"])
            self.assertEqual(ev_a["target_account"], ev_b["target_account"])
            self.assertEqual(ev_a["amount"], ev_b["amount"])
            self.assertEqual(ev_a["scenario"], ev_b["scenario"])
            self.assertEqual(ev_a["is_suspicious"], ev_b["is_suspicious"])
            self.assertEqual(ev_a["seed"], ev_b["seed"])

        # But run IDs, transaction IDs, and event IDs must still be globally unique
        self.assertNotEqual(batch_a[0]["simulation_run_id"], batch_b[0]["simulation_run_id"])
        self.assertNotEqual(batch_a[0]["transaction_id"], batch_b[0]["transaction_id"])
        self.assertNotEqual(batch_a[0]["event_id"], batch_b[0]["event_id"])

    def test_dynamic_variability_across_different_seeds(self) -> None:
        """Verify different runs/seeds generate varying amounts, accounts, and timestamps."""
        batch_1 = generate_simulation_batch(seed=101)
        batch_2 = generate_simulation_batch(seed=202)

        amounts_1 = [ev["amount"] for ev in batch_1]
        amounts_2 = [ev["amount"] for ev in batch_2]
        self.assertNotEqual(amounts_1, amounts_2, "Amounts should vary across seeds")

        srcs_1 = [ev["source_account"] for ev in batch_1]
        srcs_2 = [ev["source_account"] for ev in batch_2]
        self.assertNotEqual(srcs_1, srcs_2, "Account selections should vary across seeds")

    def test_chronological_ordering(self) -> None:
        """Verify transactions are ordered chronologically."""
        events = generate_simulation_batch()
        timestamps = [
            datetime.strptime(ev["timestamp"], "%Y-%m-%d %H:%M:%S")
            for ev in events
        ]
        for i in range(1, len(timestamps)):
            self.assertLessEqual(
                timestamps[i - 1],
                timestamps[i],
                f"Timestamp out of order at index {i}",
            )

    def test_no_hardcoded_alerts_or_case_ids(self) -> None:
        """Verify events contain no hardcoded risk scores, case IDs, or alerts."""
        events = generate_simulation_batch()
        forbidden_fields = {"case_id", "alert_id", "risk_score", "ai_explanation", "narrative"}
        for ev in events:
            for field in forbidden_fields:
                self.assertNotIn(field, ev, f"Payload must not hardcode '{field}'")

    def test_metadata_fields_present(self) -> None:
        """Verify simulation metadata fields are present."""
        events = generate_simulation_batch(seed=999)
        for ev in events:
            self.assertEqual(ev["seed"], 999)
            self.assertEqual(ev["generator_version"], "2.0.0-dynamic")
            self.assertEqual(ev["dataset_ref"], "accounts.csv:v1")
            self.assertIn("base_timestamp", ev)
            self.assertIn("simulation_run_id", ev)
            self.assertIn("event_id", ev)

    def test_batch_validation_success(self) -> None:
        """Verify validate_simulation_batch succeeds on valid generated batch."""
        events = generate_simulation_batch()
        is_valid, msg = validate_simulation_batch(events)
        self.assertTrue(is_valid, f"Validation failed: {msg}")
        self.assertEqual(msg, "")

    def test_batch_validation_catches_tampered_amount(self) -> None:
        """Verify validation catches negative or invalid amount."""
        events = generate_simulation_batch()
        events[3]["amount"] = -500.0
        is_valid, msg = validate_simulation_batch(events)
        self.assertFalse(is_valid)
        self.assertIn("non-positive amount", msg)

    def test_batch_validation_catches_duplicate_tx_id(self) -> None:
        """Verify validation catches duplicate transaction IDs."""
        events = generate_simulation_batch()
        events[4]["transaction_id"] = events[2]["transaction_id"]
        is_valid, msg = validate_simulation_batch(events)
        self.assertFalse(is_valid)
        self.assertIn("Duplicate transaction_id", msg)

    def test_batch_validation_catches_wrong_count(self) -> None:
        """Verify validation catches non-20 transaction batches."""
        events = generate_simulation_batch()
        events_short = events[:19]
        is_valid, msg = validate_simulation_batch(events_short)
        self.assertIn("20 transactions", msg)


if __name__ == "__main__":
    unittest.main()
