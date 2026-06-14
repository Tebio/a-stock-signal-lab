---
name: a-stock-signal-lab
description: A股短线技术研究与候选筛选。用于用户要求A股信号实验室、A股候选池、MA5/MA20、MACD、板块共振、逆市切换、竞价快照、个股分析或信号验证时。仅作研究辅助，不替用户下单，不将未验证小样本描述为稳定胜率。
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

## 参考资料

- 总体说明：`README.md`
- 策略规则：`references/strategy.md`
- 统一策略：`references/unified-strategy.md`
- 数据源：`references/data-sources.md`
- 回测方法：`references/backtest-methodology.md`
- 已验证策略：`references/verified-strategies.md`

只在任务需要时读取对应参考文件。
