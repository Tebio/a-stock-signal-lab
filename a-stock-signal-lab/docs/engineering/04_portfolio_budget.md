# 04 Two-Phase Portfolio Budget

## 表结构

迁移 `004_portfolio_budget` 新增：

- `portfolio_budget`：把用户确认的 `risk_budget_configs` 按账户权益和当日市场状态换算为整数分额度，保存账户总暴露、单票、逻辑簇、单日亏损和连续失败上限。
- `logic_cluster_exposure`：逐预算保存逻辑簇额度与已占用暴露。
- `budget_consumption`：一条记录贯穿资格预检和最终扣减，使用 `idempotency_key` 防止重复请求。

金额全部使用 `*_fen` 整数。第一阶段的 `precheck_cap_fen` 与第二阶段的 `final_authorized_fen` 分开保存，并由约束保证最终值不能超过预检值或请求值。

## 接口定义

- `open_budget(...)`：只能从当前有效、账户级、用户确认的风险配置开启当日预算；退潮时先应用 multiplier。
- `precheck(...)`：检查总账户、单票、逻辑簇、日亏损和连续失败，只记录资格，不增加已消费额度。
- `consume(consumption_id, ...)`：在一个 `BEGIN IMMEDIATE` 事务内重新读取所有额度，最终值只能缩小，然后同时扣减账户与逻辑簇额度。
- `as_risk_precheck(...)`：把资格结果接到现有 DecisionContext 风险门。
- `python -m fenjue --root ... v2-budget open|precheck|consume --payload-json ...`：模块 CLI。

## 伪代码

```text
precheck(request):
  cap = min(gross remaining, symbol remaining, cluster remaining)
  if daily loss hit or failure streak hit: cap = 0
  append ELIGIBLE/BLOCKED record; do not change exposure counters

consume(precheck, requested):
  begin immediate transaction
  reload budget and cluster exposure
  cap_now = recompute all remaining limits
  final = min(requested, precheck.cap, cap_now)
  increment portfolio gross and cluster exposure by final
  mark record CONSUMED (or BLOCKED_FINAL)
  commit
```

## 回滚方案

`MigrationRunner.rollback("004")` 按消费流水、逻辑簇暴露、账户预算的顺序删除本步三表，不修改 `risk_budget_configs`、账本和决策快照。代码回滚对应本步独立提交；已确认成交仍应先导出再迁移回旧系统，不能把数据库回滚当作撤单。

## 测试样例

1. 资格预检返回上限但账户已消费额度不变。
2. 最终扣减更新账户与逻辑簇，重复调用同一 consumption 不会重复扣减。
3. 两个竞争预检都通过时，第二个最终扣减会按最新逻辑簇余额缩小。
4. 单日亏损触顶后资格预检直接阻断。
5. 004 migration 可 down/up 重放。
