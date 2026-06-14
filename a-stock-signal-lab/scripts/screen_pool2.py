#!/usr/bin/env python3
"""策略4-6: 大成交暗流 + 下午多因子 + 蓄力期板块。"""
import glob
import json
import sys
from collections import Counter
from pathlib import Path

for root in (
    Path(__file__).resolve().parents[1],
    Path("/opt/data/skills/fenjue-screening"),
):
    if (root / "fenjue" / "pool.py").exists():
        sys.path.insert(0, str(root))
        break

from fenjue.pool import PoolExpiredError, validate_pool_date

pool_file = sorted(glob.glob('/opt/data/fenjue/pool_*.json'))[-1]
try:
    pool_status = validate_pool_date(pool_file)
except PoolExpiredError as exc:
    raise SystemExit(f"拒绝运行：{exc}") from exc
if pool_status["level"] == "warning":
    print(
        "⚠️ 股票池已超过1个交易日，结果仅供观察："
        f"{pool_status['trading_days_old']}T"
    )
with open(pool_file) as f:
    pool = json.load(f)['results']

# ========================================
# 策略4: 大成交暗流 — 成交>15亿 + 涨<5% + 非涨停
# ========================================
print('='*65)
print('🌊 策略4: 大成交暗流 (成交>15亿 + 涨<5% + 有MA数据)')
print('='*65)
dark = []
for s in pool:
    pct = s.get('pct', 0) or 0
    amt = s.get('amount_yi', 0) or 0
    if amt > 15 and pct < 5:
        ma5 = s.get('ma5')
        ma20 = s.get('ma20')
        gap = round((ma5/ma20 - 1)*100, 1) if ma5 and ma20 else None
        dark.append({'name': s['name'], 'code': s['code'], 'pct': pct, 'amt': amt,
                     'sector': s.get('sector',''), 'ma_gap': gap})
dark.sort(key=lambda x: x['amt'], reverse=True)
print(f'候选: {len(dark)}只')
for s in dark[:15]:
    g = f"MA差{s['ma_gap']:+5.1f}%" if s['ma_gap'] is not None else '无MA'
    print(f'  {s["code"]} {s["name"]:<8} 涨{s["pct"]:+5.1f}% 成交{s["amt"]:.0f}亿 {g} {s["sector"]}')

# ========================================
# 策略5: 板块共振 + 个股低位
# ========================================
print()
print('='*65)
print('🔗 策略5: 板块有共振 + 个股低位 (板块≥3只 + 个涨<3%)')
print('='*65)
sector_counts = Counter(s.get('sector','') for s in pool)
resonance_sectors = {sec: n for sec, n in sector_counts.items() if n >= 3}

for sec, n in sorted(resonance_sectors.items(), key=lambda x: x[1], reverse=True):
    sector_stocks = [s for s in pool if s.get('sector','') == sec and (s.get('pct',0) or 0) < 3]
    if not sector_stocks:
        continue
    print(f'\n  [{sec}] {n}只在池')
    for s in sorted(sector_stocks, key=lambda x: x.get('amount_yi',0) or 0, reverse=True)[:3]:
        pct = s.get('pct', 0) or 0
        amt = s.get('amount_yi', 0) or 0
        print(f'    {s["code"]} {s["name"]:<8} 涨{pct:+5.1f}% 成交{amt:.0f}亿')

# ========================================
# 策略6: 下午多因子评分 (模拟)
# 涨2-7% + 成交>5亿 + MA20乖离<25% + 非涨停
# ========================================
print()
print('='*65)
print('⭐ 策略6: 多因子评分 (涨2-7% + 成交>5亿 + MA20乖离<25%)')
print('='*65)
multi = []
for s in pool:
    pct = s.get('pct', 0) or 0
    amt = s.get('amount_yi', 0) or 0
    ma5 = s.get('ma5')
    ma20 = s.get('ma20')
    if not ma5 or not ma20:
        continue
    gap = (s.get('price', ma5) / ma20 - 1) * 100 if s.get('price') else (ma5/ma20 - 1)*100
    if 2 <= pct <= 7 and amt > 5 and gap < 25:
        score = (1 - abs(pct-4.5)/4.5) * 25  # 涨幅甜区4.5%
        score += (1 - abs(gap-12)/12) * 25     # MA20乖离甜区12%
        score += min(amt/30, 1) * 10            # 成交
        score += 10                              # 基础分（已通过过滤）
        multi.append({'name': s['name'], 'code': s['code'], 'pct': pct, 'amt': amt,
                      'ma_gap': round(gap,1), 'sector': s.get('sector',''), 'score': round(score,1)})
multi.sort(key=lambda x: x['score'], reverse=True)
print(f'候选: {len(multi)}只')
for s in multi[:15]:
    print(f'  [{s["score"]:4.1f}] {s["code"]} {s["name"]:<8} 涨{s["pct"]:+5.1f}% MA差{s["ma_gap"]:+4.1f}% 成交{s["amt"]:.0f}亿 {s["sector"]}')

# ========================================
# 汇总：跨策略交集
# ========================================
print()
print('='*65)
print('🔎 跨策略交集候选: 出现在 ≥2 个策略中的票')
print('='*65)
print('⚠️ 交集只表示过滤条件重叠，不代表胜率叠加，必须额外确认。')

# 重算策略1和策略3 (同 screen_pool.py 逻辑)
golden = []
low_golden = []
for s in pool:
    ma5 = s.get('ma5')
    ma20 = s.get('ma20')
    if not ma5 or not ma20:
        continue
    gap = (ma5 - ma20) / ma20 * 100
    amt = s.get('amount_yi', 0) or 0
    pct = s.get('pct', 0) or 0
    if -8 <= gap <= 3 and amt > 1:
        golden.append({'code': s['code'], 'name': s['name'], 'ma_gap': round(gap, 1)})
    if -8 <= gap <= 3 and -3 <= pct <= 3 and amt > 3:
        low_golden.append({'code': s['code'], 'name': s['name'], 'ma_gap': round(gap, 1)})

# 收集各策略的代码
s1_codes = {s['code'] for s in golden}
s3_codes = {s['code'] for s in low_golden}
s6_codes = {s['code'] for s in multi}
dark_codes = {s['code'] for s in dark}

all_codes = {}
for c in pool:
    code = str(c['code'])
    count = 0
    strategies = []
    if code in s1_codes: count += 1; strategies.append('快金叉')
    if code in s3_codes: count += 1; strategies.append('低位金叉')
    if code in s6_codes: count += 1; strategies.append('多因子')
    if code in dark_codes: count += 1; strategies.append('大成交')
    if count >= 2:
        all_codes[code] = {'name': c['name'], 'count': count, 'strategies': strategies,
                          'pct': c.get('pct',0) or 0, 'amt': c.get('amount_yi',0) or 0,
                          'sector': c.get('sector','')}

for code, info in sorted(all_codes.items(), key=lambda x: x[1]['count'], reverse=True):
    print(f'  [{info["count"]}策] {code} {info["name"]:<8} {", ".join(info["strategies"])} 涨{info["pct"]:+5.1f}% {info["sector"]}')
