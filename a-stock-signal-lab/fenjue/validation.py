from __future__ import annotations

import statistics


def update_signal_outcomes(
    runtime,
    daily_service,
    *,
    signal_type: str,
    horizons: tuple[int, ...] = (5, 10, 20),
) -> int:
    updated = 0
    for event in runtime.load_signals_for_type(signal_type):
        rows = daily_service.get_with_status(event["code"], years=4).get("rows") or []
        dates = [row["trade_date"] for row in rows]
        try:
            start = dates.index(event["signal_date"])
        except ValueError:
            continue
        entry = float(
            event.get("metadata", {}).get("entry_price")
            or rows[start]["close"]
        )
        for horizon in horizons:
            result_index = start + horizon
            if result_index >= len(rows):
                continue
            result_price = float(rows[result_index]["close"])
            runtime.upsert_signal_outcome(
                {
                    "code": event["code"],
                    "signal_type": signal_type,
                    "signal_date": event["signal_date"],
                    "horizon": horizon,
                    "result_date": rows[result_index]["trade_date"],
                    "entry_price": entry,
                    "result_price": result_price,
                    "return_pct": (result_price - entry) / entry * 100,
                }
            )
            updated += 1
    return updated


def summarize_signal_performance(rows: list[dict], *, horizon: int) -> dict:
    matching = [
        row for row in rows if int(row["horizon"]) == horizon
    ]
    values = [float(row["return_pct"]) for row in matching]
    if not values:
        return {
            "horizon": horizon,
            "sample_count": 0,
            "independent_dates": 0,
            "validated": False,
            "status": "暂无可验证样本。",
        }
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    sample_count = len(values)
    dated = {
        str(row.get("signal_date"))
        for row in matching
        if row.get("signal_date")
    }
    independent_dates = len(dated) if dated else sample_count
    validated = sample_count >= 30 and independent_dates >= 30
    if sample_count < 30:
        status = f"样本不足30（当前{sample_count}），不得标注稳定胜率。"
    elif independent_dates < 30:
        status = (
            f"独立日期不足30（当前{independent_dates}）；"
            "同日多股高度相关，不得标注稳定胜率。"
        )
    else:
        status = "达到基础独立样本门槛，仍需样本外检验。"
    return {
        "horizon": horizon,
        "sample_count": sample_count,
        "independent_dates": independent_dates,
        "win_rate": sum(value > 0 for value in values) / sample_count,
        "mean_return_pct": statistics.mean(values),
        "median_return_pct": statistics.median(values),
        "profit_factor": gains / losses if losses else None,
        "validated": validated,
        "status": status,
    }
