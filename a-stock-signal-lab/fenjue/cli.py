from __future__ import annotations

import argparse
import concurrent.futures
from dataclasses import asdict
import json
import os
import statistics
import time
from pathlib import Path

from .daily import SinaIndexDailyProvider, TencentDailyProvider
from .budget import PortfolioBudgetService
from .data_services import DailyBarService, MinuteBarService, UpstreamGate
from .engine import FenjueEngine
from .provider import SinaMinuteProvider, SinaTencentProvider
from .pool_scripts import main_build_pool, main_screen_pool, main_screen_pool2
from .runtime import Runtime
from .service import QuoteService
from .validation import summarize_signal_performance, update_signal_outcomes
from .workflows import capture_pool_snapshot, scan_pool_regime_shifts
from .decision import DecisionContext, DecisionEngine
from .execution import FillAssessment
from .events import EventStore
from .ledger import PositionLedger, RiskPrecheck
from .outcomes import IntradayOutcomeBackfiller
from .v2db import FenjueV2Database


def build_runtime(root: str | None) -> Runtime:
    path = Path(root or os.environ.get("FENJUE_HOME", "~/.fenjue")).expanduser()
    return Runtime(path)


def build_v2_database(root: str | None, initialize: bool = True) -> FenjueV2Database:
    path = Path(root or os.environ.get("FENJUE_HOME", "~/.fenjue")).expanduser()
    database = FenjueV2Database(path / "data" / "fenjue-v2.sqlite3")
    if initialize:
        database.initialize()
    return database


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
    print(f"A-Stock Signal Lab database ready: {runtime.db_path}")
    return 0


def cmd_v2_init(args: argparse.Namespace) -> int:
    with build_v2_database(args.root) as database:
        probe = database.compatibility_probe()
        print(
            f"Fenjue V2 database ready: {database.path} "
            f"(SQLite {probe['sqlite_version']}, JSON1={probe['json1']})"
        )
    return 0


def cmd_v2_integrity(args: argparse.Namespace) -> int:
    with build_v2_database(args.root) as database:
        report = database.integrity_report()
    print_json(report)
    return 0 if (
        report["integrity_check"] == "ok"
        and not report["foreign_key_violations"]
        and not report["violations"]
    ) else 2


def cmd_v2_ledger(args: argparse.Namespace) -> int:
    now_ms = args.buy_time_ms or int(time.time() * 1000)
    with build_v2_database(args.root) as database:
        ledger = PositionLedger(database)
        ledger.ensure_account(
            args.account, args.account, args.equity_fen, args.trade_date, now_ms
        )
        ledger.set_position(
            args.account, args.code, args.mode, args.core_floor,
            args.logic_cluster, "user supplied position", "user", now_ms,
        )
        lot_id = ledger.record_buy_lot(
            args.account, args.code, args.role, args.buy_date, now_ms,
            args.quantity, args.buy_price, args.sellable_from, "user", now_ms,
        )
        context = ledger.position_context(args.account, args.code, args.trade_date)
        payload = {"lot_id": lot_id, **asdict(context)}
    print_json(payload)
    return 0


def cmd_v2_decide(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.context_json).read_text(encoding="utf-8"))
    execution = payload.pop("execution", None)
    risk = payload.pop("risk_precheck", None)
    context = DecisionContext(
        **payload,
        execution=FillAssessment(**execution) if execution else None,
        risk_precheck=RiskPrecheck(**risk) if risk else None,
    )
    with build_v2_database(args.root) as database:
        result = DecisionEngine(
            database,
            run_mode=args.run_mode,
            strategy_version_id=args.strategy_version_id,
        ).decide(context)
    print_json(asdict(result))
    return 0


def cmd_v2_backfill_outcome(args: argparse.Namespace) -> int:
    calculated_at_ms = args.calculated_at_ms or int(time.time() * 1000)
    with build_v2_database(args.root) as database:
        result = IntradayOutcomeBackfiller(database).backfill_intent(
            args.intent_id,
            calculation_version=args.calculation_version,
            calculated_at_ms=calculated_at_ms,
        )
    print_json(asdict(result))
    return 0 if result.outcome_status == "scored" else 2


def cmd_v2_budget(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.payload_json).read_text(encoding="utf-8"))
    with build_v2_database(args.root) as database:
        service = PortfolioBudgetService(database)
        if args.operation == "open":
            budget_id = service.open_budget(**payload)
            result = {"budget_id": budget_id, "status": "ACTIVE"}
        elif args.operation == "precheck":
            result = asdict(service.precheck(**payload))
        else:
            consumption_id = payload.pop("consumption_id")
            result = asdict(service.consume(consumption_id, **payload))
    print_json(result)
    return 0


def cmd_v2_freeze(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.payload_json).read_text(encoding="utf-8"))
    with build_v2_database(args.root) as database:
        store = EventStore(database)
        if args.operation == "apply":
            event_version_id = payload.pop("event_version_id")
            result = store.apply_default_freezes(event_version_id, **payload)
        elif args.operation == "request":
            freeze_id = payload.pop("freeze_id")
            result = {"request_id": store.request_override(freeze_id, **payload)}
        elif args.operation == "review":
            request_id = payload.pop("request_id")
            store.review_override(request_id, **payload)
            result = {"request_id": request_id, "status": "reviewed"}
        else:
            freeze_id = payload.pop("freeze_id")
            result = {"release_audit_id": store.release_freeze(freeze_id, **payload)}
    print_json(result if isinstance(result, dict) else {"freezes": result})
    return 0


def cmd_build_pool(args: argparse.Namespace) -> int:
    argv = ["--top", str(args.top), "--sleep", str(args.sleep)]
    if args.root:
        argv.extend(["--root", args.root])
    if args.date:
        argv.extend(["--date", args.date])
    if args.out_dir:
        argv.extend(["--out-dir", args.out_dir])
    return main_build_pool(argv)


def _screen_pool_command(args: argparse.Namespace, entrypoint) -> int:
    argv = []
    if args.root:
        argv.extend(["--root", args.root])
    if args.pool_file:
        argv.append(args.pool_file)
    return entrypoint(argv)


def cmd_screen_pool(args: argparse.Namespace) -> int:
    return _screen_pool_command(args, main_screen_pool)


def cmd_screen_pool2(args: argparse.Namespace) -> int:
    return _screen_pool_command(args, main_screen_pool2)


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
    root = argparse.ArgumentParser(description="A-Stock Signal Lab toolkit")
    root.add_argument("--root", help="runtime data directory")
    sub = root.add_subparsers(dest="command", required=True)

    initialize = sub.add_parser("init", help="initialize an empty local database")
    initialize.set_defaults(func=cmd_init)

    v2_initialize = sub.add_parser(
        "v2-init", help="initialize the audited Fenjue V2 database"
    )
    v2_initialize.set_defaults(func=cmd_v2_init)

    v2_integrity = sub.add_parser(
        "v2-integrity", help="run Fenjue V2 integrity and leakage checks"
    )
    v2_integrity.set_defaults(func=cmd_v2_integrity)

    v2_ledger = sub.add_parser(
        "v2-ledger", help="record a user-supplied position lot in the V2 ledger"
    )
    v2_ledger.add_argument("--account", required=True)
    v2_ledger.add_argument("--code", required=True)
    v2_ledger.add_argument(
        "--mode", required=True,
        choices=["CORE_HOLD", "TACTICAL_T", "NEW_ENTRY", "RISK", "OBSERVE"],
    )
    v2_ledger.add_argument("--logic-cluster", required=True)
    v2_ledger.add_argument("--core-floor", required=True, type=int)
    v2_ledger.add_argument("--quantity", required=True, type=int)
    v2_ledger.add_argument("--buy-price", required=True)
    v2_ledger.add_argument("--buy-date", required=True)
    v2_ledger.add_argument("--sellable-from", required=True)
    v2_ledger.add_argument("--trade-date", required=True)
    v2_ledger.add_argument("--equity-fen", required=True, type=int)
    v2_ledger.add_argument("--buy-time-ms", type=int)
    v2_ledger.add_argument("--role", choices=["core", "tactical"], default="core")
    v2_ledger.set_defaults(func=cmd_v2_ledger)

    v2_decide = sub.add_parser(
        "v2-decide", help="evaluate a complete frozen V2 decision context JSON"
    )
    v2_decide.add_argument("--context-json", required=True)
    v2_decide.add_argument(
        "--run-mode", choices=["research", "shadow", "production"],
        default="research",
    )
    v2_decide.add_argument("--strategy-version-id")
    v2_decide.set_defaults(func=cmd_v2_decide)

    v2_outcome = sub.add_parser(
        "v2-backfill-outcome",
        help="audit and backfill next-trade-date intraday labels for an intent",
    )
    v2_outcome.add_argument("--intent-id", required=True)
    v2_outcome.add_argument("--calculation-version", required=True)
    v2_outcome.add_argument("--calculated-at-ms", type=int)
    v2_outcome.set_defaults(func=cmd_v2_backfill_outcome)

    v2_budget = sub.add_parser(
        "v2-budget", help="open, precheck, or consume a two-phase portfolio budget"
    )
    v2_budget.add_argument("operation", choices=["open", "precheck", "consume"])
    v2_budget.add_argument("--payload-json", required=True)
    v2_budget.set_defaults(func=cmd_v2_budget)

    v2_freeze = sub.add_parser(
        "v2-freeze", help="apply event freezes and audit override/release workflow"
    )
    v2_freeze.add_argument(
        "operation", choices=["apply", "request", "review", "release"]
    )
    v2_freeze.add_argument("--payload-json", required=True)
    v2_freeze.set_defaults(func=cmd_v2_freeze)

    build_pool = sub.add_parser(
        "build-pool", help="build a candidate pool without hardcoded paths or dates"
    )
    build_pool.add_argument("--date")
    build_pool.add_argument("--out-dir")
    build_pool.add_argument("--top", type=int, default=300)
    build_pool.add_argument("--sleep", type=float, default=0.4)
    build_pool.set_defaults(func=cmd_build_pool)

    screen_pool = sub.add_parser(
        "screen-pool", help="run compatibility pool strategies 1-3"
    )
    screen_pool.add_argument("pool_file", nargs="?")
    screen_pool.set_defaults(func=cmd_screen_pool)

    screen_pool2 = sub.add_parser(
        "screen-pool2", help="run compatibility pool strategies 4-6"
    )
    screen_pool2.add_argument("pool_file", nargs="?")
    screen_pool2.set_defaults(func=cmd_screen_pool2)

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
