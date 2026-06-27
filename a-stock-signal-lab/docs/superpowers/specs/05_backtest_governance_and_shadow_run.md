# 05 Backtest Governance and Shadow Run

## 目标

证明新版焚诀是否相对简单规则和旧版系统产生真实增益，并在不影响 Hermes 正式输出的前提下完成影子验证。系统在通过门槛前只能称为“具备高胜率研究条件”，不能称为高胜率生产系统。

共享单位、枚举、逻辑簇和概率状态遵守 [context_contract.md](context_contract.md)，可执行 DDL 以 [schema_v2.sql](schema_v2.sql) 为唯一来源。

## 评估单位

- 独立机会日：同一交易日的相关信号不按股票数量重复计数。
- 独立逻辑簇：同一消息链、产品链或题材内多只股票视为相关样本。
- 策略族：`CORE_HOLD`、`TACTICAL_T`、`NEW_ENTRY`、`RISK` 和 `OBSERVE` 分别评估。
- 候选样本簇：三类研究假设分别评估，不合并成一个总策略。

## 表结构

本模块拥有以下表；字段和约束见 `schema_v2.sql`：

| 表 | 用途 | 强制约束 |
|---|---|---|
| `data_manifests` | 决策和实验的数据版本总清单 | 原始快照、事件、行情源、概念映射和交易日历均带版本与哈希 |
| `strategy_versions` | 策略、参数与发布状态 | 退役统一使用 `retired`，原因写入 `retire_reason`；概率状态独立保存 |
| `experiment_registry` | 假设、切分、参数搜索和 manifest | 外键连接策略版本与数据 manifest |
| `baseline_definitions` | 强制基准定义 | 外键连接相同成本模型 |
| `evaluation_runs` | 每次样本外评估 | 保存逻辑簇、独立机会聚合版本和覆盖数量 |
| `evaluation_metrics` | 指标和置信区间 | 外键连接评估运行；区间上下界有约束 |
| `shadow_decisions` | 不触达用户的并行决策 | 携带 `logic_cluster_id`、manifest；外键连接版本、特征和结果 |

所有审计关系使用外键和 `ON DELETE RESTRICT`。影子表没有任何指向持仓写入的外键或触发器；运行时还必须使用禁止修改持仓表的独立数据库连接。

## 强制基准

每个 `NEW_ENTRY` 样本簇同时运行以下基准：

1. 同日同逻辑簇随机选择一只，使用固定种子保证可复现。
2. 只选板块或逻辑簇当日涨幅第一。
3. 只选昨日涨停但非一字板。
4. 只选竞价高开 2%–5% 且量比放大。
5. 原版 Strategy B。
6. 空仓不交易。

基准必须使用相同交易日、相同股票制度范围、相同成本模型和相同成交质量门，禁止给新版更宽松的数据。

## 输入

```json
{
  "strategy_version_id": "new-entry-event-auction-v1",
  "strategy_family": "NEW_ENTRY",
  "sample_cluster": "EVENT_LOGIC_AUCTION",
  "data_manifest_id": "manifest-2026-06-v1",
  "training_dates": ["2026-01-05", "2026-04-30"],
  "validation_dates": ["2026-05-06", "2026-06-26"],
  "purge_trading_days": 2,
  "embargo_trading_days": 1,
  "cost_model_id": "cn-a-share-main-v1",
  "baseline_ids": [
    "same-cluster-random-v1",
    "sector-leader-v1",
    "previous-limit-up-v1",
    "auction-gap-volume-v1",
    "strategy-b-legacy-v1",
    "cash-v1"
  ]
}
```

## 指标

### `NEW_ENTRY`

- `hit_net_3pct_by_t1_1030`
- `p_mae_below_minus_1_5pct`
- `p_mae_below_minus_2pct`
- `p_mae_below_minus_3pct`
- `mean_win_pct_points`、`mean_loss_pct_points`、`profit_factor`
- `net_expectancy_pct_points`
- `return_p10`、`return_p50`、`return_p90`
- `coverage_per_month`
- `best_baseline_hit_rate`
- `hit_rate_lift_pct_points`
- `net_expectancy_lift_pct_points`

净期望统一计算：

```text
net_expectancy = p_win × mean_win - p_loss × abs(mean_loss) - average_roundtrip_cost
```

### `TACTICAL_T`

- 止盈先于止损比例
- 平均 MFE、MAE 与触发时间
- 净期望与最差 10% 分位
- 反T事件率：系统战术卖出后，当日或次日出现定义内快速上冲
- 核心仓保护违规次数，目标必须为零

### `CORE_HOLD`

- 逻辑未失效期间的错误减仓率
- 相对“完全不动”基准的回撤改善与收益损失
- 逻辑证伪检测延迟
- 人工覆盖前后结果差异

### 概率质量

- Brier Score
- Log Loss
- 可靠性曲线
- Expected Calibration Error
- 不同置信度桶的实际命中率

概率未达到发布门槛前，只展示观察频率与置信区间，不输出看似精确的个人化概率。

## 时间序列验证

1. 数据按交易日排序，禁止随机打乱。
2. 标签窗口结束于下一交易日 10:30，因此训练与验证边界至少 purge 相关重叠样本，并 embargo 一个完整交易日。
3. 采用扩展窗口 walk-forward：每次只用过去数据拟合，下一段为完全样本外验证。
4. 参数只在训练段选择，验证段开始后冻结。
5. 每次参数搜索都写入 `tested_configuration_count`，包括失败和未采用版本。
6. 置信区间按独立交易日和逻辑簇做 stationary/block bootstrap，不能按股票行独立重采样。

## 多重测试治理

- 一个样本簇累计测试十个及以上配置时，必须报告 Probability of Backtest Overfitting 或等价组合验证结果。
- 收益型指标报告 Deflated Sharpe Ratio 或等价的多重测试修正；二元命中率主要使用校准、置信区间和基准 lift。
- 任何“最佳参数”必须同时展示测试配置总数和样本外表现。
- 删除规则、改标签、缩小样本都视为新策略版本，不能覆盖旧实验。

## 概率发布门槛

一个策略族只有同时满足以下条件才可从观察频率升级为概率输出：

1. 至少 100 个独立样本外决策。
2. 正类和负类各至少 20 个。
3. 至少跨越 60 个独立交易日。
4. 可靠性曲线无明显单调性破坏，Brier Score 优于无信息基准。
5. 所有输入都能从原始快照复原。

未满足时，输出格式为：“样本外 23/48 命中，区间较宽，尚未达到概率发布门槛”，而不是“概率 47.9%”。

发布状态持久化在 `strategy_versions.probability_status`：

- `frequency_only`：只显示计数、频率和区间。
- `calibrating`：允许影子校准，不允许生产概率驱动仓位。
- `probability_ready`：通过全部门槛后允许发布校准概率。
- `suspended`：发现泄漏、漂移或安全违规后立即停止概率输出。

## 影子运行

### 运行方式

- 旧版保持正式输出。
- 新版在同一决策时点读取冻结的数据快照，写入 `shadow_decisions`。
- 影子动作不显示给用户、不修改持仓、不触发交易。
- 影子运行使用独立 SQLite 连接；通过授权包装器或只读/触发器防线禁止对 `positions`、`position_lots` 和 `risk_budget_configs` 执行写操作。禁止使用“按时间关联后来持仓”的宽泛 SQL 作为唯一检测手段，因为它会把人工交易误报为影子写入。
- 人工输入仍记录，并分别评估旧版、新版和用户覆盖。

### 最短观察期

- 至少 20 个完整交易日。
- 至少覆盖正常、退潮和高波动状态中的两类；若只出现单一状态，延长影子期。
- 发生官方事件源中断、时间泄漏或核心仓保护违规时，影子计时重新开始。

### 晋级条件

进入候选生产版必须同时满足：

1. 核心仓保护违规为零。
2. 时间可用性泄漏为零。
3. 新版净期望扣成本后为正，且不劣于最佳非空仓基准。
4. 次日 3% 命中率相对最佳交易基准的 lift 为正，并报告置信区间。
5. 最差 10% 分位损失不超过已批准的风险预算。
6. 拒绝交易覆盖率与月均机会数同时报告，不能通过几乎不交易隐藏问题。
7. 所有不可评分样本和人工覆盖均已归因。

这些条件只允许进入“候选生产版”，不允许宣称稳定高胜率。

## 最小上线阶段

### 第一阶段：结果可验证

- 修复硬编码、参数消费和交易日历。
- 落地持仓账本、核心仓锁、T+1 可卖数量。
- 保存关键分钟线、原始数据版本、决策日志和人工覆盖。
- 建立 `intraday_outcomes`、目标标签、时间可用性和基础成交模型。

验收标准：任一决策都能从原始快照复原，且账本数量与人工对账一致。

### 第二阶段：事件冻结与拒绝决策

- 接入公告、停复牌、监管问询、纪律处分、重大异常波动、减持、质押、业绩预告和立案调查。
- 实现禁止加仓、冻结旧评分、只允许观察或人工确认等政策。

验收标准：预设的高严重性事件测试全部阻断新增风险，且不会被媒体利好解除。

### 第三阶段：高质量样本提纯

- 三类候选样本簇分别建模、回测和比较基准。
- 启用策略族隔离、风险预算、净期望、拒绝率和覆盖率报告。
- 完成旧版与新版影子对照。

验收标准：新版在相同成本和成交门下，相对最佳交易基准具有正 lift，并满足风险预算。

### 第四阶段：底层逻辑与产业链

- 扩展公司产品、认证、产能、收入、利润弹性和产业价格证据链。
- 用于核心持有、事件证伪和候选资格，不抢占短线执行模型权重。
- 日韩指数、宏观和小众产业价格按相关暴露逐步接入，不作为第一阶段依赖。

验收标准：每条硬逻辑均能追溯到版本化证据，并明确最弱环节与证伪条件。

## 伪代码

```python
def run_walk_forward(strategy_version, data_manifest, splits, baselines):
    for split in splits:
        train = load_as_seen_data(data_manifest, split.train_dates)
        test = load_as_seen_data(data_manifest, split.test_dates)
        params = fit_and_freeze(strategy_version, train)
        candidate = evaluate(params, test, costs="same", execution_gate="same")
        baseline_results = [
            evaluate(baseline, test, costs="same", execution_gate="same")
            for baseline in baselines
        ]
        record_metrics(candidate, baseline_results)


def aggregate_by_independent_opportunity(decisions):
    groups = group_by(decisions, keys=["trade_date", "logic_cluster_id"])
    return [select_predeclared_representative(group) for group in groups]


def publish_probability_status(metrics):
    if not probability_release_gate(metrics):
        return observed_frequency_with_interval(metrics)
    return calibrated_probability(metrics)


def shadow_tick(frozen_snapshot, versions):
    for version in versions:
        with shadow_write_boundary(allowed_tables={"shadow_decisions"}):
            decision = version.decide(frozen_snapshot)
            append_shadow_decision(decision, displayed_to_user=False)
```

## 输出

结果报告模板：

```text
策略族：NEW_ENTRY / EVENT_LOGIC_AUCTION
样本外独立机会：68 个，覆盖 74 个交易日
次日10:30净收益≥3%：36.8% [区间]
最佳交易基准：24.1% [区间]
Lift：+12.7pct [区间]
净期望：+0.42%
MAE<-2%：18.4%
最差10%分位：-2.73%
月均覆盖：3.6次
拒绝率：91.2%
成交质量：A/B 47%，C 45%，不可评分 8%
概率状态：未达到100个独立样本，继续显示观察频率
```

## 回滚方案

- 旧版正式决策在整个影子期保持不变。
- 每个策略版本和策略族独立开关，可单独退回 `research` 或 `retired`。
- 回滚不删除实验、失败参数、影子决策或基准结果。
- 若发现未来函数，受影响版本统一标为 `status='retired'`、`retire_reason='leakage'`、`probability_status='suspended'`，清除其晋级资格并从原始快照重新评估。
- 生产候选异常时，一键恢复上一 `production` 策略版本，事件冻结和持仓账本继续生效。

## 测试样例

1. **基准同口径**：新版和基准使用同一成本与成交门，不允许基准使用理论成交、新版使用实际成交或反之。
2. **独立样本去重**：同日同逻辑簇三只股票只形成一个独立机会。
3. **时间泄漏**：验证段事件发布时间晚于决策时点时必须被排除。
4. **purge/embargo**：跨越下一日10:30的标签不能同时落入训练和验证边界。
5. **参数日志**：未采用和失败配置也计入测试总数。
6. **概率门槛**：99个样本时不得输出校准概率；满足全部条件后才允许。
7. **空仓基准**：负净期望策略必须显示不如空仓。
8. **覆盖披露**：通过极端拒绝只留下一个成功样本时，报告必须显示低覆盖，不能称为高胜率。
9. **人工覆盖归因**：系统原决策、用户动作和最终结果分别统计。
10. **影子不写持仓**：影子动作不能修改 `position_lots`。
11. **核心安全回归**：任何策略升级不得造成核心仓保护违规。
12. **版本复现**：使用 manifest、代码哈希和参数可重现任一历史评估。
13. **退役枚举**：泄漏版本能成功写入合法退役状态和原因，不出现未登记状态值。
14. **逻辑簇贯穿**：影子决策、结果和分簇评估均保留相同逻辑簇；聚合评估明确记录机会分组版本。
15. **影子写边界**：尝试从影子连接写入持仓、风险预算或正式决策时必须失败。

## 正式晋级验收门

以下条件全部满足，策略才可从 `shadow` 进入 `candidate`：

- 时间可用性泄漏 0 次，核心仓保护违规 0 次。
- 影子路径修改持仓或风险预算 0 次。
- 至少 20 个完整交易日，并覆盖至少两类市场状态；概率发布仍需满足更高的 60 日与样本门槛。
- 相对最佳非空仓基准的净期望为正，次日 3% 命中率 lift 为正并报告置信区间。
- 扣成本净期望为正，最差分位损失不超过获批风险预算。
- 拒绝、不可评分、数据源事故和人工覆盖均完成归因。

## 工程交付顺序

1. `schema_v2.sql`、迁移、外键、单位、上下文契约和持仓账本。
2. 原始事件链、冻结解除审计、来源健康和 manifest。
3. 行情/盘口、成交可达性、结果标签和风险预算连接。
4. 基准运行、walk-forward、bootstrap 与至少 20 个交易日影子验证。

不绑定未经验证的固定日历日期；每一阶段以前一阶段验收门通过为开始条件。
