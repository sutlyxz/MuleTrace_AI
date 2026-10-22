"""Focused unit tests for canonical alert store, isolation, schema, and deduplication.

Tests:
1. Canonical alert path resolution (data/alerts.json across all configurations).
2. Explicit path parameter overrides default configuration.
3. Clean initialization: canonical data/alerts.json is cleanly initialized as an empty list.
4. Isolated scan execution: scans can target temporary stores without mutating canonical files.
5. Repeated-scan idempotency: re-running scans produces 0 new alerts without duplicates.
6. Schema integrity and deterministic alert ID generation.
7. Canonical data/alerts.json remains protected from mutation during temporary test scans.

Run: python -m unittest tests/test_alert_separation.py -v
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import json
import os
import tempfile
import unittest

from app.backend.db.config import (
    DATASET_ENV,
    PROJECT_ROOT,
    get_alerts_path,
)
from app.backend.services import alert_service


class TestCanonicalAlertStore(unittest.TestCase):

    def setUp(self):
        self.canonical_alerts = PROJECT_ROOT / "app" / "data" / "alerts.json"

    def test_canonical_alerts_path_resolution(self):
        """Alert path resolves to canonical data/alerts.json regardless of environment settings."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DATASET_ENV, None)
            self.assertEqual(get_alerts_path(), self.canonical_alerts)
            self.assertEqual(alert_service._resolve_alert_path(), self.canonical_alerts)

        with patch.dict(os.environ, {DATASET_ENV: "default"}):
            self.assertEqual(get_alerts_path(), self.canonical_alerts)
            self.assertEqual(alert_service._resolve_alert_path(), self.canonical_alerts)

        with patch.dict(os.environ, {DATASET_ENV: "demo"}):
            self.assertEqual(get_alerts_path(), self.canonical_alerts)
            self.assertEqual(alert_service._resolve_alert_path(), self.canonical_alerts)

    def test_explicit_path_overrides_canonical_default(self):
        """An explicitly provided path overrides default canonical path."""
        custom_path = Path("/tmp/custom_muletrace_alerts.json")
        self.assertEqual(alert_service._resolve_alert_path(custom_path), custom_path)
        self.assertEqual(alert_service._resolve_alert_path(str(custom_path)), custom_path)

    def test_clean_initial_canonical_alert_store(self):
        """Canonical data/alerts.json must be initialized cleanly as an empty list."""
        self.assertTrue(self.canonical_alerts.exists())
        data = json.loads(self.canonical_alerts.read_text(encoding="utf-8"))
        self.assertEqual(data, [], "Canonical alert store must be initialized cleanly without stale alerts")

    def test_repeated_scans_are_idempotent(self):
        """Repeated scans of the canonical dataset must be idempotent and avoid duplicates."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = Path(tmp_dir) / "alerts_idempotent.json"

            first = alert_service.scan_risk_alerts(store)
            self.assertGreater(first["new_alert_count"], 0)
            total_first = first["total_alert_count"]

            second = alert_service.scan_risk_alerts(store)
            self.assertEqual(second["new_alert_count"], 0)
            self.assertEqual(second["total_alert_count"], total_first)

            third = alert_service.scan_risk_alerts(store)
            self.assertEqual(third["new_alert_count"], 0)
            self.assertEqual(third["total_alert_count"], total_first)

            loaded = alert_service.load_alerts(store)
            self.assertEqual(len(loaded), total_first)
            alert_ids = [a["alert_id"] for a in loaded]
            self.assertEqual(len(alert_ids), len(set(alert_ids)), "Alert IDs must not have duplicates")

    def test_alert_schema_and_deterministic_ids(self):
        """Alerts must conform to the required schema and have deterministic IDs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = Path(tmp_dir) / "alerts_schema.json"

            alert_service.scan_risk_alerts(store)
            alerts = alert_service.load_alerts(store)

            required_fields = {
                "alert_id", "created_at", "status", "source", "account_id",
                "rule", "transaction_ids", "reason", "evidence", "finding"
            }

            for alert in alerts:
                self.assertTrue(required_fields.issubset(alert.keys()))
                self.assertEqual(alert["status"], "new")
                self.assertEqual(alert["source"], "rule_engine")
                self.assertTrue(alert["alert_id"].startswith("ALT-"))
                self.assertEqual(len(alert["alert_id"]), 20)  # ALT- + 16 hex chars
                self.assertIsInstance(alert["transaction_ids"], list)

                # Recomputed alert_id from finding must match stored alert_id deterministically
                recomputed = alert_service.alert_id(alert["finding"])
                self.assertEqual(alert["alert_id"], recomputed)

    def test_canonical_alerts_json_never_modified_by_isolated_tests(self):
        """Verify data/alerts.json hash remains constant before and after running test scans."""
        before_hash = sha256(self.canonical_alerts.read_bytes()).hexdigest()

        # Perform a scan to an isolated temporary file
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_target = Path(tmp_dir) / "alerts_test.json"
            alert_service.scan_risk_alerts(temp_target)

        after_hash = sha256(self.canonical_alerts.read_bytes()).hexdigest()
        self.assertEqual(before_hash, after_hash, "data/alerts.json MUST NOT be mutated by isolated scans")


if __name__ == "__main__":
    unittest.main()
