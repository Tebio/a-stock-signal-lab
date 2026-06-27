import tempfile
import unittest
from pathlib import Path

from fenjue.baseline import BaselineRunner
from fenjue.execution import CostModel, ExecutionStore
from fenjue.migrations import MigrationRunner
from fenjue.v2db import FenjueV2Database


class BaselineRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FenjueV2Database(Path(self.tmp.name) / "baseline.sqlite3")
        self.db.initialize()
        ExecutionStore(self.db).add_cost_model(
            "cost", CostModel(3, 500, 5, 1, 2), 1, 1
        )
        self.db.connection.execute(
            """INSERT INTO strategy_versions
            (strategy_version_id,strategy_family,sample_cluster,code_sha256,
             feature_set_version,policy_version,parameter_json,status,
             probability_status,created_at_ms)
            VALUES ('strategy','NEW_ENTRY','EVENT_LOGIC_AUCTION','hash','f1','p1',
                    '{}','shadow','calibrating',1)"""
        )
        self.runner = BaselineRunner(self.db)
        self.runner.register_baseline(
            baseline_id="baseline", name="fixture baseline", definition_version="v1",
            selection_rule={"kind": "field_equals", "field": "baseline_signal", "value": True},
            cost_model_id="cost", created_at_ms=1,
        )
        self.rows = [
            {
                "opportunity_id": "o1", "trade_date": "2026-06-26", "logic_cluster_id": "A",
                "features": {"baseline_signal": True}, "strategy_selected": True,
                "outcome_status": "scored", "hit_net_3pct": True,
                "net_return_pct_points": 4.0, "strategy_probability": 0.8,
                "baseline_probability": 0.6,
            },
            {
                "opportunity_id": "o2", "trade_date": "2026-06-26", "logic_cluster_id": "A",
                "features": {"baseline_signal": False}, "strategy_selected": True,
                "outcome_status": "scored", "hit_net_3pct": False,
                "net_return_pct_points": -1.0, "strategy_probability": 0.6,
                "baseline_probability": 0.5,
            },
            {
                "opportunity_id": "o3", "trade_date": "2026-06-29", "logic_cluster_id": "B",
                "features": {"baseline_signal": True}, "strategy_selected": False,
                "outcome_status": "scored", "hit_net_3pct": False,
                "net_return_pct_points": -2.0, "strategy_probability": 0.4,
                "baseline_probability": 0.4,
            },
            {
                "opportunity_id": "o4", "trade_date": "2026-06-29", "logic_cluster_id": "B",
                "features": {"baseline_signal": False}, "strategy_selected": True,
                "outcome_status": "scored", "hit_net_3pct": True,
                "net_return_pct_points": 3.0, "strategy_probability": 0.7,
                "baseline_probability": 0.5,
            },
        ]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def run_fixture(self, rows=None):
        return self.runner.run(
            run_id="run-1", strategy_version_id="strategy", baseline_id="baseline",
            opportunity_grouping_version="date-cluster-v1", observations=rows or self.rows,
            created_at_ms=10,
        )

    def test_outputs_lift_expectancy_coverage_brier_and_calibration(self):
        result = self.run_fixture()
        overall = result.overall
        self.assertAlmostEqual(overall.strategy_hit_rate, 2 / 3)
        self.assertAlmostEqual(overall.baseline_hit_rate, 1 / 2)
        self.assertAlmostEqual(overall.hit_rate_lift_pct_points, 100 / 6)
        self.assertAlmostEqual(overall.strategy_net_expectancy, 2.0)
        self.assertAlmostEqual(overall.baseline_net_expectancy, 1.0)
        self.assertAlmostEqual(overall.strategy_coverage, 0.75)
        self.assertAlmostEqual(overall.baseline_coverage, 0.5)
        self.assertAlmostEqual(overall.strategy_brier_score, (0.04 + 0.36 + 0.09) / 3)
        self.assertAlmostEqual(overall.baseline_brier_score, 0.16)
        self.assertIsNotNone(overall.strategy_calibration_error)

    def test_groups_metrics_by_trade_date_and_logic_cluster(self):
        result = self.run_fixture()
        self.assertEqual(set(result.by_trade_date), {"2026-06-26", "2026-06-29"})
        self.assertEqual(set(result.by_logic_cluster), {"A", "B"})
        self.assertAlmostEqual(
            result.by_logic_cluster["A"].strategy_coverage, 1.0
        )
        self.assertAlmostEqual(
            result.by_logic_cluster["B"].baseline_coverage, 0.5
        )

    def test_unscorable_rows_count_for_coverage_but_not_scores(self):
        rows = list(self.rows)
        rows.append(
            {
                "opportunity_id": "o5", "trade_date": "2026-06-29", "logic_cluster_id": "B",
                "features": {"baseline_signal": True}, "strategy_selected": True,
                "outcome_status": "unscorable", "hit_net_3pct": None,
                "net_return_pct_points": None, "strategy_probability": 0.9,
                "baseline_probability": 0.9,
            }
        )
        result = self.run_fixture(rows)
        self.assertEqual(result.overall.total_opportunities, 5)
        self.assertEqual(result.overall.strategy_scored, 3)
        self.assertAlmostEqual(result.overall.strategy_coverage, 4 / 5)

    def test_metrics_and_opportunities_are_persisted(self):
        self.run_fixture()
        self.assertEqual(
            self.db.connection.execute("SELECT COUNT(*) FROM baseline_run_opportunities WHERE run_id='run-1'").fetchone()[0],
            4,
        )
        dimensions = self.db.connection.execute(
            "SELECT COUNT(DISTINCT dimension_type || ':' || dimension_value) FROM baseline_run_metrics WHERE run_id='run-1'"
        ).fetchone()[0]
        self.assertEqual(dimensions, 5)

    def test_migration_007_rolls_back_and_reapplies(self):
        runner = MigrationRunner(self.db.connection, self.db.resource_dir / "migrations")
        runner.rollback("007")
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertNotIn("baseline_comparison_runs", tables)
        runner.apply_all()
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertIn("baseline_run_metrics", tables)


if __name__ == "__main__":
    unittest.main()
