# 06 Decision Engine Run Modes

## 表结构

迁移 `006_decision_run_mode` 新增 `decision_run_traces`：每次决策保存 `run_mode`、策略版本、共享决策图哈希、图内动作/理由、模式输出动作/理由和 `executable` 标记。数据库约束保证 research 和 shadow 永远不能写 `executable=1`。

既有 `decision_snapshots` 继续保存面向该运行模式的最终输出；shadow 模式同时追加既有 `shadow_decisions`，不写持仓和交易账本。

## 接口定义

- `DecisionEngine(db)`：兼容旧调用，等价于 `run_mode="research"`。
- `DecisionEngine(db, run_mode, strategy_version_id)`：shadow/production 必须显式绑定策略版本。
- `DecisionResult.graph_action / decision_graph_hash`：用于证明各模式经过同一决策图。
- `DecisionResult.action / executable`：运行模式投影后的用户输出和执行权限。
- `python -m fenjue ... v2-decide --context-json ... --run-mode ... --strategy-version-id ...`：兼容 CLI。

production 只有在图内动作本身属于可执行动作，并且策略版本状态为 `production`、策略族匹配、政策版本匹配时，才返回 `executable=true`。candidate/shadow/research/retired 版本即使通过全部市场门，也只能返回拒绝。

## 伪代码

```text
graph_result = run_identical_decision_graph(context)
graph_hash = hash(context_without_decision_id, graph_result)

if graph_result is not a trading action:
  output = graph_result; executable = false
elif mode == research:
  output = ALLOW_<action>_RESEARCH; executable = false
elif mode == shadow:
  output = SHADOW_<action>; executable = false
elif strategy is published production and family/policy match:
  output = action; executable = true
else:
  output = REJECT; executable = false

persist graph and projection in one transaction
```

## 回滚方案

`MigrationRunner.rollback("006")` 删除 run trace 表和索引，不删除既有决策快照或 shadow 记录。代码回滚后 `DecisionEngine(db).decide(context)` 的旧签名仍有效；生产回滚应先把调度显式改回 research，避免旧代码误读新动作字符串。

## 测试样例

1. 相同上下文在 research/shadow/production 下得到相同 graph action 和 graph hash。
2. research/shadow 分别输出非执行标记，只有已发布 production 版本返回可执行 ADD。
3. candidate 策略即使共享图通过，也被 `STRATEGY_NOT_PRODUCTION` 拒绝。
4. shadow 决策同时写 run trace 与 `shadow_decisions`。
5. 006 migration 可 down/up 重放。
