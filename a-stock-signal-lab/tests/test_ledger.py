from decimal import Decimal
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fenjue.ledger import PositionLedger, price_to_x10000
from fenjue.v2db import FenjueV2Database


class PositionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FenjueV2Database(Path(self.tmp.name) / "v2.sqlite3")
        self.db.initialize()
        self.ledger = PositionLedger(self.db)
        self.ledger.ensure_account("main", "Main", 10_000_000, "2026-06-26", 1)
        self.ledger.set_position(
            "main", "600378", "CORE_HOLD", 1500,
            "electronic_specialty_gases", "user configured", "user", 1,
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_price_conversion_is_decimal_and_integer(self):
        self.assertEqual(price_to_x10000("18.72"), 187200)
        self.assertEqual(price_to_x10000(Decimal("18.72005")), 187201)

    def test_t_plus_one_and_core_floor_limit_sellable_quantity(self):
        self.ledger.record_buy_lot(
            "main", "600378", "core", "2026-06-25", 1,
            2000, "18.00", "2026-06-26", "user", 1,
        )
        self.ledger.record_buy_lot(
            "main", "600378", "tactical", "2026-06-26", 2,
            1000, "18.72", "2026-06-29", "user", 2,
        )
        friday = self.ledger.position_context("main", "600378", "2026-06-26")
        monday = self.ledger.position_context("main", "600378", "2026-06-29")
        self.assertEqual(friday.total_qty, 3000)
        self.assertEqual(friday.sellable_qty, 2000)
        self.assertEqual(friday.max_sellable_without_breaking_core, 1500)
        self.assertEqual(monday.sellable_qty, 3000)

    def test_no_confirmed_risk_config_never_returns_automatic_size(self):
        result = self.ledger.risk_precheck(
            account_id="main",
            code="600378",
            strategy_family="NEW_ENTRY",
            logic_cluster_id="electronic_specialty_gases",
            at_ms=5,
            market_regime="NEUTRAL",
        )
        self.assertEqual(result.status, "UNCONFIGURED")
        self.assertIsNone(result.max_incremental_exposure_ratio)

    def test_overlapping_risk_config_is_rejected(self):
        common = dict(
            account_id="main", scope_type="symbol", scope_id="600378",
            strategy_family=None, max_gross_exposure_ratio=0.8,
            max_single_symbol_ratio=0.2, max_logic_cluster_ratio=0.3,
            max_daily_loss_ratio=0.05, max_single_trade_loss_ratio=0.02,
            consecutive_failure_limit=3, retreat_exposure_multiplier_ratio=0.5,
            family_limits={}, created_at_ms=1,
        )
        self.ledger.add_risk_budget("risk-1", effective_from_ms=1, effective_to_ms=10, **common)
        with self.assertRaises(ValueError):
            self.ledger.add_risk_budget(
                "risk-2", effective_from_ms=5, effective_to_ms=20, **common
            )

    def test_database_rejects_remaining_quantity_above_original(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.connection.execute(
                "INSERT INTO position_lots "
                "(lot_id, account_id, code, role, buy_trade_date, buy_time_ms, "
                "quantity_qty, remaining_qty, buy_price_x10000, sellable_from_date, "
                "source, created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("bad", "main", "600378", "core", "2026-06-26", 1,
                 100, 101, 100000, "2026-06-27", "user", 1),
            )

    def test_reconciliation_incident_forces_observe_and_is_audited(self):
        incident = self.ledger.record_reconciliation_incident(
            "main", "600378", {"ledger": 1000, "broker": 900}, 10
        )
        mode = self.db.connection.execute(
            "SELECT mode FROM positions WHERE account_id='main' AND code='600378'"
        ).fetchone()[0]
        self.assertEqual(mode, "OBSERVE")
        self.assertEqual(incident["forced_mode"], "OBSERVE")


if __name__ == "__main__":
    unittest.main()
