CREATE TABLE market_bars_audit (
    audit_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    code TEXT NOT NULL,
    checkpoint TEXT NOT NULL CHECK (checkpoint IN ('09:25','09:40','10:30','14:30')),
    checkpoint_trade_date TEXT NOT NULL,
    checkpoint_at_ms INTEGER NOT NULL,
    selected_bar_time_ms INTEGER,
    selected_scale_seconds INTEGER,
    selected_source TEXT,
    selected_price_x10000 INTEGER CHECK (
        selected_price_x10000 IS NULL OR selected_price_x10000 > 0
    ),
    selected_available_at_ms INTEGER,
    selected_quality TEXT CHECK (
        selected_quality IS NULL OR selected_quality IN ('A','B','C','D','U')
    ),
    selection_status TEXT NOT NULL CHECK (
        selection_status IN ('selected','missing','not_yet_available')
    ),
    selection_reason TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    audited_at_ms INTEGER NOT NULL,
    UNIQUE (intent_id, checkpoint, calculation_version),
    CHECK (
        selection_status <> 'selected' OR (
            selected_bar_time_ms IS NOT NULL AND
            selected_source IS NOT NULL AND
            selected_price_x10000 IS NOT NULL AND
            selected_available_at_ms IS NOT NULL
        )
    ),
    FOREIGN KEY (intent_id) REFERENCES trade_intents(intent_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE intraday_checkpoint_labels (
    label_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    audit_id TEXT NOT NULL,
    checkpoint TEXT NOT NULL CHECK (checkpoint IN ('09:25','09:40','10:30','14:30')),
    checkpoint_trade_date TEXT NOT NULL,
    checkpoint_at_ms INTEGER NOT NULL,
    reference_price_x10000 INTEGER CHECK (
        reference_price_x10000 IS NULL OR reference_price_x10000 > 0
    ),
    gross_return_pct_points REAL,
    net_return_pct_points REAL,
    hit_net_3pct INTEGER CHECK (hit_net_3pct IS NULL OR hit_net_3pct IN (0,1)),
    status TEXT NOT NULL CHECK (status IN ('scored','unscorable')),
    unscorable_reason TEXT,
    calculation_version TEXT NOT NULL,
    calculated_at_ms INTEGER NOT NULL,
    UNIQUE (intent_id, checkpoint, calculation_version),
    CHECK (status <> 'scored' OR net_return_pct_points IS NOT NULL),
    FOREIGN KEY (intent_id) REFERENCES trade_intents(intent_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (audit_id) REFERENCES market_bars_audit(audit_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX idx_market_bars_audit_intent_checkpoint
ON market_bars_audit(intent_id, checkpoint_at_ms);

CREATE INDEX idx_checkpoint_labels_date_cluster
ON intraday_checkpoint_labels(checkpoint_trade_date, checkpoint);
