import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent


class ContinuousIntegrationContractTests(unittest.TestCase):
    def test_workflow_declares_all_five_quality_gates(self):
        workflow_path = REPOSITORY_ROOT / ".github" / "workflows" / "quality.yml"
        if not workflow_path.exists():
            self.skipTest(
                "repository-level workflow is not included in a subdirectory Skill install"
            )
        workflow = workflow_path.read_text(
            encoding="utf-8"
        )
        for job in (
            "lint:", "unit-tests:", "migration-dry-run:",
            "fixture-replay:", "shadow-baseline-regression:",
        ):
            self.assertIn(job, workflow)
        for command in (
            "ruff check", "unittest discover", "ci_migration_dry_run.py",
            "ci_fixture_replay.py", "ci_shadow_baseline_regression.py",
        ):
            self.assertIn(command, workflow)

    def test_decision_fixture_has_expected_mode_projection_contract(self):
        payload = json.loads(
            (PROJECT_ROOT / "tests" / "fixtures" / "decision_replay.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(payload["expected"]["graph_action"], "ADD")
        self.assertFalse(payload["expected"]["research_executable"])
        self.assertTrue(payload["expected"]["production_executable"])

    def test_shadow_baseline_fixture_has_regression_thresholds(self):
        payload = json.loads(
            (PROJECT_ROOT / "tests" / "fixtures" / "shadow_baseline_regression.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertGreaterEqual(len(payload["observations"]), 6)
        self.assertGreater(payload["thresholds"]["minimum_hit_rate_lift_pct_points"], 0)
        self.assertGreater(payload["thresholds"]["minimum_net_expectancy_lift"], 0)


if __name__ == "__main__":
    unittest.main()
