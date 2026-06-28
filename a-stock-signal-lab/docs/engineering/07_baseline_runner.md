# 07 Baseline Runner

## 表结构

复用既有 `baseline_definitions` 与 `strategy_versions`。迁移 `007_baseline_runner` 新增：

- `baseline_comparison_runs`：绑定策略版本、基准定义和机会分组版本。
- `baseline_run_opportunities`：保存同一机会集上的策略选择、基准选择、逻辑簇、交易日、净结果和预测概率。
- `baseline_run_metrics`：保存 overall、trade_date、logic_cluster 三个维度的五类对比指标。

不可评分机会保留在机会表并进入覆盖率分母，但不进入命中率、净期望、Brier 或校准误差分母。

## 接口定义

- `register_baseline(...)`：注册版本化、绑定成本模型的简单选择规则。
- `run(...)`：用规则在同一机会集上生成 baseline 选择，与策略选择同时评估并持久化。
- 内置 selector：`field_equals`、`all_eligible`、`auction_gap_range`。
- `python -m fenjue ... v2-baseline register|run --payload-json ...`：模块 CLI。

输出命中率及相对基准 lift、扣成本净期望、覆盖率、Brier Score 和 10 桶 Expected Calibration Error。

## 伪代码

```text
for opportunity in same opportunity set:
  strategy_selected = frozen strategy output
  baseline_selected = versioned baseline rule(features)

for scope in overall + each trade_date + each logic_cluster:
  coverage = selected / all opportunities
  scored = selected and outcome_status == scored
  hit_rate = mean(hit_3pct over scored)
  expectancy = mean(net_return over scored)
  brier = mean((probability - hit)^2 over scored with probability)
  calibration = weighted bin error
  lift = strategy_hit_rate - baseline_hit_rate
```

## 回滚方案

`MigrationRunner.rollback("007")` 依次删除指标、机会和 run 表，不删除策略版本、成本模型或 baseline 定义。每个 run 使用独立 ID，算法升级应新建 run，不覆盖旧指标。

## 测试样例

1. 固定四机会样本精确验证 lift、净期望、覆盖率、Brier 与校准误差。
2. 同一结果可按两个交易日和两个逻辑簇分别统计。
3. unscorable 机会进入覆盖率但不污染 scored 指标。
4. run 的四个机会和五个统计维度均持久化。
5. 007 migration 可 down/up 重放。
