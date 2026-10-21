import unittest
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
        result = engine.detect_risk("B782")
        self.assertEqual(result["count"], 4)
        self.assertTrue(result["findings"])

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