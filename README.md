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

## Fenjue V2

V2 新增可审计持仓账本、T+1与核心仓保护、风险预算、事件时间可用性、监管冻结、成交可达性、个股冲高回落/V形股性、五策略族隔离和只读影子验证。所有价格与金额使用整数最小单位，SQLite 每个连接强制外键。

```bash
cd a-stock-signal-lab
python -m unittest discover -s tests -v
python -m fenjue --root ~/.fenjue v2-init
python -m fenjue --root ~/.fenjue v2-integrity
```

完整设计和极空间迁移约束见 [V2规格目录](a-stock-signal-lab/docs/superpowers/specs)。

## 声明

本项目仅用于数据研究和策略验证，不构成投资建议或买卖指令。
