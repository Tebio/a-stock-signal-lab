from __future__ import annotations

import json
import urllib.parse
from datetime import date, timedelta

from .provider import request_text, symbol
from .service import normalize_code


def parse_tencent_daily(payload: dict, code: str) -> list[dict]:
    code = normalize_code(code)
    item = (payload.get("data") or {}).get(symbol(code)) or {}
    raw_rows = item.get("qfqday") or item.get("day") or []
    rows = []
    for row in raw_rows:
        if len(row) < 6:
            continue
        rows.append(
            {
                "code": code,
                "trade_date": row[0],
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]) if row[5] not in ("", None) else None,
                "amount": (
                    float(row[6])
                    if len(row) > 6
                    and row[6] not in ("", None)
                    and not isinstance(row[6], dict)
                    else None
                ),
                "source": "tencent",
                "adjusted": "qfq",
            }
        )
    return rows


class TencentDailyProvider:
    def fetch(
        self,
        code: str,
        *,
        years: int = 2,
        end: date | None = None,
    ) -> list[dict]:
        code = normalize_code(code)
        end = end or date.today()
        start = end - timedelta(days=max(370, years * 370))
        return self.fetch_range(code, start, end)

    def fetch_range(
        self,
        code: str,
        start: date,
        end: date,
    ) -> list[dict]:
        code = normalize_code(code)
        if start > end:
            return []
        rows = []
        cursor = start
        while cursor <= end:
            window_end = min(end, cursor + timedelta(days=700))
            parameter = (
                f"{symbol(code)},day,{cursor.isoformat()},"
                f"{window_end.isoformat()},640,qfq"
            )
            url = (
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
                + urllib.parse.quote(parameter, safe=",")
            )
            payload = json.loads(request_text(url, "utf-8", timeout=10))
            rows.extend(parse_tencent_daily(payload, code))
            cursor = window_end + timedelta(days=1)
        return rows


def parse_sina_index_daily(text: str, code: str) -> list[dict]:
    left = text.find("([")
    right = text.rfind("])")
    if left < 0 or right < 0:
        raise ValueError("unexpected Sina index response")
    payload = json.loads(text[left + 1 : right + 1])
    rows = []
    for row in payload:
        try:
            rows.append(
                {
                    "code": code,
                    "trade_date": row["day"][:10],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": (
                        float(row["volume"])
                        if row.get("volume") not in ("", None)
                        else None
                    ),
                    "amount": (
                        float(row["amount"])
                        if row.get("amount") not in ("", None)
                        else None
                    ),
                    "source": "sina",
                    "adjusted": "none",
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows


class SinaIndexDailyProvider:
    def fetch(
        self,
        code: str = "sh000001",
        *,
        years: int = 2,
        end: date | None = None,
    ) -> list[dict]:
        query = urllib.parse.urlencode(
            {
                "symbol": code,
                "scale": 240,
                "ma": "no",
                "datalen": min(1023, max(370, years * 250 + 40)),
            }
        )
        url = (
            "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/"
            "CN_MarketDataService.getKLineData?"
            + query
        )
        rows = parse_sina_index_daily(
            request_text(url, "utf-8", timeout=12),
            code,
        )
        if end is not None:
            rows = [row for row in rows if row["trade_date"] <= end.isoformat()]
        return rows

    def fetch_range(
        self,
        code: str,
        start: date,
        end: date,
    ) -> list[dict]:
        if start > end:
            return []
        return [
            row
            for row in self.fetch(code, years=4, end=end)
            if start.isoformat() <= row["trade_date"] <= end.isoformat()
        ]
