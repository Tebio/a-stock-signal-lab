#!/usr/bin/env python3
"""焚诀 20260508 - 仅沪深主板 (排除300/301/688/920)"""
import os, sys, json

for k in list(os.environ.keys()):
    if 'proxy' in k.lower(): del os.environ[k]

import akshare as ak
from collections import Counter

qs = ak.stock_zt_pool_strong_em(date='20260508')
print(f'强势股池 5/8: {len(qs)}只')

# 仅沪深主板: 600/601/603/605 + 000/001/002/003
def is_main_board(code):
    code = str(code)
    return code[:3] in ('600','601','603','605') or code[:3] in ('000','001','002','003')

f = qs[
    (qs['涨跌幅'] > 5) &
    (qs['量比'] > 2) &
    (qs['换手率'] > 3) &
    (qs['换手率'] < 25) &
    (qs['总市值'] < 5e10) &
    (qs['代码'].apply(is_main_board))
].copy()
f = f.sort_values('涨跌幅', ascending=False)

print(f'🔥 焚诀 5/8 沪深主板: {len(f)}只\n')

results = []
for _, r in f.iterrows():
    mc = r['总市值']/1e8
    amt = r['成交额']/1e8
    print(f"{r['代码']} {r['名称']:<8} {r['最新价']:>7.2f} {r['涨跌幅']:>+7.2f}% 量{r['量比']:>5.1f} 换{r['换手率']:>5.1f}% {mc:>6.0f}亿 {amt:>5.0f}亿  {r['所属行业']}")
    results.append(dict(
        code=r['代码'], name=r['名称'],
        price=float(r['最新价']), pct=float(r['涨跌幅']),
        vol_ratio=float(r['量比']), turnover=float(r['换手率']),
        mcap_yi=round(mc,1), amount_yi=round(amt,1),
        sector=r.get('所属行业',''), reason=r.get('入选理由',''),
    ))

sectors = Counter(r['sector'] for r in results)
print(f'\n📋 板块TOP10:')
for sec, cnt in sectors.most_common(10):
    print(f'  {sec}: {cnt}只')

os.makedirs('/opt/data/fenjue', exist_ok=True)
with open('/opt/data/fenjue/20260508_main.json', 'w') as fh:
    json.dump({'date':'20260508','board':'沪深主板','count':len(f),'results':results}, fh, ensure_ascii=False, indent=2)

# 对比5/7沪深
try:
    with open('/opt/data/fenjue/20260507_main.json') as fh:
        old = json.load(fh)
except:
    # 如果5/7沪深版不存在，现跑一个
    with open('/opt/data/fenjue/20260507_main.json', 'w') as fh:
        json.dump({'date':'20260507','results':[]}, fh)
    old = {'results':[]}

old_codes = {r['code'] for r in old['results']}
new_codes = {r['code'] for r in results}
common = old_codes & new_codes
gone = old_codes - new_codes
fresh = new_codes - old_codes

if old['results']:
    print(f'\n🔄 5/7沪深 → 5/8沪深:')
    print(f'  连续强势({len(common)}只):', ' '.join(sorted(common)) if common else '无')
    if gone:
        print(f'  退出({len(gone)}只)')
    if fresh:
        print(f'  新进({len(fresh)}只)')

print(f'\n💾 /opt/data/fenjue/20260508_main.json')
