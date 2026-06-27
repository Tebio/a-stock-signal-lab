# 01 Position Ledger Design

## 目标

建立可回放的持仓账本，严格区分核心仓、战术仓、当日新买和可卖旧仓。该模块只回答“当前拥有什么、允许动多少、最大风险是多少”，不判断股票方向。

## 边界

- 负责：持仓批次、T+1 可卖数量、核心仓下限、风险预算、人工覆盖、交易后账本更新。
- 不负责：事件真假、底层逻辑评分、买卖时机、收益概率。
- 所有时间使用 UTC 毫秒时间戳；交易日使用 `YYYY-MM-DD`，按 `Asia/Shanghai` 交易日历解释。
- 第一版只支持沪深主板普通股票的多头现货，不支持融资融券、ETF T+0、可转债和期权。
- 单位、枚举、外键策略与完整上下文遵守 [context_contract.md](context_contract.md)；可执行 DDL 以 [schema_v2.sql](schema_v2.sql) 为唯一来源。

## 状态模型

每只股票在每个账户中具有一个当前模式：

| 模式 | 含义 | 默认允许动作 |
|---|---|---|
| `CORE_HOLD` | 逻辑持有，核心仓优先保护 | 持有、风险检查；战术仓可独立处理 |
| `TACTICAL_T` | 使用可卖旧仓做日内差价 | 买入战术批次后，可卖不低于核心仓下限的旧仓 |
| `NEW_ENTRY` | 新买或加仓研究 | 仅在全部上游门通过后生成候选仓位 |
| `RISK` | 事件或风险冻结 | 禁止新买和加仓；允许风险收缩建议 |
| `OBSERVE` | 数据不足或等待确认 | 不产生仓位动作 |

模式不由总分自动覆盖。`RISK` 优先级最高；用户可将股票显式切换为 `CORE_HOLD`、`TACTICAL_T` 或 `OBSERVE`，但不能覆盖交易所停牌等客观不可交易状态。

## 表结构

本模块拥有以下表；字段和约束见 `schema_v2.sql`：

| 表 | 用途 | 强制约束 |
|---|---|---|
| `portfolio_accounts` | 账户权益与交易日 | 金额使用 `*_fen` 整数 |
| `positions` | 当前模式、核心仓和逻辑簇 | 外键指向账户；`logic_cluster_id` 非空 |
| `position_lots` | T+1 批次账本 | `remaining_qty <= quantity_qty`；价格使用 `*_x10000` |
| `risk_budget_configs` | 版本化风险预算 | 支持全局、账户、策略族、逻辑簇和个股作用域 |
| `position_snapshots` | 决策前不可变持仓快照 | 数量、暴露比例和预算配置可追溯 |
| `manual_overrides` | 人工覆盖追加记录 | 外键指向原决策；不得覆盖原动作 |
| `ledger_incidents` | 对账异常和强制观察审计 | 未解决异常必须使相关账户或股票进入 `OBSERVE` |

删除采用 `ON DELETE RESTRICT`。持仓与审计数据不允许级联删除。开放批次、账户模式、逻辑簇和决策时间均建立访问路径索引；上线前用真实查询执行 `EXPLAIN QUERY PLAN`。

`risk_budget_configs` 不提供自动交易默认值。没有用户确认且在当前时点有效的配置时，系统只计算暴露，不生成“加多少仓”的建议。配置按 `account_id + scope_type + scope_id + effective interval` 解析；相同作用域的有效区间不得重叠。SQLite 用完整性检查发现重叠，写入服务在事务中阻止重叠。测试可使用固定夹具值，但不得把测试值带入生产配置。

## 输入

用户自然语言最终规范化为：

```json
{
  "account_id": "main",
  "code": "600378",
  "trade_date": "2026-06-27",
  "buy_time": "09:42:00+08:00",
  "buy_price": 18.72,
  "quantity": 1000,
  "existing_total_qty": 2000,
  "core_floor_qty": 1500,
  "lot_role": "tactical",
  "requested_mode": "TACTICAL_T",
  "logic_cluster_id": "electronic_specialty_gases"
}
```

自然语言入口可以接收人民币小数，但必须用十进制定点规则转换为 `buy_price_x10000=187200` 后再写库；禁止先转为二进制浮点再取整。

关键字段缺失时的规则：

- 缺数量：可记录价格观察，但不得更新持仓数量。
- 缺时间：允许用户给“大约 9:40”，保存原始文本并将解析置信度标为低；不得伪造精确秒数。
- 缺核心仓下限：沿用已有配置；首次出现且未配置时，核心仓保护状态为 `UNCONFIGURED`，禁止自动给出卖出数量。

## 输出

```json
{
  "mode": "TACTICAL_T",
  "total_qty": 3000,
  "sellable_qty": 2000,
  "core_floor_qty": 1500,
  "max_sellable_without_breaking_core": 1500,
  "symbol_exposure_ratio": 0.18,
  "cluster_exposure_ratio": 0.31,
  "risk_eligibility": "BLOCKED_CLUSTER_LIMIT",
  "allowed_actions": ["HOLD", "REDUCE_RISK"],
  "blocked_actions": ["ADD", "NEW_ENTRY", "TACTICAL_SELL_2000"],
  "reason_codes": ["CLUSTER_LIMIT_EXCEEDED", "CORE_FLOOR_LIMITS_MAX_SELL"]
}
```

## 风险预算两阶段检查

第一阶段在市场状态之后执行，只回答是否具备新增暴露资格：

```text
precheck = min(
  全账户剩余风险预算,
  单票剩余预算,
  逻辑簇剩余预算,
  策略族剩余预算
)
if market_regime == RETREAT:
    precheck *= retreat_exposure_multiplier_ratio
if daily_loss_limit_hit or failure_streak_limit_hit:
    precheck = 0
```

第二阶段在分时时机与成交可达性通过后执行，将剩余风险预算转换成最终最大数量；它只能缩小仓位，不能放大第一阶段的额度。

## 伪代码

```python
def build_position_context(account_id, code, decision_time, calendar):
    lots = load_open_lots(account_id, code)
    sellable = sum(
        lot.remaining_qty
        for lot in lots
        if lot.sellable_from_date <= calendar.trade_date(decision_time)
    )
    total = sum(lot.remaining_qty for lot in lots)
    position = load_position(account_id, code)
    core_floor = position.core_floor_qty
    return PositionContext(
        total_qty=total,
        sellable_qty=sellable,
        core_floor_qty=core_floor,
        max_sellable_without_breaking_core=max(
            0,
            min(sellable, total - core_floor),
        ),
    )


def authorize_quantity(
    context,
    requested_action,
    requested_qty,
    risk_budget,
    confirmed_core_override=False,
):
    if requested_action in {"ADD", "NEW_ENTRY"}:
        return min(requested_qty, risk_budget.max_increment_qty)
    if requested_action == "TACTICAL_SELL":
        return min(requested_qty, context.max_sellable_without_breaking_core)
    if requested_action == "RISK_REDUCE":
        limit = (
            context.sellable_qty
            if confirmed_core_override
            else context.max_sellable_without_breaking_core
        )
        return min(requested_qty, limit)
    return 0


def record_user_override(decision, user_action, reason, confidence):
    append_manual_override(
        decision_id=decision.id,
        system_action=decision.action,
        user_action=user_action,
        override_reason=reason,
        user_confidence=confidence,
    )


def handle_ledger_mismatch(account_id, code, details):
    incident = append_ledger_incident(
        account_id=account_id,
        code=code,
        incident_type="POSITION_RECONCILIATION_FAILED",
        severity="critical",
        details=details,
        forced_mode="OBSERVE",
    )
    force_observe_until_resolved(account_id, code, incident.id)
```

## 不变量

1. 当日新买批次的 `sellable_from_date` 必须是下一有效交易日。
2. 普通战术卖出后总持仓不得低于 `core_floor_qty`。
3. 风险事件可禁止加仓，但不能伪造持仓或自动修改核心仓下限。
4. 人工覆盖必须追加记录，不能覆盖原系统决策。
5. 仓位建议必须引用有效的 `risk_config_id`。
6. 所有账本价格、金额和费用使用整数最小单位；禁止在持仓写路径使用 `REAL`。
7. 同一账户与作用域在同一时点最多命中一份风险预算配置。
8. 对账异常必须留下 `ledger_incidents`，并在解决前阻断新增风险。

## 回滚方案

- 所有表均为新增表，不修改现有行情和信号表。
- 使用 `position_ledger_v2_enabled` 功能开关；关闭后恢复现有只读持仓提示。
- 上线前备份 SQLite、Hermes Skill 和定时任务配置。
- 回滚时保留新表供审计，不删除历史批次或人工覆盖记录。
- 若数量对账失败，立即将所有持仓切换为 `OBSERVE`，禁止仓位动作，等待人工核对。

## 测试样例

1. **T+1**：周五买入 1000 股，周五可卖数量不增加，下周一（非节假日）才增加。
2. **核心仓锁**：总持仓 3000、可卖 2000、核心仓 1500，请求卖 2000，只授权 1500。
3. **停牌跨日**：持仓数量不变，可卖数量按交收日计算，但交易动作由事件冻结层拒绝。
4. **逻辑簇暴露**：同一半导体材料逻辑簇已有三只票并触及上限，新票方向分再高也禁止新增暴露。
5. **退潮降仓**：市场状态为 `RETREAT` 时，新增仓位上限乘以配置中的退潮系数。
6. **连续失败降频**：达到连续失败上限后，`NEW_ENTRY` 和 `TACTICAL_T` 新动作额度归零。
7. **人工覆盖**：用户拒绝系统的减仓提示，原决策与用户覆盖均可独立回放。
8. **无风险配置**：首次使用但未确认风险参数，只输出暴露和风险提示，不输出数量建议。
9. **批次数量约束**：`remaining_qty > quantity_qty` 的写入必须失败。
10. **预算区间冲突**：同账户、同作用域的时间区间重叠时，写入服务拒绝并由完整性检查报告。
11. **账本异常降级**：数量对账失败后自动进入 `OBSERVE`，且存在不可变的事故记录。

## 验收门槛

- 持仓批次与人工或券商账本对账一致率 100%。
- 核心仓下限违规 0 次，T+1 权限错误 0 次。
- 无有效风险配置时自动数量建议 0 次。
- 有效风险预算区间重叠 0 条。
- 所有对账异常均能关联到 `ledger_incidents` 和解除记录。
