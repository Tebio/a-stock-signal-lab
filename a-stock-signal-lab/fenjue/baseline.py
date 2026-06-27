from __future__ import annotations

from dataclasses import dataclass
import json
from statistics import mean
from typing import Any, Iterable

from .v2db import FenjueV2Database


@dataclass(frozen=True)
class ComparisonMetrics:
    total_opportunities: int
    strategy_scored: int
    baseline_scored: int
    strategy_hit_rate: float | None
    baseline_hit_rate: float | None
    hit_rate_lift_pct_points: float | None
    strategy_net_expectancy: float | None
    baseline_net_expectancy: float | None
    strategy_coverage: float
    baseline_coverage: float
    strategy_brier_score: float | None
    baseline_brier_score: float | None
    strategy_calibration_error: float | None
    baseline_calibration_error: float | None


@dataclass(frozen=True)
class BaselineRunResult:
    run_id: str
    overall: ComparisonMetrics
    by_trade_date: dict[str, ComparisonMetrics]
    by_logic_cluster: dict[str, ComparisonMetrics]


def _average(values: list[float]) -> float | None:
    return mean(values) if values else None


def _calibration_error(rows: list[dict[str, Any]], probability_key: str) -> float | None:
    eligible = [
        row for row in rows
        if row.get(probability_key) is not None and row.get("hit_net_3pct") is not None
    ]
    if not eligible:
        return None
    bins: dict[int, list[dict[str, Any]]] = {}
    for row in eligible:
        probability = float(row[probability_key])
        bucket = min(9, int(probability * 10))
        bins.setdefault(bucket, []).append(row)
    total = len(eligible)
    return sum(
        len(bucket_rows) / total
        * abs(
            mean(float(row[probability_key]) for row in bucket_rows)
            - mean(float(bool(row["hit_net_3pct"])) for row in bucket_rows)
        )
        for bucket_rows in bins.values()
    )


class BaselineRunner:
    def __init__(self, db: FenjueV2Database):
        self.db = db

    def register_baseline(
        self,
        *,
        baseline_id: str,
        name: str,
        definition_version: str,
        selection_rule: dict[str, Any],
        cost_model_id: str,
        created_at_ms: int,
    ) -> None:
        self.db.connection.execute(
            """INSERT INTO baseline_definitions
            (baseline_id,name,definition_version,selection_rule_json,
             cost_model_id,active,created_at_ms)
            VALUES (?,?,?,?,?,1,?)""",
            (
                baseline_id, name, definition_version,
                json.dumps(selection_rule, ensure_ascii=False, sort_keys=True),
                cost_model_id, created_at_ms,
            ),
        )

    @staticmethod
    def _select(rule: dict[str, Any], features: dict[str, Any]) -> bool:
        kind = rule.get("kind")
        if kind == "field_equals":
            return features.get(rule["field"]) == rule.get("value")
        if kind == "all_eligible":
            return bool(features.get(rule.get("field", "eligible")))
        if kind == "auction_gap_range":
            gap = features.get("auction_gap_pct")
            volume_ratio = features.get("volume_ratio")
            return bool(
                gap is not None and volume_ratio is not None
                and float(rule["min_pct"]) <= float(gap) <= float(rule["max_pct"])
                and float(volume_ratio) >= float(rule.get("min_volume_ratio", 0))
            )
        raise ValueError(f"unsupported baseline selector: {kind}")

    @staticmethod
    def _metrics(rows: list[dict[str, Any]]) -> ComparisonMetrics:
        total = len(rows)
        strategy_selected = [row for row in rows if row["strategy_selected"]]
        baseline_selected = [row for row in rows if row["baseline_selected"]]
        strategy_scored = [
            row for row in strategy_selected if row["outcome_status"] == "scored"
        ]
        baseline_scored = [
            row for row in baseline_selected if row["outcome_status"] == "scored"
        ]
        strategy_hit = _average(
            [float(bool(row["hit_net_3pct"])) for row in strategy_scored]
        )
        baseline_hit = _average(
            [float(bool(row["hit_net_3pct"])) for row in baseline_scored]
        )
        strategy_brier_rows = [
            row for row in strategy_scored if row.get("strategy_probability") is not None
        ]
        baseline_brier_rows = [
            row for row in baseline_scored if row.get("baseline_probability") is not None
        ]
        strategy_brier = _average([
            (float(row["strategy_probability"]) - float(bool(row["hit_net_3pct"]))) ** 2
            for row in strategy_brier_rows
        ])
        baseline_brier = _average([
            (float(row["baseline_probability"]) - float(bool(row["hit_net_3pct"]))) ** 2
            for row in baseline_brier_rows
        ])
        return ComparisonMetrics(
            total_opportunities=total,
            strategy_scored=len(strategy_scored),
            baseline_scored=len(baseline_scored),
            strategy_hit_rate=strategy_hit,
            baseline_hit_rate=baseline_hit,
            hit_rate_lift_pct_points=(
                (strategy_hit - baseline_hit) * 100
                if strategy_hit is not None and baseline_hit is not None else None
            ),
            strategy_net_expectancy=_average([
                float(row["net_return_pct_points"]) for row in strategy_scored
            ]),
            baseline_net_expectancy=_average([
                float(row["net_return_pct_points"]) for row in baseline_scored
            ]),
            strategy_coverage=len(strategy_selected) / total if total else 0.0,
            baseline_coverage=len(baseline_selected) / total if total else 0.0,
            strategy_brier_score=strategy_brier,
            baseline_brier_score=baseline_brier,
            strategy_calibration_error=_calibration_error(
                strategy_scored, "strategy_probability"
            ),
            baseline_calibration_error=_calibration_error(
                baseline_scored, "baseline_probability"
            ),
        )

    def _persist_metrics(
        self,
        run_id: str,
        dimension_type: str,
        dimension_value: str,
        metrics: ComparisonMetrics,
        created_at_ms: int,
    ) -> None:
        values = {
            "hit_rate": (
                metrics.strategy_hit_rate, metrics.baseline_hit_rate,
                None if metrics.hit_rate_lift_pct_points is None
                else metrics.hit_rate_lift_pct_points / 100,
            ),
            "net_expectancy": (
                metrics.strategy_net_expectancy, metrics.baseline_net_expectancy,
                None if metrics.strategy_net_expectancy is None or metrics.baseline_net_expectancy is None
                else metrics.strategy_net_expectancy - metrics.baseline_net_expectancy,
            ),
            "coverage": (
                metrics.strategy_coverage, metrics.baseline_coverage,
                metrics.strategy_coverage - metrics.baseline_coverage,
            ),
            "brier_score": (
                metrics.strategy_brier_score, metrics.baseline_brier_score,
                None if metrics.strategy_brier_score is None or metrics.baseline_brier_score is None
                else metrics.baseline_brier_score - metrics.strategy_brier_score,
            ),
            "calibration_error": (
                metrics.strategy_calibration_error, metrics.baseline_calibration_error,
                None if metrics.strategy_calibration_error is None or metrics.baseline_calibration_error is None
                else metrics.baseline_calibration_error - metrics.strategy_calibration_error,
            ),
        }
        for name, (strategy, baseline, lift) in values.items():
            self.db.connection.execute(
                """INSERT INTO baseline_run_metrics
                (run_id,dimension_type,dimension_value,metric_name,strategy_value,
                 baseline_value,lift_value,total_opportunities,strategy_scored,
                 baseline_scored,created_at_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, dimension_type, dimension_value, name, strategy,
                    baseline, lift, metrics.total_opportunities,
                    metrics.strategy_scored, metrics.baseline_scored, created_at_ms,
                ),
            )

    def run(
        self,
        *,
        run_id: str,
        strategy_version_id: str,
        baseline_id: str,
        opportunity_grouping_version: str,
        observations: Iterable[dict[str, Any]],
        created_at_ms: int,
    ) -> BaselineRunResult:
        baseline = self.db.connection.execute(
            "SELECT * FROM baseline_definitions WHERE baseline_id=? AND active=1",
            (baseline_id,),
        ).fetchone()
        if baseline is None:
            raise KeyError(f"active baseline not found: {baseline_id}")
        rule = json.loads(baseline["selection_rule_json"])
        rows: list[dict[str, Any]] = []
        for observation in observations:
            row = dict(observation)
            row["baseline_selected"] = self._select(rule, row.get("features") or {})
            for key in ("strategy_probability", "baseline_probability"):
                if row.get(key) is not None and not 0 <= float(row[key]) <= 1:
                    raise ValueError(f"{key} must be between 0 and 1")
            rows.append(row)
        overall = self._metrics(rows)
        by_date = {
            value: self._metrics([row for row in rows if row["trade_date"] == value])
            for value in sorted({row["trade_date"] for row in rows})
        }
        by_cluster = {
            value: self._metrics([
                row for row in rows if row["logic_cluster_id"] == value
            ])
            for value in sorted({row["logic_cluster_id"] for row in rows})
        }
        with self.db.transaction():
            self.db.connection.execute(
                """INSERT INTO baseline_comparison_runs
                (run_id,strategy_version_id,baseline_id,opportunity_grouping_version,
                 status,created_at_ms,completed_at_ms)
                VALUES (?,?,?,?,'running',?,NULL)""",
                (
                    run_id, strategy_version_id, baseline_id,
                    opportunity_grouping_version, created_at_ms,
                ),
            )
            for row in rows:
                self.db.connection.execute(
                    """INSERT INTO baseline_run_opportunities
                    (run_id,opportunity_id,trade_date,logic_cluster_id,features_json,
                     strategy_selected,baseline_selected,outcome_status,hit_net_3pct,
                     net_return_pct_points,strategy_probability_ratio,
                     baseline_probability_ratio,created_at_ms)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id, row["opportunity_id"], row["trade_date"],
                        row["logic_cluster_id"], json.dumps(row.get("features") or {}, sort_keys=True),
                        int(bool(row["strategy_selected"])), int(bool(row["baseline_selected"])),
                        row["outcome_status"],
                        None if row.get("hit_net_3pct") is None else int(bool(row["hit_net_3pct"])),
                        row.get("net_return_pct_points"), row.get("strategy_probability"),
                        row.get("baseline_probability"), created_at_ms,
                    ),
                )
            self._persist_metrics(run_id, "overall", "__all__", overall, created_at_ms)
            for value, metrics in by_date.items():
                self._persist_metrics(run_id, "trade_date", value, metrics, created_at_ms)
            for value, metrics in by_cluster.items():
                self._persist_metrics(run_id, "logic_cluster", value, metrics, created_at_ms)
            self.db.connection.execute(
                """UPDATE baseline_comparison_runs
                   SET status='completed',completed_at_ms=? WHERE run_id=?""",
                (created_at_ms, run_id),
            )
        return BaselineRunResult(run_id, overall, by_date, by_cluster)
