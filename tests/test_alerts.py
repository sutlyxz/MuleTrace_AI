"""Run: python -m unittest discover -s tests -p 'test_alerts.py' -v"""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from app.backend.services.alert_service import alert_id, load_alerts, scan_risk_alerts
from app.backend.workers.auto_scanner import signature


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'alerts.json'
        self.finding = {
            'account_id': 'B777', 'rule': 'rapid_outgoing',
            'transaction_ids': 'TX0046, TX0047',
            'reason': 'Outgoing transfer within 4 minutes',
            'evidence': 'TX0046 and TX0047',
        }

    def _scan(self, findings):
        fake = types.ModuleType('app.backend.engine')
        setattr(fake, 'detect_risk', lambda: {'count': len(findings), 'findings': findings})
        with patch.dict(sys.modules, {'app.backend.engine': fake}):
            return scan_risk_alerts(self.path)

    def test_first_scan_creates_alert(self):
        result = self._scan([self.finding])
        self.assertEqual(result['new_alert_count'], 1)
        self.assertEqual(load_alerts(self.path)[0]['transaction_ids'], ['TX0046', 'TX0047'])

    def test_second_scan_does_not_duplicate(self):
        self._scan([self.finding])
        result = self._scan([self.finding])
        self.assertEqual(result['new_alert_count'], 0)
        self.assertEqual(result['total_alert_count'], 1)

    def test_different_evidence_creates_new_alert(self):
        self._scan([self.finding])
        changed = {**self.finding, 'transaction_ids': 'TX0048,TX0049'}
        result = self._scan([self.finding, changed])
        self.assertEqual(result['new_alert_count'], 1)
        self.assertEqual(result['total_alert_count'], 2)

    def test_no_findings_no_alert(self):
        result = self._scan([])
        self.assertEqual(result['new_alert_count'], 0)
        self.assertFalse(self.path.exists())

    def test_id_ignores_transaction_order(self):
        changed = {**self.finding, 'transaction_ids': 'TX0047,TX0046'}
        self.assertEqual(alert_id(self.finding), alert_id(changed))

    def test_detect_case_csv_change(self):
        transactions = Path(self.tmp.name) / 'transactions.csv'
        cases = Path(self.tmp.name) / 'case_accounts.csv'
        transactions.write_text('abc', encoding='utf-8')
        before = signature((transactions, cases))
        cases.write_text('case_id,account_id\nCASE1,B777\n', encoding='utf-8')
        self.assertNotEqual(before, signature((transactions, cases)))


if __name__ == '__main__':
    unittest.main()
