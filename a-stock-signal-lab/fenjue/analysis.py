from __future__ import annotations


def _daily_returns(rows: list[dict]) -> dict[str, float]:
    ordered = sorted(rows, key=lambda row: row["trade_date"])
    returns = {}
    for previous, current in zip(ordered, ordered[1:]):
        previous_close = float(previous["close"])
        if previous_close:
            returns[current["trade_date"]] = (
                float(current["close"]) - previous_close
            ) / previous_close
    return returns


def detect_regime_shift(
    stock_rows: list[dict],
    benchmark_rows: list[dict],
    *,
    window: int = 10,
    prior_max: float = 0.3,
    recent_min: float = 0.5,
    minimum_down_days: int = 3,
) -> dict:
    stock_returns = _daily_returns(stock_rows)
    benchmark_returns = _daily_returns(benchmark_rows)
    dates = sorted(set(stock_returns) & set(benchmark_returns))
    latest_event = None
    regime_active = False

    for end in range(window * 2, len(dates) + 1):
        prior_dates = dates[end - window * 2 : end - window]
        recent_dates = dates[end - window : end]

        def anti_rate(period: list[str]) -> tuple[float | None, int]:
            down_dates = [
                day for day in period if benchmark_returns[day] < -0.001
            ]
            if len(down_dates) < minimum_down_days:
                return None, len(down_dates)
            anti_days = sum(stock_returns[day] > 0 for day in down_dates)
            return anti_days / len(down_dates), len(down_dates)

        prior_rate, prior_down_days = anti_rate(prior_dates)
        recent_rate, recent_down_days = anti_rate(recent_dates)
        qualifies = (
            prior_rate is not None
            and recent_rate is not None
            and prior_rate <= prior_max
            and recent_rate >= recent_min
            and recent_rate - prior_rate >= 0.2
        )
        if qualifies and not regime_active:
            latest_event = {
                "signal_date": dates[end - 1],
                "prior_rate": prior_rate,
                "recent_rate": recent_rate,
                "prior_down_days": prior_down_days,
                "recent_down_days": recent_down_days,
            }
        regime_active = qualifies

    if latest_event is None:
        return {
            "triggered": False,
            "validated": False,
            "reason": "最近历史窗口未形成因果版逆市切换。",
        }

    signal_index = dates.index(latest_event["signal_date"])
    trading_days_since = len(dates) - signal_index - 1
    if trading_days_since <= 3:
        stage = "early"
    elif trading_days_since <= 10:
        stage = "golden"
    else:
        stage = "expired"
    return {
        "triggered": True,
        **latest_event,
        "trading_days_since": trading_days_since,
        "window_stage": stage,
        "validated": False,
        "validation_note": "因果版规则待重新做时间隔离和样本外验证。",
    }


def bank_relative_strength(
    bank_rows: list[dict],
    market_rows: list[dict],
    *,
    window: int = 5,
) -> dict:
    bank = {row["trade_date"]: float(row["close"]) for row in bank_rows}
    market = {row["trade_date"]: float(row["close"]) for row in market_rows}
    dates = sorted(set(bank) & set(market))
    if len(dates) <= window:
        return {
            "status": "missing",
            "relative_5d_pct": None,
            "conclusion": "银行ETF与上证共同历史不足。",
        }
    start = dates[-window - 1]
    end = dates[-1]
    bank_return = (bank[end] - bank[start]) / bank[start] * 100
    market_return = (market[end] - market[start]) / market[start] * 100
    relative = bank_return - market_return
    if relative >= 1:
        status = "strong"
        conclusion = "银行板块近5日相对上证偏强。"
    elif relative <= -1:
        status = "weak"
        conclusion = "银行板块近5日相对上证偏弱。"
    else:
        status = "neutral"
        conclusion = "银行板块近5日相对上证无明显优势。"
    return {
        "status": status,
        "relative_5d_pct": relative,
        "bank_return_5d_pct": bank_return,
        "market_return_5d_pct": market_return,
        "conclusion": conclusion,
    }


def risk_budget_reference(price: float, ma20: float | None) -> dict:
    if not ma20 or price <= ma20:
        return {
            "stop_reference": ma20,
            "risk_distance_pct": None,
            "max_exposure_pct_at_1pct_risk": None,
            "conclusion": "现价未站上MA20，不能用跌破MA20作为有效风险锚点。",
        }
    distance = (price - ma20) / price * 100
    exposure = min(100.0, 100.0 / distance) if distance > 0 else None
    return {
        "stop_reference": ma20,
        "risk_distance_pct": distance,
        "max_exposure_pct_at_1pct_risk": exposure,
        "formula": "仓位上限%=单笔风险预算%÷止损距离%×100",
        "conclusion": "仅提供风险预算反推锚点，不构成仓位建议。",
    }


def deep_v_evidence(
    rows: list[dict],
    *,
    minimum_samples: int = 5,
    minimum_win_rate: float = 0.6,
) -> dict:
    def is_shape(row: dict) -> bool:
        low = float(row["low"])
        high = float(row["high"])
        opening = float(row["open"])
        close = float(row["close"])
        amplitude = (high - low) / low * 100 if low else 0
        position = (close - low) / (high - low) if high > low else 0
        return amplitude > 7 and close > opening and position > 0.7

    outcomes = []
    for index, row in enumerate(rows[:-1]):
        if not is_shape(row):
            continue
        close = float(row["close"])
        next_close = float(rows[index + 1]["close"])
        outcomes.append((next_close - close) / close * 100)
    shape_exists = bool(rows and is_shape(rows[-1]))
    sample_count = len(outcomes)
    win_rate = (
        sum(value > 0 for value in outcomes) / sample_count
        if sample_count
        else None
    )
    supported = (
        shape_exists
        and sample_count >= minimum_samples
        and win_rate is not None
        and win_rate >= minimum_win_rate
    )
    return {
        "shape_exists": shape_exists,
        "sample_count": sample_count,
        "win_rate": win_rate,
        "mean_return_pct": (
            sum(outcomes) / sample_count if sample_count else None
        ),
        "support": "supported" if supported else "unverified",
        "conclusion": (
            "当前标的深V形态有本票历史样本支持，仍需收盘后确认。"
            if supported
            else "深V形态存在但无足够本票统计支持。"
            if shape_exists
            else "当前未形成收盘确认的深V形态。"
        ),
    }


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (1 - alpha) * output[-1])
    return output


def rolling_mean(values: list[float], period: int) -> list[float | None]:
    output = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= period:
            total -= values[index - period]
        output.append(total / period if index + 1 >= period else None)
    return output


def compute_indicators(rows: list[dict]) -> list[dict]:
    closes = [float(row["close"]) for row in rows]
    ma5 = rolling_mean(closes, 5)
    ma20 = rolling_mean(closes, 20)
    dif = [fast - slow for fast, slow in zip(ema(closes, 12), ema(closes, 26))]
    dea = ema(dif, 9)
    hist = [2 * (value - signal) for value, signal in zip(dif, dea)]
    return [
        {
            **row,
            "ma5": ma5[index],
            "ma20": ma20[index],
            "dif": dif[index],
            "dea": dea[index],
            "macd_hist": hist[index],
        }
        for index, row in enumerate(rows)
    ]


def summarize_intraday(rows: list[dict], *, stale: bool = False) -> dict:
    if not rows:
        return {
            "quality": "missing",
            "latest_time": None,
            "observations": [],
            "conclusion": "缺少5分钟线，无法判断盘中承接。",
        }
    first = rows[0]
    latest = rows[-1]
    high = max(float(row["high"]) for row in rows)
    low = min(float(row["low"]) for row in rows)
    close = float(latest["close"])
    opening = float(first["open"])
    position = (close - low) / (high - low) if high > low else 0.5
    change = (close - opening) / opening * 100 if opening else 0
    observations = [
        f"盘中涨跌{change:+.2f}%",
        f"区间位置{position * 100:.0f}%",
    ]
    if close >= opening and position >= 0.6:
        structure = "盘中承接偏强"
    elif close < opening and position <= 0.4:
        structure = "盘中承接偏弱"
    else:
        structure = "盘中结构震荡"
    if stale:
        conclusion = f"延迟缓存：{structure}，不可作为即时入场依据。"
    else:
        conclusion = f"{structure}，仍需结合题材与大盘闸门。"
    latest_time = str(latest.get("bar_time") or "")
    clock = latest_time[-8:-3] if len(latest_time) >= 16 else ""
    chase_triggered = (
        "09:35" <= clock <= "09:45"
        and change >= 5
        and position >= 0.75
    )
    return {
        "quality": "stale" if stale else "fresh",
        "latest_time": latest.get("bar_time"),
        "open": opening,
        "close": close,
        "high": high,
        "low": low,
        "position": position,
        "observations": observations,
        "conclusion": conclusion,
        "chase_risk": {
            "triggered": chase_triggered,
            "message": (
                "当前形态与9:40高位追涨场景相似；既有小样本到收盘表现偏弱，"
                "只作风险提示，不作禁止或卖出指令。"
                if chase_triggered
                else "未触发9:40追涨风险提示。"
            ),
        },
    }


def summarize_stock(
    rows: list[dict],
    *,
    quote: dict | None = None,
    is_bank: bool = False,
) -> dict:
    if len(rows) < 20:
        raise ValueError("at least 20 daily bars are required")
    current = rows[-1]
    previous = rows[-2]
    older = rows[-3]
    quality = (quote or {}).get("quality", "historical_only")
    blocked = quality == "conflict"
    close = float((quote or {}).get("price") or current["close"])
    ma5 = float(current["ma5"])
    ma20 = float(current["ma20"])

    observations = []
    observations.append("站上MA5" if close >= ma5 else "跌破MA5")
    observations.append("站上MA20" if close >= ma20 else "位于MA20下")
    observations.append(
        "MACD红柱" if current["macd_hist"] >= 0 else "MACD绿柱"
    )

    bank_signal = None
    if is_bank:
        shrinking = (
            current["macd_hist"] < 0
            and current["macd_hist"] > previous["macd_hist"] > older["macd_hist"]
        )
        near_ma5 = abs(close - ma5) / ma5 <= 0.015
        if close < ma20 and shrinking and near_ma5:
            if current["dif"] < 0 and current["dea"] < 0:
                bank_signal = "below_zero_observation"
            elif current["dif"] >= 0 and current["dea"] >= 0:
                bank_signal = "above_zero_observation"
            else:
                bank_signal = "mixed_axis_no_edge"

    if blocked:
        conclusion = "双源价格冲突，仅展示数据，不形成操作结论。"
    elif bank_signal == "below_zero_observation":
        conclusion = "银行零轴下修复观察信号，需结合板块和大盘确认。"
    elif bank_signal == "above_zero_observation":
        conclusion = "银行零轴上波段观察信号，统计优势有限。"
    elif close >= ma5 and close >= ma20:
        conclusion = "趋势结构偏强，仍需题材宽度和盘中承接确认。"
    else:
        conclusion = "趋势结构未完全确认，保持观察。"

    return {
        "trade_date": (quote or {}).get("trade_date") or current.get("trade_date"),
        "close": close,
        "ma5": ma5,
        "ma20": ma20,
        "macd_hist": current["macd_hist"],
        "data_quality": quality,
        "blocked": blocked,
        "bank_signal": bank_signal,
        "observations": observations,
        "conclusion": conclusion,
    }
