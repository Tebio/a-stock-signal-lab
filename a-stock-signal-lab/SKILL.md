---
name: a-stock-signal-lab
description: A股短线研究、持仓账本、事件冻结、个股股性、买卖时点与影子验证。用于用户提供买价/时间、询问核心仓或做T、竞价与9:40/10:30/14:30时点、公告监管、底层逻辑或次日10:30目标时。仅作研究辅助，不替用户下单，不伪造实时数据或稳定胜率。
---

# A-Stock Signal Lab

使用本目录中的 Python 核心、筛选脚本和策略参考资料完成 A 股研究任务。

## 基本规则

1. 默认仅研究沪深主板，排除科创板、创业板、北交所和 ST。
2. 候选池超过 1 个交易日要提示；超过 3 个交易日拒绝继续筛选。
3. 跨策略交集只代表候选观察，不代表胜率叠加。
4. 禁止引用旧版 90%-97% 胜率；Strategy B 的旧 11 样本不得描述为稳定胜率。
5. 同日多股触发按一个独立日期统计。
6. 所有结论必须标明“研究辅助，不是买卖指令”。
7. 先识别 `CORE_HOLD`、`TACTICAL_T`、`NEW_ENTRY`、`RISK` 或 `OBSERVE`，策略族之间不得用总分互相抵消。
8. 用户提供的大致买入时间和价格写入 V2 账本；拿不到券商成交记录时不得伪造成交价。
9. 新买或加仓前必须检查：官方事件源、时间可用性、逻辑证据、市场状态、个股股性、成交可达性和风险预算。任一关键项缺失就拒绝或观察。
10. A/B级证据决定逻辑是否可信；竞价、板块、情绪和盘口决定短线时机。C/D级利好不能解除监管冻结。
11. 竞价高开1%–3%、4%–7%、8%–10%只是待验证假设，不直接映射买卖；必须结合该股历史冲高回落率、V形修复率与当日承接。
12. 概率状态不是 `probability_ready` 时，只报告样本频率和区间，不输出精确概率或概率驱动仓位。

## Hermes 决策流程

1. 提取账户、代码、买价、大致时间、数量、核心仓下限、用户意图和逻辑簇。
2. 查询交易所、巨潮、公司公告及监管状态并记录首次看见时间。官方源不可用时禁止 `NEW_ENTRY` 和 `ADD`。
3. 用 `fenjue.thesis.evaluate_logic_evidence()` 检查 A/B 级硬证据、公司直接暴露和负面证伪。
4. 用历史同股样本生成 `StockBehaviorProfile`；少于20个样本标为未验证。
5. 用 `evaluate_entry_window()` 分别判断 09:40、10:30 或 14:30，不把竞价区间当买入指令。
6. 涨停买入无 A/B 级队列证据、跌停卖出无买盘证据时，成交状态必须为 `unknown`。
7. 运行五策略族门控，输出动作、拒绝原因、最大风险上限、失效条件和下一检查点。
8. `research`、`shadow`、`production` 必须经过同一决策图；只有已发布且策略族/政策版本匹配的 production 策略可以带 `executable=true`。
9. 明确提示这是研究辅助；不自动下单。

## 环境

运行建池和筛选脚本前安装：

```bash
python -m pip install akshare pandas
```

Python 模块命令应在本 Skill 目录执行，或将本目录加入 `PYTHONPATH`。

## 常用任务

### 个股分析

```bash
python -m fenjue --root . analyze 600176 002129 --json
```

### 建立候选池

```bash
python scripts/build_pool.py --date YYYYMMDD --top 300
```

### 六策略筛选

```bash
python scripts/screen_pool.py pool_YYYYMMDD.json
python scripts/screen_pool2.py pool_YYYYMMDD.json
```

### 竞价快照

```bash
python -m fenjue --root . snapshot --pool-file pool.json --output-dir snapshots/
```

### 逆市切换扫描

```bash
python -m fenjue --root . scan-regime --pool-file pool.json
```

### 信号验证

```bash
python -m fenjue --root . validate-signals --signal-type regime_shift
```

### 初始化审计型 V2 数据库

```bash
python -m fenjue --root /opt/data/fenjue v2-init
python -m fenjue --root /opt/data/fenjue v2-integrity
```

### 盘中标签与基准回归

```bash
python -m fenjue --root /opt/data/fenjue v2-backfill-outcome \
  --intent-id INTENT_ID --calculation-version outcome-v1

python -m fenjue --root /opt/data/fenjue v2-baseline run \
  --payload-json baseline-run.json
```

### 运行模式

```bash
python -m fenjue --root /opt/data/fenjue v2-decide \
  --context-json context.json --run-mode research

python -m fenjue --root /opt/data/fenjue v2-decide \
  --context-json context.json --run-mode shadow \
  --strategy-version-id strategy-shadow-v1
```

事件冻结始终在技术评分前执行。人工申请通过只代表可以进入解除流程，不会自动解除冻结；正式解除仍需写 `freeze_release_audits`。

### 记录用户提供的持仓

```bash
python -m fenjue --root /opt/data/fenjue v2-ledger \
  --account main --code 600378 --mode CORE_HOLD \
  --logic-cluster electronic_specialty_gases --core-floor 500 \
  --quantity 1000 --buy-price 18.72 --buy-date 2026-06-27 \
  --sellable-from 2026-06-30 --trade-date 2026-06-27 \
  --equity-fen 10000000
```

数据库只给研究权限和风险上限，不连接券商、不自动下单。生产库必须挂载到持久卷，影子运行只能通过 `ShadowWriter` 写 `shadow_decisions`。

## 参考资料

- 总体说明：`README.md`
- 策略规则：`references/strategy.md`
- 统一策略：`references/unified-strategy.md`
- 数据源：`references/data-sources.md`
- 回测方法：`references/backtest-methodology.md`
- 已验证策略：`references/verified-strategies.md`
- V2共享契约：`docs/superpowers/specs/context_contract.md`
- 持仓、事件、成交、策略族与影子治理：`docs/superpowers/specs/01_position_ledger_design.md` 至 `05_backtest_governance_and_shadow_run.md`
- 八个工程闭环：`docs/engineering/01_trading_calendar.md` 至 `08_ci.md`

只在任务需要时读取对应参考文件。
