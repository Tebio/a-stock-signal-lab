#!/usr/bin/env python3
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fenjue.decision import DecisionContext, DecisionEngine
from fenjue.execution import FillAssessment
from fenjue.ledger import PositionLedger, RiskPrecheck
from fenjue.v2db import FenjueV2Database


def main() -> int:
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "decision_replay.json").read_text(
            encoding="utf-8"
        )
    )
    with tempfile.TemporaryDirectory() as tmp:
        database = FenjueV2Database(Path(tmp) / "fixture.sqlite3")
        database.initialize()
        ledger = PositionLedger(database)
        ledger.ensure_account("main", "Main", 10_000_000, "2026-06-27", 1)
        ledger.set_position(
            "main", "600378", "CORE_HOLD", 500, "specialty_gases",
            "fixture", "user", 1,
        )
        ledger.record_buy_lot(
            "main", "600378", "core", "2026-06-26", 1,
            1000, "10.00", "2026-06-27", "user", 1,
        )
        position_snapshot_id = ledger.snapshot_position(
            "main", "600378", "2026-06-27", "10.00", 2
        )
        database.connection.execute(
            """INSERT INTO data_manifests
            (data_manifest_id,manifest_version,purpose,raw_snapshot_ids_json,
             event_version_ids_json,market_source_versions_json,concept_mapping_version,
             trading_calendar_version,source_selection_policy_version,manifest_sha256,created_at_ms)
            VALUES ('manifest','1','fixture','[]','[]','{}','c1','cal1','source-v1','hash',1)"""
        )
        database.connection.execute(
            """INSERT INTO feature_snapshots
            (feature_snapshot_id,code,logic_cluster_id,as_of_ms,feature_set_version,
             data_manifest_id,source_raw_ids_json,source_event_versions_json,
             concept_labels_json,feature_values_json,created_at_ms)
            VALUES ('feature','600378','specialty_gases',2,'f1','manifest','[]','[]','[]','{}',2)"""
        )
        strategy_id = fixture["strategy_version_id"]
        database.connection.execute(
            """INSERT INTO strategy_versions
            (strategy_version_id,strategy_family,sample_cluster,code_sha256,
             feature_set_version,policy_version,parameter_json,status,
             probability_status,created_at_ms)
            VALUES (?,'NEW_ENTRY','FIXTURE','hash','f1','fenjue-policy-v2','{}',
                    'production','probability_ready',1)""",
            (strategy_id,),
        )
        raw_context = dict(fixture["context"])
        execution = FillAssessment(**raw_context.pop("execution"))
        risk = RiskPrecheck(**raw_context.pop("risk_precheck"))
        results = {}
        for mode in ("research", "shadow", "production"):
            context = DecisionContext(
                **raw_context,
                decision_id=f"fixture-{mode}",
                position_snapshot_id=position_snapshot_id,
                feature_snapshot_id="feature",
                data_manifest_id="manifest",
                execution=execution,
                risk_precheck=risk,
            )
            results[mode] = DecisionEngine(
                database, run_mode=mode, strategy_version_id=strategy_id
            ).decide(context)
        expected = fixture["expected"]
        if {result.graph_action for result in results.values()} != {expected["graph_action"]}:
            raise AssertionError("run modes diverged on graph action")
        if len({result.decision_graph_hash for result in results.values()}) != 1:
            raise AssertionError("run modes diverged on graph hash")
        for mode in ("research", "shadow", "production"):
            if results[mode].action != expected[f"{mode}_action"]:
                raise AssertionError(f"unexpected {mode} action")
            if results[mode].executable != expected[f"{mode}_executable"]:
                raise AssertionError(f"unexpected {mode} execution permission")
        if database.integrity_report()["integrity_check"] != "ok":
            raise AssertionError("fixture replay damaged database integrity")
        summary = {mode: asdict(result) for mode, result in results.items()}
        database.close()
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
