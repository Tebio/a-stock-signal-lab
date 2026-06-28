from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .pool import validate_pool_date
from .service import is_main_board, normalize_code
from .trading_calendar import TradingCalendar


def load_pool_codes(pool_file: str | Path) -> list[str]:
    path = Path(pool_file)
    validate_pool_date(path, today=datetime.now().date())
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    codes = []
    for row in payload.get("results", []):
        code = normalize_code(row.get("code", ""))
        if is_main_board(code) and code not in codes:
            codes.append(code)
    return codes


def strategy_b_candidates(
    pool_rows: list[dict],
    quotes: dict[str, dict],
) -> list[dict]:
    """Build causal 09:25 research candidates without claiming a stable edge."""
    main_rows = [
        row
        for row in pool_rows
        if is_main_board(normalize_code(row.get("code", "")))
    ]
    sector_counts = Counter(
        str(row.get("sector") or "未分类") for row in main_rows
    )
    candidates = []
    for row in main_rows:
        code = normalize_code(row.get("code", ""))
        quote = quotes.get(code) or {}
        opening = float(quote.get("open") or 0)
        previous_close = float(quote.get("prev_close") or 0)
        if not opening or not previous_close:
            continue
        opening_gap = (opening - previous_close) / previous_close * 100
        sector = str(row.get("sector") or "未分类")
        if not (
            -5 <= opening_gap <= -2
            and sector_counts[sector] >= 3
            and row.get("line_signal") in {"MA5", "MA20"}
        ):
            continue
        candidates.append(
            {
                "code": code,
                "name": quote.get("name") or row.get("name") or code,
                "sector": sector,
                "sector_breadth": sector_counts[sector],
                "line_signal": row.get("line_signal"),
                "opening_gap_pct": opening_gap,
                "entry_price": opening,
                "validated": False,
                "status": "研究候选",
                "validation_note": (
                    "旧案例仅11个样本，不沿用91%为稳定胜率；"
                    "从真实09:25快照重新积累。"
                ),
            }
        )
    return candidates


def capture_pool_snapshot(
    runtime,
    quotes,
    pool_file: str | Path,
    *,
    now: datetime | None = None,
    output_dir: str | Path,
    calendar: TradingCalendar | None = None,
) -> dict:
    now = now or datetime.now()
    codes = load_pool_codes(pool_file)
    pool_payload = json.loads(Path(pool_file).read_text(encoding="utf-8-sig"))
    pool_rows = pool_payload.get("results", [])
    result = quotes.get_quotes(codes)
    quote_map = result.get("quotes", {})
    quote_rows = list(quote_map.values())
    is_trade_day = (
        calendar.is_trade_day(now.date().isoformat())
        if calendar is not None
        else TradingCalendar.compatibility_is_weekday(now.date())
    )
    is_live_window = (
        is_trade_day
        and now.hour == 9
        and 24 <= now.minute <= 26
    )
    quote_dates = {
        str(row.get("trade_date", "")).replace("-", "")
        for row in quote_rows
        if row.get("trade_date")
    }
    expected_date = now.strftime("%Y%m%d")
    accepted = is_live_window and quote_dates == {expected_date}
    tag = "0925" if accepted else f"manual_{now.strftime('%H%M%S')}"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"snapshot_{expected_date}_{tag}.json"
    payload = {
        "created_at": now.isoformat(timespec="seconds"),
        "tag": tag,
        "pool": Path(pool_file).name,
        "accepted_for_validation": accepted,
        "count": len(quote_rows),
        "quotes": {row["code"]: row for row in quote_rows},
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if accepted:
        runtime.upsert_quote_snapshots(
            quote_rows,
            trade_date=now.date().isoformat(),
            quote_time="09:25",
        )
        candidates = strategy_b_candidates(pool_rows, quote_map)
        for candidate in candidates:
            runtime.record_signal(
                candidate["code"],
                "strategy_b_auction",
                now.date().isoformat(),
                candidate,
            )
    else:
        candidates = []
    return {**payload, "path": path, "strategy_b_candidates": candidates}


def scan_pool_regime_shifts(engine, pool_file: str | Path) -> dict:
    codes = load_pool_codes(pool_file)
    payload = engine.analyze_many(codes, include_intraday=False)
    triggered = [
        code
        for code, row in payload.get("stocks", {}).items()
        if (row.get("regime_shift") or {}).get("triggered")
    ]
    trigger_share = len(triggered) / len(codes) if codes else 0
    market_wide = trigger_share >= 0.5
    return {
        "scanned": len(codes),
        "triggered": triggered,
        "trigger_share": trigger_share,
        "market_wide": market_wide,
        "warning": (
            "本轮信号属于市场级共振，不能把同日多股视为独立个股边际。"
            if market_wide
            else ""
        ),
        "payload": payload,
    }
