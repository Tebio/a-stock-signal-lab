# Fenjue V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把五份焚诀设计规格落成可测试、默认拒绝低质量动作、可在 Hermes Docker 中持久化和影子运行的 Python 实现。

**Architecture:** 保留现有行情分析内核，新增独立 V2 SQLite 存储与四个业务模块；所有动作先生成不可变快照，再经过账本、事件、成交、策略族和风险门。生产路径只给研究动作与拒绝原因，不自动下单；影子路径使用受限写接口。

**Tech Stack:** Python 3.10+ 标准库、SQLite、`unittest`、现有 `fenjue` CLI。

---

### Task 1: V2 database foundation

**Files:**
- Create: `fenjue/sql/schema_v2.sql`
- Create: `fenjue/sql/integrity_checks.sql`
- Create: `fenjue/v2db.py`
- Test: `tests/test_v2db.py`

- [ ] 写失败测试：每个连接启用外键、30张表可初始化、孤儿记录被拒绝、金额价格列不用 `REAL`。
- [ ] 运行 `python -m unittest tests.test_v2db -v`，确认因 `fenjue.v2db` 不存在而失败。
- [ ] 实现 `FenjueV2Database`、事务、schema初始化、完整性报告和兼容性探针。
- [ ] 重跑测试并提交 `feat: add fenjue v2 database foundation`。

### Task 2: Position ledger and risk budget

**Files:**
- Create: `fenjue/ledger.py`
- Test: `tests/test_ledger.py`

- [ ] 写失败测试：T+1、核心仓下限、整数价格、无风险配置不出数量、配置重叠拒绝、对账异常切换 `OBSERVE`。
- [ ] 运行单测确认失败。
- [ ] 实现账户、持仓、批次、快照、两阶段风险预算和事故审计。
- [ ] 重跑测试并提交 `feat: implement position ledger and risk budgets`。

### Task 3: Event availability and freezes

**Files:**
- Create: `fenjue/events.py`
- Test: `tests/test_events.py`

- [ ] 写失败测试：延迟抓取不可提前使用、冻结必须有事件、无解除审计不能释放、A级源中断阻止新增风险。
- [ ] 运行单测确认失败。
- [ ] 实现原始快照、事件版本、实体关联、冻结/解除事务和来源健康门。
- [ ] 重跑测试并提交 `feat: add event availability and freeze gates`。

### Task 4: Execution and outcomes

**Files:**
- Create: `fenjue/execution.py`
- Test: `tests/test_execution.py`

- [ ] 写失败测试：涨停无队列不判成交、跌停无买盘不判成交、同分钟双触发为歧义、10:30缺失不可评分、扣成本后3%标签反转。
- [ ] 运行单测确认失败。
- [ ] 实现整数价格成本、来源选择、成交评估和 `NEW_ENTRY`/`TACTICAL_T` 结果计算。
- [ ] 重跑测试并提交 `feat: add execution reachability and outcomes`。

### Task 5: Strategy family decision and rejection

**Files:**
- Create: `fenjue/decision.py`
- Test: `tests/test_decision.py`

- [ ] 写失败测试：强逻辑退潮不加仓、监管冻结接管、风险预算为零拒绝、输入缺失观察、未校准概率不出生产概率。
- [ ] 运行单测确认失败。
- [ ] 实现完整 `DecisionContext`、五策略族、门控顺序、决策快照与拒绝审计。
- [ ] 重跑测试并提交 `feat: implement strategy-family decision engine`。

### Task 6: Shadow governance and CLI

**Files:**
- Create: `fenjue/shadow.py`
- Modify: `fenjue/cli.py`
- Modify: `fenjue/__init__.py`
- Test: `tests/test_shadow.py`
- Test: `tests/test_v2_cli.py`

- [ ] 写失败测试：影子接口不能写持仓、99样本仍只给频率、泄漏版本退役、CLI 可初始化/检查/录入持仓/决策。
- [ ] 运行单测确认失败。
- [ ] 实现受限影子写、概率门、V2 CLI 子命令和 JSON 输出。
- [ ] 重跑测试并提交 `feat: expose safe fenjue v2 workflows`。

### Task 7: Package, docs, and release verification

**Files:**
- Create: `pyproject.toml`
- Create: `docs/superpowers/specs/*`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: repository root `README.md`

- [ ] 同步设计规格、schema说明、迁移与验收矩阵，排除缓存和运行数据库。
- [ ] 更新 Hermes 安装、持久卷、初始化、只读影子和回滚说明。
- [ ] 运行 `python -m unittest discover -s tests -v`、`compileall`、CLI烟测和SQLite完整性检查。
- [ ] 查看 `git diff --check` 和变更清单，提交并推送功能分支。
- [ ] 通过 GitHub App 创建 PR，附测试证据和极空间部署前置条件。
