# A-Stock Signal Lab

A 股短线技术研究、候选池构建、六策略筛选、个股分析和信号验证工具。

## 发给 Agent

```text
安装并使用 A-Stock Signal Lab：https://github.com/Tebio/a-stock-signal-lab/tree/main/a-stock-signal-lab
```

Codex 安装命令：

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --url https://github.com/Tebio/a-stock-signal-lab/tree/main/a-stock-signal-lab
```

安装后重启 Agent 或 Codex。

详细说明见 [a-stock-signal-lab/SKILL.md](a-stock-signal-lab/SKILL.md) 和 [a-stock-signal-lab/README.md](a-stock-signal-lab/README.md)。

## Fenjue V2 工程闭环

V2 现已完成交易日历、盘中标签、两阶段预算、事件冻结、三运行模式、基准评估和 CI 等工程闭环。它是可回放的研究与持仓决策系统，不连接券商，也不自动下单。

- 统一 `trading_calendar` 服务处理下一交易日与 T+N，日历覆盖不足时拒绝猜测。
- 回填次交易日 09:25、09:40、10:30、14:30 标签，并审计实际使用的 bar。
- 风险预算分为资格预检和最终定量扣减，账户、单票和逻辑簇额度均需通过。
- 停复牌、问询、纪律处分和重大公告默认先冻结，人工解除必须申请、复核、留痕。
- `research`、`shadow`、`production` 共用同一决策图；只有已发布 production 策略能输出可执行标记。
- baseline runner 输出 lift、净期望、覆盖率、Brier Score、校准误差以及逐日/逐逻辑簇结果。
- GitHub Actions 独立执行 lint、单测、迁移 dry-run、fixture replay 和 shadow-vs-baseline regression。

```bash
cd a-stock-signal-lab
python -m unittest discover -s tests -v
python -m fenjue --root ~/.fenjue v2-init
python -m fenjue --root ~/.fenjue v2-integrity
python -m fenjue --root ~/.fenjue v2-decide \
  --context-json context.json --run-mode shadow \
  --strategy-version-id strategy-shadow-v1
```

完整设计见 [V2规格目录](a-stock-signal-lab/docs/superpowers/specs)，逐步表结构、接口、伪代码、回滚和测试见 [工程闭环文档](a-stock-signal-lab/docs/engineering)。

## 声明

本项目仅用于数据研究和策略验证，不构成投资建议或买卖指令。
