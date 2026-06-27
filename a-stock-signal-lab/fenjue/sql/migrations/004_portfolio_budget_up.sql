CREATE TABLE portfolio_budget (
    budget_id TEXT PRIMARY KEY,
    risk_config_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    market_regime TEXT NOT NULL CHECK (
        market_regime IN ('RISK_ON','NEUTRAL','RETREAT','UNKNOWN')
    ),
    regime_multiplier_ratio REAL NOT NULL CHECK (
        regime_multiplier_ratio BETWEEN 0 AND 1
    ),
    equity_fen INTEGER NOT NULL CHECK (equity_fen > 0),
    gross_limit_fen INTEGER NOT NULL CHECK (gross_limit_fen >= 0),
    single_symbol_limit_fen INTEGER NOT NULL CHECK (single_symbol_limit_fen >= 0),
    default_cluster_limit_fen INTEGER NOT NULL CHECK (default_cluster_limit_fen >= 0),
    daily_loss_limit_fen INTEGER NOT NULL CHECK (daily_loss_limit_fen >= 0),
    gross_consumed_fen INTEGER NOT NULL CHECK (gross_consumed_fen >= 0),
    realized_loss_fen INTEGER NOT NULL DEFAULT 0 CHECK (realized_loss_fen >= 0),
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    consecutive_failure_limit INTEGER NOT NULL CHECK (consecutive_failure_limit >= 0),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','FROZEN','CLOSED')),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE (account_id, trade_date, risk_config_id),
    FOREIGN KEY (risk_config_id) REFERENCES risk_budget_configs(config_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (account_id) REFERENCES portfolio_accounts(account_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE logic_cluster_exposure (
    budget_id TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    exposure_limit_fen INTEGER NOT NULL CHECK (exposure_limit_fen >= 0),
    consumed_exposure_fen INTEGER NOT NULL CHECK (consumed_exposure_fen >= 0),
    updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (budget_id, logic_cluster_id),
    FOREIGN KEY (budget_id) REFERENCES portfolio_budget(budget_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE budget_consumption (
    consumption_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    budget_id TEXT NOT NULL,
    decision_id TEXT,
    code TEXT NOT NULL,
    logic_cluster_id TEXT NOT NULL,
    strategy_family TEXT NOT NULL CHECK (
        strategy_family IN ('CORE_HOLD','TACTICAL_T','NEW_ENTRY','RISK','OBSERVE')
    ),
    requested_fen INTEGER NOT NULL CHECK (requested_fen > 0),
    symbol_exposure_at_precheck_fen INTEGER NOT NULL CHECK (
        symbol_exposure_at_precheck_fen >= 0
    ),
    precheck_cap_fen INTEGER NOT NULL CHECK (precheck_cap_fen >= 0),
    final_authorized_fen INTEGER CHECK (
        final_authorized_fen IS NULL OR final_authorized_fen >= 0
    ),
    released_fen INTEGER NOT NULL DEFAULT 0 CHECK (released_fen >= 0),
    status TEXT NOT NULL CHECK (
        status IN ('ELIGIBLE','BLOCKED','CONSUMED','BLOCKED_FINAL',
                   'PARTIALLY_RELEASED','RELEASED')
    ),
    reason_codes_json TEXT NOT NULL,
    prechecked_at_ms INTEGER NOT NULL,
    consumed_at_ms INTEGER,
    released_at_ms INTEGER,
    CHECK (final_authorized_fen IS NULL OR final_authorized_fen <= precheck_cap_fen),
    CHECK (final_authorized_fen IS NULL OR final_authorized_fen <= requested_fen),
    CHECK (final_authorized_fen IS NULL OR released_fen <= final_authorized_fen),
    FOREIGN KEY (budget_id) REFERENCES portfolio_budget(budget_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (decision_id) REFERENCES decision_snapshots(decision_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX idx_budget_consumption_budget_status
ON budget_consumption(budget_id, status, code, logic_cluster_id);

CREATE INDEX idx_portfolio_budget_account_date
ON portfolio_budget(account_id, trade_date, status);
