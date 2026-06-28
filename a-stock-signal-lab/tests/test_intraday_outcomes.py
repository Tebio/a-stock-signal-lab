import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fenjue.decision import DecisionContext, DecisionEngine
from fenjue.execution import CostModel, ExecutionStore, FillAssessment
from fenjue.ledger import PositionLedger, RiskPrecheck
from fenjue.migrations import MigrationRunner
from fenjue.outcomes import IntradayOutcomeBackfiller
from fenjue.trading_calendar import TradingCalendar
from fenjue.v2db import FenjueV2Database


SHANGHAI = ZoneInfo("Asia/Shanghai")


def at_ms(day: str, clock: str) -> int:
    return int(datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=SHANGHAI).timestamp() * 1000)


class IntradayOutcomeBackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FenjueV2Database(Path(self.tmp.name) / "outcomes.sqlite3")
        self.db.initialize()
        ledger = PositionLedger(self.db)
        ledger.ensure_account("main", "Main", 10_000_000, "2026-06-26", 1)
        ledger.set_position(
            "main", "600378", "NEW_ENTRY", 0, "specialty_gases", "fixture", "user", 1
        )
        ledger.record_buy_lot(
            "main", "600378", "tactical", "2026-06-26", at_ms("2026-06-26", "14:30"),
            1000, "10.00", "2026-06-29", "user", 1,
        )
        position_snapshot_id = ledger.snapshot_position(
            "main", "600378", "2026-06-26", "10.00", 2
        )
        self.db.connection.execute(
            """INSERT INTO data_manifests
            (data_manifest_id,manifest_version,purpose,raw_snapshot_ids_json,
             event_version_ids_json,market_source_versions_json,concept_mapping_version,
             trading_calendar_version,source_selection_policy_version,manifest_sha256,created_at_ms)
            VALUES ('manifest','1','test','[]','[]','{}','c1','cal1','s1','hash',1)"""
        )
        self.db.connection.execute(
            """INSERT INTO feature_snapshots
            (feature_snapshot_id,code,logic_cluster_id,as_of_ms,feature_set_version,
             data_manifest_id,source_raw_ids_json,source_event_versions_json,
             concept_labels_json,feature_values_json,created_at_ms)
            VALUES ('feature','600378','specialty_gases',2,'f1','manifest','[]','[]','[]','{}',2)"""
        )
        context = DecisionContext(
            decision_id="decision", decision_at_ms=at_ms("2026-06-26", "14:30"),
            account_id="main", code="600378", logic_cluster_id="specialty_gases",
            user_intent="fixture", requested_action="NEW_ENTRY", position_mode="NEW_ENTRY",
            position_snapshot_id=position_snapshot_id, feature_snapshot_id="feature",
            data_manifest_id="manifest", exchange_status="CONTINUOUS", event_freezes=[],
            logic_gate={"eligible_for_new_entry": True, "logic_invalidated": False},
            market_regime="NEUTRAL", market_features={}, market_microstructure={},
            execution=FillAssessment("fillable", "C", "fixture", 100000),
            risk_precheck=RiskPrecheck("ELIGIBLE", "risk", 0.1),
            probability_status="frequency_only", source_selection_policy_version="s1",
        )
        DecisionEngine(self.db).decide(context)
        self.calendar = TradingCalendar(self.db.connection)
        self.calendar.upsert_days(
            [
                {"trade_date": "2026-06-26", "is_trade_day": True},
                {"trade_date": "2026-06-27", "is_trade_day": False},
                {"trade_date": "2026-06-28", "is_trade_day": False},
                {"trade_date": "2026-06-29", "is_trade_day": True},
            ],
            source="fixture", calendar_version="cal1", available_at_ms=1,
        )
        store = ExecutionStore(self.db)
        store.add_cost_model(
            "cost", CostModel(3, 500, 5, 1, 2), 1, 1
        )
        self.intent_id = store.create_intent(
            intent_id="intent", decision_id="decision", account_id="main", code="600378",
            logic_cluster_id="specialty_gases", strategy_family="NEW_ENTRY", side="buy",
            intended_at_ms=at_ms("2026-06-26", "14:30"), intended_price_x10000=100000,
            intended_qty=1000, entry_price_source="user_actual", cost_model_id="cost",
            target_net_return_pct_points=3.0, status="user_confirmed",
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def add_bar(self, checkpoint: str, price: int, *, available_at_ms: int | None = None):
        target = self.calendar.checkpoints("2026-06-29")[checkpoint]
        self.db.connection.execute(
            """INSERT INTO market_bars
            (code,bar_time_ms,scale_seconds,open_price_x10000,high_price_x10000,
             low_price_x10000,close_price_x10000,volume_qty,amount_fen,source,
             available_at_ms,quality)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "600378", target, 60, price, price, price, price, 1000,
                price * 10, "fixture", available_at_ms or target + 1000, "C",
            ),
        )

    def test_backfills_four_next_trade_date_checkpoints_and_1030_outcome(self):
        for checkpoint, price in {
            "09:25": 101000, "09:40": 102000, "10:30": 104000, "14:30": 103000,
        }.items():
            self.add_bar(checkpoint, price)
        result = IntradayOutcomeBackfiller(self.db).backfill_intent(
            self.intent_id, calculation_version="calc-v1", calculated_at_ms=at_ms("2026-06-29", "15:00")
        )
        self.assertEqual(result.next_trade_date, "2026-06-29")
        self.assertEqual(result.outcome_status, "scored")
        self.assertTrue(result.hit_net_3pct)
        labels = [tuple(row) for row in self.db.connection.execute(
            "SELECT checkpoint,status FROM intraday_checkpoint_labels WHERE intent_id=? ORDER BY checkpoint_at_ms",
            (self.intent_id,),
        ).fetchall()]
        self.assertEqual(labels, [("09:25", "scored"), ("09:40", "scored"), ("10:30", "scored"), ("14:30", "scored")])
        self.assertEqual(
            self.db.connection.execute("SELECT COUNT(*) FROM market_bars_audit WHERE intent_id=?", (self.intent_id,)).fetchone()[0],
            4,
        )

    def test_bar_not_available_at_calculation_time_is_not_used(self):
        target = self.calendar.checkpoints("2026-06-29")["10:30"]
        self.add_bar("10:30", 104000, available_at_ms=target + 3_600_000)
        result = IntradayOutcomeBackfiller(self.db).backfill_intent(
            self.intent_id, calculation_version="calc-late", calculated_at_ms=target + 60_000
        )
        self.assertEqual(result.outcome_status, "unscorable")
        status = self.db.connection.execute(
            "SELECT selection_status FROM market_bars_audit WHERE intent_id=? AND checkpoint='10:30' AND calculation_version='calc-late'",
            (self.intent_id,),
        ).fetchone()[0]
        self.assertEqual(status, "not_yet_available")

    def test_bar_older_than_five_minutes_is_unscorable(self):
        target = self.calendar.checkpoints("2026-06-29")["10:30"]
        self.db.connection.execute(
            """INSERT INTO market_bars
            (code,bar_time_ms,scale_seconds,open_price_x10000,high_price_x10000,
             low_price_x10000,close_price_x10000,source,available_at_ms,quality)
            VALUES ('600378',?,60,104000,104000,104000,104000,'fixture',?,'C')""",
            (target - 301_000, target - 300_000),
        )
        result = IntradayOutcomeBackfiller(self.db).backfill_intent(
            self.intent_id, calculation_version="calc-missing", calculated_at_ms=target + 60_000
        )
        self.assertEqual(result.outcome_status, "unscorable")
        self.assertEqual(result.unscorable_reason, "NO_TRADABLE_1030_PRICE")

    def test_migration_003_rolls_back_and_reapplies(self):
        runner = MigrationRunner(self.db.connection, self.db.resource_dir / "migrations")
        runner.rollback("003")
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertNotIn("market_bars_audit", tables)
        runner.apply_all()
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertIn("intraday_checkpoint_labels", tables)


if __name__ == "__main__":
    unittest.main()
