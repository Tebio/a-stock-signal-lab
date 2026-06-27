# 05 Event Freeze and Override Workflow

## 表结构

既有 `event_freezes` 和 `freeze_release_audits` 保持不变。迁移 `005_event_override` 新增：

- `event_freeze_policies`：版本化映射事件类型、最低严重度、证据等级、冻结范围和解除条件。
- `override_requests`：人工申请、复核人、复核结论和证据的追加记录。
- 活跃冻结唯一索引：同一股票、事件、范围和政策版本不能重复生成活跃冻结。

默认政策覆盖停牌、复牌、监管问询、纪律处分和重大公告；问询/重大公告至少冻结新买和加仓，处分/停牌进入 `all_scoring` 风险复核。

## 接口定义

- `apply_default_freezes(event_version_id, evaluated_at_ms)`：只对在该时点已可见、有效、证据等级合格的股票事件应用政策，重复执行幂等。
- `request_override(...)`：只能给活跃冻结提交待复核请求，不改变冻结状态。
- `review_override(...)`：批准或拒绝请求；批准本身仍不解冻。
- `release_freeze(...)`：人工解除必须引用已批准的 release 请求，并继续写入原有解除审计。
- `python -m fenjue --root ... v2-freeze apply|request|review|release --payload-json ...`：模块 CLI。

DecisionEngine 的顺序保持为输入完整性/停牌/冻结，之后才进入逻辑、技术、时机和预算评分，因此冻结默认高于技术评分。

## 伪代码

```text
apply(event, as_of):
  require event.available_at <= as_of and event.status == active
  for stock link and matching policy:
    append active freeze if identical active freeze does not exist

manual release(freeze, request):
  require request.freeze == freeze
  require request.action == release and request.status == approved
  transaction:
    append freeze_release_audit
    mark freeze released
```

## 回滚方案

`MigrationRunner.rollback("005")` 删除 override 请求、默认政策和活跃唯一索引，既有冻结与解除审计完整保留。若回滚代码，旧 `EventStore.freeze/release_freeze/active_freezes` 接口仍在；但生产回滚前需保留人工审批记录导出，避免丢失治理证据。

## 测试样例

1. 停牌、复牌、问询、处分和重大公告分别命中默认硬冻结范围。
2. 尚未到 `available_at_ms` 的事件不能提前冻结，防止未来信息泄漏。
3. 人工直接解除被拒绝；请求获批后冻结仍活跃，显式解除才写审计并释放。
4. 005 migration 可 down/up 重放。
5. 现有 DecisionEngine 测试证明技术执行条件良好时，监管冻结仍先返回 RISK。
