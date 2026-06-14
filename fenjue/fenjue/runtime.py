from __future__ import annotations

import sqlite3
import threading
import time
import json
from contextlib import closing
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_bars (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    amount REAL,
    source TEXT NOT NULL,
    adjusted TEXT NOT NULL DEFAULT 'qfq',
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (code, trade_date, adjusted)
);
CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_bars(trade_date);

CREATE TABLE IF NOT EXISTS minute_bars (
    code TEXT NOT NULL,
    bar_time TEXT NOT NULL,
    scale INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    amount REAL,
    source TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY (code, bar_time, scale)
);
CREATE INDEX IF NOT EXISTS idx_minute_code_time
ON minute_bars(code, scale, bar_time);

CREATE TABLE IF NOT EXISTS refresh_state (
    resource TEXT NOT NULL,
    code TEXT NOT NULL,
    refresh_date TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (resource, code)
);

CREATE TABLE IF NOT EXISTS quote_snapshots (
    trade_date TEXT NOT NULL,
    quote_time TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    open REAL,
    prev_close REAL,
    price REAL,
    high REAL,
    low REAL,
    volume REAL,
    amount REAL,
    pct REAL,
    source TEXT NOT NULL,
    quality TEXT,
    raw_json TEXT,
    PRIMARY KEY (trade_date, quote_time, code, source)
);
CREATE INDEX IF NOT EXISTS idx_quote_date
ON quote_snapshots(trade_date, quote_time);

CREATE TABLE IF NOT EXISTS evidence (
    trade_date TEXT NOT NULL,
    code TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL,
    available_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, code, evidence_type, source)
);

CREATE TABLE IF NOT EXISTS strategy_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    run_at TEXT NOT NULL,
    sample_start TEXT,
    sample_end TEXT,
    sample_count INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signal_events (
    code TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    detected_at INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY (code, signal_type, signal_date)
);
CREATE INDEX IF NOT EXISTS idx_signal_events_lookup
ON signal_events(code, signal_type, signal_date);

CREATE TABLE IF NOT EXISTS signal_outcomes (
    code TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    result_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    result_price REAL NOT NULL,
    return_pct REAL NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (code, signal_type, signal_date, horizon)
);
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_type
ON signal_outcomes(signal_type, horizon, signal_date);
"""


class Runtime:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.data_dir = self.root / "data"
        self.db_path = self.data_dir / "fenjue.sqlite3"
        self._initialize_lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialize_lock:
            if self._initialized:
                return
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.executescript(SCHEMA)
                conn.commit()
            self._initialized = True

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def upsert_daily(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        self.initialize()
        now = int(time.time())
        values = [{**row, "updated_at": now} for row in rows]
        with closing(self.connect()) as connection:
            connection.executemany(
                """
                INSERT INTO daily_bars
                    (code, trade_date, open, high, low, close, volume, amount,
                     source, adjusted, updated_at)
                VALUES
                    (:code, :trade_date, :open, :high, :low, :close, :volume,
                     :amount, :source, :adjusted, :updated_at)
                ON CONFLICT(code, trade_date, adjusted) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    amount=excluded.amount,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                values,
            )
            connection.commit()
        return len(values)

    def load_daily(self, code: str) -> list[dict]:
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT code, trade_date, open, high, low, close, volume, amount,
                       source, adjusted
                FROM daily_bars
                WHERE code=?
                ORDER BY trade_date
                """,
                (code,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_minute(
        self,
        rows: list[dict],
        *,
        fetched_at: int | None = None,
    ) -> int:
        if not rows:
            return 0
        self.initialize()
        fetched_at = int(time.time()) if fetched_at is None else fetched_at
        values = [{**row, "fetched_at": fetched_at} for row in rows]
        with closing(self.connect()) as connection:
            connection.executemany(
                """
                INSERT INTO minute_bars
                    (code, bar_time, scale, open, high, low, close, volume,
                     amount, source, fetched_at)
                VALUES
                    (:code, :bar_time, :scale, :open, :high, :low, :close,
                     :volume, :amount, :source, :fetched_at)
                ON CONFLICT(code, bar_time, scale) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    amount=excluded.amount,
                    source=excluded.source,
                    fetched_at=excluded.fetched_at
                """,
                values,
            )
            connection.commit()
        return len(values)

    def load_minute(self, code: str, scale: int = 5) -> dict:
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT code, bar_time, scale, open, high, low, close, volume,
                       amount, source, fetched_at
                FROM minute_bars
                WHERE code=? AND scale=?
                ORDER BY bar_time
                """,
                (code, scale),
            ).fetchall()
        payload = [dict(row) for row in rows]
        fetched_at = max((row["fetched_at"] for row in payload), default=None)
        for row in payload:
            row.pop("fetched_at", None)
        return {"rows": payload, "fetched_at": fetched_at}

    def refresh_state(self, resource: str, code: str) -> dict | None:
        self.initialize()
        with closing(self.connect()) as connection:
            row = connection.execute(
                """
                SELECT refresh_date, status, error, updated_at
                FROM refresh_state
                WHERE resource=? AND code=?
                """,
                (resource, code),
            ).fetchone()
        return dict(row) if row else None

    def mark_refresh(
        self,
        resource: str,
        code: str,
        refresh_date: str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        self.initialize()
        with closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT INTO refresh_state
                    (resource, code, refresh_date, status, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(resource, code) DO UPDATE SET
                    refresh_date=excluded.refresh_date,
                    status=excluded.status,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    resource,
                    code,
                    refresh_date,
                    status,
                    error,
                    int(time.time()),
                ),
            )
            connection.commit()

    def record_signal(
        self,
        code: str,
        signal_type: str,
        signal_date: str,
        metadata: dict,
    ) -> None:
        self.initialize()
        with closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT INTO signal_events
                    (code, signal_type, signal_date, detected_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(code, signal_type, signal_date) DO UPDATE SET
                    detected_at=excluded.detected_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    code,
                    signal_type,
                    signal_date,
                    int(time.time()),
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            connection.commit()

    def load_signals(
        self,
        code: str,
        signal_type: str | None = None,
    ) -> list[dict]:
        self.initialize()
        parameters: list[str] = [code]
        condition = "WHERE code=?"
        if signal_type is not None:
            condition += " AND signal_type=?"
            parameters.append(signal_type)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT code, signal_type, signal_date, detected_at, metadata_json
                FROM signal_events
                {condition}
                ORDER BY signal_date DESC
                """,
                parameters,
            ).fetchall()
        return [
            {
                "code": row["code"],
                "signal_type": row["signal_type"],
                "signal_date": row["signal_date"],
                "detected_at": row["detected_at"],
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def load_signals_for_type(self, signal_type: str) -> list[dict]:
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT code, signal_type, signal_date, detected_at, metadata_json
                FROM signal_events
                WHERE signal_type=?
                ORDER BY signal_date, code
                """,
                (signal_type,),
            ).fetchall()
        return [
            {
                "code": row["code"],
                "signal_type": row["signal_type"],
                "signal_date": row["signal_date"],
                "detected_at": row["detected_at"],
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def upsert_quote_snapshots(
        self,
        rows: list[dict],
        *,
        trade_date: str,
        quote_time: str,
    ) -> int:
        if not rows:
            return 0
        self.initialize()
        values = []
        for row in rows:
            values.append(
                {
                    "trade_date": trade_date,
                    "quote_time": quote_time,
                    "code": row["code"],
                    "name": row.get("name"),
                    "open": row.get("open"),
                    "prev_close": row.get("prev_close"),
                    "price": row.get("price"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "volume": row.get("volume"),
                    "amount": row.get("amount"),
                    "pct": row.get("pct"),
                    "source": row.get("source", "unknown"),
                    "quality": row.get("quality"),
                    "raw_json": json.dumps(row, ensure_ascii=False),
                }
            )
        with closing(self.connect()) as connection:
            connection.executemany(
                """
                INSERT INTO quote_snapshots
                    (trade_date, quote_time, code, name, open, prev_close,
                     price, high, low, volume, amount, pct, source, quality,
                     raw_json)
                VALUES
                    (:trade_date, :quote_time, :code, :name, :open,
                     :prev_close, :price, :high, :low, :volume, :amount,
                     :pct, :source, :quality, :raw_json)
                ON CONFLICT(trade_date, quote_time, code, source) DO UPDATE SET
                    name=excluded.name,
                    open=excluded.open,
                    prev_close=excluded.prev_close,
                    price=excluded.price,
                    high=excluded.high,
                    low=excluded.low,
                    volume=excluded.volume,
                    amount=excluded.amount,
                    pct=excluded.pct,
                    quality=excluded.quality,
                    raw_json=excluded.raw_json
                """,
                values,
            )
            connection.commit()
        return len(values)

    def load_quote_snapshots(
        self,
        trade_date: str,
        quote_time: str,
    ) -> list[dict]:
        self.initialize()
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT trade_date, quote_time, code, name, open, prev_close,
                       price, high, low, volume, amount, pct, source, quality
                FROM quote_snapshots
                WHERE trade_date=? AND quote_time=?
                ORDER BY code, source
                """,
                (trade_date, quote_time),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_signal_outcome(self, row: dict) -> None:
        self.initialize()
        value = {**row, "updated_at": int(time.time())}
        with closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT INTO signal_outcomes
                    (code, signal_type, signal_date, horizon, result_date,
                     entry_price, result_price, return_pct, updated_at)
                VALUES
                    (:code, :signal_type, :signal_date, :horizon, :result_date,
                     :entry_price, :result_price, :return_pct, :updated_at)
                ON CONFLICT(code, signal_type, signal_date, horizon) DO UPDATE SET
                    result_date=excluded.result_date,
                    entry_price=excluded.entry_price,
                    result_price=excluded.result_price,
                    return_pct=excluded.return_pct,
                    updated_at=excluded.updated_at
                """,
                value,
            )
            connection.commit()

    def load_signal_outcomes(
        self,
        signal_type: str | None = None,
    ) -> list[dict]:
        self.initialize()
        condition = ""
        parameters: list[str] = []
        if signal_type is not None:
            condition = "WHERE signal_type=?"
            parameters.append(signal_type)
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT code, signal_type, signal_date, horizon, result_date,
                       entry_price, result_price, return_pct
                FROM signal_outcomes
                {condition}
                ORDER BY horizon, signal_date, code
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]
