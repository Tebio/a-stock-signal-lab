# 03 Audited Intraday Outcomes

## 表结构

既有 `trade_intents` 继续作为用户实际/模拟意图入口，既有 `intraday_outcomes` 继续保存次交易日 10:30 主目标。迁移 `003_intraday_audit` 追加：

- `market_bars_audit`：逐意图、逐检查点记录应取时间、实际选中 bar、数据可用时间、质量和未选原因。
- `intraday_checkpoint_labels`：保存次交易日 09:25、09:40、10:30、14:30 四个扣成本标签。

两表均以 `intent_id + checkpoint + calculation_version` 唯一，旧计算版本不会被覆盖。

## 接口定义

- `IntradayOutcomeBackfiller.backfill_intent(intent_id, calculation_version, calculated_at_ms)`：执行四时点审计并回填 10:30 主结果。
- `python -m fenjue --root ... v2-backfill-outcome --intent-id ... --calculation-version ...`：兼容模块 CLI。
- bar 选择只接受 `available_at_ms <= calculated_at_ms` 且目标前五分钟内的数据；超过五分钟或未来才可见的数据不计分。

## 伪代码

```text
signal_date = Shanghai date(intent.intended_at_ms)
next_date = trading_calendar.next_trade_date(signal_date)
for checkpoint in 09:25, 09:40, 10:30, 14:30:
  target = trading_calendar.checkpoint(next_date, checkpoint)
  bar = latest deterministic as-seen bar in [target-5m, target]
  persist selection or explicit missing/not-yet-available audit
  if entry, quantity, cost model and bar exist:
    persist gross return, full-cost net return and net-3% label
  else persist unscorable label
persist intraday_outcomes using 10:30 label plus MFE/MAE and open decomposition
```

## 回滚方案

`MigrationRunner.rollback("003")` 依次删除检查点标签、bar 审计和索引，不触碰既有 `trade_intents`、`market_bars`、`intraday_outcomes`。恢复时重新 `apply_all()` 并从原始 bars 使用新 calculation version 回放。

## 测试样例

1. 周五意图跳过周末，在周一四个检查点全部回填，10:30 结果命中净 3%。
2. bar 虽存在但在计算时点之后才可见，审计标记 `not_yet_available` 且不可评分。
3. 10:30 前最近成交超过五分钟，结果为 `NO_TRADABLE_1030_PRICE`，不算失败样本。
4. 003 migration 可 down/up 重放且不影响旧表。
