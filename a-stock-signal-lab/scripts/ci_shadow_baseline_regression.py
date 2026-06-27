#!/usr/bin/env python3
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fenjue.baseline import BaselineRunner
from fenjue.execution import CostModel, ExecutionStore
from fenjue.v2db import FenjueV2Database


def main() -> int:
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "shadow_baseline_regression.json").read_text(
            encoding="utf-8"
        )
    )
    with tempfile.TemporaryDirectory() as tmp:
        database = FenjueV2Database(Path(tmp) / "regression.sqlite3")
        database.initialize()
        ExecutionStore(database).add_cost_model(
            "fixture-cost", CostModel(3, 500, 5, 1, 2), 1, 1
        )
        database.connection.execute(
            """INSERT INTO strategy_versions
            (strategy_version_id,strategy_family,sample_cluster,code_sha256,
             feature_set_version,policy_version,parameter_json,status,
             probability_status,created_at_ms)
            VALUES ('fixture-shadow','NEW_ENTRY','FIXTURE','hash','f1','p1','{}',
                    'shadow','calibrating',1)"""
        )
        runner = BaselineRunner(database)
        runner.register_baseline(
            baseline_id="fixture-baseline", name="fixture baseline",
            definition_version="v1", selection_rule=fixture["baseline_rule"],
            cost_model_id="fixture-cost", created_at_ms=1,
        )
        result = runner.run(
            run_id="fixture-run", strategy_version_id="fixture-shadow",
            baseline_id="fixture-baseline", opportunity_grouping_version="fixture-v1",
            observations=fixture["observations"], created_at_ms=2,
        )
        metrics = result.overall
        thresholds = fixture["thresholds"]
        checks = {
            "hit_rate_lift": metrics.hit_rate_lift_pct_points
            >= thresholds["minimum_hit_rate_lift_pct_points"],
            "net_expectancy_lift": (
                metrics.strategy_net_expectancy - metrics.baseline_net_expectancy
                >= thresholds["minimum_net_expectancy_lift"]
            ),
            "brier": metrics.strategy_brier_score
            <= thresholds["maximum_strategy_brier_score"],
            "trade_dates": len(result.by_trade_date)
            >= thresholds["required_trade_dates"],
            "logic_clusters": len(result.by_logic_cluster)
            >= thresholds["required_logic_clusters"],
        }
        if not all(checks.values()):
            raise AssertionError(f"shadow baseline regression failed: {checks}")
        output = {"checks": checks, "metrics": asdict(metrics)}
        database.close()
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
