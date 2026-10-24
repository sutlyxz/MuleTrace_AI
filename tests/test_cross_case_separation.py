"""Focused tests for separating cross_case_overlap from transaction risk detection."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.backend import engine
from app.backend.core import risk_rules


class TestCrossCaseSeparation(unittest.TestCase):
    """Verify cross_case_overlap is decoupled from transaction risk but preserved for investigation/scoring."""

    def test_detect_risk_excludes_cross_case_overlap(self) -> None:
        """detect_risk() must only return transaction risk rules, never cross_case_overlap."""
        all_findings = engine.detect_risk()
        rule_names = {f["rule"] for f in all_findings["findings"]}
        self.assertNotIn("cross_case_overlap", rule_names)
        self.assertTrue(rule_names.issubset({
            "multiple_incoming", "rapid_outgoing", "high_value_transfer"
        }))

        b782_findings = engine.detect_risk("B782")
        b782_rules = {f["rule"] for f in b782_findings["findings"]}
        self.assertNotIn("cross_case_overlap", b782_rules)

    def test_cross_case_investigation_tools_preserved(self) -> None:
        """find_cross_case_links and search_previous_cases remain fully operational."""
        links = engine.find_cross_case_links("B782")
        self.assertEqual(links["count"], 1)
        self.assertIn("CASE001", links["links"][0]["case_ids"])
        self.assertIn("CASE002", links["links"][0]["case_ids"])

        history = engine.search_previous_cases("B782")
        self.assertGreaterEqual(history["case_count"], 2)
        self.assertIn("CASE001", history["case_ids"])
        self.assertIn("CASE002", history["case_ids"])

    def test_score_investigation_includes_cross_case_exactly_once(self) -> None:
        """score_investigation applies cross_case_overlap (+25) at most once per scope."""
        weights = {
            "multiple_incoming": 35,
            "rapid_outgoing": 30,
            "high_value_transfer": 20,
            "cross_case_overlap": 25,
        }
        result = engine.score_investigation(case_id="CASE001")
        matched_rules = result["rule_types_matched"]

        # cross_case_overlap must be matched because B782 is in CASE001 and linked to CASE002
        self.assertIn("cross_case_overlap", matched_rules)

        # Reason for cross_case_overlap must appear exactly once
        co_reasons = [r for r in result["reasons"] if "cross_case_overlap" in r]
        self.assertEqual(len(co_reasons), 1)
        self.assertEqual(co_reasons[0], "cross_case_overlap: +25 triage points")

        # The score must be derived dynamically from actual matched rules, never hardcoded
        expected_score = min(sum(weights[r] for r in matched_rules), 100)
        self.assertEqual(result["score"], expected_score)

    def test_score_investigation_no_cross_case_when_unlinked(self) -> None:
        """When an account has no cross-case links, cross_case_overlap is not scored."""
        # A900 appears in only 1 case or 0 cases
        result = engine.score_investigation(account_id="A900")
        self.assertNotIn("cross_case_overlap", result["rule_types_matched"])
        co_reasons = [r for r in result["reasons"] if "cross_case_overlap" in r]
        self.assertEqual(len(co_reasons), 0)

    def test_canonical_account_B782_and_CASE001_scoring_breakdown(self) -> None:
        """Verify explainable scoring for B782 and CASE001 under canonical dataset."""
        # B782 transaction-only risk findings:
        # 1 multiple_incoming + 2 high_value_transfer (TX0041, TX0042)
        tx_risks = engine.detect_risk("B782")
        self.assertEqual(tx_risks["count"], 3)
        self.assertEqual(
            sorted([f["rule"] for f in tx_risks["findings"]]),
            ["high_value_transfer", "high_value_transfer", "multiple_incoming"]
        )

        # CASE001 score breakdown:
        case_score = engine.score_investigation(case_id="CASE001")
        self.assertEqual(case_score["accounts_in_scope"], ["A001", "B782"])
        self.assertEqual(
            case_score["rule_types_matched"],
            ["cross_case_overlap", "high_value_transfer", "multiple_incoming"]
        )
        # 35 (multiple_incoming) + 20 (high_value_transfer) + 25 (cross_case_overlap) = 80
        self.assertEqual(case_score["score"], 80)
        self.assertEqual(case_score["priority"], "High")


if __name__ == "__main__":
    unittest.main()
