CREATE TABLE decision_run_traces (
    trace_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    run_mode TEXT NOT NULL CHECK (run_mode IN ('research','shadow','production')),
    strategy_version_id TEXT,
    decision_graph_hash TEXT NOT NULL,
    graph_action TEXT NOT NULL,
    graph_reason_codes_json TEXT NOT NULL,
    output_action TEXT NOT NULL,
    output_reason_codes_json TEXT NOT NULL,
    executable INTEGER NOT NULL CHECK (executable IN (0,1)),
    created_at_ms INTEGER NOT NULL,
    CHECK (run_mode='production' OR executable=0),
    FOREIGN KEY (decision_id) REFERENCES decision_snapshots(decision_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (strategy_version_id) REFERENCES strategy_versions(strategy_version_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX idx_decision_run_traces_mode_time
ON decision_run_traces(run_mode, created_at_ms, strategy_version_id);
