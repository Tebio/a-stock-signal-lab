from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .trading_calendar import TradingCalendar


class PoolExpiredError(ValueError):
    pass


def _trading_days_between(start: date, end: date) -> int:
    """Compatibility wrapper retained for external imports."""
    return TradingCalendar.compatibility_weekdays_between(start, end)


def validate_pool_date(
    filename: str | Path,
    *,
    today: date | None = None,
    calendar: TradingCalendar | None = None,
) -> dict:
    match = re.search(r"pool_(\d{8})", Path(filename).name)
    if not match:
        raise ValueError("池文件名缺少 YYYYMMDD 日期。")
    pool_date = datetime.strptime(match.group(1), "%Y%m%d").date()
    current = today or date.today()
    age = (
        calendar.trading_days_between(
            pool_date.isoformat(), current.isoformat()
        )
        if calendar is not None
        else _trading_days_between(pool_date, current)
    )
    if age > 3:
        raise PoolExpiredError(
            f"股票池已过期 {age} 个交易日，请先重建后再筛选。"
        )
    return {
        "pool_date": pool_date.isoformat(),
        "trading_days_old": age,
        "level": "warning" if age > 1 else "ok",
    }
