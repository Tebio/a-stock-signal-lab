# 03 Intraday Outcome and Execution Model

## 目标

建立分钟级、可成交、扣成本的统一结果口径，分别评估：

1. `TACTICAL_T`：战术买入后，当日是先触及净止盈目标还是先触及止损。
2. `NEW_ENTRY`：从用户实际买价或保守模拟成交价到下一交易日 10:30，净收益是否达到 3%。
3. `CORE_HOLD`：不以次日 3% 为目标，只记录逻辑持有期间的回撤、机会成本和错误卖飞事件。

单位、数据质量、逻辑簇和来源选择遵守 [context_contract.md](context_contract.md)，可执行 DDL 以 [schema_v2.sql](schema_v2.sql) 为唯一来源。

## 基本原则

- 理论价格不等于可成交价格。
- 涨停附近主要评估买入可达性；跌停附近主要评估卖出可达性。
- 五分钟K只能用于股性与粗粒度结果；止盈止损先后顺序需要一分钟或更细数据。
- 同一分钟内止盈和止损都被触及时，若无逐笔数据，结果必须标记为 `AMBIGUOUS`，不能选择有利顺序。
- 所有收益均扣除配置化的佣金、印花税、过户费和滑点。

## 数据质量等级

| 等级 | 数据 | 允许结论 |
|---|---|---|
| A | 逐笔成交、盘口队列或可靠竞价未匹配量 | 可估计成交概率与保守成交价 |
| B | 五档盘口、成交量和有效报价 | 可做盘口近似，必须给置信区间 |
| C | 一分钟K | 可判断大多数先后触发，成交价使用保守规则 |
| D | 五分钟K或关键时点快照 | 只做粗略路径判断；双触发时不可判定 |
| U | 缺失、停牌或时间不一致 | 不计入可验证样本 |

## 表结构

本模块拥有以下表；字段和约束见 `schema_v2.sql`：

| 表 | 用途 | 强制约束 |
|---|---|---|
| `cost_models` | 交易费用版本 | bps 和最低佣金均使用整数；有效区间不得倒置 |
| `market_bars` | 分钟或更细行情 | 价格 `*_x10000`、金额 `*_fen`、数量整数；外键连接原始快照 |
| `orderbook_snapshots` | 竞价与盘口证据 | 保存来源、可用时间、质量和队列快照 |
| `trade_intents` | 用户实际或模拟交易意图 | 外键连接决策、账户和成本模型；携带 `logic_cluster_id` |
| `execution_assessments` | 成交可达性判断 | 保存评估模型、政策、来源选择版本和实际选中来源 |
| `intraday_outcomes` | 扣成本结果与标签 | 每个意图和计算版本唯一；收益使用 `*_pct_points` |

行情、盘口、意图、评估和结果均建立真实访问路径索引。多来源行情不能临时“挑最好看的”，必须按版本化的来源选择政策决定主源和降级顺序。

## 输入

```json
{
  "decision_id": "decision-123",
  "account_id": "main",
  "code": "600378",
  "logic_cluster_id": "electronic_specialty_gases",
  "strategy_family": "NEW_ENTRY",
  "side": "buy",
  "intended_at": "2026-06-27T09:42:00+08:00",
  "user_entry_price": 18.72,
  "quantity": 1000,
  "target_net_return_pct_points": 3.0,
  "structure_stop_price": 18.31,
  "hard_loss_cap_pct_points": 3.0,
  "cost_model_id": "cn-a-share-main-v1",
  "source_selection_policy_version": "market-source-v1"
}
```

自然语言或 API 可以接收 `18.72`，但持久化前必须转换为 `187200`；结果展示时再转换成人民币小数。

## 入场价格规则

优先级从高到低：

1. 用户明确提供的实际买价与大致时间，标为 `user_actual`。
2. 券商成交记录，标为 `broker_actual`。
3. 模拟研究使用信号之后第一根可成交分钟K的保守价格：买入取该K线 `max(open, vwap_proxy)` 加滑点；卖出取 `min(open, vwap_proxy)` 减滑点。
4. 只有收盘价或当日最高价时不允许模拟分钟成交。

`vwap_proxy_price_x10000` 只在成交额和成交量单位经过数据源校验后使用，由 `amount_fen` 与 `volume_qty` 以整数/十进制定点计算并按股票最小价位取整；单位不明、成交量为零或结果落在该K线高低价之外时，代理价无效，回退到对交易者更不利的 `high_price_x10000`（模拟买入）或 `low_price_x10000`（模拟卖出）。

用户提供“大约 9:40”时，研究窗口覆盖 09:38–09:42，并使用对买方更不利的可成交价格；结果标记为较低入场质量。

## 次日 10:30 规则

- 使用下一有效交易日，而非自然日。
- 优先使用 10:30:00 对应的一分钟成交区间。
- 若 10:30 无成交，可向前寻找不超过五分钟的最近有效成交；超过五分钟则 `unscorable`。
- 停牌、全天无成交、数据源日期冲突均为 `unscorable`，不计入失败或成功。
- `hit_net_3pct` 基于 10:30 可成交参考价扣除完整往返成本；MFE 不代替该指标。

## 战术做T规则

战术做T结果以当天收盘前为垂直屏障：

```text
上屏障 = 达成用户目标净收益所需的卖价
下屏障 = max(结构止损价, 硬止损价格)
垂直屏障 = 当日 14:57 前最后可交易分钟
```

这里的 `max` 指价格更高、离买价更近的保护线。若上、下屏障在同一低质量K线中同时触及，状态为 `ambiguous`。

## 伪代码

### 成交可达性

```python
def assess_fill(intent, market_candidates, source_policy, model_version, policy_version):
    market = source_policy.select_as_seen_source(market_candidates, intent.intended_at_ms)
    if market.suspended:
        return FillAssessment("not_fillable", quality="U", reason="SUSPENDED")

    if intent.side == "buy" and market.at_limit_up:
        if market.quality in {"A", "B"} and market.ask_liquidity_available:
            return conservative_queue_assessment(intent, market)
        return FillAssessment("unknown", quality=market.quality, reason="LIMIT_UP_BUY_QUEUE_UNKNOWN")

    if intent.side == "sell" and market.at_limit_down:
        if market.quality in {"A", "B"} and market.bid_liquidity_available:
            return conservative_queue_assessment(intent, market)
        return FillAssessment("unknown", quality=market.quality, reason="LIMIT_DOWN_SELL_QUEUE_UNKNOWN")

    return assess_from_spread_volume_and_slippage(
        intent,
        market,
        assessment_model_version=model_version,
        policy_version=policy_version,
        source_selection_policy_version=source_policy.version,
        selected_market_source=market.source,
    )
```

### 结果计算

```python
def calculate_outcome(intent, bars, calendar, cost_model):
    assert all(bar.available_at_ms >= bar.bar_time_ms for bar in bars)
    entry = resolve_entry_price(intent, bars, cost_model)

    if intent.strategy_family == "TACTICAL_T":
        path = bars_between(intent.intended_at_ms, same_day_last_trade_minute(intent))
        barrier = first_barrier_hit(
            path,
            entry,
            intent.target_net_return_pct_points,
            intent.stop_price_x10000,
        )
        if barrier == "both_same_low_quality_bar":
            return Outcome(status="ambiguous")
        return score_tactical_path(path, entry, barrier, cost_model)

    if intent.strategy_family == "NEW_ENTRY":
        next_day = calendar.next_trade_date(intent.intended_at_ms)
        end = time_at(next_day, "10:30:00", timezone="Asia/Shanghai")
        path = bars_between(intent.intended_at_ms, end)
        exit_price = conservative_1030_price(path)
        if exit_price is None:
            return Outcome(status="unscorable", reason="NO_TRADABLE_1030_PRICE")
        return score_overnight_path(path, entry, exit_price, cost_model)

    return Outcome(status="unscorable", reason="FAMILY_HAS_NO_INTRADAY_RETURN_TARGET")
```

## 输出

```json
{
  "intent_id": "intent-123",
  "strategy_family": "NEW_ENTRY",
  "entry_price": 18.72,
  "entry_quality": "user_actual_approximate_time",
  "exit_reference_price": 19.36,
  "gross_return_pct_points": 3.42,
  "net_return_pct_points": 3.21,
  "hit_net_3pct": true,
  "mfe_pct_points": 4.06,
  "mae_pct_points": -1.18,
  "next_open_return_pct_points": 2.31,
  "open_to_1030_return_pct_points": 0.88,
  "execution_shortfall_pct_points": 0.14,
  "execution_quality": "C",
  "outcome_status": "scored"
}
```

## 回滚方案

- 新表与现有 `signal_outcomes` 并存；通过 `intraday_outcomes_v2_enabled` 控制新口径。
- 不迁移或覆盖旧结果；旧结果标为 legacy，仅用于对照。
- 若分钟数据质量异常，停止新增评分但继续保存原始行情。
- 计算规则升级时创建新的 `calculation_version`，从原始快照重算，不修改旧结果。

## 测试样例

1. **实际买价优先**：用户价格与模型价格不同，结果使用用户价格并保留模型短缺值。
2. **下一交易日**：周五信号正确使用下周一 10:30；节假日顺延。
3. **成本反转**：毛收益 3.05% 但净收益 2.86%，`hit_net_3pct=false`。
4. **同分钟双触发**：一分钟数据同根K触及止盈止损，无逐笔数据时标记 `ambiguous`。
5. **涨停买入**：无盘口队列数据时不得判定可以买到。
6. **跌停卖出**：无买盘证据时不得判定可以卖出。
7. **10:30缺失**：最近成交超过五分钟，结果不可评分。
8. **停牌**：停牌期间不产生价格代理，结果不可评分。
9. **隔夜与日内拆分**：分别计算 `next_open_return_pct_points` 和 `open_to_1030_return_pct_points`，二者之和与总收益方向一致。
10. **核心持有**：`CORE_HOLD` 不被错误纳入次日 3% 胜率。
11. **五分钟歧义**：D 级数据出现路径不确定时不能强行给成功标签。
12. **重算版本**：新成本模型生成新结果版本，旧结果保持可复现。
13. **来源选择复现**：多行情源价格不同时，结果使用政策版本选中的来源，并保存实际来源。
14. **逻辑簇贯穿**：意图、成交评估和结果使用同一 `logic_cluster_id`。
15. **整数资金字段**：账本、K线、盘口与成交价格不存在 `REAL` 类型价格列。

## 验收门槛

- 涨停买入无 A/B 级队列或卖盘证据时，判定 `fillable` 的次数为 0。
- 跌停卖出无有效买盘证据时，判定 `fillable` 的次数为 0。
- 同一低质量K线双触发时强行选择有利路径的次数为 0。
- 次日 10:30 超过五分钟无成交时全部 `unscorable`。
- 成本反转、交易日历、停牌、限价和来源冲突测试通过率 100%。
- 每个成交评估都能复原评估模型、政策、来源选择版本及实际数据源。
