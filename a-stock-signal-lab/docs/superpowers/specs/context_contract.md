# Fenjue V2 Shared Context Contract

## 目的

本文件是五份设计规格和 `schema_v2.sql` 的共享契约。字段、单位、枚举或发布状态发生变化时，必须先升级 `context_contract_version`，再修改下游模型；禁止在单份规格中重新解释同名字段。

## 运行时兼容性门

Hermes 容器启动时必须执行并记录：

```sql
SELECT sqlite_version();
PRAGMA compile_options;
PRAGMA foreign_keys = ON;
PRAGMA foreign_keys;
PRAGMA integrity_check;
```

启动条件：

- `PRAGMA foreign_keys` 返回 `1`，否则拒绝启动写入服务。
- 基础 V2 DDL 不依赖 `STRICT` 和 JSON1；确认极空间容器的 SQLite 版本及 JSON1 可用后，才允许通过独立迁移增加 `STRICT` 或 `CHECK(json_valid(...))`。
- 所有写连接都必须单独执行 `PRAGMA foreign_keys=ON`，不能依赖另一个连接的设置。
- 审计、快照和实验表默认 `ON DELETE RESTRICT`；不得级联删除历史证据。

## 单位规则

| 后缀 | 含义 | 示例 |
|---|---|---|
| `*_ratio` | 0 到 1 的比例 | `symbol_exposure_ratio=0.18` 表示 18% |
| `*_pct_points` | 百分点，可正可负 | `net_return_pct_points=3.21` 表示 3.21% |
| `*_bps` | 基点整数 | `commission_bps=3` 表示 0.03% |
| `*_fen` | 人民币分整数 | `equity_fen=10000000` 表示 10 万元 |
| `*_price_x10000` | 每股价格乘 10000 后的整数 | `187200` 表示 18.7200 元 |
| `*_qty` | 股数整数 | `quantity_qty=1000` |
| `*_at_ms` | UTC Unix 毫秒 | 展示时转为 `Asia/Shanghai` |

价格、金额、费用、数量进入账本或成交模型时不得使用二进制浮点数。概率、分数、收益率和研究统计可使用 `REAL`，但必须使用上述明确后缀。

## 共享枚举

```text
strategy_family / position_mode:
  CORE_HOLD | TACTICAL_T | NEW_ENTRY | RISK | OBSERVE

requested_action:
  HOLD | ADD | NEW_ENTRY | TACTICAL_BUY | TACTICAL_SELL |
  RISK_REDUCE | EXIT | OBSERVE

exchange_status:
  PREOPEN | AUCTION | CONTINUOUS | LUNCH_BREAK | CLOSED |
  SUSPENDED | UNKNOWN

market_regime:
  ADVANCE | NEUTRAL | RETREAT | HIGH_VOLATILITY | UNKNOWN

probability_status:
  frequency_only | calibrating | probability_ready | suspended

strategy_version_status:
  research | shadow | candidate | production | retired

retire_reason:
  leakage | superseded | failed_safety | failed_expectancy |
  operator_request | other

data_quality:
  A | B | C | D | U
```

策略版本只使用 `retired` 状态；具体原因写入 `retire_reason`，不得创造 `retired_leakage` 等未登记状态。

## 完整决策输入契约

```json
{
  "context_contract_version": "fenjue-context-v2",
  "decision_id": "decision-123",
  "decision_at_ms": 1782525300000,
  "account_id": "main",
  "code": "600378",
  "logic_cluster_id": "electronic_specialty_gases",
  "user_intent": "保护核心仓，评估是否做T",
  "requested_action": "TACTICAL_SELL",
  "position_mode": "CORE_HOLD",
  "position_snapshot_id": "position-snapshot-123",
  "feature_snapshot_id": "feature-snapshot-123",
  "data_manifest_id": "manifest-2026-06-27-0925",
  "exchange_status": "CONTINUOUS",
  "event_freezes": [],
  "logic_gate": {
    "eligible_for_core_hold": true,
    "eligible_for_new_entry": false,
    "logic_invalidated": false,
    "evidence_tier": "A+B",
    "exposure_purity_ratio": 0.72,
    "invalidation_codes": []
  },
  "market_regime": "RETREAT",
  "market_features": {},
  "market_microstructure": {},
  "risk_budget_precheck_ratio": 0.0,
  "probability_status": "frequency_only",
  "source_selection_policy_version": "market-source-v1"
}
```

生产决策的必填字段：`decision_id`、`decision_at_ms`、`account_id`、`code`、`logic_cluster_id`、`user_intent`、`requested_action`、`position_mode`、两个快照 ID、manifest ID、交易所状态、市场状态、概率状态和来源选择政策版本。缺失任一项时只能输出 `OBSERVE` 或明确拒绝，不能补造默认事实。

## 输出契约

每个生产或影子决策必须保存：

- 策略族、请求动作和最终动作。
- 通过或拒绝的门、结构化原因码和人类可读解释。
- `logic_cluster_id`、快照、manifest、模型、政策与上下文契约版本。
- 风险预算上限；没有有效预算配置时为空，不得自动给数量。
- 置信度、概率发布状态、失效条件和下一检查时间。
- 来源选择政策与本次实际采用的数据源。

## 逻辑簇规则

`logic_cluster_id` 是独立机会和风险暴露的一级键，必须贯穿：

```text
positions
→ position_snapshots
→ feature_snapshots
→ decision_snapshots
→ strategy_family_scores / rejection_audits
→ trade_intents / execution_assessments
→ intraday_outcomes
→ shadow_decisions / evaluation_runs
```

不能确定逻辑簇时使用版本化的 `UNCLASSIFIED:<mapping_version>`，不得留空后按股票行当作独立样本。

## 数据来源选择

- 同一时点存在多个行情来源时，由版本化的 `source_selection_policy_version` 决定主源和降级顺序。
- `feature_snapshots` 保存候选源清单；`execution_assessments` 保存实际选中的行情与盘口源。
- A 级官方事件源不可用时，`NEW_ENTRY` 和 `ADD` 必须拒绝；不得由媒体源静默替代。

## 变更纪律

1. 数据库列改名、单位改变、枚举增加都属于契约破坏性变更。
2. 破坏性变更必须提供迁移、回滚和历史重放说明。
3. 旧决策永远按其原 `context_contract_version` 解释。
4. 模型不得读取契约未声明的临时字段进入生产评分。
