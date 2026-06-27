CREATE TABLE baseline_comparison_runs (
    run_id TEXT PRIMARY KEY,
    strategy_version_id TEXT NOT NULL,
    baseline_id TEXT NOT NULL,
    opportunity_grouping_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
    created_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    CHECK (completed_at_ms IS NULL OR completed_at_ms >= created_at_ms),
    FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (baseline_id) REFERENCES baseline_definitions(baseline_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE baseline_run_opportunities (
    run_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    features_json TEXT NOT NULL,
    strategy_selected INTEGER NOT NULL CHECK (strategy_selected IN (0,1)),
    baseline_selected INTEGER NOT NULL CHECK (baseline_selected IN (0,1)),
    outcome_status TEXT NOT NULL CHECK (outcome_status IN ('scored','unscorable')),
    hit_net_3pct INTEGER CHECK (hit_net_3pct IS NULL OR hit_net_3pct IN (0,1)),
    net_return_pct_points REAL,
    strategy_probability_ratio REAL CHECK (
        strategy_probability_ratio IS NULL OR strategy_probability_ratio BETWEEN 0 AND 1
    ),
    baseline_probability_ratio REAL CHECK (
        baseline_probability_ratio IS NULL OR baseline_probability_ratio BETWEEN 0 AND 1
    ),
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (run_id, opportunity_id),
    CHECK (
        outcome_status='unscorable' OR
        (hit_net_3pct IS NOT NULL AND net_return_pct_points IS NOT NULL)
    ),
    FOREIGN KEY (run_id) REFERENCES baseline_comparison_runs(run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE baseline_run_metrics (
    run_id TEXT NOT NULL,
    dimension_type TEXT NOT NULL CHECK (
        dimension_type IN ('overall','trade_date','logic_cluster')
    ),
    dimension_value TEXT NOT NULL,
    metric_name TEXT NOT NULL CHECK (
        metric_name IN ('hit_rate','net_expectancy','coverage','brier_score','calibration_error')
    ),
    strategy_value REAL,
    baseline_value REAL,
    lift_value REAL,
    total_opportunities INTEGER NOT NULL CHECK (total_opportunities >= 0),
    strategy_scored INTEGER NOT NULL CHECK (strategy_scored >= 0),
    baseline_scored INTEGER NOT NULL CHECK (baseline_scored >= 0),
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (run_id, dimension_type, dimension_value, metric_name),
    FOREIGN KEY (run_id) REFERENCES baseline_comparison_runs(run_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX idx_baseline_opportunities_date_cluster
ON baseline_run_opportunities(run_id, trade_date, logic_cluster_id);
