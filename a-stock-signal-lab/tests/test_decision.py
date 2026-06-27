import json
import tempfile
import unittest
from pathlib import Path

from fenjue.decision import DecisionContext, DecisionEngine
from fenjue.execution import FillAssessment
from fenjue.ledger import PositionLedger, RiskPrecheck
from fenjue.migrations import MigrationRunner
from fenjue.v2db import FenjueV2Database


class DecisionEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FenjueV2Database(Path(self.tmp.name) / "v2.sqlite3")
        self.db.initialize()
        ledger = PositionLedger(self.db)
        ledger.ensure_account("main", "Main", 10_000_000, "2026-06-27", 1)
        ledger.set_position(
            "main", "600378", "CORE_HOLD", 500,
            "electronic_specialty_gases", "user", "user", 1,
        )
        ledger.record_buy_lot(
            "main", "600378", "core", "2026-06-26", 1,
            1000, "18.72", "2026-06-27", "user", 1,
        )
        self.position_snapshot_id = ledger.snapshot_position(
            "main", "600378", "2026-06-27", "18.90", 2
        )
        self.db.connection.execute(
            """
            INSERT INTO data_manifests
                (data_manifest_id,manifest_version,purpose,raw_snapshot_ids_json,
                 event_version_ids_json,market_source_versions_json,
                 concept_mapping_version,trading_calendar_version,
                 source_selection_policy_version,manifest_sha256,created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("manifest-1", "1", "decision", "[]", "[]", "{}", "concept-v1",
             "calendar-v1", "source-v1", "hash-1", 1),
        )
        self.db.connection.execute(
            """
            INSERT INTO feature_snapshots
                (feature_snapshot_id,code,logic_cluster_id,as_of_ms,
                 feature_set_version,data_manifest_id,source_raw_ids_json,
                 source_event_versions_json,concept_labels_json,
                 feature_values_json,created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("feature-1", "600378", "electronic_specialty_gases", 2, "features-v1",
             "manifest-1", "[]", "[]", "[]", "{}", 2),
        )
        self.engine = DecisionEngine(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def context(self, **overrides):
        values = dict(
            decision_id=None,
            decision_at_ms=10,
            account_id="main",
            code="600378",
            logic_cluster_id="electronic_specialty_gases",
            user_intent="保护核心仓，评估动作",
            requested_action="ADD",
            position_mode="CORE_HOLD",
            position_snapshot_id=self.position_snapshot_id,
            feature_snapshot_id="feature-1",
            data_manifest_id="manifest-1",
            exchange_status="CONTINUOUS",
            event_freezes=[],
            logic_gate={
                "eligible_for_core_hold": True,
                "eligible_for_new_entry": True,
                "logic_invalidated": False,
            },
            market_regime="NEUTRAL",
            market_features={},
            market_microstructure={},
            execution=FillAssessment(
                "fillable", "C", "CONSERVATIVE_PRICE_AVAILABLE", 189000
            ),
            risk_precheck=RiskPrecheck("ELIGIBLE", "risk-1", 0.1),
            probability_status="probability_ready",
            source_selection_policy_version="source-v1",
        )
        values.update(overrides)
        return DecisionContext(**values)

    def add_strategy(self, strategy_id, status):
        self.db.connection.execute(
            """INSERT INTO strategy_versions
            (strategy_version_id,strategy_family,sample_cluster,code_sha256,
             feature_set_version,policy_version,parameter_json,status,
             probability_status,created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                strategy_id, "NEW_ENTRY", "EVENT_LOGIC_AUCTION", "hash",
                "features-v1", "fenjue-policy-v2", "{}", status,
                "probability_ready", 1,
            ),
        )

    def test_strong_logic_does_not_override_retreat_for_add(self):
        result = self.engine.decide(self.context(market_regime="RETREAT"))
        self.assertEqual(result.strategy_family, "NEW_ENTRY")
        self.assertEqual(result.action, "REJECT")
        self.assertIn("MARKET_RETREAT", result.reason_codes)

    def test_regulatory_freeze_is_risk_family_even_with_good_execution(self):
        result = self.engine.decide(
            self.context(event_freezes=[{"freeze_scope": "add", "freeze_id": "f1"}])
        )
        self.assertEqual(result.strategy_family, "RISK")
        self.assertEqual(result.action, "RISK_REVIEW")

    def test_zero_risk_budget_rejects_new_exposure(self):
        result = self.engine.decide(
            self.context(risk_precheck=RiskPrecheck("BLOCKED", "risk-1", 0.0))
        )
        self.assertEqual(result.action, "REJECT")
        self.assertIn("RISK_BUDGET_ZERO", result.reason_codes)

    def test_stock_specific_timing_gate_can_reject_entry(self):
        result = self.engine.decide(self.context(market_features={
            "timing_gate": {
                "eligible": False,
                "reason_codes": ["STOCK_SPECIFIC_FADE_RISK"],
            }
        }))
        self.assertEqual(result.action, "REJECT")
        self.assertIn("STOCK_SPECIFIC_FADE_RISK", result.reason_codes)

    def test_incomplete_context_can_only_observe(self):
        result = self.engine.decide(self.context(market_microstructure=None))
        self.assertEqual(result.strategy_family, "OBSERVE")
        self.assertEqual(result.action, "OBSERVE")
        self.assertIn("INPUT_CONTRACT_INCOMPLETE", result.reason_codes)

    def test_frequency_only_state_does_not_publish_probability_or_position(self):
        result = self.engine.decide(self.context(probability_status="frequency_only"))
        self.assertEqual(result.action, "REJECT")
        self.assertIsNone(result.probability_ratio)
        self.assertIsNone(result.max_incremental_exposure_ratio)

    def test_core_hold_survives_retreat_but_cannot_add(self):
        result = self.engine.decide(
            self.context(requested_action="HOLD", market_regime="RETREAT")
        )
        self.assertEqual(result.strategy_family, "CORE_HOLD")
        self.assertEqual(result.action, "HOLD_CORE_NO_ADD")

    def test_every_rejection_is_persisted_with_logic_cluster(self):
        result = self.engine.decide(self.context(market_regime="RETREAT"))
        row = self.db.connection.execute(
            "SELECT logic_cluster_id,reason_code FROM rejection_audits "
            "WHERE decision_id=?", (result.decision_id,)
        ).fetchone()
        self.assertEqual(row["logic_cluster_id"], "electronic_specialty_gases")
        self.assertEqual(row["reason_code"], "MARKET_RETREAT")

    def test_all_run_modes_share_graph_but_only_production_is_executable(self):
        self.add_strategy("strategy-prod", "production")
        results = {
            mode: DecisionEngine(
                self.db, run_mode=mode, strategy_version_id="strategy-prod"
            ).decide(self.context(decision_id=f"decision-{mode}"))
            for mode in ("research", "shadow", "production")
        }
        self.assertEqual({result.graph_action for result in results.values()}, {"ADD"})
        self.assertEqual(len({result.decision_graph_hash for result in results.values()}), 1)
        self.assertEqual(results["research"].action, "ALLOW_ADD_RESEARCH")
        self.assertEqual(results["shadow"].action, "SHADOW_ADD")
        self.assertFalse(results["research"].executable)
        self.assertFalse(results["shadow"].executable)
        self.assertEqual(results["production"].action, "ADD")
        self.assertTrue(results["production"].executable)

    def test_production_rejects_candidate_strategy_after_shared_graph_passes(self):
        self.add_strategy("strategy-candidate", "candidate")
        result = DecisionEngine(
            self.db, run_mode="production", strategy_version_id="strategy-candidate"
        ).decide(self.context(decision_id="decision-candidate"))
        self.assertEqual(result.graph_action, "ADD")
        self.assertEqual(result.action, "REJECT")
        self.assertFalse(result.executable)
        self.assertIn("STRATEGY_NOT_PRODUCTION", result.reason_codes)

    def test_run_trace_and_shadow_record_are_persisted(self):
        self.add_strategy("strategy-shadow", "shadow")
        result = DecisionEngine(
            self.db, run_mode="shadow", strategy_version_id="strategy-shadow"
        ).decide(self.context(decision_id="decision-shadow-trace"))
        trace = self.db.connection.execute(
            "SELECT run_mode,graph_action,output_action,executable FROM decision_run_traces WHERE decision_id=?",
            (result.decision_id,),
        ).fetchone()
        self.assertEqual(tuple(trace), ("shadow", "ADD", "SHADOW_ADD", 0))
        self.assertEqual(
            self.db.connection.execute(
                "SELECT COUNT(*) FROM shadow_decisions WHERE strategy_version_id='strategy-shadow'"
            ).fetchone()[0],
            1,
        )

    def test_migration_006_rolls_back_and_reapplies(self):
        runner = MigrationRunner(self.db.connection, self.db.resource_dir / "migrations")
        runner.rollback("006")
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertNotIn("decision_run_traces", tables)
        runner.apply_all()
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertIn("decision_run_traces", tables)


if __name__ == "__main__":
    unittest.main()
