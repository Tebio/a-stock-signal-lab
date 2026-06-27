from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable
from uuid import uuid4

from .v2db import FenjueV2Database


@dataclass(frozen=True)
class CostModel:
    commission_bps: int
    min_commission_fen: int
    sell_stamp_duty_bps: int
    transfer_fee_bps: int
    default_slippage_bps: int


@dataclass(frozen=True)
class MarketState:
    quality: str
    suspended: bool
    price_limit_state: str
    ask_liquidity_qty: int
    bid_liquidity_qty: int
    conservative_price_x10000: int | None


@dataclass(frozen=True)
class FillAssessment:
    fill_status: str
    data_quality: str
    reason_code: str
    conservative_fill_price_x10000: int | None = None
    estimated_fill_probability_ratio: float | None = None


@dataclass(frozen=True)
class BarrierOutcome:
    status: str
    hit_at_ms: int | None = None


@dataclass(frozen=True)
class NewEntryScore:
    gross_return_pct_points: float
    net_return_pct_points: float
    hit_net_3pct: bool
    total_cost_fen: int


def _bps_cost(notional_fen: int, bps: int) -> int:
    if bps <= 0:
        return 0
    return (notional_fen * bps + 9999) // 10000


def assess_fill(side: str, market: MarketState) -> FillAssessment:
    if market.suspended:
        return FillAssessment("not_fillable", "U", "SUSPENDED")
    if side == "buy" and market.price_limit_state == "limit_up":
        if market.quality in {"A", "B"} and market.ask_liquidity_qty > 0:
            return FillAssessment(
                "fillable", market.quality, "LIMIT_UP_ASK_AVAILABLE",
                market.conservative_price_x10000, 0.5,
            )
        return FillAssessment(
            "unknown", market.quality, "LIMIT_UP_BUY_QUEUE_UNKNOWN"
        )
    if side == "sell" and market.price_limit_state == "limit_down":
        if market.quality in {"A", "B"} and market.bid_liquidity_qty > 0:
            return FillAssessment(
                "fillable", market.quality, "LIMIT_DOWN_BID_AVAILABLE",
                market.conservative_price_x10000, 0.5,
            )
        return FillAssessment(
            "unknown", market.quality, "LIMIT_DOWN_SELL_QUEUE_UNKNOWN"
        )
    if market.quality == "U" or market.conservative_price_x10000 is None:
        return FillAssessment("unknown", market.quality, "NO_TRADABLE_PRICE")
    return FillAssessment(
        "fillable", market.quality, "CONSERVATIVE_PRICE_AVAILABLE",
        market.conservative_price_x10000, None,
    )


def first_barrier_outcome(
    bars: Iterable[dict[str, Any]],
    *,
    take_profit_price_x10000: int,
    stop_price_x10000: int,
    data_quality: str,
) -> BarrierOutcome:
    for bar in sorted(bars, key=lambda item: item["time_ms"]):
        hit_take_profit = bar["high_price_x10000"] >= take_profit_price_x10000
        hit_stop = bar["low_price_x10000"] <= stop_price_x10000
        if hit_take_profit and hit_stop:
            sequence = bar.get("first_hit")
            if data_quality == "A" and sequence in {"take_profit", "stop_loss"}:
                return BarrierOutcome(sequence, bar["time_ms"])
            return BarrierOutcome("ambiguous", bar["time_ms"])
        if hit_take_profit:
            return BarrierOutcome("take_profit", bar["time_ms"])
        if hit_stop:
            return BarrierOutcome("stop_loss", bar["time_ms"])
    return BarrierOutcome("none", None)


def resolve_1030_price(
    bars: Iterable[dict[str, Any]],
    *,
    target_ms: int,
    max_lookback_ms: int = 300_000,
) -> int | None:
    candidates = [
        bar for bar in bars
        if bar["time_ms"] <= target_ms
        and target_ms - bar["time_ms"] <= max_lookback_ms
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["time_ms"])["close_price_x10000"]


def score_new_entry(
    *,
    entry_price_x10000: int,
    exit_price_x10000: int,
    quantity_qty: int,
    cost_model: CostModel,
) -> NewEntryScore:
    if min(entry_price_x10000, exit_price_x10000, quantity_qty) <= 0:
        raise ValueError("prices and quantity must be positive")
    buy_notional_fen = entry_price_x10000 * quantity_qty // 100
    sell_notional_fen = exit_price_x10000 * quantity_qty // 100
    buy_commission = max(
        cost_model.min_commission_fen,
        _bps_cost(buy_notional_fen, cost_model.commission_bps),
    )
    sell_commission = max(
        cost_model.min_commission_fen,
        _bps_cost(sell_notional_fen, cost_model.commission_bps),
    )
    transfer = _bps_cost(
        buy_notional_fen + sell_notional_fen,
        cost_model.transfer_fee_bps,
    )
    stamp = _bps_cost(sell_notional_fen, cost_model.sell_stamp_duty_bps)
    total_cost = buy_commission + sell_commission + transfer + stamp
    gross = (sell_notional_fen - buy_notional_fen) / buy_notional_fen * 100
    net = (
        sell_notional_fen - buy_notional_fen - total_cost
    ) / buy_notional_fen * 100
    return NewEntryScore(gross, net, net >= 3.0, total_cost)


class ExecutionStore:
    def __init__(self, db: FenjueV2Database):
        self.db = db

    def add_cost_model(
        self,
        cost_model_id: str,
        model: CostModel,
        effective_from_ms: int,
        created_at_ms: int,
        effective_to_ms: int | None = None,
    ) -> None:
        self.db.connection.execute(
            """
            INSERT INTO cost_models
                (cost_model_id,effective_from_ms,effective_to_ms,commission_bps,
                 min_commission_fen,sell_stamp_duty_bps,transfer_fee_bps,
                 default_slippage_bps,created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                cost_model_id, effective_from_ms, effective_to_ms,
                model.commission_bps, model.min_commission_fen,
                model.sell_stamp_duty_bps, model.transfer_fee_bps,
                model.default_slippage_bps, created_at_ms,
            ),
        )

    def create_intent(
        self,
        *,
        decision_id: str,
        account_id: str,
        code: str,
        logic_cluster_id: str,
        strategy_family: str,
        side: str,
        intended_at_ms: int,
        entry_price_source: str,
        status: str,
        intended_price_x10000: int | None = None,
        intended_qty: int | None = None,
        cost_model_id: str | None = None,
        target_net_return_pct_points: float | None = None,
        stop_price_x10000: int | None = None,
        hard_loss_cap_pct_points: float | None = None,
        intent_id: str | None = None,
    ) -> str:
        intent_id = intent_id or f"intent-{uuid4().hex}"
        self.db.connection.execute(
            """
            INSERT INTO trade_intents
                (intent_id,decision_id,account_id,code,logic_cluster_id,
                 strategy_family,side,intended_at_ms,intended_price_x10000,
                 intended_qty,entry_price_source,cost_model_id,
                 target_net_return_pct_points,stop_price_x10000,
                 hard_loss_cap_pct_points,status,created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                intent_id, decision_id, account_id, code, logic_cluster_id,
                strategy_family, side, intended_at_ms, intended_price_x10000,
                intended_qty, entry_price_source, cost_model_id,
                target_net_return_pct_points, stop_price_x10000,
                hard_loss_cap_pct_points, status, intended_at_ms,
            ),
        )
        return intent_id

    def record_assessment(
        self,
        intent_id: str,
        logic_cluster_id: str,
        result: FillAssessment,
        *,
        assessed_at_ms: int,
        model_version: str,
        policy_version: str,
        source_selection_policy_version: str,
        selected_market_source: str | None,
        selected_orderbook_source: str | None,
        source_snapshot_ids: list[str],
    ) -> str:
        assessment_id = f"assessment-{uuid4().hex}"
        self.db.connection.execute(
            """
            INSERT INTO execution_assessments
                (assessment_id,intent_id,logic_cluster_id,assessed_at_ms,
                 assessment_model_version,policy_version,
                 source_selection_policy_version,selected_market_source,
                 selected_orderbook_source,data_quality,fill_status,
                 conservative_fill_price_x10000,estimated_fill_probability_ratio,
                 price_limit_state,reason_codes_json,source_snapshot_ids_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                assessment_id, intent_id, logic_cluster_id, assessed_at_ms,
                model_version, policy_version, source_selection_policy_version,
                selected_market_source, selected_orderbook_source,
                result.data_quality, result.fill_status,
                result.conservative_fill_price_x10000,
                result.estimated_fill_probability_ratio, "unknown",
                json.dumps([result.reason_code]),
                json.dumps(source_snapshot_ids),
            ),
        )
        return assessment_id
