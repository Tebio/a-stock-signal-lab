from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import time
from pathlib import Path

from .daily import SinaIndexDailyProvider, TencentDailyProvider
from .data_services import DailyBarService, MinuteBarService, UpstreamGate
from .engine import FenjueEngine
from .provider import SinaMinuteProvider, SinaTencentProvider
from .runtime import Runtime
from .service import QuoteService
from .validation import summarize_signal_performance, update_signal_outcomes
from .workflows import capture_pool_snapshot, scan_pool_regime_shifts


def build_runtime(root: str | None) -> Runtime:
    path = Path(root or os.environ.get("FENJUE_HOME", "~/.fenjue")).expanduser()
    return Runtime(path)


def build_engine(root: str | None, cache_ttl: float = 2) -> FenjueEngine:
    runtime = build_runtime(root)
    runtime.initialize()
    gate = UpstreamGate(6)
    daily_provider = TencentDailyProvider()
    quotes = QuoteService(
        SinaTencentProvider(gate=gate),
        cache_ttl=cache_ttl,
    )
    return FenjueEngine(
        runtime,
        quotes,
        daily_provider,
        daily_service=DailyBarService(runtime, daily_provider, gate=gate),
        minute_service=MinuteBarService(
            runtime,
            SinaMinuteProvider(),
            cache_ttl=60,
            gate=gate,
        ),
        benchmark_service=DailyBarService(
            runtime,
            SinaIndexDailyProvider(),
            gate=gate,
        ),
        bank_benchmark_service=DailyBarService(
            runtime,
            SinaIndexDailyProvider(),
            gate=gate,
        ),
    )


def print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_analysis(payload: dict) -> None:
    for code, row in payload["stocks"].items():
        if row.get("error"):
            print(f"{code}: {row['error']}")
            continue
        print(
            f"{code} {row['name']} | {row['trade_date']} | "
            f"现价 {row['close']:.2f} | MA5 {row['ma5']:.2f} | "
            f"MA20 {row['ma20']:.2f}"
        )
        print(
            f"  数据={row['data_quality']} | "
            f"{'；'.join(row['observations'])}"
        )
        if row.get("daily_stale"):
            print("  日K=延迟缓存")
        regime = row.get("regime_shift")
        if regime and regime.get("triggered"):
            validation = regime.get("rolling_validation") or {}
            print(
                "  逆市切换="
                f"{regime['signal_date']} 后第{regime['trading_days_since']}T "
                f"({regime['window_stage']}，"
                f"10T样本{validation.get('sample_count', 0)}，"
                f"{validation.get('status', '等待结果回填')})"
            )
        bank_strength = row.get("bank_relative_strength")
        if bank_strength:
            print(
                "  银行相对强度="
                f"{bank_strength['relative_5d_pct']:+.2f}% "
                f"({bank_strength['status']})"
            )
        deep_v = row.get("deep_v") or {}
        if deep_v.get("shape_exists"):
            print(
                "  深V="
                f"{deep_v['support']}，历史样本{deep_v['sample_count']}"
            )
        risk = row.get("risk_budget") or {}
        if risk.get("risk_distance_pct") is not None:
            print(
                "  风险预算="
                f"MA20 {risk['stop_reference']:.2f}，"
                f"距离{risk['risk_distance_pct']:.2f}%"
            )
        print(f"  结论：{row['conclusion']}")
        intraday = row.get("intraday")
        if intraday:
            print(
                f"  5分钟线={intraday['quality']} | "
                f"{'；'.join(intraday['observations'])}"
            )
            print(f"  盘中：{intraday['conclusion']}")
            if (intraday.get("chase_risk") or {}).get("triggered"):
                print(f"  追涨风险：{intraday['chase_risk']['message']}")
    if payload["rejected"]:
        print("已排除非沪深主板：" + "、".join(payload["rejected"]))


def cmd_init(args: argparse.Namespace) -> int:
    runtime = build_runtime(args.root)
    runtime.initialize()
    print(f"Fenjue database ready: {runtime.db_path}")
    return 0


def cmd_quote(args: argparse.Namespace) -> int:
    service = QuoteService(SinaTencentProvider(), cache_ttl=args.cache_ttl)
    payload = service.get_quotes(args.codes)
    print_json(payload)
    return 0 if payload["quotes"] else 2


def cmd_analyze(args: argparse.Namespace) -> int:
    payload = build_engine(args.root, args.cache_ttl).analyze_many(
        args.codes,
        years=args.years,
        max_workers=args.workers,
    )
    if args.json:
        print_json(payload)
    else:
        print_analysis(payload)
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    engine = build_engine(args.root, args.cache_ttl)
    result = capture_pool_snapshot(
        engine.runtime,
        engine.quotes,
        args.pool_file,
        output_dir=args.output_dir,
    )
    print_json(
        {
            "path": str(result["path"]),
            "count": result["count"],
            "accepted_for_validation": result["accepted_for_validation"],
            "tag": result["tag"],
            "strategy_b_candidates": result["strategy_b_candidates"],
        }
    )
    return 0 if result["count"] else 2


def cmd_scan_regime(args: argparse.Namespace) -> int:
    result = scan_pool_regime_shifts(
        build_engine(args.root, args.cache_ttl),
        args.pool_file,
    )
    if args.json:
        print_json(result)
    else:
        print(
            f"主池扫描 {result['scanned']} 只，"
            f"因果版逆市切换 {len(result['triggered'])} 只。"
        )
        if result["warning"]:
            print("警告：" + result["warning"])
        if result["triggered"]:
            print("、".join(result["triggered"]))
    return 0


def cmd_validate_signals(args: argparse.Namespace) -> int:
    engine = build_engine(args.root, args.cache_ttl)
    updated = update_signal_outcomes(
        engine.runtime,
        engine.daily_service,
        signal_type=args.signal_type,
    )
    rows = engine.runtime.load_signal_outcomes(args.signal_type)
    payload = {
        "updated": updated,
        "signal_type": args.signal_type,
        "metrics": [
            summarize_signal_performance(rows, horizon=horizon)
            for horizon in (5, 10, 20)
        ],
    }
    print_json(payload)
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    codes = args.codes[: args.symbols]

    def one(_: int) -> dict:
        started = time.perf_counter()
        quotes = SinaTencentProvider().fetch(codes)
        return {
            "seconds": time.perf_counter() - started,
            "count": len(quotes),
            "ok": sum(row.get("quality") == "ok" for row in quotes.values()),
            "conflicts": sum(
                row.get("quality") == "conflict" for row in quotes.values()
            ),
        }

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as pool:
        results = list(pool.map(one, range(args.users)))
    ordered = sorted(result["seconds"] for result in results)
    payload = {
        "concurrent_users": args.users,
        "symbols_per_user": len(codes),
        "success_requests": sum(result["count"] == len(codes) for result in results),
        "total_requests": args.users,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "median_seconds": round(statistics.median(ordered), 3),
        "p95_seconds": round(
            ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
            3,
        ),
        "verified_quotes": sum(result["ok"] for result in results),
        "conflicts": sum(result["conflicts"] for result in results),
    }
    print_json(payload)
    return 0 if payload["success_requests"] == args.users else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Portable Fenjue toolkit")
    root.add_argument("--root", help="runtime data directory")
    sub = root.add_subparsers(dest="command", required=True)

    initialize = sub.add_parser("init", help="initialize an empty local database")
    initialize.set_defaults(func=cmd_init)

    quote = sub.add_parser("quote", help="fetch dual-source realtime quotes")
    quote.add_argument("codes", nargs="+")
    quote.add_argument("--cache-ttl", type=float, default=2)
    quote.set_defaults(func=cmd_quote)

    analyze = sub.add_parser("analyze", help="analyze one or more main-board stocks")
    analyze.add_argument("codes", nargs="+")
    analyze.add_argument("--years", type=int, default=2)
    analyze.add_argument("--workers", type=int, default=8)
    analyze.add_argument("--cache-ttl", type=float, default=2)
    analyze.add_argument("--json", action="store_true")
    analyze.set_defaults(func=cmd_analyze)

    snapshot = sub.add_parser(
        "snapshot",
        help="capture a pool quote snapshot; only real 09:25 data enters validation",
    )
    snapshot.add_argument("--pool-file", required=True)
    snapshot.add_argument("--output-dir", required=True)
    snapshot.add_argument("--cache-ttl", type=float, default=0)
    snapshot.set_defaults(func=cmd_snapshot)

    regime = sub.add_parser(
        "scan-regime",
        help="scan every main-board stock in a current pool",
    )
    regime.add_argument("--pool-file", required=True)
    regime.add_argument("--cache-ttl", type=float, default=2)
    regime.add_argument("--json", action="store_true")
    regime.set_defaults(func=cmd_scan_regime)

    validate = sub.add_parser(
        "validate-signals",
        help="fill signal outcomes and report honest rolling metrics",
    )
    validate.add_argument("--signal-type", default="regime_shift")
    validate.add_argument("--cache-ttl", type=float, default=2)
    validate.set_defaults(func=cmd_validate_signals)

    benchmark = sub.add_parser("benchmark", help="stress-test free quote sources")
    benchmark.add_argument("--users", type=int, default=20)
    benchmark.add_argument("--symbols", type=int, default=20)
    benchmark.add_argument(
        "codes",
        nargs="*",
        default=[
            "600000", "600036", "600519", "601318", "601398",
            "000001", "000333", "000858", "002230", "002415",
            "600276", "600309", "600887", "601166", "601888",
            "000725", "002594", "002475", "600030", "601012",
        ],
    )
    benchmark.set_defaults(func=cmd_benchmark)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)
