"""Integration tests against a REAL, DISPOSABLE PostgreSQL database.

Skipped unless TEST_DATABASE_URL is set and SQLAlchemy/Alembic are installed.
Safety guards: the database name must contain "test" and the URL must differ
from DATABASE_URL. The test DROPS and recreates all MuleTrace tables there
(alembic downgrade base -> upgrade head). It never touches DATABASE_URL.

    set TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/muletrace_test
    python -m unittest tests.test_db_postgres -v
"""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
import importlib.util
import json
import os
import unittest

from app.backend.db import config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_URL_RAW = os.environ.get(config.TEST_DATABASE_URL_ENV, "").strip()
HAVE_DEPS = all(importlib.util.find_spec(m) for m in ("sqlalchemy", "alembic", "psycopg"))


def _skip_reason() -> str | None:
    if not HAVE_DEPS:
        return "sqlalchemy/alembic/psycopg not installed"
    if not TEST_URL_RAW:
        return "TEST_DATABASE_URL not set"
    from sqlalchemy.engine import make_url
    url = make_url(config.normalize_database_url(TEST_URL_RAW))
    if "test" not in (url.database or "").lower():
        return "refusing: TEST_DATABASE_URL database name must contain 'test'"
    main = os.environ.get(config.DATABASE_URL_ENV, "").strip()
    if main and config.normalize_database_url(main) == config.normalize_database_url(TEST_URL_RAW):
        return "refusing: TEST_DATABASE_URL must differ from DATABASE_URL"
    return None


SKIP_REASON = _skip_reason()


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config

        from app.backend.db.seed import apply_plan, build_plan
        from app.backend.db.session import get_engine

        cls.url = config.get_database_url(config.TEST_DATABASE_URL_ENV)
        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        cfg.cmd_opts = Namespace(x=[f"url_env={config.TEST_DATABASE_URL_ENV}"])
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")

        cls.engine = get_engine(cls.url)
        cls.first_seed = apply_plan(build_plan(), cls.engine)
        cls.pg_env = {config.BACKEND_ENV: "postgres", config.DATABASE_URL_ENV: cls.url}

    @classmethod
    def tearDownClass(cls):
        from app.backend.db.session import dispose_engines
        dispose_engines()

    def setUp(self):
        from sqlalchemy import text
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM alerts"))

    # ---------- schema & seed ----------

    def test_schema_tables_and_indexes(self):
        from sqlalchemy import inspect
        insp = inspect(self.engine)
        tables = set(insp.get_table_names())
        self.assertTrue({"accounts", "transactions", "cases", "case_accounts",
                         "alerts", "alert_transactions", "alembic_version"} <= tables)
        tx_indexes = {ix["name"] for ix in insp.get_indexes("transactions")}
        self.assertTrue({"ix_transactions_source_ts", "ix_transactions_target_ts",
                         "ix_transactions_ts_id"} <= tx_indexes)
        self.assertEqual(insp.get_pk_constraint("case_accounts")["constrained_columns"],
                         ["case_id", "account_id"])

    def test_first_seed_imported_every_csv_row(self):
        inserted = self.first_seed["inserted"]
        self.assertEqual(inserted["transactions"], 52)
        self.assertEqual(inserted["case_accounts"], 4)
        self.assertEqual(inserted["cases"], 2)
        self.assertEqual(self.first_seed["skipped_rows"], [])

    def test_seed_is_idempotent(self):
        from app.backend.db.seed import apply_plan, build_plan
        report = apply_plan(build_plan(), self.engine)
        self.assertEqual(set(report["inserted"].values()), {0})
        self.assertEqual(report["conflicts"], [])

    def test_dry_run_writes_nothing(self):
        from app.backend.db.repositories import TransactionRepository
        from app.backend.db.seed import apply_plan, build_plan
        before = TransactionRepository(self.engine).count()
        report = apply_plan(build_plan(), self.engine, dry_run=True)
        self.assertIn("would_insert", report)
        self.assertEqual(TransactionRepository(self.engine).count(), before)

    def test_foreign_key_rejects_unknown_account(self):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO transactions (transaction_id, timestamp, source_account, "
                    "target_account, amount) VALUES ('TXFK', '2026-10-01 00:00', 'NOPE', 'B782', 1)"
                ))

    def test_amount_and_timestamp_round_trip(self):
        from app.backend.db.repositories import TransactionRepository
        df = TransactionRepository(self.engine).as_dataframe()
        row = df[df["transaction_id"] == "TX0041"].iloc[0]
        self.assertEqual(str(df["amount"].dtype), "int64")
        self.assertEqual(int(row["amount"]), 90000)
        self.assertEqual(str(row["timestamp"]), "2026-10-02 01:20:00")

    # ---------- engine parity ----------

    def test_tool_outputs_match_csv_mode(self):
        from app.backend import engine
        calls = {
            "detect_risk": lambda: engine.detect_risk(),
            "get_account_profile": lambda: engine.get_account_profile("B782"),
            "get_transaction_history": lambda: engine.get_transaction_history("B782"),
            "expand_network": lambda: engine.expand_network("B782", 3),
            "trace_money": lambda: engine.trace_money("A001", "E450", 4),
            "get_evidence": lambda: engine.get_evidence(["TX0041", "TX0046", "TX9999"]),
            "search_previous_cases": lambda: engine.search_previous_cases("B782"),
            "find_cross_case_links": lambda: engine.find_cross_case_links(),
            "score_investigation": lambda: engine.score_investigation(case_id="CASE001"),
        }
        with patch.dict(os.environ, {config.BACKEND_ENV: "csv"}):
            expected = {name: fn() for name, fn in calls.items()}
        with patch.dict(os.environ, self.pg_env):
            actual = {name: fn() for name, fn in calls.items()}
        for name in calls:
            with self.subTest(tool=name):
                self.assertEqual(json.dumps(expected[name], sort_keys=True),
                                 json.dumps(actual[name], sort_keys=True))

    # ---------- alerts ----------

    def test_scan_creates_then_dedupes_alerts(self):
        from app.backend import engine
        from app.backend.services import alert_service
        from sqlalchemy import text

        with patch.dict(os.environ, {config.BACKEND_ENV: "csv"}):
            expected_ids = [alert_service.alert_id(f) for f in engine.detect_risk()["findings"]]
        with patch.dict(os.environ, self.pg_env):
            first = alert_service.scan_risk_alerts()
            second = alert_service.scan_risk_alerts()
            loaded = alert_service.load_alerts()

        self.assertEqual([a["alert_id"] for a in first["new_alerts"]], expected_ids)
        self.assertEqual(second["new_alert_count"], 0)
        self.assertEqual([a["alert_id"] for a in loaded], expected_ids)  # append order kept
        self.assertTrue(all(a["created_at"].endswith("+00:00") for a in loaded))
        with self.engine.connect() as conn:
            links = conn.execute(text("SELECT count(*) FROM alert_transactions")).scalar_one()
        self.assertEqual(links, sum(len(a["transaction_ids"]) for a in loaded))

    def test_alert_round_trip_preserves_json_shape(self):
        from app.backend.db.repositories import AlertRepository
        original = {
            "alert_id": "ALT-0000000000000001",
            "created_at": "2026-10-21T15:29:22.433977+00:00",
            "status": "new",
            "source": "rule_engine",
            "account_id": "B777",
            "rule": "rapid_outgoing",
            "transaction_ids": ["TX0046", "TX0047"],
            "reason": "Incoming TX0046 (12000) followed by outgoing TX0047 (11500) after 4.0 minutes",
            "evidence": 4.0,
            "finding": {"account_id": "B777", "evidence": 4.0, "transaction_ids": None},
        }
        repo = AlertRepository(self.engine)
        self.assertEqual(len(repo.insert_many([original])), 1)
        self.assertEqual(repo.insert_many([original]), [])  # PK dedupe
        self.assertEqual(repo.list_alerts(), [original])

    def test_seed_imports_existing_alerts_json(self):
        from app.backend.db.repositories import AlertRepository
        from app.backend.db.seed import apply_plan, build_plan
        alerts_file = PROJECT_ROOT / "app" / "data" / "alerts.json"
        if not alerts_file.exists():
            self.skipTest("data/alerts.json not present")
        original = json.loads(alerts_file.read_text(encoding="utf-8"))
        report = apply_plan(build_plan(with_alerts=True), self.engine)
        self.assertEqual(report["inserted"]["alerts"], len(original))
        self.assertEqual(AlertRepository(self.engine).list_alerts(), original)


if __name__ == "__main__":
    unittest.main()
