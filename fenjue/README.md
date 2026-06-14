# 焚诀（Fenjue）— A股短线技术筛选系统

基于 MA5/MA20 金叉、MACD、成交额等多策略交叉筛选沪深主板强势标的。

## 快速开始

```bash
pip install akshare pandas
cd fenjue-pkg/scripts
python3 build_pool.py --date 20260612 --top 300
python3 screen_pool.py pool_YYYYMMDD.json    # 策略1-3
python3 screen_pool2.py pool_YYYYMMDD.json   # 策略4-6 + 跨策略交集
```

深度分析：

```bash
cd fenjue-pkg
python3 -m fenjue --root . analyze 600176 002129 --json
```

## 新增功能（v2）

### CLI 新命令

```bash
# 09:25 竞价快照 + Strategy B 研究候选（盘中用）
python -m fenjue --root . snapshot --pool-file pool.json --output-dir snapshots/

# 主池全量逆市切换扫描（盘后用）
python -m fenjue --root . scan-regime --pool-file pool.json

# 信号结果回填验证（回测5T/10T/20T）
python -m fenjue --root . validate-signals --signal-type regime_shift
```

### 新模块
- `fenjue/pool.py` — 池过期校验：>1T 警告，>3T 拒绝
- `fenjue/validation.py` — 信号回测：独立日期统计、胜率/盈亏比
- `fenjue/workflows.py` — 竞价快照 + Strategy B + 逆市切换

---

## 六策略

| # | 策略 | 条件 |
|---|------|------|
| 1 | 快金叉 | MA5/MA20差 -8%~+3% + 成交>1亿 |
| 2 | 底部潜伏 | 涨<5% + 成交3-15亿 + 非热门板块 |
| 3 | 低位金叉+量 | 同1 + 涨-3%~+3% + 成交>3亿 |
| 4 | 大成交暗流 | 成交>15亿 + 涨<5% |
| 5 | 板块共振+个股低位 | 板块≥3只在池 + 个股涨<3% |
| 6 | 多因子评分 | 涨2-7% + 成交>5亿 + MA20乖离<25% |

**跨策略交集（≥2策）为候选观察，不=胜率叠加。**

---

## 规则

1. 仅沪深主板，排除科创/创业/北交/ST
2. 池>1T警告，>3T拒绝
3. 禁止引用旧版90-97%胜率（存在未来函数）
4. Strategy B 旧11样本91%不得写成稳定胜率
5. 同日多股触发只算一个独立日期
6. 不替用户下单

## 目录

```
fenjue-pkg/
├── fenjue/          # Python 核心（CLI + 引擎 + 校验 + 工作流）
├── scripts/         # 建池 + 六策略筛选
├── references/      # 策略文档 + 回测记录
└── README.md
```
