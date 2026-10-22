import os
import unittest
from unittest.mock import patch

import engine


class TestEngine(unittest.TestCase):

    def test_health_check(self):
        result = engine.health_check()
        self.assertEqual(result["status"], "ok")
        self.assertIn("trace_money", result["available_tools"])

    def test_account_profile(self):
        result = engine.get_account_profile("B782")
        self.assertEqual(result["account_id"], "B782")
        self.assertEqual(result["transaction_count"], 13)
        self.assertIn("CASE001", result["case_ids"])
        self.assertIn("CASE002", result["case_ids"])

    def test_transaction_history(self):
        result = engine.get_transaction_history("B782")
        self.assertEqual(result["account_id"], "B782")
        self.assertEqual(result["count"], 13)

    def test_detect_risk(self):
        # Canonical dataset: B782 has 1 multiple_incoming burst (TX0030-TX0039 in 9m)
        # and 2 high_value_transfer fallback findings (TX0041, TX0042).
        # Cross-case overlap is separated from detect_risk to investigation scoring.
        result = engine.detect_risk("B782")
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["findings"]), 3)
        for f in result["findings"]:
            self.assertEqual(f["account_id"], "B782")
        rules = {f["rule"] for f in result["findings"]}
        self.assertEqual(rules, {"high_value_transfer", "multiple_incoming"})

        mi_finding = next(f for f in result["findings"] if f["rule"] == "multiple_incoming")
        self.assertEqual(mi_finding["evidence"], 10.0)

        hvt_findings = [f for f in result["findings"] if f["rule"] == "high_value_transfer"]
        self.assertEqual(len(hvt_findings), 2)
        hvt_txs = {f["transaction_ids"] for f in hvt_findings}
        self.assertEqual(hvt_txs, {"TX0041", "TX0042"})

    def test_evidence(self):
        result = engine.get_evidence("TX0041")
        self.assertEqual(result["count"], 1)
        self.assertEqual(
            result["transactions"][0]["amount"],
            90000
        )
        self.assertEqual(result["missing_transaction_ids"], [])

    def test_cross_case_links(self):
        result = engine.find_cross_case_links("B782")
        self.assertEqual(result["count"], 1)
        self.assertIn(
            "CASE001",
            result["links"][0]["case_ids"]
        )
        self.assertIn(
            "CASE002",
            result["links"][0]["case_ids"]
        )

    def test_trace_money_evidence(self):
        result = engine.trace_money("B782", "C991", 4)
        self.assertEqual(result["path_count"], 1)
        self.assertIn(
            "TX0041",
            result["evidence_transaction_ids"]
        )
        self.assertTrue(result["evidence"])

    def test_search_previous_cases(self):
        result = engine.search_previous_cases("B782")
        self.assertEqual(result["case_count"], 2)

    def test_invalid_account(self):
        with self.assertRaises(ValueError):
            engine.get_account_profile("")


if __name__ == "__main__":
    unittest.main()