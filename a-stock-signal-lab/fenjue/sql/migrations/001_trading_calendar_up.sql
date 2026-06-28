CREATE TABLE trading_calendar (
    trade_date TEXT PRIMARY KEY,
    is_trade_day INTEGER NOT NULL CHECK (is_trade_day IN (0,1)),
    exchange TEXT NOT NULL DEFAULT 'SSE_SZSE',
    session_open_ms INTEGER,
    auction_0925_ms INTEGER,
    checkpoint_0940_ms INTEGER,
    checkpoint_1030_ms INTEGER,
    checkpoint_1430_ms INTEGER,
    session_close_ms INTEGER,
    source TEXT NOT NULL,
    calendar_version TEXT NOT NULL,
    available_at_ms INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    CHECK (
        is_trade_day = 0 OR (
            auction_0925_ms < checkpoint_0940_ms AND
            checkpoint_0940_ms < checkpoint_1030_ms AND
            checkpoint_1030_ms < checkpoint_1430_ms AND
            checkpoint_1430_ms < session_close_ms
        )
    )
);

CREATE INDEX idx_trading_calendar_open_date
ON trading_calendar(is_trade_day, trade_date);
