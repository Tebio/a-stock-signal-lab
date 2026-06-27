-- Fenjue V2 canonical research schema.
-- Base DDL intentionally avoids STRICT and json_valid() until the Hermes
-- container passes the compatibility probe documented in context_contract.md.
PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS data_manifests (
    data_manifest_id TEXT PRIMARY KEY,
    manifest_version TEXT NOT NULL,
    purpose TEXT NOT NULL,
    raw_snapshot_ids_json TEXT NOT NULL,
    event_version_ids_json TEXT NOT NULL,
    market_source_versions_json TEXT NOT NULL,
    concept_mapping_version TEXT NOT NULL,
    trading_calendar_version TEXT NOT NULL,
    source_selection_policy_version TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL UNIQUE,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_accounts (
    account_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'CNY',
    equity_fen INTEGER NOT NULL CHECK (equity_fen >= 0),
    realized_pnl_today_fen INTEGER NOT NULL DEFAULT 0,
    trading_date TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 2
);

CREATE TABLE IF NOT EXISTS positions (
    account_id TEXT NOT NULL,
    code TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (
        mode IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    core_floor_qty INTEGER NOT NULL DEFAULT 0 CHECK (core_floor_qty >= 0),
    thesis_id TEXT,
    logic_cluster_id TEXT NOT NULL,
    mode_reason TEXT NOT NULL,
    mode_set_by TEXT NOT NULL CHECK (mode_set_by IN ('user','system','event_freeze')),
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (account_id, code),
    FOREIGN KEY (account_id) REFERENCES portfolio_accounts(account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS position_lots (
    lot_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    code TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('core','tactical')),
    buy_trade_date TEXT NOT NULL,
    buy_time_ms INTEGER NOT NULL,
    quantity_qty INTEGER NOT NULL CHECK (quantity_qty > 0),
    remaining_qty INTEGER NOT NULL CHECK (
        remaining_qty >= 0 AND remaining_qty <= quantity_qty
    ),
    buy_price_x10000 INTEGER NOT NULL CHECK (buy_price_x10000 > 0),
    sellable_from_date TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('user','broker_import','system_reconstruction')),
    created_at_ms INTEGER NOT NULL,
    closed_at_ms INTEGER,
    CHECK (closed_at_ms IS NULL OR closed_at_ms >= created_at_ms),
    FOREIGN KEY (account_id, code) REFERENCES positions(account_id, code)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS risk_budget_configs (
    config_id TEXT PRIMARY KEY,
    account_id TEXT,
    scope_type TEXT NOT NULL CHECK (
        scope_type IN ('global','account','strategy_family','logic_cluster','symbol')
    ),
    scope_id TEXT,
    strategy_family TEXT CHECK (
        strategy_family IS NULL OR strategy_family IN (
            'CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE'
        )
    ),
    effective_from_ms INTEGER NOT NULL,
    effective_to_ms INTEGER,
    max_gross_exposure_ratio REAL NOT NULL CHECK (
        max_gross_exposure_ratio BETWEEN 0 AND 1
    ),
    max_single_symbol_ratio REAL NOT NULL CHECK (
        max_single_symbol_ratio BETWEEN 0 AND 1
    ),
    max_logic_cluster_ratio REAL NOT NULL CHECK (
        max_logic_cluster_ratio BETWEEN 0 AND 1
    ),
    max_daily_loss_ratio REAL NOT NULL CHECK (max_daily_loss_ratio BETWEEN 0 AND 1),
    max_single_trade_loss_ratio REAL NOT NULL CHECK (
        max_single_trade_loss_ratio BETWEEN 0 AND 1
    ),
    consecutive_failure_limit INTEGER NOT NULL CHECK (consecutive_failure_limit >= 0),
    retreat_exposure_multiplier_ratio REAL NOT NULL CHECK (
        retreat_exposure_multiplier_ratio BETWEEN 0 AND 1
    ),
    family_limits_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    CHECK (effective_to_ms IS NULL OR effective_to_ms > effective_from_ms),
    CHECK (
        (scope_type = 'global' AND account_id IS NULL AND scope_id IS NULL) OR
        (scope_type = 'account' AND account_id IS NOT NULL AND scope_id IS NULL) OR
        (scope_type IN ('strategy_family','logic_cluster','symbol')
            AND account_id IS NOT NULL AND scope_id IS NOT NULL)
    ),
    CHECK (
        (scope_type = 'strategy_family' AND strategy_family IS NOT NULL
            AND scope_id = strategy_family) OR
        (scope_type <> 'strategy_family' AND strategy_family IS NULL)
    ),
    FOREIGN KEY (account_id) REFERENCES portfolio_accounts(account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS position_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    code TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (
        mode IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    total_qty INTEGER NOT NULL CHECK (total_qty >= 0),
    sellable_qty INTEGER NOT NULL CHECK (sellable_qty >= 0 AND sellable_qty <= total_qty),
    core_floor_qty INTEGER NOT NULL CHECK (core_floor_qty >= 0 AND core_floor_qty <= total_qty),
    tactical_qty INTEGER NOT NULL CHECK (tactical_qty >= 0 AND tactical_qty <= total_qty),
    average_cost_price_x10000 INTEGER NOT NULL CHECK (average_cost_price_x10000 >= 0),
    market_value_fen INTEGER CHECK (market_value_fen IS NULL OR market_value_fen >= 0),
    account_equity_fen INTEGER NOT NULL CHECK (account_equity_fen >= 0),
    symbol_exposure_ratio REAL NOT NULL CHECK (symbol_exposure_ratio BETWEEN 0 AND 1),
    cluster_exposure_ratio REAL NOT NULL CHECK (cluster_exposure_ratio BETWEEN 0 AND 1),
    risk_config_id TEXT,
    captured_at_ms INTEGER NOT NULL,
    FOREIGN KEY (account_id, code) REFERENCES positions(account_id, code)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (risk_config_id) REFERENCES risk_budget_configs(config_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ledger_incidents (
    incident_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    code TEXT,
    incident_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('watch','high','critical')),
    details_json TEXT NOT NULL,
    forced_mode TEXT CHECK (forced_mode IS NULL OR forced_mode = 'OBSERVE'),
    detected_at_ms INTEGER NOT NULL,
    resolved_at_ms INTEGER,
    resolved_by TEXT,
    CHECK (resolved_at_ms IS NULL OR resolved_at_ms >= detected_at_ms),
    FOREIGN KEY (account_id) REFERENCES portfolio_accounts(account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS raw_snapshots (
    raw_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_tier TEXT NOT NULL CHECK (source_tier IN ('A','B','C','D')),
    source_url TEXT NOT NULL,
    external_id TEXT,
    content_type TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    raw_content BLOB NOT NULL,
    http_status INTEGER,
    published_at_ms INTEGER,
    observed_at_ms INTEGER NOT NULL,
    ingested_at_ms INTEGER NOT NULL,
    fetch_metadata_json TEXT NOT NULL,
    UNIQUE (source_id, content_sha256),
    CHECK (ingested_at_ms >= observed_at_ms)
);

CREATE TABLE IF NOT EXISTS normalized_events (
    event_version_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    event_at_ms INTEGER,
    published_at_ms INTEGER,
    observed_at_ms INTEGER NOT NULL,
    available_at_ms INTEGER NOT NULL,
    effective_at_ms INTEGER,
    severity TEXT NOT NULL CHECK (severity IN ('info','watch','high','critical')),
    evidence_tier TEXT NOT NULL CHECK (evidence_tier IN ('A','B','C','D')),
    status TEXT NOT NULL CHECK (status IN ('active','superseded','retracted')),
    normalized_payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE (event_id, parser_version, schema_version),
    CHECK (available_at_ms >= observed_at_ms),
    CHECK (published_at_ms IS NULL OR available_at_ms >= published_at_ms),
    FOREIGN KEY (raw_id) REFERENCES raw_snapshots(raw_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS event_entity_links (
    event_version_id TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (
        entity_type IN ('stock','company','product','industry','sector','macro','country')
    ),
    entity_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    exposure_direction TEXT CHECK (
        exposure_direction IN ('positive','negative','mixed','unknown')
    ),
    exposure_confidence_ratio REAL NOT NULL CHECK (
        exposure_confidence_ratio BETWEEN 0 AND 1
    ),
    evidence_json TEXT NOT NULL,
    PRIMARY KEY (event_version_id, entity_type, entity_id, relation),
    FOREIGN KEY (event_version_id) REFERENCES normalized_events(event_version_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS event_freezes (
    freeze_id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    event_version_id TEXT NOT NULL,
    freeze_scope TEXT NOT NULL CHECK (
        freeze_scope IN ('all_scoring','new_entry','add','tactical_t','risk_review')
    ),
    freeze_reason TEXT NOT NULL,
    starts_at_ms INTEGER NOT NULL,
    ends_at_ms INTEGER,
    release_condition TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('active','released','superseded')
    ),
    policy_version TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    CHECK (ends_at_ms IS NULL OR ends_at_ms >= starts_at_ms),
    FOREIGN KEY (event_version_id) REFERENCES normalized_events(event_version_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS freeze_release_audits (
    release_audit_id TEXT PRIMARY KEY,
    freeze_id TEXT NOT NULL,
    release_type TEXT NOT NULL CHECK (
        release_type IN ('condition_met','expired','manual','superseded')
    ),
    released_by TEXT NOT NULL CHECK (released_by IN ('event_policy','user','system')),
    release_evidence_json TEXT NOT NULL,
    release_event_version_id TEXT,
    policy_version TEXT NOT NULL,
    released_at_ms INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (freeze_id) REFERENCES event_freezes(freeze_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (release_event_version_id) REFERENCES normalized_events(event_version_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS source_health_incidents (
    source_incident_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_tier TEXT NOT NULL CHECK (source_tier IN ('A','B','C','D')),
    incident_type TEXT NOT NULL CHECK (
        incident_type IN ('unavailable','stale','parser_failed','time_inconsistent','recovered')
    ),
    status TEXT NOT NULL CHECK (status IN ('open','resolved')),
    blocks_new_risk INTEGER NOT NULL CHECK (blocks_new_risk IN (0,1)),
    details_json TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    started_at_ms INTEGER NOT NULL,
    resolved_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    CHECK (resolved_at_ms IS NULL OR resolved_at_ms >= started_at_ms)
);

CREATE TABLE IF NOT EXISTS feature_snapshots (
    feature_snapshot_id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    as_of_ms INTEGER NOT NULL,
    feature_set_version TEXT NOT NULL,
    data_manifest_id TEXT NOT NULL,
    source_raw_ids_json TEXT NOT NULL,
    source_event_versions_json TEXT NOT NULL,
    concept_labels_json TEXT NOT NULL,
    feature_values_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (data_manifest_id) REFERENCES data_manifests(data_manifest_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS decision_snapshots (
    decision_id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    account_id TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    strategy_family TEXT NOT NULL CHECK (
        strategy_family IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    requested_action TEXT NOT NULL CHECK (
        requested_action IN ('HOLD','ADD','NEW_ENTRY','TACTICAL_BUY','TACTICAL_SELL',
                             'RISK_REDUCE','EXIT','OBSERVE')
    ),
    exchange_status TEXT NOT NULL CHECK (
        exchange_status IN ('PREOPEN','AUCTION','CONTINUOUS','LUNCH_BREAK','CLOSED',
                            'SUSPENDED','UNKNOWN')
    ),
    decision_at_ms INTEGER NOT NULL,
    feature_snapshot_id TEXT NOT NULL,
    position_snapshot_id TEXT NOT NULL,
    data_manifest_id TEXT NOT NULL,
    context_contract_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    probability_status TEXT NOT NULL CHECK (
        probability_status IN ('frequency_only','calibrating','probability_ready','suspended')
    ),
    action TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    human_readable_reason TEXT NOT NULL,
    next_checkpoint_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (account_id) REFERENCES portfolio_accounts(account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (feature_snapshot_id) REFERENCES feature_snapshots(feature_snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (position_snapshot_id) REFERENCES position_snapshots(snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (data_manifest_id) REFERENCES data_manifests(data_manifest_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS manual_overrides (
    override_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    system_action TEXT NOT NULL,
    user_action TEXT NOT NULL,
    override_reason TEXT NOT NULL,
    user_confidence_ratio REAL CHECK (user_confidence_ratio BETWEEN 0 AND 1),
    quantity_qty INTEGER CHECK (quantity_qty IS NULL OR quantity_qty > 0),
    price_x10000 INTEGER CHECK (price_x10000 IS NULL OR price_x10000 > 0),
    action_time_ms INTEGER NOT NULL,
    outcome_hit_net_3pct INTEGER CHECK (
        outcome_hit_net_3pct IS NULL OR outcome_hit_net_3pct IN (0,1)
    ),
    postmortem_note TEXT,
    reviewed_at_ms INTEGER,
    FOREIGN KEY (decision_id) REFERENCES decision_snapshots(decision_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS cost_models (
    cost_model_id TEXT PRIMARY KEY,
    effective_from_ms INTEGER NOT NULL,
    effective_to_ms INTEGER,
    commission_bps INTEGER NOT NULL CHECK (commission_bps >= 0),
    min_commission_fen INTEGER NOT NULL CHECK (min_commission_fen >= 0),
    sell_stamp_duty_bps INTEGER NOT NULL CHECK (sell_stamp_duty_bps >= 0),
    transfer_fee_bps INTEGER NOT NULL CHECK (transfer_fee_bps >= 0),
    default_slippage_bps INTEGER NOT NULL CHECK (default_slippage_bps >= 0),
    created_at_ms INTEGER NOT NULL,
    CHECK (effective_to_ms IS NULL OR effective_to_ms > effective_from_ms)
);

CREATE TABLE IF NOT EXISTS market_bars (
    code TEXT NOT NULL,
    bar_time_ms INTEGER NOT NULL,
    scale_seconds INTEGER NOT NULL CHECK (scale_seconds > 0),
    open_price_x10000 INTEGER NOT NULL CHECK (open_price_x10000 > 0),
    high_price_x10000 INTEGER NOT NULL CHECK (high_price_x10000 > 0),
    low_price_x10000 INTEGER NOT NULL CHECK (low_price_x10000 > 0),
    close_price_x10000 INTEGER NOT NULL CHECK (close_price_x10000 > 0),
    volume_qty INTEGER CHECK (volume_qty IS NULL OR volume_qty >= 0),
    amount_fen INTEGER CHECK (amount_fen IS NULL OR amount_fen >= 0),
    source TEXT NOT NULL,
    source_raw_id TEXT,
    available_at_ms INTEGER NOT NULL,
    quality TEXT NOT NULL CHECK (quality IN ('A','B','C','D','U')),
    PRIMARY KEY (code, bar_time_ms, scale_seconds, source),
    CHECK (high_price_x10000 >= open_price_x10000),
    CHECK (high_price_x10000 >= close_price_x10000),
    CHECK (low_price_x10000 <= open_price_x10000),
    CHECK (low_price_x10000 <= close_price_x10000),
    CHECK (high_price_x10000 >= low_price_x10000),
    CHECK (available_at_ms >= bar_time_ms),
    FOREIGN KEY (source_raw_id) REFERENCES raw_snapshots(raw_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    quote_time_ms INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_raw_id TEXT,
    last_price_x10000 INTEGER CHECK (last_price_x10000 IS NULL OR last_price_x10000 > 0),
    limit_up_price_x10000 INTEGER CHECK (
        limit_up_price_x10000 IS NULL OR limit_up_price_x10000 > 0
    ),
    limit_down_price_x10000 INTEGER CHECK (
        limit_down_price_x10000 IS NULL OR limit_down_price_x10000 > 0
    ),
    bids_json TEXT,
    asks_json TEXT,
    matched_volume_qty INTEGER CHECK (matched_volume_qty IS NULL OR matched_volume_qty >= 0),
    unmatched_direction TEXT CHECK (
        unmatched_direction IS NULL OR unmatched_direction IN ('buy','sell','balanced','unknown')
    ),
    unmatched_volume_qty INTEGER CHECK (
        unmatched_volume_qty IS NULL OR unmatched_volume_qty >= 0
    ),
    available_at_ms INTEGER NOT NULL,
    quality TEXT NOT NULL CHECK (quality IN ('A','B','C','D','U')),
    CHECK (available_at_ms >= quote_time_ms),
    FOREIGN KEY (source_raw_id) REFERENCES raw_snapshots(raw_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS trade_intents (
    intent_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    code TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    strategy_family TEXT NOT NULL CHECK (
        strategy_family IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    side TEXT NOT NULL CHECK (side IN ('buy','sell','hold','none')),
    intended_at_ms INTEGER NOT NULL,
    intended_price_x10000 INTEGER CHECK (
        intended_price_x10000 IS NULL OR intended_price_x10000 > 0
    ),
    intended_qty INTEGER CHECK (intended_qty IS NULL OR intended_qty > 0),
    entry_price_source TEXT NOT NULL CHECK (
        entry_price_source IN ('user_actual','broker_actual','conservative_simulation','none')
    ),
    cost_model_id TEXT,
    target_net_return_pct_points REAL,
    stop_price_x10000 INTEGER CHECK (stop_price_x10000 IS NULL OR stop_price_x10000 > 0),
    hard_loss_cap_pct_points REAL CHECK (
        hard_loss_cap_pct_points IS NULL OR hard_loss_cap_pct_points >= 0
    ),
    status TEXT NOT NULL CHECK (
        status IN ('observed','user_confirmed','simulated','cancelled','unscorable')
    ),
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (decision_id) REFERENCES decision_snapshots(decision_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (account_id) REFERENCES portfolio_accounts(account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (cost_model_id) REFERENCES cost_models(cost_model_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS execution_assessments (
    assessment_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    assessed_at_ms INTEGER NOT NULL,
    assessment_model_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    source_selection_policy_version TEXT NOT NULL,
    selected_market_source TEXT,
    selected_orderbook_source TEXT,
    data_quality TEXT NOT NULL CHECK (data_quality IN ('A','B','C','D','U')),
    fill_status TEXT NOT NULL CHECK (
        fill_status IN ('fillable','partially_fillable','not_fillable','unknown')
    ),
    conservative_fill_price_x10000 INTEGER CHECK (
        conservative_fill_price_x10000 IS NULL OR conservative_fill_price_x10000 > 0
    ),
    estimated_fill_probability_ratio REAL CHECK (
        estimated_fill_probability_ratio IS NULL OR
        estimated_fill_probability_ratio BETWEEN 0 AND 1
    ),
    estimated_slippage_bps INTEGER CHECK (
        estimated_slippage_bps IS NULL OR estimated_slippage_bps >= 0
    ),
    price_limit_state TEXT CHECK (
        price_limit_state IN ('normal','near_limit_up','limit_up','near_limit_down',
                              'limit_down','unknown')
    ),
    reason_codes_json TEXT NOT NULL,
    source_snapshot_ids_json TEXT NOT NULL,
    FOREIGN KEY (intent_id) REFERENCES trade_intents(intent_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS intraday_outcomes (
    outcome_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    code TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    strategy_family TEXT NOT NULL CHECK (
        strategy_family IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    signal_trade_date TEXT NOT NULL,
    entry_time_ms INTEGER NOT NULL,
    entry_price_x10000 INTEGER NOT NULL CHECK (entry_price_x10000 > 0),
    entry_quality TEXT NOT NULL,
    next_trade_date TEXT,
    evaluation_end_ms INTEGER,
    exit_reference_price_x10000 INTEGER CHECK (
        exit_reference_price_x10000 IS NULL OR exit_reference_price_x10000 > 0
    ),
    exit_price_quality TEXT,
    gross_return_pct_points REAL,
    net_return_pct_points REAL,
    hit_net_3pct INTEGER CHECK (hit_net_3pct IS NULL OR hit_net_3pct IN (0,1)),
    hit_tp_before_sl INTEGER CHECK (hit_tp_before_sl IS NULL OR hit_tp_before_sl IN (0,1)),
    tp_hit_at_ms INTEGER,
    sl_hit_at_ms INTEGER,
    mfe_pct_points REAL,
    mfe_at_ms INTEGER,
    mae_pct_points REAL,
    mae_at_ms INTEGER,
    next_open_return_pct_points REAL,
    open_to_1030_return_pct_points REAL,
    execution_shortfall_pct_points REAL,
    outcome_status TEXT NOT NULL CHECK (
        outcome_status IN ('scored','ambiguous','unscorable','pending')
    ),
    unscorable_reason TEXT,
    source_bar_ids_json TEXT NOT NULL,
    calculated_at_ms INTEGER NOT NULL,
    calculation_version TEXT NOT NULL,
    UNIQUE (intent_id, calculation_version),
    CHECK (outcome_status <> 'scored' OR net_return_pct_points IS NOT NULL),
    FOREIGN KEY (intent_id) REFERENCES trade_intents(intent_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS strategy_family_scores (
    decision_id TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    strategy_family TEXT NOT NULL CHECK (
        strategy_family IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    score_name TEXT NOT NULL,
    score_value REAL,
    score_status TEXT NOT NULL CHECK (
        score_status IN ('valid','shadow_only','insufficient_data','blocked','not_applicable')
    ),
    model_version TEXT NOT NULL,
    feature_snapshot_id TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    calculated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (decision_id, strategy_family, score_name),
    FOREIGN KEY (decision_id) REFERENCES decision_snapshots(decision_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (feature_snapshot_id) REFERENCES feature_snapshots(feature_snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS rejection_audits (
    rejection_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    strategy_family TEXT NOT NULL CHECK (
        strategy_family IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    requested_action TEXT NOT NULL,
    rejected_action TEXT NOT NULL,
    gate_name TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    evidence_snapshot_ids_json TEXT NOT NULL,
    next_checkpoint_ms INTEGER,
    policy_version TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (decision_id) REFERENCES decision_snapshots(decision_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS strategy_versions (
    strategy_version_id TEXT PRIMARY KEY,
    strategy_family TEXT NOT NULL CHECK (
        strategy_family IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    sample_cluster TEXT NOT NULL,
    code_sha256 TEXT NOT NULL,
    feature_set_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    parameter_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('research','shadow','candidate','production','retired')
    ),
    retire_reason TEXT CHECK (
        retire_reason IS NULL OR retire_reason IN (
            'leakage','superseded','failed_safety','failed_expectancy',
            'operator_request','other'
        )
    ),
    probability_status TEXT NOT NULL DEFAULT 'frequency_only' CHECK (
        probability_status IN ('frequency_only','calibrating','probability_ready','suspended')
    ),
    created_at_ms INTEGER NOT NULL,
    frozen_at_ms INTEGER,
    CHECK (
        (status = 'retired' AND retire_reason IS NOT NULL) OR
        (status <> 'retired' AND retire_reason IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS experiment_registry (
    experiment_id TEXT PRIMARY KEY,
    strategy_version_id TEXT NOT NULL,
    data_manifest_id TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    training_start_date TEXT NOT NULL,
    training_end_date TEXT NOT NULL,
    validation_start_date TEXT NOT NULL,
    validation_end_date TEXT NOT NULL,
    purge_trading_days INTEGER NOT NULL CHECK (purge_trading_days >= 0),
    embargo_trading_days INTEGER NOT NULL CHECK (embargo_trading_days >= 0),
    parameter_search_space_json TEXT NOT NULL,
    tested_configuration_count INTEGER NOT NULL CHECK (tested_configuration_count >= 0),
    random_seed INTEGER NOT NULL,
    started_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    status TEXT NOT NULL CHECK (status IN ('running','passed','failed','cancelled')),
    CHECK (completed_at_ms IS NULL OR completed_at_ms >= started_at_ms),
    FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (data_manifest_id) REFERENCES data_manifests(data_manifest_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS baseline_definitions (
    baseline_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    definition_version TEXT NOT NULL,
    selection_rule_json TEXT NOT NULL,
    cost_model_id TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (cost_model_id) REFERENCES cost_models(cost_model_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    evaluation_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    strategy_version_id TEXT NOT NULL,
    baseline_id TEXT,
    evaluation_scope TEXT NOT NULL CHECK (
        evaluation_scope IN ('all_clusters','logic_cluster')
    ),
    logic_cluster_id TEXT,
    split_id TEXT NOT NULL,
    opportunity_grouping_version TEXT NOT NULL,
    evaluation_start_date TEXT NOT NULL,
    evaluation_end_date TEXT NOT NULL,
    independent_dates INTEGER NOT NULL CHECK (independent_dates >= 0),
    independent_logic_clusters INTEGER NOT NULL CHECK (independent_logic_clusters >= 0),
    scored_decisions INTEGER NOT NULL CHECK (scored_decisions >= 0),
    rejected_decisions INTEGER NOT NULL CHECK (rejected_decisions >= 0),
    unscorable_decisions INTEGER NOT NULL CHECK (unscorable_decisions >= 0),
    created_at_ms INTEGER NOT NULL,
    CHECK (
        (evaluation_scope = 'all_clusters' AND logic_cluster_id IS NULL) OR
        (evaluation_scope = 'logic_cluster' AND logic_cluster_id IS NOT NULL)
    ),
    FOREIGN KEY (experiment_id) REFERENCES experiment_registry(experiment_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (baseline_id) REFERENCES baseline_definitions(baseline_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS evaluation_metrics (
    evaluation_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    ci_low REAL,
    ci_high REAL,
    method TEXT NOT NULL,
    sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
    PRIMARY KEY (evaluation_id, metric_name),
    CHECK (ci_low IS NULL OR ci_high IS NULL OR ci_low <= ci_high),
    FOREIGN KEY (evaluation_id) REFERENCES evaluation_runs(evaluation_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS shadow_decisions (
    shadow_id TEXT PRIMARY KEY,
    production_decision_id TEXT,
    strategy_version_id TEXT NOT NULL,
    code TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    strategy_family TEXT NOT NULL CHECK (
        strategy_family IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    decision_at_ms INTEGER NOT NULL,
    action TEXT NOT NULL,
    max_exposure_ratio REAL NOT NULL CHECK (max_exposure_ratio BETWEEN 0 AND 1),
    reason_codes_json TEXT NOT NULL,
    feature_snapshot_id TEXT NOT NULL,
    data_manifest_id TEXT NOT NULL,
    outcome_id TEXT,
    displayed_to_user INTEGER NOT NULL DEFAULT 0 CHECK (displayed_to_user IN (0,1)),
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (production_decision_id) REFERENCES decision_snapshots(decision_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (feature_snapshot_id) REFERENCES feature_snapshots(feature_snapshot_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (data_manifest_id) REFERENCES data_manifests(data_manifest_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (outcome_id) REFERENCES intraday_outcomes(outcome_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

-- Access-path indexes. Keep only indexes confirmed by actual application queries;
-- every release must run EXPLAIN QUERY PLAN for the query catalogue.
CREATE INDEX IF NOT EXISTS idx_positions_account_mode
    ON positions(account_id, mode);
CREATE INDEX IF NOT EXISTS idx_positions_account_cluster
    ON positions(account_id, logic_cluster_id);
CREATE INDEX IF NOT EXISTS idx_position_lots_open
    ON position_lots(account_id, code, sellable_from_date, remaining_qty)
    WHERE remaining_qty > 0;
CREATE INDEX IF NOT EXISTS idx_risk_budget_scope_time
    ON risk_budget_configs(account_id, scope_type, scope_id, effective_from_ms, effective_to_ms);
CREATE INDEX IF NOT EXISTS idx_position_snapshots_account_code_time
    ON position_snapshots(account_id, code, captured_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_manual_overrides_decision_time
    ON manual_overrides(decision_id, action_time_ms);
CREATE INDEX IF NOT EXISTS idx_events_available
    ON normalized_events(available_at_ms, event_type, status);
CREATE INDEX IF NOT EXISTS idx_event_entity_lookup
    ON event_entity_links(entity_type, entity_id, event_version_id);
CREATE INDEX IF NOT EXISTS idx_event_freezes_active
    ON event_freezes(code, freeze_scope, starts_at_ms, ends_at_ms)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_feature_snapshots_code_time
    ON feature_snapshots(code, as_of_ms DESC);
CREATE INDEX IF NOT EXISTS idx_decision_snapshots_code_time_family
    ON decision_snapshots(code, decision_at_ms DESC, strategy_family);
CREATE INDEX IF NOT EXISTS idx_market_bars_lookup
    ON market_bars(code, scale_seconds, bar_time_ms);
CREATE INDEX IF NOT EXISTS idx_orderbook_lookup
    ON orderbook_snapshots(code, quote_time_ms);
CREATE INDEX IF NOT EXISTS idx_trade_intents_decision
    ON trade_intents(decision_id);
CREATE INDEX IF NOT EXISTS idx_execution_assessments_intent_time
    ON execution_assessments(intent_id, assessed_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_intraday_outcomes_family_date
    ON intraday_outcomes(strategy_family, signal_trade_date);
CREATE INDEX IF NOT EXISTS idx_intraday_outcomes_cluster_date
    ON intraday_outcomes(logic_cluster_id, signal_trade_date);
CREATE INDEX IF NOT EXISTS idx_shadow_decisions_version_time
    ON shadow_decisions(strategy_version_id, decision_at_ms);

CREATE TRIGGER IF NOT EXISTS trg_event_freeze_release_requires_audit
BEFORE UPDATE OF status ON event_freezes
WHEN NEW.status = 'released'
 AND OLD.status <> 'released'
 AND NOT EXISTS (
     SELECT 1 FROM freeze_release_audits a WHERE a.freeze_id = OLD.freeze_id
 )
BEGIN
    SELECT RAISE(ABORT, 'freeze release requires freeze_release_audits row');
END;

COMMIT;

