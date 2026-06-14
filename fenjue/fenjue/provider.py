from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Iterable

from .service import normalize_code


def symbol(code: str) -> str:
    code = normalize_code(code)
    return ("sh" if code.startswith(("5", "6")) else "sz") + code


def request_text(url: str, encoding: str, timeout: int = 8) -> str:
    referer = "https://finance.sina.com.cn/" if "sina" in url else "https://finance.qq.com/"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 FenjuePortable/1.0",
            "Referer": referer,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode(encoding, errors="replace")


def parse_sina_quotes(text: str) -> dict[str, dict]:
    result = {}
    for line in text.splitlines():
        if '="' not in line:
            continue
        left, raw = line.split('="', 1)
        code = left.rsplit("_", 1)[-1][-6:]
        fields = raw.rstrip('";').split(",")
        if len(fields) < 32 or not fields[0]:
            continue
        try:
            previous = float(fields[2])
            price = float(fields[3])
            if previous <= 0 or price <= 0:
                continue
            result[code] = {
                "code": code,
                "name": fields[0],
                "open": float(fields[1]),
                "prev_close": previous,
                "price": price,
                "high": float(fields[4]),
                "low": float(fields[5]),
                "volume": float(fields[8]),
                "amount": float(fields[9]),
                "pct": (price - previous) / previous * 100,
                "trade_date": fields[30],
                "quote_time": fields[31],
                "source": "sina",
            }
        except (IndexError, ValueError):
            continue
    return result


def parse_tencent_quotes(text: str) -> dict[str, dict]:
    result = {}
    for line in text.splitlines():
        if '="' not in line:
            continue
        _, raw = line.split('="', 1)
        fields = raw.rstrip('";').split("~")
        if len(fields) < 38 or not fields[1]:
            continue
        try:
            code = normalize_code(fields[2])
            price = float(fields[3])
            previous = float(fields[4])
            if previous <= 0 or price <= 0:
                continue
            result[code] = {
                "code": code,
                "name": fields[1],
                "open": float(fields[5]),
                "prev_close": previous,
                "price": price,
                "high": float(fields[33]),
                "low": float(fields[34]),
                "volume": float(fields[36]) * 100,
                "amount": float(fields[37]) * 10000,
                "pct": (price - previous) / previous * 100,
                "trade_date": fields[30][:8],
                "quote_time": fields[30][8:],
                "source": "tencent",
            }
        except (IndexError, ValueError):
            continue
    return result


def parse_sina_minutes(text: str, code: str, scale: int = 5) -> list[dict]:
    left = text.find("([")
    right = text.rfind("])")
    if left < 0 or right < 0:
        raise ValueError("unexpected Sina minute response")
    payload = json.loads(text[left + 1 : right + 1])
    rows = []
    for row in payload:
        try:
            rows.append(
                {
                    "code": normalize_code(code),
                    "bar_time": row["day"],
                    "scale": scale,
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
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows


class SinaMinuteProvider:
    def fetch(self, code: str, *, scale: int = 5, limit: int = 240) -> list[dict]:
        query = urllib.parse.urlencode(
            {
                "symbol": symbol(code),
                "scale": scale,
                "ma": "no",
                "datalen": limit,
            }
        )
        url = (
            "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/"
            "CN_MarketDataService.getKLineData?"
            + query
        )
        return parse_sina_minutes(request_text(url, "utf-8", timeout=12), code, scale)


class SinaTencentProvider:
    def __init__(self, conflict_threshold: float = 0.002, gate=None):
        self.conflict_threshold = conflict_threshold
        self.gate = gate

    def _request(self, callback):
        if self.gate is None:
            return callback()
        with self.gate:
            return callback()

    def fetch_sina(self, codes: Iterable[str]) -> dict[str, dict]:
        symbols = ",".join(symbol(code) for code in codes)
        return self._request(
            lambda: parse_sina_quotes(
                request_text("https://hq.sinajs.cn/list=" + symbols, "gbk")
            )
        )

    def fetch_tencent(self, codes: Iterable[str]) -> dict[str, dict]:
        symbols = ",".join(symbol(code) for code in codes)
        return self._request(
            lambda: parse_tencent_quotes(
                request_text("https://qt.gtimg.cn/q=" + symbols, "gbk")
            )
        )

    def fetch(self, codes: list[str]) -> dict[str, dict]:
        try:
            sina = self.fetch_sina(codes)
        except Exception:
            sina = {}
        try:
            tencent = self.fetch_tencent(codes)
        except Exception:
            tencent = {}

        for code, quote in sina.items():
            peer = tencent.get(code)
            quote["verified_by"] = []
            if peer and peer.get("price", 0) > 0:
                drift = abs(quote["price"] - peer["price"]) / peer["price"]
                quote["verified_by"].append("tencent")
                quote["price_drift"] = drift
                quote["quality"] = (
                    "ok" if drift <= self.conflict_threshold else "conflict"
                )
            else:
                quote["quality"] = "single_source"

        for code, quote in tencent.items():
            if code not in sina:
                quote["verified_by"] = []
                quote["quality"] = "fallback"
                sina[code] = quote
        return sina
