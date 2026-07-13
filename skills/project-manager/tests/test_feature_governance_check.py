import unittest

from scripts.feature_governance_check import checkers_for_stage, combine_decisions, combine_risk, should_fail


class FeatureGovernanceCheckTests(unittest.TestCase):
    def test_aggregation_uses_strictest_result(self) -> None:
        results = [
            {"normalized_decision": "allow", "risk": "low"},
            {"normalized_decision": "block", "risk": "high"},
            {"normalized_decision": "revise", "risk": "medium"},
        ]
        self.assertEqual(("BLOCK", "block"), combine_decisions(results))
        self.assertEqual("high", combine_risk(results))

    def test_fail_threshold(self) -> None:
        self.assertFalse(should_fail("allow", "revise"))
        self.assertTrue(should_fail("revise", "revise"))
        self.assertTrue(should_fail("block", "revise"))
        self.assertFalse(should_fail("revise", "block"))
        self.assertFalse(should_fail("block", None))

    def test_stage_selects_only_available_checkers(self) -> None:
        intake = {checker["name"] for checker in checkers_for_stage("intake")}
        development = {checker["name"] for checker in checkers_for_stage("development")}
        self.assertEqual({"project-status-checker", "prd-qa-checker", "artifact-consistency-checker"}, intake)
        self.assertIn("architecture-design-checker", development)
        self.assertIn("test-case-checker", development)
        self.assertIn("api-contract-checker", development)
        self.assertNotIn("test-report-checker", development)
        self.assertIn("test-report-checker", {checker["name"] for checker in checkers_for_stage("release")})
        self.assertIn("retrospective-checker", {checker["name"] for checker in checkers_for_stage("closure")})


if __name__ == "__main__":
    unittest.main()
