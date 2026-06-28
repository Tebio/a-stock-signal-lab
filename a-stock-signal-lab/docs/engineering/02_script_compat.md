# 02 Script Configuration Compatibility

## 表结构

本步不改变数据库表。脚本参数解析属于无状态边界；把配置写入表反而会让离线筛选依赖数据库。可回滚单元是本步独立提交，旧文件名保留为兼容 wrapper。

## 接口定义

- `resolve_trade_date(value, now=None)`：显式日期优先；缺省时使用 Asia/Shanghai 时钟，并返回日期来源。
- `resolve_runtime_root(cli_root, env=None)`：优先级为 `--root`、`FENJUE_HOME`、`~/.fenjue`。
- `resolve_pool_file(pool_file, root)`：显式文件优先，否则在 `<root>` 与 `<root>/pools` 中选日期最新的池。
- `python -m fenjue build-pool|screen-pool|screen-pool2`：正式入口。
- `scripts/build_pool.py|screen_pool.py|screen_pool2.py`：保留旧部署调用方式的薄 wrapper。

## 伪代码

```text
resolve configuration:
  root = CLI root or FENJUE_HOME or user home/.fenjue
  date = CLI date or current date converted to Asia/Shanghai
  pool = explicit positional pool or newest dated pool below root
  report where every implicit value came from
  execute the same package implementation from module CLI or legacy wrapper
```

## 回滚方案

回退本步提交即可恢复三个旧脚本；无 SQL 迁移需要逆转。新实现未删除旧文件名、旧位置参数或 `--out-dir`，因此也可在不回滚的情况下继续运行旧 Docker 调度命令。

## 测试样例

1. `2026-06-27` 被标准化为 `20260627`，来源标记为参数。
2. UTC 16:30 对应上海次日，缺省日期不会落回静态常量。
3. CLI、环境变量和用户目录按固定优先级解析。
4. 从任意当前工作目录都能找到最新池并运行三个旧 wrapper 的帮助命令。
5. `python -m fenjue` 暴露与 wrapper 相同的新子命令，原有命令仍保留。
