from __future__ import annotations

import re

from .service import is_main_board


QUALITY_LABELS = {
    "ok": "双源一致",
    "single_source": "单源数据",
    "fallback": "备用源数据",
    "conflict": "双源冲突",
    "historical_only": "仅历史数据",
}


def extract_main_board_codes(text: str, limit: int = 20) -> list[str]:
    codes = []
    for code in re.findall(r"(?<!\d)(\d{6})(?!\d)", text or ""):
        if is_main_board(code) and code not in codes:
            codes.append(code)
        if len(codes) >= limit:
            break
    return codes


def format_group_report(payload: dict) -> str:
    lines = ["焚诀个股研究（研究辅助，不是买卖指令）"]
    for code, row in payload.get("stocks", {}).items():
        if row.get("error"):
            lines.append(f"{code}：{row['error']}")
            continue
        quality = QUALITY_LABELS.get(
            row.get("data_quality"),
            row.get("data_quality", "未知"),
        )
        lines.append(f"{code} {row.get('name', code)}｜{quality}")
        regime = row.get("regime_shift")
        if regime and regime.get("triggered"):
            validation = regime.get("rolling_validation") or {}
            lines.append(
                "  优先研究｜逆市切换："
                f"{regime['signal_date']} 后第"
                f"{regime['trading_days_since']}个交易日，"
                f"阶段={regime['window_stage']}；"
                f"10T样本={validation.get('sample_count', 0)}，"
                f"{validation.get('status', '等待结果回填')}"
            )
        bank_strength = row.get("bank_relative_strength")
        if bank_strength:
            lines.append(
                "  板块验证｜银行相对强度："
                f"{bank_strength.get('relative_5d_pct', 0):+.2f}% "
                f"({bank_strength.get('status', 'unknown')})"
            )
        deep_v = row.get("deep_v") or {}
        if deep_v.get("shape_exists"):
            if deep_v.get("support") == "supported":
                lines.append(
                    "  个股证据｜深V：本票历史样本"
                    f"{deep_v.get('sample_count')}，仅作收盘后观察。"
                )
            else:
                lines.append("  个股证据｜深V形态存在但无统计支持。")
        risk = row.get("risk_budget") or {}
        if risk.get("risk_distance_pct") is not None:
            lines.append(
                "  风险预算｜MA20参考"
                f"{risk['stop_reference']:.2f}，距离"
                f"{risk['risk_distance_pct']:.2f}%；"
                "按1%账户风险预算反推的理论敞口上限"
                f"{risk['max_exposure_pct_at_1pct_risk']:.1f}%（非仓位建议）。"
            )
        if row.get("daily_stale"):
            lines.append("  日K延迟：使用最近缓存，结论需降低权重。")
        observations = "、".join(row.get("observations") or [])
        if observations:
            lines.append(f"  结构：{observations}")
        lines.append(f"  结论：{row.get('conclusion', '保持观察。')}")
        intraday = row.get("intraday")
        if intraday:
            minute_label = (
                "5分钟线延迟"
                if intraday.get("quality") == "stale"
                else "5分钟线"
            )
            detail = "、".join(intraday.get("observations") or [])
            lines.append(f"  {minute_label}：{detail}")
            lines.append(f"  盘中：{intraday.get('conclusion', '')}")
            chase = intraday.get("chase_risk") or {}
            if chase.get("triggered"):
                lines.append(f"  风险提示：{chase.get('message')}")
    rejected = payload.get("rejected") or []
    if rejected:
        lines.append("已排除非沪深主板：" + "、".join(rejected))
    return "\n".join(lines)
