from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path


class PoolExpiredError(ValueError):
    pass


def _trading_days_between(start: date, end: date) -> int:
    if start >= end:
        return 0
    days = 0
    cursor = start + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() < 5:
            days += 1
        cursor += timedelta(days=1)
    return days


def validate_pool_date(
    filename: str | Path,
    *,
    today: date | None = None,
) -> dict:
    match = re.search(r"pool_(\d{8})", Path(filename).name)
    if not match:
        raise ValueError("池文件名缺少 YYYYMMDD 日期。")
    pool_date = datetime.strptime(match.group(1), "%Y%m%d").date()
    current = today or date.today()
    age = _trading_days_between(pool_date, current)
    if age > 3:
        raise PoolExpiredError(
            f"股票池已过期 {age} 个交易日，请先重建后再筛选。"
        )
    return {
        "pool_date": pool_date.isoformat(),
        "trading_days_old": age,
        "level": "warning" if age > 1 else "ok",
    }
