import tempfile
import unittest
from pathlib import Path

from fenjue.budget import PortfolioBudgetService
from fenjue.ledger import PositionLedger
from fenjue.migrations import MigrationRunner
from fenjue.v2db import FenjueV2Database


class PortfolioBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FenjueV2Database(Path(self.tmp.name) / "budget.sqlite3")
        self.db.initialize()
        ledger = PositionLedger(self.db)
        ledger.ensure_account("main", "Main", 10_000_000, "2026-06-29", 1)
        ledger.add_risk_budget(
            "risk-v1", account_id="main", scope_type="account", scope_id=None,
            strategy_family=None, effective_from_ms=1, effective_to_ms=None,
            max_gross_exposure_ratio=0.8, max_single_symbol_ratio=0.2,
            max_logic_cluster_ratio=0.3, max_daily_loss_ratio=0.05,
            max_single_trade_loss_ratio=0.02, consecutive_failure_limit=3,
            retreat_exposure_multiplier_ratio=0.5, family_limits={}, created_at_ms=1,
        )
        self.service = PortfolioBudgetService(self.db)
        self.service.open_budget(
            budget_id="budget-1", risk_config_id="risk-v1", trade_date="2026-06-29",
            market_regime="NEUTRAL", initial_gross_exposure_fen=1_000_000,
            cluster_exposures_fen={"specialty_gases": 1_000_000}, now_ms=2,
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def precheck(self, key: str, amount: int = 1_500_000):
        return self.service.precheck(
            budget_id="budget-1", code="600378", logic_cluster_id="specialty_gases",
            strategy_family="NEW_ENTRY", requested_fen=amount,
            current_symbol_exposure_fen=0, idempotency_key=key, at_ms=3,
        )

    def test_precheck_grants_eligibility_without_consuming_budget(self):
        result = self.precheck("pre-1")
        self.assertEqual(result.status, "ELIGIBLE")
        self.assertEqual(result.authorized_fen, 1_500_000)
        row = self.db.connection.execute(
            "SELECT gross_consumed_fen FROM portfolio_budget WHERE budget_id='budget-1'"
        ).fetchone()
        self.assertEqual(row[0], 1_000_000)

    def test_final_consumption_is_quantitative_transactional_and_idempotent(self):
        precheck = self.precheck("pre-2")
        first = self.service.consume(
            precheck.consumption_id, requested_fen=1_200_000,
            current_symbol_exposure_fen=0, at_ms=4,
        )
        second = self.service.consume(
            precheck.consumption_id, requested_fen=1_200_000,
            current_symbol_exposure_fen=0, at_ms=5,
        )
        self.assertEqual(first.status, "CONSUMED")
        self.assertEqual(first.authorized_fen, 1_200_000)
        self.assertEqual(second, first)
        row = self.db.connection.execute(
            "SELECT gross_consumed_fen FROM portfolio_budget WHERE budget_id='budget-1'"
        ).fetchone()
        self.assertEqual(row[0], 2_200_000)

    def test_final_phase_rechecks_cluster_limit_after_competing_prechecks(self):
        first = self.precheck("pre-3")
        second = self.precheck("pre-4")
        used_first = self.service.consume(
            first.consumption_id, requested_fen=1_500_000,
            current_symbol_exposure_fen=0, at_ms=4,
        )
        used_second = self.service.consume(
            second.consumption_id, requested_fen=1_500_000,
            current_symbol_exposure_fen=0, at_ms=5,
        )
        self.assertEqual(used_first.authorized_fen, 1_500_000)
        self.assertEqual(used_second.authorized_fen, 500_000)
        cluster = self.db.connection.execute(
            "SELECT consumed_exposure_fen FROM logic_cluster_exposure WHERE budget_id='budget-1' AND logic_cluster_id='specialty_gases'"
        ).fetchone()[0]
        self.assertEqual(cluster, 3_000_000)

    def test_blocked_daily_loss_prevents_qualification(self):
        self.db.connection.execute(
            "UPDATE portfolio_budget SET realized_loss_fen=500000 WHERE budget_id='budget-1'"
        )
        result = self.precheck("pre-loss")
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("DAILY_LOSS_LIMIT", result.reason_codes)

    def test_migration_004_rolls_back_and_reapplies(self):
        runner = MigrationRunner(self.db.connection, self.db.resource_dir / "migrations")
        runner.rollback("004")
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertNotIn("portfolio_budget", tables)
        runner.apply_all()
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertIn("budget_consumption", tables)


if __name__ == "__main__":
    unittest.main()
