from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any


@dataclass(frozen=True)
class LogicGate:
    eligible_for_core_hold: bool
    eligible_for_new_entry: bool
    logic_invalidated: bool
    exposure_purity_ratio: float
    hard_evidence_count: int
    weakest_link: str | None


def evaluate_logic_evidence(events: Iterable[Mapping[str, Any]]) -> LogicGate:
    rows = list(events)
    critical_negative = any(
        row.get("evidence_tier") == "A"
        and row.get("exposure_direction") == "negative"
        and row.get("severity") in {"high", "critical"}
        for row in rows
    )
    hard_positive = [
        row for row in rows
        if row.get("evidence_tier") in {"A", "B"}
        and row.get("exposure_direction") == "positive"
        and float(row.get("exposure_confidence_ratio", 0.0)) >= 0.5
    ]
    purity = (
        sum(float(row.get("exposure_confidence_ratio", 0.0)) for row in hard_positive)
        / len(hard_positive)
        if hard_positive else 0.0
    )
    if critical_negative:
        weakest = "A_LEVEL_NEGATIVE_EVENT"
    elif not hard_positive:
        weakest = "NO_A_OR_B_LEVEL_POSITIVE_EVIDENCE"
    elif len(hard_positive) < 2:
        weakest = "HARD_EVIDENCE_NOT_CROSS_VALIDATED"
    elif purity < 0.7:
        weakest = "LOW_DIRECT_EXPOSURE_PURITY"
    else:
        weakest = None
    core_eligible = bool(hard_positive) and not critical_negative
    entry_eligible = (
        len(hard_positive) >= 2
        and purity >= 0.7
        and not critical_negative
    )
    return LogicGate(
        eligible_for_core_hold=core_eligible,
        eligible_for_new_entry=entry_eligible,
        logic_invalidated=critical_negative,
        exposure_purity_ratio=purity,
        hard_evidence_count=len(hard_positive),
        weakest_link=weakest,
    )
