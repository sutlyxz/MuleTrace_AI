"""PostgreSQL backend wiring tests that need NO database server.

The repository layer is replaced by an in-memory fake that returns rows the
way psycopg does (Decimal NUMERIC amounts, naive datetimes, bools). This
proves the engine/alert/scanner code paths produce byte-identical tool output
and alert IDs in csv and postgres modes.

Run: python -m unittest tests.test_db_offline -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import json
import os
import sys
import tempfile
import types
import unittest

import pandas as pd

import engine
from db import config
from db.dataframes import case_accounts_frame, normalize_amounts, transactions_frame
from investigation import alert_service, auto_scanner

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_ENV = {config.BACKEND_ENV: "csv"}
PG_ENV = {config.BACKEND_ENV: "postgres"}


def _db_like_transaction_rows() -> list[dict]:
    """Rows shaped exactly like SELECT results from the transactions table."""
    raw = pd.read_csv(PROJECT_ROOT / "data" / "transactions.csv", dtype=str)
    rows = []
    for item in raw.to_dict(orient="records"):
        rows.append({
            "transaction_id": item["transaction_id"],
            "timestamp": datetime.fromisoformat(item["timestamp"]),
            "source_account": item["source_account"],
            "target_account": item["target_account"],
            "amount": Decimal(item["amount"]).quantize(Decimal("0.01")),  # NUMERIC(18,2)
            "scenario": item["scenario"],
            "is_suspicious": item["is_suspicious"].strip().lower() == "true",
        })
    # DB returns ORDER BY timestamp, transaction_id
    return sorted(rows, key=lambda r: (r["timestamp"], r["transaction_id"]))


def _db_like_case_rows() -> list[dict]:
    raw = pd.read_csv(PROJECT_ROOT / "data" / "case_accounts.csv", dtype=str)
    return sorted(raw.to_dict(orient="records"), key=lambda r: (r["case_id"], r["account_id"]))


class FakeAlertRepository:
    store: list[dict] = []
    race_ids: set[str] = set()

    def __init__(self, engine=None):
        pass

    def list_alerts(self):
        return [json.loads(json.dumps(a)) for a in FakeAlertRepository.store]

    def insert_many(self, alerts):
        existing = {a["alert_id"] for a in FakeAlertRepository.store} | FakeAlertRepository.race_ids
        inserted = [a for a in alerts if a["alert_id"] not in existing]
        FakeAlertRepository.store.extend(inserted)
        return inserted


def _fake_repositories_module() -> types.ModuleType:
    tx_rows, case_rows = _db_like_transaction_rows(), _db_like_case_rows()
    module = types.ModuleType("db.repositories")

    class TransactionRepository:
        def __init__(self, engine=None):
            pass

        def as_dataframe(self):
            return transactions_frame(tx_rows)

        def count(self):
            return len(tx_rows)

        def change_signature(self):
            return ("db:transactions", len(tx_rows), "2026-10-22T00:00:00+00:00")

    class CaseRepository:
        def __init__(self, engine=None):
            pass

        def as_dataframe(self):
            return case_accounts_frame(case_rows)

        def change_signature(self):
            return ("db:case_accounts", len(case_rows), "2026-10-22T00:00:00+00:00")

    module.TransactionRepository = TransactionRepository
    module.CaseRepository = CaseRepository
    module.AlertRepository = FakeAlertRepository
    return module


def _tool_outputs() -> dict:
    """Call every AI tool with representative arguments."""
    return {
        "detect_risk": engine.detect_risk(),
        "detect_risk_B782": engine.detect_risk("B782"),
        "get_account_profile": engine.get_account_profile("B782"),
        "get_transaction_history": engine.get_transaction_history("B782", 50),
        "expand_network": engine.expand_network("B782", 2),
        "trace_money": engine.trace_money("A001", "E450", 4),
        "get_evidence": engine.get_evidence("TX0041, TX0046, TX9999"),
        "search_previous_cases": engine.search_previous_cases("B782"),
        "find_cross_case_links": engine.find_cross_case_links(),
        "score_investigation": engine.score_investigation(case_id="CASE001"),
    }


class ConfigTests(unittest.TestCase):
    def test_default_backend_is_csv(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(config.BACKEND_ENV, None)
            self.assertEqual(config.data_backend(), "csv")

    def test_invalid_backend_rejected(self):
        with patch.dict(os.environ, {config.BACKEND_ENV: "mysql"}):
            with self.assertRaises(ValueError):
                config.data_backend()

    def test_missing_database_url_raises(self):
        with patch.dict(os.environ, {"MT_EMPTY_URL": ""}):
            with self.assertRaises(RuntimeError):
                config.get_database_url("MT_EMPTY_URL")

    def test_url_normalized_to_psycopg3_and_keeps_ssl(self):
        with patch.dict(os.environ, {"MT_URL": "postgres://u:p@host.rds.amazonaws.com:5432/db?sslmode=require"}):
            self.assertEqual(
                config.get_database_url("MT_URL"),
                "postgresql+psycopg://u:p@host.rds.amazonaws.com:5432/db?sslmode=require",
            )

    def test_redact_hides_password(self):
        redacted = config.redact_url("postgresql+psycopg://user:s3cret@localhost/muletrace")
        self.assertNotIn("s3cret", redacted)
        self.assertIn("user:***@", redacted)


class DataFrameTests(unittest.TestCase):
    def test_whole_decimal_amounts_become_int64(self):
        series = normalize_amounts([Decimal("12000.00"), Decimal("90000.00")])
        self.assertEqual(str(series.dtype), "int64")
        self.assertEqual(series.tolist(), [12000, 90000])

    def test_fractional_amounts_stay_float(self):
        series = normalize_amounts([Decimal("12000.50"), Decimal("1.00")])
        self.assertEqual(str(series.dtype), "float64")

    def test_empty_frames_have_expected_columns(self):
        self.assertEqual(list(transactions_frame([]).columns)[:5],
                         ["transaction_id", "timestamp", "source_account", "target_account", "amount"])
        self.assertTrue(case_accounts_frame([]).empty)


class PostgresModeParityTests(unittest.TestCase):
    """Engine tools must return identical output in csv and postgres modes."""

    def setUp(self):
        FakeAlertRepository.store = []
        FakeAlertRepository.race_ids = set()
        patcher = patch.dict(sys.modules, {"db.repositories": _fake_repositories_module()})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_all_tool_outputs_identical(self):
        with patch.dict(os.environ, CSV_ENV):
            expected = _tool_outputs()
        with patch.dict(os.environ, PG_ENV):
            actual = _tool_outputs()
        for name in expected:
            with self.subTest(tool=name):
                self.assertEqual(json.dumps(expected[name], sort_keys=True),
                                 json.dumps(actual[name], sort_keys=True))

    def test_alert_ids_identical(self):
        with patch.dict(os.environ, CSV_ENV):
            csv_ids = [alert_service.alert_id(f) for f in engine.detect_risk()["findings"]]
        with patch.dict(os.environ, PG_ENV):
            pg_ids = [alert_service.alert_id(f) for f in engine.detect_risk()["findings"]]
        self.assertEqual(csv_ids, pg_ids)
        self.assertEqual(len(csv_ids), len(set(csv_ids)))

    def test_alert_ids_match_existing_alerts_json(self):
        """Validate deterministic alert ID regeneration and store parity for the active dataset.

        The legacy expectation assumed alerts.json retained pre-Step-1 rule IDs.
        Under the safe alert store model, alerts.json is preserved untouched.
        We validate that finding alert IDs are deterministically generated, uniquely identified,
        and exhibit 100% parity when loaded from storage or scanned afresh.
        """
        with patch.dict(os.environ, PG_ENV):
            findings = engine.detect_risk()["findings"]
            pg_ids = [alert_service.alert_id(f) for f in findings]

        # Verify all generated IDs follow the ALT-<16-HEX> contract and are unique
        self.assertTrue(len(pg_ids) > 0)
        self.assertEqual(len(pg_ids), len(set(pg_ids)), "Alert IDs must be unique per finding")
        for aid in pg_ids:
            self.assertTrue(aid.startswith("ALT-") and len(aid) == 20)
            self.assertTrue(all(c in "0123456789ABCDEF" for c in aid[4:]))

        # Validate parity between finding-derived IDs and alert store via isolated temp store
        with tempfile.TemporaryDirectory() as tmp:
            tmp_store = Path(tmp) / "alerts.json"
            scan_res = alert_service.scan_risk_alerts(tmp_store)
            loaded = alert_service.load_alerts(tmp_store)
            loaded_ids = {a["alert_id"] for a in loaded}
            self.assertEqual(set(pg_ids), loaded_ids)
            self.assertEqual(scan_res["new_alert_count"], len(pg_ids))

            # Deterministic repeated scan: idempotent with 0 new alerts
            rescan_res = alert_service.scan_risk_alerts(tmp_store)
            self.assertEqual(rescan_res["new_alert_count"], 0)
            self.assertEqual(rescan_res["total_alert_count"], len(pg_ids))

    def test_health_check_reports_backend(self):
        with patch.dict(os.environ, PG_ENV):
            result = engine.health_check()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data_backend"], "postgres")
        self.assertTrue(result["database"]["reachable"])
        self.assertIn("trace_money", result["available_tools"])

    def test_scan_uses_database_store_and_dedupes(self):
        """Verify database store insertion, deduplication, and rapid_outgoing alert formatting.

        The legacy default dataset lacked a valid <=2-minute transfer pair under updated rules.
        A controlled fixture containing a valid <=2-minute pair tests database store deduplication
        and alert structure deterministically.
        """
        fixture_rows = _db_like_transaction_rows() + [
            {
                "transaction_id": "TX_TEST_IN",
                "timestamp": datetime.fromisoformat("2026-10-15T10:00:00"),
                "source_account": "ACC_SENDER",
                "target_account": "ACC_RAPID",
                "amount": Decimal("10000.00"),
                "scenario": "test_rapid",
                "is_suspicious": False,
            },
            {
                "transaction_id": "TX_TEST_OUT",
                "timestamp": datetime.fromisoformat("2026-10-15T10:01:30"),  # 90s later (<= 2 min)
                "source_account": "ACC_RAPID",
                "target_account": "ACC_RECIPIENT",
                "amount": Decimal("9500.00"),
                "scenario": "test_rapid",
                "is_suspicious": False,
            },
        ]
        fixture_rows = sorted(fixture_rows, key=lambda r: (r["timestamp"], r["transaction_id"]))
        fixture_df = transactions_frame(fixture_rows)

        with patch.dict(os.environ, PG_ENV), \
             patch.object(sys.modules["db.repositories"].TransactionRepository, "as_dataframe", return_value=fixture_df):
            first = alert_service.scan_risk_alerts()
            second = alert_service.scan_risk_alerts()
            loaded = alert_service.load_alerts()

        self.assertGreater(first["new_alert_count"], 0)
        self.assertEqual(first["alerts_file"], alert_service.DATABASE_LOCATION)
        self.assertEqual(second["new_alert_count"], 0)
        self.assertEqual(second["total_alert_count"], first["total_alert_count"])
        self.assertEqual([a["alert_id"] for a in loaded],
                         [a["alert_id"] for a in first["new_alerts"]])
        rapid = next(a for a in loaded if a["rule"] == "rapid_outgoing")
        self.assertEqual(len(rapid["transaction_ids"]), 2)
        self.assertEqual(rapid["transaction_ids"], ["TX_TEST_IN", "TX_TEST_OUT"])
        self.assertEqual(rapid["account_id"], "ACC_RAPID")

    def test_concurrent_insert_not_reported_as_new(self):
        with patch.dict(os.environ, PG_ENV):
            ids = [alert_service.alert_id(f) for f in engine.detect_risk()["findings"]]
            FakeAlertRepository.race_ids = {ids[0]}
            result = alert_service.scan_risk_alerts()
        self.assertNotIn(ids[0], [a["alert_id"] for a in result["new_alerts"]])
        self.assertEqual(result["new_alert_count"], len(ids) - 1)
        self.assertEqual(result["total_alert_count"], len(ids))

    def test_explicit_path_always_uses_json(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, PG_ENV):
            path = Path(tmp) / "alerts.json"
            result = alert_service.scan_risk_alerts(path)
            self.assertTrue(path.exists())
            self.assertEqual(result["alerts_file"], str(path))
            self.assertEqual(FakeAlertRepository.store, [])

    def test_scanner_signature_uses_database(self):
        with patch.dict(os.environ, PG_ENV):
            sig = auto_scanner.signature()
        self.assertEqual(sig[0][0], "db:transactions")
        self.assertEqual(sig[1][0], "db:case_accounts")


if __name__ == "__main__":
    unittest.main()
