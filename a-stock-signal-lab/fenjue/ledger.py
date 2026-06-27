from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Any
from uuid import uuid4

from .v2db import FenjueV2Database


def price_to_x10000(value: str | int | float | Decimal) -> int:
    price = Decimal(str(value))
    if price <= 0:
        raise ValueError("price must be positive")
    return int((price * Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class PositionContext:
    total_qty: int
    sellable_qty: int
    core_floor_qty: int
    tactical_qty: int
    max_sellable_without_breaking_core: int


@dataclass(frozen=True)
class RiskPrecheck:
    status: str
    config_id: str | None
    max_incremental_exposure_ratio: float | None


class PositionLedger:
    def __init__(self, db: FenjueV2Database):
        self.db = db

    def ensure_account(
        self,
        account_id: str,
        name: str,
        equity_fen: int,
        trading_date: str,
        now_ms: int,
    ) -> None:
        if equity_fen < 0:
            raise ValueError("equity_fen must be non-negative")
        self.db.connection.execute(
            """
            INSERT INTO portfolio_accounts
                (account_id,name,base_currency,equity_fen,realized_pnl_today_fen,
                 trading_date,updated_at_ms,schema_version)
            VALUES (?,?, 'CNY', ?,0,?,?,2)
            ON CONFLICT(account_id) DO UPDATE SET
                name=excluded.name,
                equity_fen=excluded.equity_fen,
                trading_date=excluded.trading_date,
                updated_at_ms=excluded.updated_at_ms
            """,
            (account_id, name, equity_fen, trading_date, now_ms),
        )

    def set_position(
        self,
        account_id: str,
        code: str,
        mode: str,
        core_floor_qty: int,
        logic_cluster_id: str,
        reason: str,
        set_by: str,
        now_ms: int,
        thesis_id: str | None = None,
    ) -> None:
        if not logic_cluster_id:
            raise ValueError("logic_cluster_id is required")
        self.db.connection.execute(
            """
            INSERT INTO positions
                (account_id,code,mode,core_floor_qty,thesis_id,logic_cluster_id,
                 mode_reason,mode_set_by,updated_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(account_id,code) DO UPDATE SET
                mode=excluded.mode,
                core_floor_qty=excluded.core_floor_qty,
                thesis_id=excluded.thesis_id,
                logic_cluster_id=excluded.logic_cluster_id,
                mode_reason=excluded.mode_reason,
                mode_set_by=excluded.mode_set_by,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                account_id, code, mode, core_floor_qty, thesis_id, logic_cluster_id,
                reason, set_by, now_ms,
            ),
        )

    def record_buy_lot(
        self,
        account_id: str,
        code: str,
        role: str,
        buy_trade_date: str,
        buy_time_ms: int,
        quantity_qty: int,
        buy_price: str | int | float | Decimal,
        sellable_from_date: str,
        source: str,
        created_at_ms: int,
        lot_id: str | None = None,
    ) -> str:
        if quantity_qty <= 0:
            raise ValueError("quantity_qty must be positive")
        lot_id = lot_id or f"lot-{uuid4().hex}"
        self.db.connection.execute(
            """
            INSERT INTO position_lots
                (lot_id,account_id,code,role,buy_trade_date,buy_time_ms,
                 quantity_qty,remaining_qty,buy_price_x10000,sellable_from_date,
                 source,created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                lot_id, account_id, code, role, buy_trade_date, buy_time_ms,
                quantity_qty, quantity_qty, price_to_x10000(buy_price),
                sellable_from_date, source, created_at_ms,
            ),
        )
        return lot_id

    def position_context(
        self, account_id: str, code: str, trade_date: str
    ) -> PositionContext:
        position = self.db.connection.execute(
            "SELECT core_floor_qty FROM positions WHERE account_id=? AND code=?",
            (account_id, code),
        ).fetchone()
        if position is None:
            raise KeyError(f"position not found: {account_id}/{code}")
        rows = self.db.connection.execute(
            """
            SELECT role,remaining_qty,sellable_from_date
            FROM position_lots
            WHERE account_id=? AND code=? AND remaining_qty>0
            """,
            (account_id, code),
        ).fetchall()
        total = sum(row["remaining_qty"] for row in rows)
        sellable = sum(
            row["remaining_qty"]
            for row in rows
            if row["sellable_from_date"] <= trade_date
        )
        tactical = sum(
            row["remaining_qty"] for row in rows if row["role"] == "tactical"
        )
        core_floor = position["core_floor_qty"]
        return PositionContext(
            total_qty=total,
            sellable_qty=sellable,
            core_floor_qty=core_floor,
            tactical_qty=tactical,
            max_sellable_without_breaking_core=max(
                0, min(sellable, total - core_floor)
            ),
        )

    def authorize_quantity(
        self,
        context: PositionContext,
        requested_action: str,
        requested_qty: int,
        risk_max_increment_qty: int | None = None,
        confirmed_core_override: bool = False,
    ) -> int:
        if requested_qty <= 0:
            return 0
        if requested_action in {"ADD", "NEW_ENTRY", "TACTICAL_BUY"}:
            return 0 if risk_max_increment_qty is None else min(
                requested_qty, risk_max_increment_qty
            )
        if requested_action == "TACTICAL_SELL":
            return min(requested_qty, context.max_sellable_without_breaking_core)
        if requested_action in {"RISK_REDUCE", "EXIT"}:
            limit = (
                context.sellable_qty
                if confirmed_core_override
                else context.max_sellable_without_breaking_core
            )
            return min(requested_qty, limit)
        return 0

    def add_risk_budget(
        self,
        config_id: str,
        *,
        account_id: str | None,
        scope_type: str,
        scope_id: str | None,
        strategy_family: str | None,
        effective_from_ms: int,
        effective_to_ms: int | None,
        max_gross_exposure_ratio: float,
        max_single_symbol_ratio: float,
        max_logic_cluster_ratio: float,
        max_daily_loss_ratio: float,
        max_single_trade_loss_ratio: float,
        consecutive_failure_limit: int,
        retreat_exposure_multiplier_ratio: float,
        family_limits: dict[str, Any],
        created_at_ms: int,
    ) -> None:
        overlap = self.db.connection.execute(
            """
            SELECT config_id FROM risk_budget_configs
            WHERE COALESCE(account_id,'')=COALESCE(?, '')
              AND scope_type=?
              AND COALESCE(scope_id,'')=COALESCE(?, '')
              AND COALESCE(strategy_family,'')=COALESCE(?, '')
              AND effective_from_ms < COALESCE(?, 9223372036854775807)
              AND ? < COALESCE(effective_to_ms, 9223372036854775807)
            LIMIT 1
            """,
            (
                account_id, scope_type, scope_id, strategy_family,
                effective_to_ms, effective_from_ms,
            ),
        ).fetchone()
        if overlap:
            raise ValueError(f"risk budget overlaps {overlap['config_id']}")
        self.db.connection.execute(
            """
            INSERT INTO risk_budget_configs
                (config_id,account_id,scope_type,scope_id,strategy_family,
                 effective_from_ms,effective_to_ms,max_gross_exposure_ratio,
                 max_single_symbol_ratio,max_logic_cluster_ratio,max_daily_loss_ratio,
                 max_single_trade_loss_ratio,consecutive_failure_limit,
                 retreat_exposure_multiplier_ratio,family_limits_json,created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                config_id, account_id, scope_type, scope_id, strategy_family,
                effective_from_ms, effective_to_ms, max_gross_exposure_ratio,
                max_single_symbol_ratio, max_logic_cluster_ratio, max_daily_loss_ratio,
                max_single_trade_loss_ratio, consecutive_failure_limit,
                retreat_exposure_multiplier_ratio,
                json.dumps(family_limits, ensure_ascii=False, sort_keys=True), created_at_ms,
            ),
        )

    def risk_precheck(
        self,
        *,
        account_id: str,
        code: str,
        strategy_family: str,
        logic_cluster_id: str,
        at_ms: int,
        market_regime: str,
    ) -> RiskPrecheck:
        candidates = self.db.connection.execute(
            """
            SELECT * FROM risk_budget_configs
            WHERE effective_from_ms<=?
              AND (effective_to_ms IS NULL OR effective_to_ms>?)
              AND (account_id IS NULL OR account_id=?)
              AND (
                    scope_type IN ('global','account')
                 OR (scope_type='symbol' AND scope_id=?)
                 OR (scope_type='logic_cluster' AND scope_id=?)
                 OR (scope_type='strategy_family' AND scope_id=?)
              )
            """,
            (at_ms, at_ms, account_id, code, logic_cluster_id, strategy_family),
        ).fetchall()
        if not candidates:
            return RiskPrecheck("UNCONFIGURED", None, None)

        def applicable_limit(config) -> float:
            limits = [float(config["max_gross_exposure_ratio"])]
            if config["scope_type"] == "symbol":
                limits.append(float(config["max_single_symbol_ratio"]))
            elif config["scope_type"] == "logic_cluster":
                limits.append(float(config["max_logic_cluster_ratio"]))
            elif config["scope_type"] == "strategy_family":
                family_limits = json.loads(config["family_limits_json"] or "{}")
                if strategy_family in family_limits:
                    limits.append(float(family_limits[strategy_family]))
            limit = min(limits)
            if market_regime == "RETREAT":
                limit *= float(config["retreat_exposure_multiplier_ratio"])
            return limit

        constrained = [(applicable_limit(config), config) for config in candidates]
        limit, config = min(constrained, key=lambda item: item[0])
        return RiskPrecheck(
            "ELIGIBLE" if limit > 0 else "BLOCKED",
            config["config_id"],
            limit,
        )

    def record_reconciliation_incident(
        self,
        account_id: str,
        code: str,
        details: dict[str, Any],
        now_ms: int,
    ) -> dict[str, Any]:
        incident_id = f"ledger-incident-{uuid4().hex}"
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO ledger_incidents
                    (incident_id,account_id,code,incident_type,severity,details_json,
                     forced_mode,detected_at_ms)
                VALUES (?,?,?,'POSITION_RECONCILIATION_FAILED','critical',?,'OBSERVE',?)
                """,
                (incident_id, account_id, code, json.dumps(details, sort_keys=True), now_ms),
            )
            connection.execute(
                """
                UPDATE positions SET mode='OBSERVE',mode_reason=?,mode_set_by='system',
                    updated_at_ms=? WHERE account_id=? AND code=?
                """,
                (f"ledger incident {incident_id}", now_ms, account_id, code),
            )
        row = self.db.connection.execute(
            "SELECT * FROM ledger_incidents WHERE incident_id=?", (incident_id,)
        ).fetchone()
        return dict(row)

    def snapshot_position(
        self,
        account_id: str,
        code: str,
        trade_date: str,
        market_price: str | int | float | Decimal,
        captured_at_ms: int,
        risk_config_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> str:
        snapshot_id = snapshot_id or f"position-snapshot-{uuid4().hex}"
        context = self.position_context(account_id, code, trade_date)
        position = self.db.connection.execute(
            "SELECT mode,logic_cluster_id FROM positions WHERE account_id=? AND code=?",
            (account_id, code),
        ).fetchone()
        account = self.db.connection.execute(
            "SELECT equity_fen FROM portfolio_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        lots = self.db.connection.execute(
            "SELECT remaining_qty,buy_price_x10000 FROM position_lots "
            "WHERE account_id=? AND code=? AND remaining_qty>0",
            (account_id, code),
        ).fetchall()
        average = (
            sum(row["remaining_qty"] * row["buy_price_x10000"] for row in lots)
            // context.total_qty
            if context.total_qty else 0
        )
        market_price_x10000 = price_to_x10000(market_price)
        market_value_fen = context.total_qty * market_price_x10000 // 100
        equity = account["equity_fen"]
        symbol_ratio = market_value_fen / equity if equity else 0.0
        self.db.connection.execute(
            """
            INSERT INTO position_snapshots
                (snapshot_id,account_id,code,logic_cluster_id,mode,total_qty,
                 sellable_qty,core_floor_qty,tactical_qty,average_cost_price_x10000,
                 market_value_fen,account_equity_fen,symbol_exposure_ratio,
                 cluster_exposure_ratio,risk_config_id,captured_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                snapshot_id, account_id, code, position["logic_cluster_id"],
                position["mode"], context.total_qty, context.sellable_qty,
                context.core_floor_qty, context.tactical_qty, average,
                market_value_fen, equity, symbol_ratio, symbol_ratio,
                risk_config_id, captured_at_ms,
            ),
        )
        return snapshot_id
