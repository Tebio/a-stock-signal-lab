# 04 Strategy Family and Rejection Policy

## 目标

隔离核心持有、战术做T、新买加仓、风险处理和观察五个策略族。各策略族使用不同目标、特征和评分；系统不再计算一个掩盖矛盾的总分。

完整输入、单位、枚举和概率状态遵守 [context_contract.md](context_contract.md)，可执行 DDL 以 [schema_v2.sql](schema_v2.sql) 为唯一来源。

## 设计原则

1. 底层逻辑决定“是否可信、是否允许继续持有或进入候选”，不直接主导次日 10:30 的短线预测。
2. 盘口、竞价、情绪和板块状态决定短线是否给溢价。
3. 风险冻结优先于所有正向分数。
4. 风险预算只决定仓位上限，不决定方向。
5. 数据不足、概率未校准或成交不可达时，“拒绝交易”是正常结果。

## 策略族

| 策略族 | 主要目标 | 核心输入 | 输出分数 |
|---|---|---|---|
| `CORE_HOLD` | 逻辑未失效前避免被震出，控制结构性风险 | A/B级事件、逻辑证据、趋势与相对强弱 | `core_hold_score` |
| `TACTICAL_T` | 止盈先于止损，且不卖飞核心仓 | 可卖旧仓、滚动股性、分时路径、成交质量 | `tactical_t_score` |
| `NEW_ENTRY` | 次日10:30净收益≥3%且回撤可接受 | 竞价、板块、情绪、换手、承接、成交可达性 | `new_entry_score` |
| `RISK` | 阻断新增风险并保留可执行的风险收缩路径 | 停复牌、监管、事件严重性、流动性 | `risk_freeze_score` |
| `OBSERVE` | 等待证据，不制造低质量交易 | 缺失数据、冲突证据、低置信度 | `no_trade_score` |

这些分数只在本策略族内解释，不得相加或比较。例如 `core_hold_score=80` 不能抵消 `risk_freeze_score=100`，也不能自动提高 `new_entry_score`。

## 表结构

本模块拥有以下表；字段和约束见 `schema_v2.sql`：

| 表 | 用途 | 强制约束 |
|---|---|---|
| `strategy_family_scores` | 各策略族独立评分 | 外键指向决策和特征快照；携带 `logic_cluster_id` |
| `rejection_audits` | 每个拒绝门的结构化记录 | 外键指向决策；保存请求动作、拒绝动作、证据、政策和下一检查点 |

生产决策的公共字段保存在 `decision_snapshots`。评分与拒绝表只追加策略族特有结果，避免复制并漂移账户、时间、manifest 和上下文版本。

## 候选样本簇

第一阶段只研究三类高质量样本，均为待验证假设：

1. `EVENT_LOGIC_AUCTION`：A级事件、高逻辑纯度、次日竞价继续强化。
2. `CORE_LEADER_RELAY`：昨日核心强势、非一字可参与、竞价强于所属逻辑簇。
3. `DISAGREEMENT_TO_CONSENSUS`：分歧转一致、早盘回踩不破、板块资金回流。

三类样本独立建标签、版本和统计，不合并为一个“高胜率策略”。

## 决策顺序

```text
持仓账本
→ 数据时间可用性检查
→ 事件冻结检查
→ 持仓模式识别
→ 策略族识别
→ 底层逻辑门
→ 市场状态门
→ 风险预算资格预检
→ 成交可达性门
→ 分时时机模型
→ 风险预算最终定量
→ 拒绝决策层
→ 输出动作、理由、置信度、失效条件
```

风险预算分两次执行：预检只判断是否允许增加暴露；最终定量只能在成交与时机通过后缩小仓位。

## 输入契约

```json
{
  "context_contract_version": "fenjue-context-v2",
  "decision_id": "decision-123",
  "decision_at_ms": 1782525300000,
  "account_id": "main",
  "code": "600378",
  "logic_cluster_id": "electronic_specialty_gases",
  "user_intent": "保护核心仓，退潮时不加仓",
  "requested_action": "ADD",
  "position_mode": "CORE_HOLD",
  "position_snapshot_id": "position-snapshot-123",
  "feature_snapshot_id": "feature-snapshot-123",
  "data_manifest_id": "manifest-2026-06-27-1030",
  "exchange_status": "CONTINUOUS",
  "event_freezes": [],
  "logic_gate": {
    "eligible": true,
    "evidence_tier": "A+B",
    "exposure_purity_ratio": 0.72,
    "invalidation_codes": []
  },
  "market_regime": "RETREAT",
  "market_features": {},
  "market_microstructure": {},
  "execution_quality": "C",
  "risk_budget_precheck_ratio": 0.0,
  "probability_status": "frequency_only",
  "source_selection_policy_version": "market-source-v1"
}
```

以上字段在生产路径全部必填。输入缺失时只能拒绝或进入 `OBSERVE`；禁止在评分函数中补造用户意图、交易所状态或盘口事实。

## 输出

```json
{
  "strategy_family": "CORE_HOLD",
  "scores": {
    "core_hold_score": 74,
    "tactical_t_score": null,
    "new_entry_score": null,
    "risk_freeze_score": 18,
    "no_trade_score": 82
  },
  "action": "HOLD_CORE_NO_ADD",
  "max_incremental_exposure_ratio": 0,
  "confidence": "LOW",
  "reason_codes": [
    "THESIS_NOT_INVALIDATED",
    "MARKET_RETREAT",
    "NEW_RISK_BUDGET_ZERO",
    "PROBABILITY_NOT_CALIBRATED"
  ],
  "invalidation_conditions": [
    "A_LEVEL_NEGATIVE_EVENT",
    "CORE_STRUCTURE_BREAK_WITH_SECTOR_CONFIRMATION"
  ],
  "next_checkpoint": "2026-06-27T14:30:00+08:00"
}
```

## 逻辑门

底层逻辑证据图输出以下门控字段，而不是把故事强行转换成短线高分：

- `eligible_for_core_hold`
- `eligible_for_new_entry`
- `logic_invalidated`
- `event_not_fully_priced_confidence`
- `exposure_purity_ratio`
- `weakest_link`

在 `NEW_ENTRY` 中，逻辑门最多决定候选资格和事件未定价特征；短线动作仍由市场与执行数据决定。

## 市场状态门

市场状态不是单一大盘红绿，而是与策略族匹配的状态：

- 涨停成功率与炸板率
- 昨日强势股反馈
- 板块或逻辑簇宽度与成交扩张
- 持仓相对逻辑簇强弱
- 高位股亏钱效应
- 大盘/小盘与风格分化
- 与该股票暴露相关的海外指数或宏观事件

`CORE_HOLD` 在退潮中可以继续持有但禁止新增；`NEW_ENTRY` 在退潮中通常直接拒绝；`RISK` 不受正向市场状态解除。

## 风险预算门

风险预算配置来自 `01_position_ledger_design.md`。资格预检考虑：

- 全账户总暴露
- 单票暴露
- 单逻辑簇暴露
- 核心仓、战术仓和新买仓的策略族上限
- 单日已实现与浮动损失
- 连续失败次数
- 市场退潮乘数

最终仓位按以下上限取最小值：

```text
final_size = min(
  prechecked_budget,
  execution_liquidity_capacity,
  stop_based_risk_capacity,
  user_confirmed_family_limit
)
```

## 拒绝策略

以下任一条件成立时，`NEW_ENTRY` 和 `ADD` 必须拒绝：

1. A级官方事件源不可用或存在未处理的高严重性事件。
2. 数据 `available_at` 晚于决策时间。
3. 停牌、买入涨停队列未知或成交质量为 `U`。
4. 风险预算预检为零。
5. 策略族 `probability_status` 尚未达到 `probability_ready`，却尝试输出生产概率或由概率直接计算仓位。
6. 同逻辑簇暴露达到上限。
7. 市场状态与该策略族历史有效状态不匹配。
8. 关键来源冲突且无法交叉验证。

拒绝输出必须包含原因和下一检查点，不能只给一句“谨慎”。

## 伪代码

```python
def decide(context):
    if context.exchange_status == "SUSPENDED":
        return reject("NOT_TRADABLE_SUSPENDED")

    if context.event_freeze.blocks(context.requested_action):
        return risk_policy(context)

    family = select_family(context.position_mode, context.user_intent)
    logic = logic_gate(family, context.evidence)
    if not logic.eligible:
        return reject(logic.reason)

    market = market_gate(family, context.market_features)
    prebudget = risk_budget_precheck(family, context.position, market)
    if context.requested_action in {"ADD", "NEW_ENTRY"} and prebudget <= 0:
        return reject("RISK_BUDGET_ZERO")

    execution = execution_gate(context.intent, context.market_microstructure)
    if not execution.acceptable:
        return reject(execution.reason)

    family_score = score_family(family, context, logic, market, execution)
    final_size = finalize_risk_size(prebudget, execution, context.stop_distance)

    return rejection_policy.apply(
        family=family,
        family_score=family_score,
        final_size=final_size,
        probability_status=context.probability_status,
    )
```

## 人工覆盖

- 用户可以选择不执行、提前卖、继续持有或减少数量。
- 覆盖记录写入 `manual_overrides`，系统原决策不可修改。
- 人工覆盖不能使停牌证券变得可交易，也不能让当天新买股份变为可卖。
- 复盘分别报告“系统原动作结果”和“人工覆盖后结果”。

## 回滚方案

- 以 `strategy_family_v2_enabled` 控制多策略族输出。
- 回滚时恢复现有单一提示逻辑，但保留决策快照和拒绝原因。
- 每个策略族独立开关；某一族异常不影响事件冻结和持仓账本。
- 阈值配置必须版本化，回滚到前一策略版本时不得删除新版本结果。

## 测试样例

1. **强逻辑、退潮市场**：`CORE_HOLD` 输出按仓不动且禁止加仓，不能因逻辑强而提高新买分。
2. **监管冻结**：技术形态满分仍由 `RISK` 策略族接管。
3. **反T保护**：深V概率高且处于日内低位时，战术卖出被拒绝或缩量，核心仓不动。
4. **策略族隔离**：同一特征对 `NEW_ENTRY` 有利，但不应自动提高 `CORE_HOLD`。
5. **逻辑簇超限**：同题材已有多只票，新增候选被风险预算拒绝。
6. **未校准概率**：影子期只输出研究分和拒绝动作，不输出精确生产概率或仓位。
7. **无盘口数据**：涨停买入质量未知，系统拒绝将理论涨停价当成交价。
8. **人工不执行**：系统动作与用户覆盖分别保存，后续可独立评估。
9. **观察模式**：数据源冲突时 `no_trade_score` 生效，并给出下一检查时间。
10. **风险预算双阶段**：预检额度不能被最终定量放大。
11. **输入契约缺失**：缺少 `user_intent`、`requested_action`、`exchange_status` 或 `market_microstructure` 时只能拒绝或观察。
12. **逻辑簇一致性**：决策、评分、拒绝、意图和结果的逻辑簇必须一致。
13. **概率发布保护**：`frequency_only` 和 `calibrating` 状态下不得输出生产概率或概率驱动仓位。

## 验收门槛

- 每个生产决策都包含策略族、请求动作、门控结果、原因码和下一检查点。
- 风险预算为零时 `NEW_ENTRY` 和 `ADD` 许可 0 次。
- `CORE_HOLD` 处于 `RETREAT` 时自动加仓 0 次。
- `probability_status != probability_ready` 时生产概率和概率驱动数量输出 0 次。
- 事件冻结、逻辑门、市场门、成交门和风险门均可独立回放并定位拒绝原因。
