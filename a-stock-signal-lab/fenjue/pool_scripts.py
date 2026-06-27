from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path
import time
from typing import Sequence

from .pool import PoolExpiredError, validate_pool_date
from .script_compat import (
    resolve_pool_file,
    resolve_runtime_root,
    resolve_trade_date,
)


def _pool_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("pool_file", nargs="?", help="explicit pool JSON (legacy positional argument)")
    parser.add_argument("--root", help="runtime root; defaults to FENJUE_HOME or ~/.fenjue")
    return parser


def _load_pool(args: argparse.Namespace) -> tuple[Path, list[dict]]:
    path = resolve_pool_file(args.pool_file, resolve_runtime_root(args.root))
    try:
        status = validate_pool_date(path)
    except PoolExpiredError as exc:
        raise SystemExit(f"拒绝运行：{exc}") from exc
    if status["level"] == "warning":
        print(f"⚠️ 股票池已超过1个交易日，结果仅供观察：{status['trading_days_old']}T")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise SystemExit(f"池文件格式错误，缺少 results 数组：{path}")
    return path, rows


def main_build_pool(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build T-1 A-Stock Signal Lab candidate pool")
    parser.add_argument("--date", help="trade date YYYYMMDD; omitted means Asia/Shanghai current date")
    parser.add_argument("--root", help="runtime root; defaults to FENJUE_HOME or ~/.fenjue")
    parser.add_argument("--out-dir", help="compatibility override for output directory")
    parser.add_argument("--top", type=int, default=300)
    parser.add_argument("--sleep", type=float, default=0.4)
    args = parser.parse_args(argv)

    trade_date, date_source = resolve_trade_date(args.date)
    root = resolve_runtime_root(args.root)
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else root / "pools"
    start_date = (
        datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=370)
    ).strftime("%Y%m%d")
    print(f"⏳ {trade_date} 备选池 (日期来源: {date_source}; Sina源 K线)...", flush=True)

    try:
        import akshare as ak
    except ImportError as exc:
        raise SystemExit("缺少 akshare；请在 Hermes 容器环境安装后重试。") from exc

    strong = ak.stock_zt_pool_strong_em(date=trade_date)
    main_prefixes = ("600", "601", "603", "605", "000", "001", "002", "003")
    strong = strong[strong["代码"].apply(lambda code: str(code)[:3] in main_prefixes)]
    strong = strong.sort_values("成交额", ascending=False).head(args.top)
    print(f"沪深主板前{args.top}: {len(strong)}只", flush=True)
    results: list[dict] = []
    errors = 0
    started = time.time()
    for index, (_, row) in enumerate(strong.iterrows(), start=1):
        code = str(row["代码"])
        try:
            symbol = ("sh" if code.startswith("6") else "sz") + code
            history = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_date,
                end_date=trade_date,
                adjust="qfq",
            )
            if len(history) < 20:
                errors += 1
                continue
            closes = history["close"].tolist()
            ma5 = sum(closes[-5:]) / 5
            ma20 = sum(closes[-20:]) / 20
            close = closes[-1]
            if close > ma5 or close > ma20:
                results.append(
                    {
                        "code": code,
                        "name": row["名称"],
                        "price": float(row["最新价"]),
                        "pct": float(row["涨跌幅"]),
                        "amount_yi": round(row["成交额"] / 1e8, 1),
                        "mcap_yi": round(row["总市值"] / 1e8, 1),
                        "sector": row.get("所属行业", ""),
                        "ma5": round(ma5, 2),
                        "ma20": round(ma20, 2),
                        "line_signal": "MA5" if close > ma5 else "MA20",
                    }
                )
        except Exception as exc:  # provider rows can fail independently
            errors += 1
            print(f"  {code} 数据失败: {exc}", flush=True)
        time.sleep(args.sleep)
        if index % 30 == 0:
            print(
                f"  {index}/{len(strong)} ({time.time()-started:.0f}s) "
                f"通过{len(results)} 错{errors}",
                flush=True,
            )
    results.sort(key=lambda row: row["amount_yi"], reverse=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"pool_{trade_date}.json"
    out_path.write_text(
        json.dumps(
            {
                "date": trade_date,
                "date_source": date_source,
                "count": len(results),
                "elapsed": round(time.time() - started),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"💾 {out_path} ({len(results)}只)", flush=True)
    return 0


def main_screen_pool(argv: Sequence[str] | None = None) -> int:
    args = _pool_parser("Screen pool strategies 1-3").parse_args(argv)
    path, pool = _load_pool(args)
    print(f"池文件: {path.name}\n池内: {len(pool)}只\n")

    golden = []
    for stock in pool:
        ma5, ma20 = stock.get("ma5"), stock.get("ma20")
        if not ma5 or not ma20:
            continue
        gap = (ma5 - ma20) / ma20 * 100
        if -8 <= gap <= 3 and (stock.get("amount_yi", 0) or 0) > 1:
            golden.append({**stock, "ma_gap": round(gap, 1)})
    golden.sort(key=lambda row: abs(row["ma_gap"]))
    print("=" * 65)
    print("📐 策略1: 快金叉 (MA5/MA20差 -8%→+3% + 成交>1亿)")
    print(f"候选: {len(golden)}只")
    for stock in golden[:12]:
        print(f"  {stock['code']} {stock['name']} MA差{stock['ma_gap']:+.1f}%")

    hot = ["半导体", "消费电子", "元件", "光学光电", "通信设备", "电力", "煤炭", "军工电子", "其他电源", "电池"]
    low = [
        stock for stock in pool
        if (stock.get("pct", 0) or 0) < 5
        and 3 <= (stock.get("amount_yi", 0) or 0) <= 15
        and not any(item in (stock.get("sector", "") or "") for item in hot)
    ]
    low.sort(key=lambda row: row.get("amount_yi", 0) or 0, reverse=True)
    print("\n" + "=" * 65)
    print("🥷 策略2: 底部潜伏 (昨涨<5% + 成交3-15亿 + 非主线)")
    print(f"候选: {len(low)}只")
    for stock in low[:10]:
        print(f"  {stock['code']} {stock['name']} {stock.get('sector', '')}")

    low_golden = [
        stock for stock in golden
        if -3 <= (stock.get("pct", 0) or 0) <= 3
        and (stock.get("amount_yi", 0) or 0) > 3
    ]
    print("\n" + "=" * 65)
    print("🎯 策略3: 低位金叉 + 量")
    print(f"候选: {len(low_golden)}只")
    for stock in low_golden[:10]:
        print(f"  {stock['code']} {stock['name']} MA差{stock['ma_gap']:+.1f}%")
    return 0


def main_screen_pool2(argv: Sequence[str] | None = None) -> int:
    args = _pool_parser("Screen pool strategies 4-6").parse_args(argv)
    path, pool = _load_pool(args)
    print(f"池文件: {path.name}\n池内: {len(pool)}只")

    dark = [
        stock for stock in pool
        if (stock.get("amount_yi", 0) or 0) > 15
        and (stock.get("pct", 0) or 0) < 5
    ]
    dark.sort(key=lambda row: row.get("amount_yi", 0) or 0, reverse=True)
    print("=" * 65)
    print("🌊 策略4: 大成交暗流")
    print(f"候选: {len(dark)}只")
    for stock in dark[:15]:
        print(f"  {stock['code']} {stock['name']} 成交{stock.get('amount_yi', 0):.0f}亿")

    sector_counts = Counter(stock.get("sector", "") for stock in pool)
    print("\n" + "=" * 65)
    print("🔗 策略5: 板块有共振 + 个股低位")
    for sector, count in sorted(sector_counts.items(), key=lambda item: item[1], reverse=True):
        if sector and count >= 3:
            print(f"  [{sector}] {count}只在池")

    multi = []
    for stock in pool:
        ma5, ma20 = stock.get("ma5"), stock.get("ma20")
        if not ma5 or not ma20:
            continue
        pct = stock.get("pct", 0) or 0
        amount = stock.get("amount_yi", 0) or 0
        gap = ((stock.get("price") or ma5) / ma20 - 1) * 100
        if 2 <= pct <= 7 and amount > 5 and gap < 25:
            score = (1 - abs(pct - 4.5) / 4.5) * 25
            score += (1 - abs(gap - 12) / 12) * 25
            score += min(amount / 30, 1) * 10 + 10
            multi.append({**stock, "score": round(score, 1)})
    multi.sort(key=lambda row: row["score"], reverse=True)
    print("\n" + "=" * 65)
    print("⭐ 策略6: 多因子评分")
    print(f"候选: {len(multi)}只")
    for stock in multi[:15]:
        print(f"  [{stock['score']:.1f}] {stock['code']} {stock['name']}")

    groups = {
        "大成交": {stock["code"] for stock in dark},
        "多因子": {stock["code"] for stock in multi},
    }
    print("\n" + "=" * 65)
    print("🔎 跨策略交集候选（过滤重叠，不代表胜率叠加）")
    for stock in pool:
        labels = [name for name, codes in groups.items() if stock.get("code") in codes]
        if len(labels) >= 2:
            print(f"  {stock['code']} {stock['name']} {', '.join(labels)}")
    return 0
