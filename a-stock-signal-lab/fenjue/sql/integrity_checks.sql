-- Fenjue V2 integrity catalogue.
-- Every SELECT must return zero violation rows unless explicitly labelled INFO.
PRAGMA foreign_keys = ON;

PRAGMA integrity_check;
PRAGMA foreign_key_check;

-- CHECK: open lots cannot exceed the original lot quantity.
SELECT 'LOT_REMAINING_EXCEEDS_ORIGINAL' AS check_name, lot_id AS entity_id
FROM position_lots
WHERE remaining_qty < 0 OR remaining_qty > quantity_qty;

-- CHECK: snapshots must be internally reconcilable.
SELECT 'POSITION_SNAPSHOT_QUANTITY_INVALID' AS check_name, snapshot_id AS entity_id
FROM position_snapshots
WHERE sellable_qty > total_qty
   OR core_floor_qty > total_qty
   OR tactical_qty > total_qty
   OR total_qty < 0;

-- CHECK: no two configurations may be active for the same resolved scope/time.
SELECT 'RISK_CONFIG_INTERVAL_OVERLAP' AS check_name,
       a.config_id || ':' || b.config_id AS entity_id
FROM risk_budget_configs a
JOIN risk_budget_configs b
  ON a.config_id < b.config_id
 AND COALESCE(a.account_id, '') = COALESCE(b.account_id, '')
 AND a.scope_type = b.scope_type
 AND COALESCE(a.scope_id, '') = COALESCE(b.scope_id, '')
 AND COALESCE(a.strategy_family, '') = COALESCE(b.strategy_family, '')
 AND a.effective_from_ms < COALESCE(b.effective_to_ms, 9223372036854775807)
 AND b.effective_from_ms < COALESCE(a.effective_to_ms, 9223372036854775807);

-- CHECK: time availability must never precede source visibility.
SELECT 'EVENT_TIME_LEAK' AS check_name, event_version_id AS entity_id
FROM normalized_events
WHERE available_at_ms < observed_at_ms
   OR (published_at_ms IS NOT NULL AND available_at_ms < published_at_ms);

SELECT 'MARKET_BAR_TIME_LEAK' AS check_name,
       code || ':' || bar_time_ms || ':' || scale_seconds || ':' || source AS entity_id
FROM market_bars
WHERE available_at_ms < bar_time_ms;

SELECT 'ORDERBOOK_TIME_LEAK' AS check_name, snapshot_id AS entity_id
FROM orderbook_snapshots
WHERE available_at_ms < quote_time_ms;

-- CHECK: freeze status transitions require an audit, and audits cannot predate freezes.
SELECT 'RELEASED_FREEZE_WITHOUT_AUDIT' AS check_name, f.freeze_id AS entity_id
FROM event_freezes f
LEFT JOIN freeze_release_audits a ON a.freeze_id = f.freeze_id
WHERE f.status = 'released'
GROUP BY f.freeze_id
HAVING COUNT(a.release_audit_id) = 0;

SELECT 'FREEZE_RELEASE_BEFORE_START' AS check_name, a.release_audit_id AS entity_id
FROM freeze_release_audits a
JOIN event_freezes f ON f.freeze_id = a.freeze_id
WHERE a.released_at_ms < f.starts_at_ms;

-- CHECK: an unresolved blocking A-tier source incident must not coexist with a
-- permitted ADD/NEW_ENTRY decision after the incident begins. Actions are
-- checked from immutable decision snapshots, not from narrative text.
SELECT 'NEW_RISK_DURING_OFFICIAL_SOURCE_OUTAGE' AS check_name,
       d.decision_id AS entity_id
FROM decision_snapshots d
WHERE d.requested_action IN ('ADD','NEW_ENTRY')
  AND d.action NOT IN ('REJECT','OBSERVE','HOLD_CORE_NO_ADD','NOT_TRADABLE')
  AND EXISTS (
      SELECT 1
      FROM source_health_incidents s
      WHERE s.source_tier = 'A'
        AND s.blocks_new_risk = 1
        AND s.started_at_ms <= d.decision_at_ms
        AND (s.resolved_at_ms IS NULL OR s.resolved_at_ms > d.decision_at_ms)
  );

-- CHECK: logic cluster must be stable along the main decision chain.
SELECT 'DECISION_FEATURE_CLUSTER_MISMATCH' AS check_name, d.decision_id AS entity_id
FROM decision_snapshots d
JOIN feature_snapshots f ON f.feature_snapshot_id = d.feature_snapshot_id
WHERE d.logic_cluster_id <> f.logic_cluster_id;

SELECT 'DECISION_POSITION_CLUSTER_MISMATCH' AS check_name, d.decision_id AS entity_id
FROM decision_snapshots d
JOIN position_snapshots p ON p.snapshot_id = d.position_snapshot_id
WHERE d.logic_cluster_id <> p.logic_cluster_id;

SELECT 'INTENT_DECISION_CLUSTER_MISMATCH' AS check_name, i.intent_id AS entity_id
FROM trade_intents i
JOIN decision_snapshots d ON d.decision_id = i.decision_id
WHERE i.logic_cluster_id <> d.logic_cluster_id;

SELECT 'ASSESSMENT_INTENT_CLUSTER_MISMATCH' AS check_name, a.assessment_id AS entity_id
FROM execution_assessments a
JOIN trade_intents i ON i.intent_id = a.intent_id
WHERE a.logic_cluster_id <> i.logic_cluster_id;

SELECT 'OUTCOME_INTENT_CLUSTER_MISMATCH' AS check_name, o.outcome_id AS entity_id
FROM intraday_outcomes o
JOIN trade_intents i ON i.intent_id = o.intent_id
WHERE o.logic_cluster_id <> i.logic_cluster_id;

-- CHECK: scored labels must have their required result fields.
SELECT 'SCORED_OUTCOME_MISSING_RESULT' AS check_name, outcome_id AS entity_id
FROM intraday_outcomes
WHERE outcome_status = 'scored'
  AND (net_return_pct_points IS NULL OR hit_net_3pct IS NULL);

SELECT 'UNSCORABLE_OUTCOME_MISSING_REASON' AS check_name, outcome_id AS entity_id
FROM intraday_outcomes
WHERE outcome_status = 'unscorable'
  AND (unscorable_reason IS NULL OR TRIM(unscorable_reason) = '');

-- CHECK: probability release state and strategy lifecycle must be coherent.
SELECT 'RETIRED_STRATEGY_MISSING_REASON' AS check_name, strategy_version_id AS entity_id
FROM strategy_versions
WHERE status = 'retired' AND retire_reason IS NULL;

SELECT 'ACTIVE_STRATEGY_HAS_RETIRE_REASON' AS check_name, strategy_version_id AS entity_id
FROM strategy_versions
WHERE status <> 'retired' AND retire_reason IS NOT NULL;

SELECT 'SUSPENDED_PROBABILITY_STILL_PRODUCTION' AS check_name, strategy_version_id AS entity_id
FROM strategy_versions
WHERE status = 'production' AND probability_status = 'suspended';

-- CHECK: shadow outputs must remain invisible. Database write boundaries and
-- negative permission tests enforce no position writes; a broad time join is
-- deliberately not used because it would misclassify unrelated user trades.
SELECT 'SHADOW_DECISION_DISPLAYED' AS check_name, shadow_id AS entity_id
FROM shadow_decisions
WHERE displayed_to_user <> 0;

-- INFO: schema inventory. This is not a fixed table-count assertion.
SELECT 'INFO_TABLE_COUNT' AS check_name, COUNT(*) AS value
FROM sqlite_schema
WHERE type = 'table' AND name NOT LIKE 'sqlite_%';

SELECT 'INFO_INDEX_COUNT' AS check_name, COUNT(*) AS value
FROM sqlite_schema
WHERE type = 'index' AND name NOT LIKE 'sqlite_%';


