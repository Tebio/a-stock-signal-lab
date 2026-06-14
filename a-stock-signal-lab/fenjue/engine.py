from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .analysis import (
    bank_relative_strength,
    compute_indicators,
    deep_v_evidence,
    detect_regime_shift,
    risk_budget_reference,
    summarize_intraday,
    summarize_stock,
)
from .data_services import DailyBarService
from .runtime import Runtime
from .service import QuoteService, is_main_board, normalize_code
from .validation import summarize_signal_performance


BANK_CODES = {
    "000001", "001227", "002142", "002807", "002839", "002936", "002948",
    "002958", "002966", "600000", "600015", "600016", "600036", "600908",
    "600919", "600926", "600928", "601009", "601077", "601128", "601166",
    "601169", "601187", "601229", "601288", "601328", "601398", "601528",
    "601577", "601658", "601665", "601818", "601825", "601838", "601860",
    "601916", "601939", "601963", "601988", "601997", "601998", "603323",
}


class FenjueEngine:
    def __init__(
        self,
        runtime: Runtime,
        quotes: QuoteService,
        daily_provider,
        *,
        daily_service: DailyBarService | None = None,
        minute_service=None,
        benchmark_service=None,
        bank_benchmark_service=None,
    ):
        self.runtime = runtime
        self.quotes = quotes
        self.daily_provider = daily_provider
        self.daily_service = daily_service or DailyBarService(runtime, daily_provider)
        self.minute_service = minute_service
        self.benchmark_service = benchmark_service
        self.bank_benchmark_service = bank_benchmark_service

    def _daily_rows(self, code: str, years: int) -> dict:
        return self.daily_service.get_with_status(code, years=years)

    def _minute_rows(self, code: str) -> dict | None:
        if self.minute_service is None:
            return None
        return self.minute_service.get(code)

    def analyze_many(
        self,
        values: list[str],
        *,
        years: int = 2,
        max_workers: int = 8,
        include_intraday: bool = True,
    ) -> dict:
        accepted = []
        rejected = []
        for value in values:
            code = normalize_code(value)
            if is_main_board(code):
                if code not in accepted:
                    accepted.append(code)
            elif code not in rejected:
                rejected.append(code)
        quote_result = self.quotes.get_quotes(accepted)
        benchmark_result = (
            self.benchmark_service.get_with_status("sh000001", years=years)
            if self.benchmark_service is not None
            else None
        )
        bank_benchmark_result = (
            self.bank_benchmark_service.get_with_status("sh512800", years=years)
            if self.bank_benchmark_service is not None
            else None
        )
        regime_validation = summarize_signal_performance(
            self.runtime.load_signal_outcomes("regime_shift"),
            horizon=10,
        )

        with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(accepted)))) as pool:
            daily_results = dict(
                zip(
                    accepted,
                    pool.map(lambda code: self._daily_rows(code, years), accepted),
                )
            )
            minute_results = (
                dict(zip(accepted, pool.map(self._minute_rows, accepted)))
                if include_intraday and self.minute_service is not None
                else {}
            )

        stocks = {}
        for code in accepted:
            daily_result = daily_results.get(code) or {}
            rows = daily_result.get("rows") or []
            if len(rows) < 20:
                stocks[code] = {
                    "code": code,
                    "error": "历史日线不足20条，无法形成技术结论。",
                }
                continue
            quote = quote_result["quotes"].get(code)
            summary = summarize_stock(
                compute_indicators(rows),
                quote=quote,
                is_bank=code in BANK_CODES,
            )
            stocks[code] = {
                "code": code,
                "name": (quote or {}).get("name", code),
                "daily_stale": bool(daily_result.get("stale")),
                "daily_error": daily_result.get("error"),
                **summary,
            }
            stocks[code]["risk_budget"] = risk_budget_reference(
                summary["close"],
                summary["ma20"],
            )
            stocks[code]["deep_v"] = deep_v_evidence(rows)
            if benchmark_result is not None:
                regime_shift = detect_regime_shift(
                    rows,
                    benchmark_result.get("rows") or [],
                )
                stocks[code]["regime_shift"] = regime_shift
                if regime_shift.get("triggered"):
                    regime_shift["rolling_validation"] = regime_validation
                    self.runtime.record_signal(
                        code,
                        "regime_shift",
                        regime_shift["signal_date"],
                        regime_shift,
                    )
            if (
                code in BANK_CODES
                and benchmark_result is not None
                and bank_benchmark_result is not None
            ):
                stocks[code]["bank_relative_strength"] = bank_relative_strength(
                    bank_benchmark_result.get("rows") or [],
                    benchmark_result.get("rows") or [],
                )
            minute_result = minute_results.get(code)
            if minute_result is not None:
                stocks[code]["intraday"] = summarize_intraday(
                    minute_result.get("rows") or [],
                    stale=bool(minute_result.get("stale")),
                )
                stocks[code]["intraday_error"] = minute_result.get("error")
        return {
            "stocks": stocks,
            "rejected": rejected + quote_result.get("rejected", []),
        }
