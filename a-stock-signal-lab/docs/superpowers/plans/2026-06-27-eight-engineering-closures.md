# Fenjue Eight Engineering Closures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按用户指定顺序补齐交易日历、脚本兼容、标签回填、两阶段预算、事件冻结、运行模式、基准评估和 CI 八个工程闭环。

**Architecture:** 在现有30表 V2 schema 之上使用版本化 SQL migration；每个闭环独立 migration、服务模块、接口文档和测试，完成后单独提交。旧 CLI 和旧表保持可用，新接口只追加能力。

**Tech Stack:** Python 3.10+ 标准库、SQLite、unittest、GitHub Actions。

---

### Task 1: Trading calendar

**Files:** `fenjue/migrations.py`, `fenjue/sql/migrations/001_trading_calendar_up.sql`, `001_trading_calendar_down.sql`, `fenjue/trading_calendar.py`, `tests/test_trading_calendar.py`, `docs/engineering/01_trading_calendar.md`。

- [x] 先写失败测试：周末、节假日、T+N、缺日历拒绝。
- [x] 实现 migration runner 和 `TradingCalendar.next_trade_date/add_trade_days`。
- [x] 替换 V2 新代码中的手写交易日推进接口。
- [x] 运行全量测试、migration up/down/up dry-run并提交。

### Task 2: Script configuration compatibility

**Files:** `scripts/build_pool.py`, `scripts/screen_pool.py`, `scripts/screen_pool2.py`, `scripts/compat_*.py`, `tests/test_script_compat.py`, `docs/engineering/02_script_compat.md`。

- [ ] 先写失败测试：任意工作目录、显式日期、环境根目录、旧参数 wrapper。
- [ ] 清理硬编码路径和运行日默认值；日期缺失时明确取上海当前日期并输出来源。
- [ ] 保留旧入口 wrapper，运行原 CLI 回归并提交。

### Task 3: Audited intraday labels

**Files:** migration `003_intraday_audit_*`, `fenjue/outcomes.py`, CLI增量、测试与 `docs/engineering/03_intraday_outcomes.md`。

- [ ] 先写失败测试：next trade date、四时点、缺bar不可评分、时间可用性。
- [ ] 新增 `market_bars_audit` 并复用现有 `trade_intents/intraday_outcomes`。
- [ ] 实现09:25/09:40/10:30/14:30标签回填和CLI，回归并提交。

### Task 4: Two-phase portfolio budgets

**Files:** migration `004_portfolio_budget_*`, `fenjue/budget.py`,测试与 `docs/engineering/04_portfolio_budget.md`。

- [ ] 先写失败测试：资格预检、最终扣减、幂等、逻辑簇上限。
- [ ] 新增三张预算表和事务化 reserve/consume/release。
- [ ] 接入 DecisionEngine 风险门，回归并提交。

### Task 5: Freeze and override workflow

**Files:** migration `005_event_override_*`, `fenjue/events.py`,测试与 `docs/engineering/05_event_freezes.md`。

- [ ] 先写失败测试：停复牌、问询、处分、重大公告、人工覆盖不能直接解除。
- [ ] 复用既有冻结/解除表，新增 `override_requests` 和事件政策映射。
- [ ] 确保冻结优先于技术评分，回归并提交。

### Task 6: Decision run modes

**Files:** migration `006_decision_run_mode_*`, `fenjue/decision.py`, `fenjue/shadow.py`, CLI、测试与 `docs/engineering/06_decision_run_modes.md`。

- [ ] 先写失败测试：research/shadow/production共享图、仅production可执行、未发布策略拒绝。
- [ ] 增加 `run_mode` 与统一决策图结果持久化。
- [ ] 保持原 `DecisionEngine.decide(context)` 兼容，回归并提交。

### Task 7: Baseline runner

**Files:** migration `007_baseline_runs_*`, `fenjue/baselines.py`, CLI、测试与 `docs/engineering/07_baseline_runner.md`。

- [ ] 先写失败测试：日/簇去重、lift、净期望、覆盖率、Brier、ECE。
- [ ] 实现相同成本/成交门下的候选与基准对比并持久化。
- [ ] 输出JSON报告，回归并提交。

### Task 8: GitHub Actions

**Files:** `.github/workflows/quality.yml`, `scripts/ci_*.py`, fixtures、测试与 `docs/engineering/08_ci.md`。

- [ ] 增加 lint、unit、migration dry-run、fixture replay、shadow-vs-baseline regression 五个 job/step。
- [ ] 本地逐个运行相同命令并保存稳定 fixture。
- [ ] 验证旧 CLI 帮助与命令不变，提交并推送分支。
