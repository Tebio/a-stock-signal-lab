from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import sqlite3
from zoneinfo import ZoneInfo

from .execution import CostModel, score_new_entry
from .trading_calendar import TradingCalendar
from .v2db import FenjueV2Database


SHANGHAI = ZoneInfo("Asia/Shanghai")
CHECKPOINTS = ("09:25", "09:40", "10:30", "14:30")


@dataclass(frozen=True)
class BackfillResult:
    outcome_id: str
    intent_id: str
    next_trade_date: str
    outcome_status: str
    hit_net_3pct: bool | None
    net_return_pct_points: float | None
    unscorable_reason: str | None


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


class IntradayOutcomeBackfiller:
    def __init__(self, db: FenjueV2Database, max_lookback_ms: int = 300_000):
        self.db = db
        self.calendar = TradingCalendar(db.connection)
        self.max_lookback_ms = max_lookback_ms

    def _existing(self, intent_id: str, version: str) -> BackfillResult | None:
        row = self.db.connection.execute(
            """SELECT outcome_id,intent_id,next_trade_date,outcome_status,
                      hit_net_3pct,net_return_pct_points,unscorable_reason
               FROM intraday_outcomes
               WHERE intent_id=? AND calculation_version=?""",
            (intent_id, version),
        ).fetchone()
        if row is None:
            return None
        return BackfillResult(
            row["outcome_id"], row["intent_id"], row["next_trade_date"],
            row["outcome_status"],
            None if row["hit_net_3pct"] is None else bool(row["hit_net_3pct"]),
            row["net_return_pct_points"], row["unscorable_reason"],
        )

    def _select_bar(
        self, code: str, target_ms: int, calculated_at_ms: int
    ) -> tuple[sqlite3.Row | None, str]:
        row = self.db.connection.execute(
            """SELECT * FROM market_bars
               WHERE code=? AND bar_time_ms BETWEEN ? AND ?
                 AND available_at_ms<=? AND quality<>'U'
               ORDER BY bar_time_ms DESC,
                        CASE quality WHEN 'A' THEN 1 WHEN 'B' THEN 2
                                     WHEN 'C' THEN 3 WHEN 'D' THEN 4 ELSE 5 END,
                        source ASC
               LIMIT 1""",
            (code, target_ms - self.max_lookback_ms, target_ms, calculated_at_ms),
        ).fetchone()
        if row is not None:
            return row, "selected"
        later = self.db.connection.execute(
            """SELECT 1 FROM market_bars
               WHERE code=? AND bar_time_ms BETWEEN ? AND ?
                 AND available_at_ms>? LIMIT 1""",
            (code, target_ms - self.max_lookback_ms, target_ms, calculated_at_ms),
        ).fetchone()
        return None, "not_yet_available" if later else "missing"

    def _cost_model(self, intent: sqlite3.Row) -> CostModel | None:
        if not intent["cost_model_id"]:
            return None
        row = self.db.connection.execute(
            "SELECT * FROM cost_models WHERE cost_model_id=?",
            (intent["cost_model_id"],),
        ).fetchone()
        if row is None:
            return None
        return CostModel(
            row["commission_bps"], row["min_commission_fen"],
            row["sell_stamp_duty_bps"], row["transfer_fee_bps"],
            row["default_slippage_bps"],
        )

    def backfill_intent(
        self,
        intent_id: str,
        *,
        calculation_version: str,
        calculated_at_ms: int,
    ) -> BackfillResult:
        existing = self._existing(intent_id, calculation_version)
        if existing:
            return existing
        intent = self.db.connection.execute(
            "SELECT * FROM trade_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if intent is None:
            raise KeyError(f"unknown trade intent: {intent_id}")
        signal_date = datetime.fromtimestamp(
            intent["intended_at_ms"] / 1000, tz=SHANGHAI
        ).date().isoformat()
        next_date = self.calendar.next_trade_date(signal_date)
        targets = self.calendar.checkpoints(next_date)
        cost_model = self._cost_model(intent)
        selected: dict[str, sqlite3.Row | None] = {}
        labels: dict[str, dict[str, object]] = {}

        with self.db.transaction():
            for checkpoint in CHECKPOINTS:
                target_ms = targets[checkpoint]
                bar, selection_status = self._select_bar(
                    intent["code"], target_ms, calculated_at_ms
                )
                selected[checkpoint] = bar
                audit_id = _stable_id(
                    "bar-audit", intent_id, checkpoint, calculation_version
                )
                reason = {
                    "selected": "LATEST_AS_SEEN_BAR_WITHIN_5M",
                    "not_yet_available": "BAR_EXISTED_BUT_NOT_AS_SEEN_AT_CALCULATION",
                    "missing": "NO_BAR_WITHIN_5M",
                }[selection_status]
                self.db.connection.execute(
                    """INSERT INTO market_bars_audit
                    (audit_id,intent_id,code,checkpoint,checkpoint_trade_date,
                     checkpoint_at_ms,selected_bar_time_ms,selected_scale_seconds,
                     selected_source,selected_price_x10000,selected_available_at_ms,
                     selected_quality,selection_status,selection_reason,
                     calculation_version,audited_at_ms)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        audit_id, intent_id, intent["code"], checkpoint, next_date,
                        target_ms, None if bar is None else bar["bar_time_ms"],
                        None if bar is None else bar["scale_seconds"],
                        None if bar is None else bar["source"],
                        None if bar is None else bar["close_price_x10000"],
                        None if bar is None else bar["available_at_ms"],
                        None if bar is None else bar["quality"], selection_status,
                        reason, calculation_version, calculated_at_ms,
                    ),
                )
                label: dict[str, object] = {
                    "status": "unscorable",
                    "reason": reason,
                    "gross": None,
                    "net": None,
                    "hit": None,
                }
                if (
                    bar is not None
                    and intent["intended_price_x10000"]
                    and intent["intended_qty"]
                    and cost_model is not None
                ):
                    score = score_new_entry(
                        entry_price_x10000=intent["intended_price_x10000"],
                        exit_price_x10000=bar["close_price_x10000"],
                        quantity_qty=intent["intended_qty"],
                        cost_model=cost_model,
                    )
                    label.update(
                        status="scored", reason=None,
                        gross=score.gross_return_pct_points,
                        net=score.net_return_pct_points,
                        hit=score.hit_net_3pct,
                    )
                elif bar is not None:
                    label["reason"] = "MISSING_ENTRY_QTY_OR_COST_MODEL"
                labels[checkpoint] = label
                self.db.connection.execute(
                    """INSERT INTO intraday_checkpoint_labels
                    (label_id,intent_id,audit_id,checkpoint,checkpoint_trade_date,
                     checkpoint_at_ms,reference_price_x10000,gross_return_pct_points,
                     net_return_pct_points,hit_net_3pct,status,unscorable_reason,
                     calculation_version,calculated_at_ms)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _stable_id("checkpoint", intent_id, checkpoint, calculation_version),
                        intent_id, audit_id, checkpoint, next_date, target_ms,
                        None if bar is None else bar["close_price_x10000"],
                        label["gross"], label["net"],
                        None if label["hit"] is None else int(bool(label["hit"])),
                        label["status"], label["reason"], calculation_version,
                        calculated_at_ms,
                    ),
                )

            ten_thirty = selected["10:30"]
            ten_label = labels["10:30"]
            scored = ten_label["status"] == "scored"
            outcome_status = "scored" if scored else "unscorable"
            unscorable_reason = None if scored else (
                "NO_TRADABLE_1030_PRICE" if ten_thirty is None
                else str(ten_label["reason"])
            )
            path_rows = self.db.connection.execute(
                """SELECT * FROM market_bars
                   WHERE code=? AND bar_time_ms BETWEEN ? AND ?
                     AND available_at_ms<=? AND quality<>'U'
                   ORDER BY bar_time_ms""",
                (
                    intent["code"], intent["intended_at_ms"], targets["10:30"],
                    calculated_at_ms,
                ),
            ).fetchall()
            entry = intent["intended_price_x10000"]
            mfe_row = max(path_rows, key=lambda row: row["high_price_x10000"], default=None)
            mae_row = min(path_rows, key=lambda row: row["low_price_x10000"], default=None)
            mfe = ((mfe_row["high_price_x10000"] / entry - 1) * 100) if mfe_row and entry else None
            mae = ((mae_row["low_price_x10000"] / entry - 1) * 100) if mae_row and entry else None
            auction = selected["09:25"]
            next_open_return = (
                (auction["close_price_x10000"] / entry - 1) * 100
                if auction is not None and entry else None
            )
            open_to_1030 = (
                (ten_thirty["close_price_x10000"] / auction["close_price_x10000"] - 1) * 100
                if auction is not None and ten_thirty is not None else None
            )
            source_ids = [
                f"{row['source']}:{row['bar_time_ms']}:{row['scale_seconds']}"
                for row in selected.values() if row is not None
            ]
            outcome_id = _stable_id("outcome", intent_id, calculation_version)
            self.db.connection.execute(
                """INSERT INTO intraday_outcomes
                (outcome_id,intent_id,code,logic_cluster_id,strategy_family,
                 signal_trade_date,entry_time_ms,entry_price_x10000,entry_quality,
                 next_trade_date,evaluation_end_ms,exit_reference_price_x10000,
                 exit_price_quality,gross_return_pct_points,net_return_pct_points,
                 hit_net_3pct,mfe_pct_points,mfe_at_ms,mae_pct_points,mae_at_ms,
                 next_open_return_pct_points,open_to_1030_return_pct_points,
                 outcome_status,unscorable_reason,source_bar_ids_json,
                 calculated_at_ms,calculation_version)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    outcome_id, intent_id, intent["code"], intent["logic_cluster_id"],
                    intent["strategy_family"], signal_date, intent["intended_at_ms"],
                    entry, intent["entry_price_source"], next_date, targets["10:30"],
                    None if ten_thirty is None else ten_thirty["close_price_x10000"],
                    None if ten_thirty is None else ten_thirty["quality"],
                    ten_label["gross"], ten_label["net"],
                    None if ten_label["hit"] is None else int(bool(ten_label["hit"])),
                    mfe, None if mfe_row is None else mfe_row["bar_time_ms"],
                    mae, None if mae_row is None else mae_row["bar_time_ms"],
                    next_open_return, open_to_1030, outcome_status,
                    unscorable_reason, json.dumps(source_ids), calculated_at_ms,
                    calculation_version,
                ),
            )
        result = self._existing(intent_id, calculation_version)
        assert result is not None
        return result
