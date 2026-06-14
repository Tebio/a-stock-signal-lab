#!/usr/bin/env python3
"""T-1备选池 v4 — Sina数据源 K线"""
import argparse, os, sys, json, time
from pathlib import Path

for k in list(os.environ.keys()):
    if 'proxy' in k.lower(): del os.environ[k]

if "/opt/data/python-libs" not in sys.path:
    sys.path.insert(0, "/opt/data/python-libs")

import akshare as ak

parser = argparse.ArgumentParser(description="Build T-1 Fenjue candidate pool")
parser.add_argument("--date", default="20260508", help="Trade date, e.g. 20260508")
parser.add_argument("--out-dir", default="/opt/data/fenjue", help="Output directory")
parser.add_argument("--top", type=int, default=300)
parser.add_argument("--sleep", type=float, default=0.4)
args = parser.parse_args()

DATE = args.date.replace("-", "")
print(f'⏳ {DATE} 备选池 (Sina源 K线)...', flush=True)

qs = ak.stock_zt_pool_strong_em(date=DATE)
def mb(c): return str(c)[:3] in ('600','601','603','605','000','001','002','003')
qs = qs[qs['代码'].apply(mb)].sort_values('成交额', ascending=False).head(args.top)
codes = qs['代码'].tolist()
print(f'沪深主板前300: {len(codes)}只', flush=True)

def to_sina(code):
    c = str(code)
    return ('sh' if c[0] == '6' else 'sz') + c

results = []
errors = 0
start = time.time()

for i, (_, row) in enumerate(qs.iterrows()):
    code = row['代码']
    try:
        sina_code = to_sina(code)
        hist = ak.stock_zh_a_daily(symbol=sina_code, start_date='20250801', end_date=DATE, adjust='qfq')
        if len(hist) < 20:
            errors += 1
            time.sleep(0.2)
            continue
        closes = hist['close'].tolist()
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        close = closes[-1]
        
        if close > ma5 or close > ma20:
            results.append(dict(
                code=code, name=row['名称'],
                price=float(row['最新价']), pct=float(row['涨跌幅']),
                amount_yi=round(row['成交额']/1e8, 1),
                mcap_yi=round(row['总市值']/1e8, 1),
                sector=row.get('所属行业', ''),
                ma5=round(ma5, 2), ma20=round(ma20, 2),
                line_signal='MA5' if close > ma5 else 'MA20',
            ))
    except Exception as e:
        errors += 1
    
    time.sleep(args.sleep)  # Sina源轻量限流
    if (i+1) % 30 == 0:
        e = time.time() - start
        print(f'  {i+1}/{len(codes)} ({e:.0f}s) 通过{len(results)} 错{errors}', flush=True)

elapsed = time.time() - start
print(f'\n✅ {elapsed:.0f}秒 | 通过{len(results)}只 | 错误{errors}', flush=True)

results.sort(key=lambda x: x['amount_yi'], reverse=True)

print(f'\n📋 T-1备选池({len(results)}只): 仅沪深主板，科创/创业/北交排除；成交额前{args.top}，收盘站上MA5或MA20\n', flush=True)
for r in results[:50]:
    print(f"{r['code']} {r['name']:<8} {r['price']:>7.2f} {r['pct']:>+6.2f}% {r['amount_yi']:>5.0f}亿 MA5={r['ma5']} MA20={r['ma20']} {r['line_signal']} {r['sector']}", flush=True)

out_dir = Path(args.out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f'pool_{DATE}.json'
with out_path.open('w', encoding='utf-8') as fh:
    json.dump({'date': DATE, 'count': len(results), 'elapsed': round(elapsed), 'results': results}, fh, ensure_ascii=False, indent=2)
print(f'\n💾 {out_path} ({len(results)}只)', flush=True)
