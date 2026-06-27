from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from uuid import uuid4

from .ledger import RiskPrecheck
from .v2db import FenjueV2Database


@dataclass(frozen=True)
class BudgetDecision:
    consumption_id: str
    status: str
    authorized_fen: int
    reason_codes: tuple[str, ...]


def _ratio_amount(equity_fen: int, ratio: float) -> int:
    return int(Decimal(equity_fen) * Decimal(str(ratio)))


class PortfolioBudgetService:
    def __init__(self, db: FenjueV2Database):
        self.db = db

    def open_budget(
        self,
        *,
        budget_id: str,
        risk_config_id: str,
        trade_date: str,
        market_regime: str,
        initial_gross_exposure_fen: int,
        cluster_exposures_fen: dict[str, int],
        now_ms: int,
    ) -> str:
        config = self.db.connection.execute(
            "SELECT * FROM risk_budget_configs WHERE config_id=?",
            (risk_config_id,),
        ).fetchone()
        if config is None or config["account_id"] is None:
            raise ValueError("portfolio budget requires an account-scoped confirmed config")
        if not (
            config["effective_from_ms"] <= now_ms
            and (config["effective_to_ms"] is None or config["effective_to_ms"] > now_ms)
        ):
            raise ValueError("risk config is not effective at budget open time")
        account = self.db.connection.execute(
            "SELECT equity_fen FROM portfolio_accounts WHERE account_id=?",
            (config["account_id"],),
        ).fetchone()
        if account is None or account["equity_fen"] <= 0:
            raise ValueError("account equity must be positive")
        equity = account["equity_fen"]
        multiplier = (
            float(config["retreat_exposure_multiplier_ratio"])
            if market_regime == "RETREAT" else 1.0
        )
        with self.db.transaction():
            self.db.connection.execute(
                """INSERT INTO portfolio_budget
                (budget_id,risk_config_id,account_id,trade_date,market_regime,
                 regime_multiplier_ratio,equity_fen,gross_limit_fen,
                 single_symbol_limit_fen,default_cluster_limit_fen,
                 daily_loss_limit_fen,gross_consumed_fen,realized_loss_fen,
                 consecutive_failures,consecutive_failure_limit,status,
                 created_at_ms,updated_at_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,'ACTIVE',?,?)""",
                (
                    budget_id, risk_config_id, config["account_id"], trade_date,
                    market_regime, multiplier, equity,
                    _ratio_amount(equity, float(config["max_gross_exposure_ratio"]) * multiplier),
                    _ratio_amount(equity, float(config["max_single_symbol_ratio"]) * multiplier),
                    _ratio_amount(equity, float(config["max_logic_cluster_ratio"]) * multiplier),
                    _ratio_amount(equity, float(config["max_daily_loss_ratio"])),
                    initial_gross_exposure_fen, config["consecutive_failure_limit"],
                    now_ms, now_ms,
                ),
            )
            for cluster_id, exposure in cluster_exposures_fen.items():
                self.db.connection.execute(
                    """INSERT INTO logic_cluster_exposure
                    (budget_id,logic_cluster_id,exposure_limit_fen,
                     consumed_exposure_fen,updated_at_ms)
                    SELECT budget_id,?,default_cluster_limit_fen,?,?
                    FROM portfolio_budget WHERE budget_id=?""",
                    (cluster_id, exposure, now_ms, budget_id),
                )
        return budget_id

    def _decision(self, row) -> BudgetDecision:
        amount = (
            row["final_authorized_fen"]
            if row["final_authorized_fen"] is not None
            else row["precheck_cap_fen"]
        )
        return BudgetDecision(
            row["consumption_id"], row["status"], amount,
            tuple(json.loads(row["reason_codes_json"])),
        )

    def _ensure_cluster(self, budget_id: str, cluster_id: str, at_ms: int):
        self.db.connection.execute(
            """INSERT INTO logic_cluster_exposure
            (budget_id,logic_cluster_id,exposure_limit_fen,consumed_exposure_fen,updated_at_ms)
            SELECT budget_id,?,default_cluster_limit_fen,0,?
            FROM portfolio_budget WHERE budget_id=?
            ON CONFLICT(budget_id,logic_cluster_id) DO NOTHING""",
            (cluster_id, at_ms, budget_id),
        )
        return self.db.connection.execute(
            """SELECT * FROM logic_cluster_exposure
               WHERE budget_id=? AND logic_cluster_id=?""",
            (budget_id, cluster_id),
        ).fetchone()

    def _recorded_symbol_exposure(self, budget_id: str, code: str) -> int:
        return self.db.connection.execute(
            """SELECT COALESCE(SUM(final_authorized_fen-released_fen),0)
               FROM budget_consumption
               WHERE budget_id=? AND code=?
                 AND status IN ('CONSUMED','PARTIALLY_RELEASED')""",
            (budget_id, code),
        ).fetchone()[0]

    @staticmethod
    def _capacity(
        budget, cluster, symbol_exposure_fen: int
    ) -> tuple[int, list[str]]:
        reasons: list[str] = []
        if budget["status"] != "ACTIVE":
            reasons.append("BUDGET_NOT_ACTIVE")
        if budget["realized_loss_fen"] >= budget["daily_loss_limit_fen"]:
            reasons.append("DAILY_LOSS_LIMIT")
        if budget["consecutive_failures"] >= budget["consecutive_failure_limit"]:
            reasons.append("FAILURE_STREAK_LIMIT")
        gross = max(0, budget["gross_limit_fen"] - budget["gross_consumed_fen"])
        symbol = max(0, budget["single_symbol_limit_fen"] - symbol_exposure_fen)
        cluster_remaining = max(
            0, cluster["exposure_limit_fen"] - cluster["consumed_exposure_fen"]
        )
        if gross == 0:
            reasons.append("GROSS_LIMIT")
        if symbol == 0:
            reasons.append("SYMBOL_LIMIT")
        if cluster_remaining == 0:
            reasons.append("CLUSTER_LIMIT")
        if reasons:
            return 0, reasons
        return min(gross, symbol, cluster_remaining), []

    def precheck(
        self,
        *,
        budget_id: str,
        code: str,
        logic_cluster_id: str,
        strategy_family: str,
        requested_fen: int,
        current_symbol_exposure_fen: int,
        idempotency_key: str,
        at_ms: int,
        decision_id: str | None = None,
    ) -> BudgetDecision:
        if requested_fen <= 0 or current_symbol_exposure_fen < 0:
            raise ValueError("requested and current exposure amounts are invalid")
        existing = self.db.connection.execute(
            "SELECT * FROM budget_consumption WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            return self._decision(existing)
        consumption_id = f"budget-use-{uuid4().hex}"
        with self.db.transaction():
            budget = self.db.connection.execute(
                "SELECT * FROM portfolio_budget WHERE budget_id=?", (budget_id,)
            ).fetchone()
            if budget is None:
                raise KeyError(f"unknown portfolio budget: {budget_id}")
            cluster = self._ensure_cluster(budget_id, logic_cluster_id, at_ms)
            recorded = self._recorded_symbol_exposure(budget_id, code)
            symbol_exposure = max(current_symbol_exposure_fen, recorded)
            capacity, reasons = self._capacity(budget, cluster, symbol_exposure)
            cap = min(requested_fen, capacity)
            status = "ELIGIBLE" if cap > 0 else "BLOCKED"
            self.db.connection.execute(
                """INSERT INTO budget_consumption
                (consumption_id,idempotency_key,budget_id,decision_id,code,
                 logic_cluster_id,strategy_family,requested_fen,
                 symbol_exposure_at_precheck_fen,precheck_cap_fen,
                 final_authorized_fen,status,reason_codes_json,prechecked_at_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,?)""",
                (
                    consumption_id, idempotency_key, budget_id, decision_id, code,
                    logic_cluster_id, strategy_family, requested_fen,
                    current_symbol_exposure_fen, cap, status,
                    json.dumps(reasons), at_ms,
                ),
            )
        row = self.db.connection.execute(
            "SELECT * FROM budget_consumption WHERE consumption_id=?",
            (consumption_id,),
        ).fetchone()
        return self._decision(row)

    def consume(
        self,
        consumption_id: str,
        *,
        requested_fen: int,
        current_symbol_exposure_fen: int,
        at_ms: int,
    ) -> BudgetDecision:
        with self.db.transaction():
            row = self.db.connection.execute(
                "SELECT * FROM budget_consumption WHERE consumption_id=?",
                (consumption_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown budget consumption: {consumption_id}")
            if row["status"] != "ELIGIBLE":
                return self._decision(row)
            budget = self.db.connection.execute(
                "SELECT * FROM portfolio_budget WHERE budget_id=?",
                (row["budget_id"],),
            ).fetchone()
            cluster = self._ensure_cluster(
                row["budget_id"], row["logic_cluster_id"], at_ms
            )
            recorded = self._recorded_symbol_exposure(row["budget_id"], row["code"])
            capacity, reasons = self._capacity(
                budget, cluster, max(current_symbol_exposure_fen, recorded)
            )
            amount = min(
                requested_fen, row["precheck_cap_fen"], capacity
            )
            if amount <= 0:
                self.db.connection.execute(
                    """UPDATE budget_consumption
                       SET final_authorized_fen=0,status='BLOCKED_FINAL',
                           reason_codes_json=?,consumed_at_ms=?
                       WHERE consumption_id=?""",
                    (json.dumps(reasons or ["CAPACITY_CHANGED"]), at_ms, consumption_id),
                )
            else:
                self.db.connection.execute(
                    """UPDATE portfolio_budget
                       SET gross_consumed_fen=gross_consumed_fen+?,updated_at_ms=?
                       WHERE budget_id=?""",
                    (amount, at_ms, row["budget_id"]),
                )
                self.db.connection.execute(
                    """UPDATE logic_cluster_exposure
                       SET consumed_exposure_fen=consumed_exposure_fen+?,updated_at_ms=?
                       WHERE budget_id=? AND logic_cluster_id=?""",
                    (amount, at_ms, row["budget_id"], row["logic_cluster_id"]),
                )
                final_reasons = reasons + (["FINAL_CAP_REDUCED"] if amount < requested_fen else [])
                self.db.connection.execute(
                    """UPDATE budget_consumption
                       SET final_authorized_fen=?,status='CONSUMED',
                           reason_codes_json=?,consumed_at_ms=?
                       WHERE consumption_id=?""",
                    (amount, json.dumps(final_reasons), at_ms, consumption_id),
                )
            result = self.db.connection.execute(
                "SELECT * FROM budget_consumption WHERE consumption_id=?",
                (consumption_id,),
            ).fetchone()
        return self._decision(result)

    def as_risk_precheck(self, decision: BudgetDecision, equity_fen: int) -> RiskPrecheck:
        return RiskPrecheck(
            "ELIGIBLE" if decision.status == "ELIGIBLE" else "BLOCKED",
            decision.consumption_id,
            decision.authorized_fen / equity_fen if equity_fen > 0 else 0.0,
        )
