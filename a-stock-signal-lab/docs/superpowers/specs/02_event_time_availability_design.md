# 02 Event and Time Availability Design

## 目标

保存决策当时系统真实看见的世界，阻断盘后公告、后修数据、后来增加的板块标签进入更早决策。该模块负责原始快照、事件规范化、实体关联和事件冻结，不负责判断买卖时机。

单位、版本和外键策略遵守 [context_contract.md](context_contract.md)，可执行 DDL 以 [schema_v2.sql](schema_v2.sql) 为唯一来源。

## 数据流水线

```text
raw_snapshot
→ normalized_event
→ event_entity_link
→ feature_snapshot
→ decision_snapshot
→ outcome
```

任一阶段都不得覆盖上一阶段。解析规则升级时，从同一份 `raw_snapshot` 产生新的规范化版本，并保留旧版本。

## 来源等级

| 等级 | 来源 | 默认用途 |
|---|---|---|
| A | 交易所、巨潮、公司正式公告、监管机关、央行和政府 | 可触发冻结或重写股票状态 |
| B | 海关、行业协会、官方价格与统计数据 | 可更新产业证据，需要实体暴露验证 |
| C | 主流财经媒体、券商研究、可靠产业媒体 | 作为催化线索，关键结论需 A/B 级交叉验证 |
| D | 自媒体、论坛、市场传闻 | 只保存为待验证线索，不进入自动决策特征 |

## 时间语义

所有事件必须包含以下时间：

- `event_at_ms`：事件实际发生时间；未知时为空。
- `published_at_ms`：来源声称的发布时间。
- `observed_at_ms`：Hermes 第一次成功取得内容的时间。
- `available_at_ms`：该事件最早允许进入决策特征的时间，取可靠的发布时间与观测时间中较晚者，并应用交易规则延迟。
- `ingested_at_ms`：成功写入数据库的时间。
- `effective_at_ms`：停牌、复牌、政策生效等实际生效时间；无明确生效时间时为空。

回测过滤条件只有一条：`available_at_ms <= decision_at_ms`。不得根据标题中的日期反推更早可用时间。

## 表结构

本模块拥有以下表；字段和约束见 `schema_v2.sql`：

| 表 | 用途 | 强制约束 |
|---|---|---|
| `raw_snapshots` | 来源原文与抓取元数据 | 内容哈希去重；原文不可覆盖 |
| `normalized_events` | 事件解析版本 | 外键指向原文；`available_at_ms` 不早于发布与观测时间 |
| `event_entity_links` | 股票、产品、行业和宏观实体映射 | 外键指向事件版本；置信度使用 `*_ratio` |
| `event_freezes` | 追加式权限冻结 | 保存状态、政策版本、起止时间和释放条件 |
| `freeze_release_audits` | 独立冻结解除凭证 | 每次解除保存操作者、证据、政策版本和时间 |
| `source_health_incidents` | 来源中断、陈旧、解析失败审计 | A 级源事故明确标记是否阻断新增风险 |
| `feature_snapshots` | 决策可见特征快照 | 包含 `logic_cluster_id` 与 `data_manifest_id` |
| `decision_snapshots` | 不可变决策快照 | 完整保存策略族、请求动作、逻辑簇、manifest 和概率状态 |

事件、实体、冻结、特征和决策均有外键。删除使用 `RESTRICT`；`event_entity_links`、活动冻结、特征时间和决策时间建立访问路径索引。

## 事件冻结策略

冻结是权限控制，不是方向评分。

| 事件 | 默认冻结范围 | 释放条件 |
|---|---|---|
| 正在停牌 | `all_scoring` | 官方复牌时间到达并重新生成行情与事件快照 |
| 复牌公告 | `new_entry`、`add` | 复牌后取得有效竞价/连续竞价数据并完成风险复核 |
| 立案调查、重大监管核查 | `new_entry`、`add`、`tactical_t` | A 级后续公告或人工风险复核 |
| 问询函、纪律处分 | `new_entry`、`add` | 解析严重性后由策略政策释放 |
| 业绩预告大幅修正、重大减持 | `add` | 新事实进入底层逻辑证据图并完成人工确认 |
| C/D 级利好传闻 | 不冻结 | 只作为待验证线索 |

风险收缩建议不能被“禁止加仓”冻结挡住；停牌时则必须返回不可交易。

## 输入

```json
{
  "source_id": "cninfo",
  "source_tier": "A",
  "source_url": "https://www.cninfo.com.cn/new/index",
  "external_id": "cninfo-2026-035",
  "observed_at_ms": 1782525300000,
  "content_type": "application/pdf",
  "raw_content": "<binary bytes>"
}
```

## 输出

解析输出：

```json
{
  "event_id": "cninfo:cninfo-2026-035",
  "event_type": "REGULATORY_INQUIRY",
  "published_at_ms": 1782525000000,
  "available_at_ms": 1782525300000,
  "severity": "high",
  "evidence_tier": "A",
  "entities": [{"type": "stock", "id": "600378", "relation": "subject"}],
  "freeze_scopes": ["new_entry", "add"]
}
```

## 伪代码

```python
def ingest(source, response, observed_at_ms):
    raw_id = append_raw_snapshot(
        source_id=source.id,
        source_tier=source.tier,
        content=response.body,
        content_sha256=sha256(response.body),
        observed_at_ms=observed_at_ms,
    )
    parsed = parser_registry[source.parser_name].parse(response.body)
    available_at_ms = max(
        parsed.published_at_ms or observed_at_ms,
        observed_at_ms,
    )
    event_version = append_normalized_event(
        raw_id=raw_id,
        parser_version=source.parser_version,
        available_at_ms=available_at_ms,
        **parsed.fields,
    )
    link_entities(event_version, parsed.entities)
    apply_freeze_policy(event_version)
    return event_version


def features_available_for(code, decision_at_ms):
    return query_events(
        code=code,
        status="active",
        available_at_lte=decision_at_ms,
    )


def release_freeze(freeze, evidence, actor):
    assert actor in {"event_policy", "user"}
    assert release_condition_satisfied(freeze.release_condition, evidence)
    with transaction():
        append_release_audit(
            freeze_id=freeze.id,
            release_type="condition_met",
            evidence=evidence,
            actor=actor,
            policy_version=freeze.policy_version,
        )
        mark_freeze_released(freeze.id)


def source_health_changed(source, status, now_ms):
    incident = append_source_health_incident(source, status, now_ms)
    if source.tier == "A" and status in {"unavailable", "stale", "time_inconsistent"}:
        incident.blocks_new_risk = True
        block_actions({"NEW_ENTRY", "ADD"}, reason="OFFICIAL_EVENT_SOURCE_UNAVAILABLE")
```

## 数据修正

- 来源内容改变时生成新的 `raw_snapshot`，不能覆盖旧内容。
- 公告撤回或更正时，将旧事件版本标为 `superseded` 或 `retracted`，并生成新版本。
- 板块、概念和公司产品映射必须写入 `feature_snapshot`，回测不能重新调用今天的标签服务替换历史标签。
- 复权价格、财务数据和产业价格的修订也遵守相同版本链。

## 降级策略

- A 级源不可用：相关股票的新买与加仓状态降为 `OBSERVE`，不得用 C/D 级新闻替代官方事实。
- C 级新闻源不可用：不影响官方事件冻结，只减少催化信息覆盖。
- 解析失败：保存原始内容，创建 `PARSER_FAILED` 监控事件，不从失败内容提取特征。
- 发布时间缺失：`available_at_ms = observed_at_ms`，禁止反推。

## 回滚方案

- 通过 `event_time_v2_enabled` 和 `event_freeze_enabled` 分别控制记录与冻结；记录功能可继续开启，冻结策略可独立回退。
- 原始快照与决策快照均为追加写入，回滚不删除数据。
- 策略异常时切换到“只展示 A 级事件、不自动冻结”的安全模式。
- parser 升级失败时恢复旧 parser 版本，使用同一原始快照重放。
- 冻结解除逻辑异常时恢复上一政策版本；已写入的 `freeze_release_audits` 不删除，错误解除通过新审计记录纠正。

## 测试样例

1. **盘后公告**：15:30 发布的公告不能进入当天 14:30 的决策。
2. **延迟抓取**：09:20 发布、09:31 才抓到的公告，不能进入 09:25 决策。
3. **更正公告**：旧事件保留并标记 `superseded`，新决策只读取最新有效版本。
4. **停牌冻结**：停牌状态下所有行情评分返回不可交易，而不是零分。
5. **复牌重评**：复牌公告不能立即解除新买冻结，必须等待有效竞价或连续竞价数据。
6. **重复内容**：相同内容重复抓取不生成第二份原始记录。
7. **解析器升级**：同一原始公告可产生两个解析版本，历史决策仍引用原版本。
8. **标签漂移**：今天新增的概念标签不能出现在一个月前的决策回放中。
9. **官方源中断**：系统输出 `OFFICIAL_EVENT_SOURCE_UNAVAILABLE` 并禁止新增动作。
10. **传闻隔离**：D 级利好不得解除 A 级监管冻结。
11. **解除可审计**：没有 `freeze_release_audits` 的状态变更必须失败。
12. **官方源事故**：A 级源中断立即生成 `source_health_incidents`，并阻断 `NEW_ENTRY` 和 `ADD`。
13. **外键完整性**：不存在没有原始快照的事件、没有事件的冻结或没有特征快照的决策。
14. **逻辑簇贯穿**：特征和决策的 `logic_cluster_id` 必须一致；未知时使用版本化 `UNCLASSIFIED`。

## 验收门槛

- 时间可用性泄漏 0 条，孤儿事件与孤儿冻结 0 条。
- 所有冻结解除均有独立审计记录和证据。
- A 级来源不可用期间产生的 `NEW_ENTRY`、`ADD` 许可 0 次。
- 任一历史决策都能通过 manifest、原始快照和解析版本复原。

