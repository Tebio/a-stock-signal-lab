from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any


@dataclass(frozen=True)
class StockBehaviorProfile:
    dominant_pattern: str
    fade_ratio: float
    v_recovery_ratio: float
    sample_count: int
    status: str


@dataclass(frozen=True)
class TimingGate:
    eligible: bool
    entry_window: str
    auction_regime: str
    reason_codes: tuple[str, ...]


def classify_auction_gap(gap_pct_points: float) -> str:
    if 1.0 <= gap_pct_points <= 3.0:
        return "CONSTRUCTIVE_GAP"
    if 4.0 <= gap_pct_points <= 7.0:
        return "FADE_RISK_GAP"
    if 8.0 <= gap_pct_points <= 10.0:
        return "HIGH_OPEN_CONFIRMATION_REQUIRED"
    return "OUTSIDE_PRIMARY_HYPOTHESIS"


def profile_stock_behavior(
    episodes: Iterable[Mapping[str, Any]], minimum_samples: int = 20
) -> StockBehaviorProfile:
    rows = list(episodes)
    sample_count = len(rows)
    if not rows:
        return StockBehaviorProfile("UNKNOWN", 0.0, 0.0, 0, "UNVERIFIED")
    fade_ratio = sum(bool(row.get("faded")) for row in rows) / sample_count
    v_ratio = sum(bool(row.get("v_recovered")) for row in rows) / sample_count
    status = "VERIFIED" if sample_count >= minimum_samples else "UNVERIFIED"
    if fade_ratio >= 0.55 and fade_ratio - v_ratio >= 0.15:
        pattern = "FADE"
    elif v_ratio >= 0.55 and v_ratio - fade_ratio >= 0.15:
        pattern = "V_RECOVERY"
    else:
        pattern = "MIXED"
    return StockBehaviorProfile(pattern, fade_ratio, v_ratio, sample_count, status)


def evaluate_entry_window(
    entry_window: str,
    profile: StockBehaviorProfile,
    *,
    auction_gap_pct_points: float,
    stabilized: bool,
    wash_and_reclaim: bool,
    market_regime: str,
) -> TimingGate:
    auction = classify_auction_gap(auction_gap_pct_points)
    reasons: list[str] = []
    if profile.status != "VERIFIED":
        reasons.append("STOCK_BEHAVIOR_UNVERIFIED")
    if market_regime == "RETREAT":
        reasons.append("MARKET_RETREAT")
    if entry_window == "09:40":
        if auction == "FADE_RISK_GAP" and profile.dominant_pattern == "FADE":
            reasons.append("STOCK_SPECIFIC_FADE_RISK")
        if auction == "HIGH_OPEN_CONFIRMATION_REQUIRED" and not wash_and_reclaim:
            reasons.append("HIGH_OPEN_NOT_RECLAIMED")
    elif entry_window == "10:30":
        if not stabilized:
            reasons.append("TEN_THIRTY_NOT_STABILIZED")
    elif entry_window == "14:30":
        if not stabilized:
            reasons.append("LATE_SESSION_STRUCTURE_UNSTABLE")
    else:
        reasons.append("UNSUPPORTED_ENTRY_WINDOW")
    return TimingGate(not reasons, entry_window, auction, tuple(reasons or ["TIMING_GATE_PASSED"]))
