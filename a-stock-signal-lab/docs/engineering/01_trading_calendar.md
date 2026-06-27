# 01 Trading Calendar Closure

## 表结构

`001_trading_calendar_up.sql` 新增 `trading_calendar`，保存交易所交易日、四个盘中检查点、来源、版本和当时可用时间；`schema_migrations` 由迁移运行器维护，保证版本只执行一次。

## 接口定义

- `TradingCalendar.upsert_days(rows, source, calendar_version, available_at_ms)`：导入带来源和版本的交易日快照。
- `is_trade_day(date)`：读取交易所日历，不在覆盖范围内则拒绝猜测。
- `next_trade_date(date)` / `add_trade_days(date, offset)`：唯一的 T+N 日期推进接口。
- `trading_days_between(start, end)`：按数据库日历计算池文件年龄。
- `checkpoints(date)`：返回次交易日 09:25、09:40、10:30、14:30 时间戳。

旧调用方可以暂时不注入数据库日历；兼容路径集中在 `TradingCalendar.compatibility_*`，不再在业务脚本中复制日期循环。

## 伪代码

```text
add_trade_days(day, N):
  if N == 0: require day is an exchange trading day
  query trading_calendar
    where is_trade_day = true and trade_date is after/before day
    order by trade_date in requested direction
    offset abs(N)-1 limit 1
  if no row: reject because calendar coverage is incomplete
  return trade_date
```

## 回滚方案

执行 `MigrationRunner.rollback("001")`：先删除索引，再删除 `trading_calendar`，最后从 `schema_migrations` 移除版本。回滚不修改旧 30 张 V2 表；重新执行 `apply_all()` 可恢复。生产回滚前应先导出日历来源与版本快照。

## 测试样例

1. 周五的下一交易日跳过周末到周一。
2. 交易所休市日即使是周二也被 T+N 跳过。
3. 日历覆盖不足时抛出 `CalendarCoverageError`，禁止退化为自然日猜测。
4. 池文件年龄使用注入日历，正确跳过交易所休市日。
5. migration 按 up/down/up 执行后结构和完整性保持一致。
